#!/usr/bin/env python3
"""
SSIP v3.4.0.3.1 — DST Category Discovery Gap Consolidation

Consolidates CATEGORY_INDEX_DISCOVERY_GAP rows produced by v3.4.0.3 into a
small, evidence-based set of unique missing permanent-entity candidates.

Safety guarantees
-----------------
* No network access and no DST recrawl.
* Input files are never modified.
* Existing provisional entities are matched and removed from discovery gaps.
* Calls, application windows, deadline extensions, results and other temporary
  opportunities can never become permanent scheme/programme candidates.
* This phase proposes discovery candidates only. It does not create or lock a
  canonical scheme/programme identity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERSION = "3.4.0.3.1"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

REVIEW_INPUT = "dst_identity_review_queue_v3_4_0_3.csv"
SCHEME_INPUT = "dst_provisional_scheme_inventory_v3_4_0_3.csv"
PROGRAMME_INPUT = "dst_provisional_programme_inventory_v3_4_0_3.csv"
ALIAS_INPUT = "dst_scheme_alias_candidates_v3_4_0_3.csv"
CLASSIFIED_PAGES_INPUT = "dst_classified_pages_v3_4_0_2.csv"
LINK_GRAPH_INPUT = "dst_link_graph_v3_4_0_1.csv"

UNIQUE_OUTPUT = "dst_unique_category_gaps_v3_4_0_3_1.csv"
SCHEME_CANDIDATES_OUTPUT = "dst_possible_new_scheme_pages_v3_4_0_3_1.csv"
PROGRAMME_CANDIDATES_OUTPUT = "dst_possible_new_programme_pages_v3_4_0_3_1.csv"
DUPLICATES_OUTPUT = "dst_gap_duplicates_v3_4_0_3_1.csv"
NON_ENTITY_OUTPUT = "dst_gap_non_scheme_pages_v3_4_0_3_1.csv"
EXISTING_MATCHES_OUTPUT = "dst_gap_existing_entity_matches_v3_4_0_3_1.csv"
REVIEW_OUTPUT = "dst_gap_review_queue_v3_4_0_3_1.csv"
AUDIT_OUTPUT = "dst_gap_audit_v3_4_0_3_1.csv"
VALIDATION_OUTPUT = "dst_gap_validation_v3_4_0_3_1.json"
SUMMARY_OUTPUT = "dst_gap_summary_v3_4_0_3_1.json"

FORBIDDEN_IDENTITY_FIELDS = {
    "canonical_scheme_name",
    "canonical_programme_name",
    "locked_scheme_name",
    "locked_programme_name",
    "identity_locked",
    "scheme_id",
    "programme_id",
}

CALL_ROLES = {
    "CALL_FOR_PROPOSALS",
    "APPLICATION_INVITATION",
    "EXPRESSION_OF_INTEREST",
    "DEADLINE_EXTENSION",
    "CALL_CORRIGENDUM",
    "CALL_RESULT",
    "CURRENT_CALL_INDEX",
    "CALL_ARCHIVE_INDEX",
}
SUPPORTING_ROLES = {
    "GUIDELINE_PAGE",
    "APPLICATION_GUIDANCE",
    "SANCTIONED_PROJECT_EVIDENCE",
    "NOTIFICATION",
    "OFFICE_MEMORANDUM",
    "CONTACT_PAGE",
    "GENERAL_INFORMATION",
}
INDEX_ROLES = {
    "SCHEME_CATEGORY_INDEX",
    "PROGRAMME_CATEGORY_INDEX",
    "CURRENT_CALL_INDEX",
    "CALL_ARCHIVE_INDEX",
}
NON_SCHEME_ROLES = {
    "NEWS",
    "EVENT",
    "RECRUITMENT",
    "NON_SCHEME",
    "BROKEN_OFFICIAL_LINK",
}
MASTER_ROLES = {
    "SCHEME_MASTER_CANDIDATE",
    "PROGRAMME_MASTER_CANDIDATE",
}

GAP_CLASSIFICATIONS = {
    "EXISTING_PROVISIONAL_ENTITY",
    "POSSIBLE_NEW_SCHEME",
    "POSSIBLE_NEW_PROGRAMME",
    "CALL_OR_TEMPORARY_OPPORTUNITY",
    "SUPPORTING_PAGE",
    "NAVIGATION_OR_INDEX_LINK",
    "NON_SCHEME_PAGE",
    "BROKEN_OR_MISSING_TARGET",
    "UNRESOLVED",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "possible_candidate_threshold": 0.66,
    "strong_candidate_threshold": 0.78,
    "minimum_review_confidence": 0.40,
    "maximum_unresolved_rate": 0.30,
    "fuzzy_existing_name_threshold": 0.96,
    "maximum_excerpt_length": 600,
    "tracking_query_parameters": [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "_ga", "_gl",
    ],
    "generic_anchor_terms": [
        "read more", "click here", "view details", "details", "more", "home",
        "back", "next", "previous", "download", "english", "hindi", "skip to main content",
    ],
    "call_terms": [
        "call for proposal", "call for proposals", "call for project proposals",
        "applications invited", "application invited", "inviting applications",
        "expression of interest", "eoi", "deadline extension", "last date extended",
        "corrigendum", "addendum", "result", "selected proposals", "shortlisted",
        "apply now", "submission deadline", "closing date", "open call", "special call",
        "joint call", "current call", "request for proposal", "rfp",
    ],
    "temporary_terms": [
        "round", "cycle", "cohort", "phase i", "phase ii", "phase iii",
        "2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027",
    ],
    "scheme_terms": [
        "scheme", "fellowship", "scholarship", "award", "grant", "assistance",
        "support scheme", "funding scheme", "research grant", "travel support",
    ],
    "programme_terms": [
        "programme", "program", "mission", "initiative", "platform", "network",
        "facility", "cooperation", "capacity building", "research council", "hub",
        "centre", "center", "technology mission", "national programme",
    ],
    "master_evidence_terms": {
        "objective": ["objective", "objectives", "aims to", "purpose", "vision"],
        "eligibility": ["eligibility", "eligible", "who can apply"],
        "benefit": ["financial assistance", "funding support", "grant", "support provided"],
        "application": ["how to apply", "application process", "application procedure"],
        "scope": ["scope", "thrust areas", "focus areas", "areas of support"],
        "beneficiary": ["beneficiaries", "researchers", "scientists", "institutions"],
        "duration": ["duration", "tenure", "period of support"],
    },
    "navigation_url_terms": [
        "/archive", "/taxonomy/", "/search", "/sitemap", "/contact", "/about-us",
        "/whatsnew", "/announcement", "/news", "/event", "/recruitment",
    ],
    "call_url_terms": [
        "/call-for-proposals", "/callforproposals/", "/archive-call-for-proposals",
        "/announcement/applications", "/results", "/corrigendum",
    ],
}


@dataclass
class GapGroup:
    normalized_target_url: str
    occurrences: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ConsolidationResult:
    unique_gaps: list[dict[str, Any]]
    scheme_candidates: list[dict[str, Any]]
    programme_candidates: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
    non_entity: list[dict[str, Any]]
    existing_matches: list[dict[str, Any]]
    review: list[dict[str, Any]]
    audit: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def lower(value: Any) -> str:
    return collapse_ws(value).casefold()


def upper(value: Any) -> str:
    return collapse_ws(value).upper()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(collapse_ws(value))
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(collapse_ws(value)))
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(collapse_ws(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def first_value(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = collapse_ws(row.get(name))
        if value:
            return value
    return ""


def normalize_name(value: str) -> str:
    text = html.unescape(collapse_ws(value)).casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def normalize_url(value: str, config: Mapping[str, Any] = DEFAULT_CONFIG) -> str:
    value = collapse_ws(value)
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    scheme = parts.scheme.casefold() or "https"
    netloc = parts.netloc.casefold()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    tracking = {lower(x) for x in config.get("tracking_query_parameters", [])}
    query_items = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if lower(k) not in tracking
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def read_csv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["record_status"]
        rows = [{"record_status": "NO_RECORDS"}]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    temp.replace(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path is None:
        return config
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def page_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "final_url", "canonical_url", "normalized_url", "requested_url")


def page_title(row: Mapping[str, Any]) -> str:
    return first_value(row, "page_title", "title")


def build_page_index(pages: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for row in pages:
        for field in ("final_url", "canonical_url", "normalized_url", "requested_url"):
            url = normalize_url(first_value(row, field), config)
            if url:
                index[url] = row
    return index


def provisional_entity_rows(
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, entity_type in ((schemes, "SCHEME"), (programmes, "PROGRAMME")):
        for row in source:
            item = dict(row)
            item["_entity_type"] = entity_type
            rows.append(item)
    return rows


def entity_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "official_source_url", "primary_source_url", "source_url")


def entity_name(row: Mapping[str, Any]) -> str:
    return first_value(row, "proposed_canonical_name", "entity_name")


def entity_id(row: Mapping[str, Any]) -> str:
    return first_value(row, "provisional_entity_id")


def build_entity_indexes(
    entities: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    by_url: dict[str, Mapping[str, Any]] = {}
    by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    entities_by_id = {entity_id(row): row for row in entities if entity_id(row)}
    for row in entities:
        url = normalize_url(entity_url(row), config)
        if url:
            by_url[url] = row
        key = normalize_name(entity_name(row))
        if key:
            by_name[key].append(row)
    for alias in aliases:
        parent = entities_by_id.get(first_value(alias, "provisional_entity_id"))
        if not parent:
            continue
        key = normalize_name(first_value(alias, "alias_text"))
        if key:
            by_name[key].append(parent)
    return by_url, by_name


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    haystack = lower(text)
    return [term for term in terms if lower(term) and lower(term) in haystack]


def looks_generic_anchor(anchor: str, config: Mapping[str, Any]) -> bool:
    normalized = lower(anchor)
    if not normalized:
        return True
    if normalized in {lower(x) for x in config.get("generic_anchor_terms", [])}:
        return True
    return len(normalized) < 4


def call_evidence(title: str, anchor: str, url: str, text: str, role: str, config: Mapping[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if role in CALL_ROLES:
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    combined_head = f"{title} {anchor} {url}"
    call_matches = contains_any(combined_head, config.get("call_terms", []))
    url_matches = contains_any(url, config.get("call_url_terms", []))
    text_matches = contains_any(text[:2500], config.get("call_terms", []))
    if call_matches:
        reasons.append("CALL_TERM_IN_TITLE_ANCHOR_OR_URL:" + ",".join(call_matches[:5]))
    if url_matches:
        reasons.append("CALL_URL_PATTERN:" + ",".join(url_matches[:4]))
    if text_matches:
        reasons.append("CALL_TERM_IN_TEXT:" + ",".join(text_matches[:4]))
    score = 0.0
    if role in CALL_ROLES:
        score += 0.72
    score += min(0.42, 0.12 * len(call_matches))
    score += min(0.28, 0.10 * len(url_matches))
    score += min(0.18, 0.05 * len(text_matches))
    year_present = bool(re.search(r"\b20(?:1\d|2\d)\b", combined_head))
    temporary = contains_any(combined_head, config.get("temporary_terms", []))
    if year_present and (call_matches or role in CALL_ROLES):
        score += 0.10
        reasons.append("TEMPORAL_CALL_YEAR_PRESENT")
    if temporary and call_matches:
        score += 0.08
        reasons.append("TEMPORARY_CALL_TOKEN_PRESENT")
    return clamp(score), reasons


def master_evidence(text: str, config: Mapping[str, Any]) -> tuple[float, list[str], dict[str, int]]:
    categories: dict[str, int] = {}
    reasons: list[str] = []
    for category, terms in config.get("master_evidence_terms", {}).items():
        count = sum(1 for term in terms if lower(term) in lower(text))
        categories[category] = count
        if count:
            reasons.append(f"MASTER_EVIDENCE_{category.upper()}")
    present = sum(1 for count in categories.values() if count)
    score = min(0.64, present * 0.105)
    return score, reasons, categories


def score_entity_type(
    title: str,
    anchor: str,
    url: str,
    text: str,
    role: str,
    source_roles: Sequence[str],
    config: Mapping[str, Any],
) -> tuple[float, float, list[str]]:
    head = f"{title} {anchor} {url}"
    scheme_matches = contains_any(head, config.get("scheme_terms", []))
    programme_matches = contains_any(head, config.get("programme_terms", []))
    reasons: list[str] = []
    scheme_score = 0.18
    programme_score = 0.18

    if role == "SCHEME_MASTER_CANDIDATE":
        scheme_score += 0.42
        reasons.append("CLASSIFIER_SCHEME_MASTER_CANDIDATE")
    elif role == "PROGRAMME_MASTER_CANDIDATE":
        programme_score += 0.42
        reasons.append("CLASSIFIER_PROGRAMME_MASTER_CANDIDATE")

    if scheme_matches:
        scheme_score += min(0.28, 0.10 * len(scheme_matches))
        reasons.append("SCHEME_TERMS:" + ",".join(scheme_matches[:4]))
    if programme_matches:
        programme_score += min(0.28, 0.10 * len(programme_matches))
        reasons.append("PROGRAMME_TERMS:" + ",".join(programme_matches[:4]))

    if "SCHEME_CATEGORY_INDEX" in source_roles:
        scheme_score += 0.10
        reasons.append("LINKED_FROM_SCHEME_CATEGORY_INDEX")
    if "PROGRAMME_CATEGORY_INDEX" in source_roles:
        programme_score += 0.10
        reasons.append("LINKED_FROM_PROGRAMME_CATEGORY_INDEX")

    classifier_scheme = safe_float(0)
    # Scheme evidence from prior classifier is broad permanent-entity evidence,
    # not a direct scheme-vs-programme decision, so apply equally.
    master_score, master_reasons, _ = master_evidence(text, config)
    scheme_score += master_score
    programme_score += master_score
    reasons.extend(master_reasons)

    if re.search(r"\b(scheme|fellowship|scholarship|award)\b", lower(title)):
        scheme_score += 0.10
    if re.search(r"\b(programme|program|mission|initiative)\b", lower(title)):
        programme_score += 0.10

    return clamp(scheme_score), clamp(programme_score), reasons


def match_existing_entity(
    normalized_target_url: str,
    names: Sequence[str],
    by_url: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str, float]:
    if normalized_target_url in by_url:
        return by_url[normalized_target_url], "OFFICIAL_SOURCE_URL_EXACT_MATCH", 1.0
    normalized_names = [normalize_name(name) for name in names if normalize_name(name)]
    for name in normalized_names:
        candidates = by_name.get(name, [])
        if candidates:
            return candidates[0], "CANONICAL_OR_ALIAS_NAME_EXACT_MATCH", 0.97
    threshold = safe_float(config.get("fuzzy_existing_name_threshold"), 0.96)
    best: tuple[float, Mapping[str, Any] | None] = (0.0, None)
    for name in normalized_names:
        if len(name) < 10:
            continue
        for known, candidates in by_name.items():
            if len(known) < 10:
                continue
            ratio = SequenceMatcher(None, name, known).ratio()
            if ratio > best[0] and candidates:
                best = (ratio, candidates[0])
    if best[1] is not None and best[0] >= threshold:
        return best[1], "CANONICAL_OR_ALIAS_NAME_HIGH_SIMILARITY", round(best[0], 4)
    return None, "", 0.0


def aggregate_gaps(
    gap_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[list[GapGroup], list[dict[str, Any]]]:
    groups: dict[str, GapGroup] = {}
    duplicates: list[dict[str, Any]] = []
    for index, raw in enumerate(gap_rows, start=1):
        row = {k: collapse_ws(v) for k, v in raw.items()}
        target = first_value(row, "source_url", "target_url", "final_url")
        normalized = normalize_url(target, config)
        if not normalized:
            normalized = f"missing://row-{index}"
        group = groups.setdefault(normalized, GapGroup(normalized_target_url=normalized))
        group.occurrences.append(row)
    ordered = sorted(groups.values(), key=lambda item: item.normalized_target_url)
    for group in ordered:
        unique_id = stable_id("dst_gap", group.normalized_target_url)
        for position, row in enumerate(group.occurrences[1:], start=2):
            duplicates.append({
                "duplicate_gap_id": stable_id("dst_gap_duplicate", unique_id, str(position), first_value(row, "review_id")),
                "duplicate_of_unique_gap_id": unique_id,
                "normalized_target_url": group.normalized_target_url,
                "target_url": first_value(row, "source_url", "target_url"),
                "anchor_text": first_value(row, "proposed_canonical_name", "anchor_text"),
                "source_category_title": first_value(row, "source_page_title"),
                "original_review_id": first_value(row, "review_id"),
                "deduplication_reason": "SAME_NORMALIZED_TARGET_URL",
            })
    return ordered, duplicates


def classify_group(
    group: GapGroup,
    page_index: Mapping[str, Mapping[str, Any]],
    entity_by_url: Mapping[str, Mapping[str, Any]],
    entity_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    source_page_index: Mapping[str, Mapping[str, Any]],
    inbound_counts: Mapping[str, int],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    occurrences = group.occurrences
    unique_id = stable_id("dst_gap", group.normalized_target_url)
    target_url = first_value(occurrences[0], "source_url", "target_url")
    anchors = sorted({first_value(row, "proposed_canonical_name", "anchor_text") for row in occurrences if first_value(row, "proposed_canonical_name", "anchor_text")})
    source_titles = sorted({first_value(row, "source_page_title") for row in occurrences if first_value(row, "source_page_title")})
    source_urls = sorted({first_value(row, "category_source_url", "source_category_url") for row in occurrences if first_value(row, "category_source_url", "source_category_url")})
    # v3.4.0.3 review rows store the target in source_url and category title only.
    # Recover source category roles by matching all category page titles.
    source_roles: list[str] = []
    for source_title in source_titles:
        for page in source_page_index.values():
            if normalize_name(page_title(page)) == normalize_name(source_title):
                role = upper(page.get("page_role"))
                if role:
                    source_roles.append(role)
    source_roles = sorted(set(source_roles))

    page = page_index.get(group.normalized_target_url)
    title = page_title(page or {}) or (anchors[0] if anchors else "")
    role = upper((page or {}).get("page_role"))
    text = first_value(page or {}, "main_text", "text_excerpt")
    classifier_confidence = safe_float((page or {}).get("page_role_confidence"), 0.0)
    classifier_scheme_evidence = safe_float((page or {}).get("scheme_evidence_score"), 0.0)
    classifier_call_evidence = safe_float((page or {}).get("call_evidence_score"), 0.0)
    review_flags: list[str] = []
    reasons: list[str] = []

    existing, existing_method, existing_confidence = match_existing_entity(
        group.normalized_target_url,
        [title, *anchors],
        entity_by_url,
        entity_by_name,
        config,
    )
    if existing:
        classification = "EXISTING_PROVISIONAL_ENTITY"
        confidence = existing_confidence
        reasons.append(existing_method)
        proposed_type = first_value(existing, "_entity_type")
    elif not page:
        classification = "BROKEN_OR_MISSING_TARGET"
        confidence = 0.35
        proposed_type = "UNRESOLVED"
        reasons.append("TARGET_NOT_FOUND_IN_CLASSIFIED_PAGE_INVENTORY")
        review_flags.append("VERIFY_TARGET_URL_OR_MISSING_CRAWL_RECORD")
    elif role in CALL_ROLES:
        classification = "CALL_OR_TEMPORARY_OPPORTUNITY"
        confidence = max(0.90, classifier_confidence)
        proposed_type = "CALL"
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    elif role in INDEX_ROLES:
        classification = "NAVIGATION_OR_INDEX_LINK"
        confidence = max(0.88, classifier_confidence)
        proposed_type = "INDEX"
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    elif role in SUPPORTING_ROLES:
        classification = "SUPPORTING_PAGE"
        confidence = max(0.82, classifier_confidence)
        proposed_type = "SUPPORTING"
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    elif role in NON_SCHEME_ROLES:
        classification = "NON_SCHEME_PAGE"
        confidence = max(0.90, classifier_confidence)
        proposed_type = "NON_SCHEME"
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    else:
        anchor = anchors[0] if anchors else title
        call_score, call_reasons = call_evidence(title, anchor, target_url, text, role, config)
        reasons.extend(call_reasons)
        if call_score >= 0.58 or classifier_call_evidence >= 0.70:
            classification = "CALL_OR_TEMPORARY_OPPORTUNITY"
            confidence = max(call_score, classifier_call_evidence, 0.72)
            proposed_type = "CALL"
        elif looks_generic_anchor(anchor, config):
            classification = "NAVIGATION_OR_INDEX_LINK"
            confidence = 0.76
            proposed_type = "INDEX"
            reasons.append("GENERIC_NAVIGATION_ANCHOR")
        elif any(term in lower(target_url) for term in config.get("navigation_url_terms", [])):
            classification = "NON_SCHEME_PAGE"
            confidence = 0.75
            proposed_type = "NON_SCHEME"
            reasons.append("NON_ENTITY_URL_PATTERN")
        else:
            scheme_score, programme_score, entity_reasons = score_entity_type(
                title, anchor, target_url, text, role, source_roles, config
            )
            # Incorporate prior classifier's broad scheme evidence without allowing
            # it to override call exclusion.
            scheme_score = clamp(scheme_score + min(0.18, classifier_scheme_evidence * 0.18))
            programme_score = clamp(programme_score + min(0.18, classifier_scheme_evidence * 0.18))
            reasons.extend(entity_reasons)
            top_score = max(scheme_score, programme_score)
            margin = abs(scheme_score - programme_score)
            threshold = safe_float(config.get("possible_candidate_threshold"), 0.66)
            if top_score >= threshold:
                if margin < 0.08:
                    # Use category role and explicit title term as tie breakers.
                    if "PROGRAMME_CATEGORY_INDEX" in source_roles or re.search(r"\b(programme|program|mission|initiative)\b", lower(title)):
                        proposed_type = "PROGRAMME"
                        classification = "POSSIBLE_NEW_PROGRAMME"
                    elif "SCHEME_CATEGORY_INDEX" in source_roles or re.search(r"\b(scheme|fellowship|scholarship|award)\b", lower(title)):
                        proposed_type = "SCHEME"
                        classification = "POSSIBLE_NEW_SCHEME"
                    else:
                        proposed_type = "UNRESOLVED"
                        classification = "UNRESOLVED"
                        review_flags.append("SCHEME_PROGRAMME_TYPE_AMBIGUOUS")
                elif scheme_score > programme_score:
                    proposed_type = "SCHEME"
                    classification = "POSSIBLE_NEW_SCHEME"
                else:
                    proposed_type = "PROGRAMME"
                    classification = "POSSIBLE_NEW_PROGRAMME"
                confidence = top_score
                if classification.startswith("POSSIBLE_NEW"):
                    review_flags.append("NEW_PERMANENT_ENTITY_REQUIRES_V3_4_0_4_CURATION")
                    if classifier_confidence < 0.70:
                        review_flags.append("SOURCE_PAGE_ROLE_CONFIDENCE_BELOW_0_70")
            else:
                proposed_type = "UNRESOLVED"
                classification = "UNRESOLVED"
                confidence = max(0.30, top_score)
                review_flags.append("INSUFFICIENT_PERMANENT_ENTITY_EVIDENCE")
            reasons.append(f"SCHEME_SCORE={scheme_score:.3f}")
            reasons.append(f"PROGRAMME_SCORE={programme_score:.3f}")

    if classification not in GAP_CLASSIFICATIONS:
        classification = "UNRESOLVED"
        review_flags.append("INTERNAL_INVALID_CLASSIFICATION_RECOVERED")

    row: dict[str, Any] = {
        "unique_gap_id": unique_id,
        "normalized_target_url": group.normalized_target_url,
        "target_url": target_url,
        "target_page_id": first_value(page or {}, "classified_page_id", "page_id"),
        "target_page_title": title,
        "target_page_role": role,
        "target_page_role_confidence": f"{classifier_confidence:.4f}",
        "anchor_text_primary": anchors[0] if anchors else "",
        "anchor_text_variants": " | ".join(anchors),
        "source_category_titles": " | ".join(source_titles),
        "source_category_roles": " | ".join(source_roles),
        "occurrence_count": len(occurrences),
        "inbound_link_count": inbound_counts.get(group.normalized_target_url, 0),
        "gap_classification": classification,
        "proposed_entity_type": proposed_type,
        "classification_confidence": f"{clamp(confidence):.4f}",
        "classification_reasons": " | ".join(dict.fromkeys(reasons)),
        "review_flags": " | ".join(sorted(set(review_flags))),
        "requires_admin_review": "1" if classification.startswith("POSSIBLE_NEW") or classification in {"UNRESOLVED", "BROKEN_OR_MISSING_TARGET"} else "0",
        "existing_provisional_entity_id": entity_id(existing or {}),
        "existing_provisional_entity_name": entity_name(existing or {}),
        "existing_provisional_entity_type": first_value(existing or {}, "_entity_type"),
        "main_text_excerpt": collapse_ws(text)[: safe_int(config.get("maximum_excerpt_length"), 600)],
        "identity_safeguard": "DISCOVERY_CANDIDATE_ONLY_NO_CANONICAL_IDENTITY_CREATED",
        "consolidated_at": utc_now(),
    }
    return row


def build_inbound_counts(links: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in links:
        target = normalize_url(first_value(row, "normalized_to_url", "to_url", "target_url"), config)
        if target:
            counts[target] += 1
    return dict(counts)


def consolidate(
    review_rows: Sequence[Mapping[str, Any]],
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
    pages: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> ConsolidationResult:
    gap_rows = [row for row in review_rows if upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP"]
    groups, duplicates = aggregate_gaps(gap_rows, config)
    page_index = build_page_index(pages, config)
    source_page_index = page_index
    entities = provisional_entity_rows(schemes, programmes)
    entity_by_url, entity_by_name = build_entity_indexes(entities, aliases, config)
    inbound_counts = build_inbound_counts(links, config)

    unique_gaps: list[dict[str, Any]] = []
    scheme_candidates: list[dict[str, Any]] = []
    programme_candidates: list[dict[str, Any]] = []
    non_entity: list[dict[str, Any]] = []
    existing_matches: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for group in groups:
        row = classify_group(
            group,
            page_index,
            entity_by_url,
            entity_by_name,
            source_page_index,
            inbound_counts,
            config,
        )
        unique_gaps.append(row)
        classification = row["gap_classification"]
        if classification == "POSSIBLE_NEW_SCHEME":
            scheme_candidates.append(row)
        elif classification == "POSSIBLE_NEW_PROGRAMME":
            programme_candidates.append(row)
        elif classification == "EXISTING_PROVISIONAL_ENTITY":
            existing_matches.append(row)
        elif classification in {
            "CALL_OR_TEMPORARY_OPPORTUNITY",
            "SUPPORTING_PAGE",
            "NAVIGATION_OR_INDEX_LINK",
            "NON_SCHEME_PAGE",
        }:
            non_entity.append(row)
        if row["requires_admin_review"] == "1":
            recommended = {
                "POSSIBLE_NEW_SCHEME": "VERIFY_AS_MISSING_PERMANENT_SCHEME_THEN_ADD_TO_V3_4_0_4_CURATION",
                "POSSIBLE_NEW_PROGRAMME": "VERIFY_AS_MISSING_PERMANENT_PROGRAMME_THEN_ADD_TO_V3_4_0_4_CURATION",
                "BROKEN_OR_MISSING_TARGET": "VERIFY_URL_OR_RESTORE_MISSING_OFFICIAL_PAGE_EVIDENCE",
                "UNRESOLVED": "REVIEW_PAGE_TEXT_AND_CATEGORY_CONTEXT",
            }.get(classification, "REVIEW")
            review.append({
                "review_id": stable_id("dst_gap_review", row["unique_gap_id"]),
                "unique_gap_id": row["unique_gap_id"],
                "review_type": classification,
                "proposed_name": row["target_page_title"] or row["anchor_text_primary"],
                "proposed_entity_type": row["proposed_entity_type"],
                "classification_confidence": row["classification_confidence"],
                "review_flags": row["review_flags"],
                "classification_reasons": row["classification_reasons"],
                "target_url": row["target_url"],
                "source_category_titles": row["source_category_titles"],
                "recommended_action": recommended,
            })
        audit.append({
            "audit_id": stable_id("dst_gap_audit", row["unique_gap_id"]),
            "unique_gap_id": row["unique_gap_id"],
            "target_url": row["target_url"],
            "gap_classification": classification,
            "confidence": row["classification_confidence"],
            "occurrence_count": row["occurrence_count"],
            "target_page_role": row["target_page_role"],
            "classification_reasons": row["classification_reasons"],
            "review_flags": row["review_flags"],
            "identity_safeguard": row["identity_safeguard"],
        })

    return ConsolidationResult(
        unique_gaps=unique_gaps,
        scheme_candidates=scheme_candidates,
        programme_candidates=programme_candidates,
        duplicates=duplicates,
        non_entity=non_entity,
        existing_matches=existing_matches,
        review=review,
        audit=audit,
    )


def validate(
    input_review_rows: Sequence[Mapping[str, Any]],
    result: ConsolidationResult,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    input_gap_rows = [row for row in input_review_rows if upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP"]
    unique = result.unique_gaps
    candidate_rows = result.scheme_candidates + result.programme_candidates
    classifications = [first_value(row, "gap_classification") for row in unique]
    invalid_classifications = [value for value in classifications if value not in GAP_CLASSIFICATIONS]
    possible_call_contamination = sum(
        upper(row.get("target_page_role")) in CALL_ROLES
        or first_value(row, "gap_classification") == "CALL_OR_TEMPORARY_OPPORTUNITY"
        for row in candidate_rows
    )
    duplicate_candidate_urls = len(candidate_rows) - len({first_value(row, "normalized_target_url") for row in candidate_rows})
    existing_candidate_overlap = sum(bool(first_value(row, "existing_provisional_entity_id")) for row in candidate_rows)
    forbidden_fields = sorted({field for row in candidate_rows for field in row if field in FORBIDDEN_IDENTITY_FIELDS})
    unresolved = sum(value in {"UNRESOLVED", "BROKEN_OR_MISSING_TARGET"} for value in classifications)
    unresolved_rate = unresolved / len(unique) if unique else 0.0
    max_unresolved_rate = safe_float(config.get("maximum_unresolved_rate"), 0.30)
    occurrence_total = sum(safe_int(row.get("occurrence_count")) for row in unique)

    checks = {
        "all_input_gap_occurrences_accounted_for": occurrence_total == len(input_gap_rows),
        "unique_gap_urls_unique": len(unique) == len({first_value(row, "normalized_target_url") for row in unique}),
        "all_unique_gaps_classified": all(classifications),
        "gap_classifications_valid": not invalid_classifications,
        "duplicate_rows_accounted_for": len(result.duplicates) == max(0, len(input_gap_rows) - len(unique)),
        "possible_candidates_have_unique_urls": duplicate_candidate_urls == 0,
        "possible_candidates_not_existing_entities": existing_candidate_overlap == 0,
        "call_pages_not_proposed_as_permanent_entities": possible_call_contamination == 0,
        "forbidden_identity_fields_absent": not forbidden_fields,
        "canonical_scheme_identity_created": False,
        "identity_locked": False,
        "unresolved_rate_within_limit": unresolved_rate <= max_unresolved_rate,
    }
    validation_passed = all(
        value for key, value in checks.items()
        if key not in {"canonical_scheme_identity_created", "identity_locked"}
    ) and checks["canonical_scheme_identity_created"] is False and checks["identity_locked"] is False

    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "generated_at": utc_now(),
        "counts": {
            "input_review_rows": len(input_review_rows),
            "input_category_gap_rows": len(input_gap_rows),
            "unique_category_gaps": len(unique),
            "duplicate_gap_occurrences": len(result.duplicates),
            "possible_new_schemes": len(result.scheme_candidates),
            "possible_new_programmes": len(result.programme_candidates),
            "existing_entity_matches": len(result.existing_matches),
            "non_entity_gaps": len(result.non_entity),
            "admin_review_rows": len(result.review),
            "unresolved_unique_gaps": unresolved,
        },
        "quality": {
            "unresolved_rate": round(unresolved_rate, 6),
            "maximum_unresolved_rate": max_unresolved_rate,
            "invalid_classifications": invalid_classifications,
            "possible_call_contamination": possible_call_contamination,
            "duplicate_candidate_urls": duplicate_candidate_urls,
            "existing_candidate_overlap": existing_candidate_overlap,
            "forbidden_identity_fields_found": forbidden_fields,
        },
        "checks": checks,
        "gap_validation_passed": validation_passed,
        "ready_for_v3_4_0_4": validation_passed,
    }


def build_summary(
    result: ConsolidationResult,
    validation: Mapping[str, Any],
    input_dir: Path,
    output_dir: Path,
    classifier_dir: Path,
    link_graph_path: Path,
) -> dict[str, Any]:
    classification_counts = Counter(first_value(row, "gap_classification") for row in result.unique_gaps)
    source_role_counts = Counter()
    for row in result.unique_gaps:
        for role in first_value(row, "source_category_roles").split(" | "):
            if role:
                source_role_counts[role] += 1
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "completed_at": utc_now(),
        "input_dir": str(input_dir),
        "classifier_dir": str(classifier_dir),
        "link_graph": str(link_graph_path),
        "output_dir": str(output_dir),
        "network_access_used": False,
        "recrawl_performed": False,
        "identity_safeguard": {
            "canonical_scheme_identity_created": False,
            "identity_locked": False,
            "call_pages_used_as_permanent_candidates": False,
            "description": "Category gaps are consolidated into discovery candidates only; v3.4.0.4 must curate and lock permanent identities.",
        },
        "counts": validation.get("counts", {}),
        "gap_classification_counts": dict(sorted(classification_counts.items())),
        "source_category_role_counts": dict(sorted(source_role_counts.items())),
        "gap_validation_passed": validation.get("gap_validation_passed", False),
        "ready_for_v3_4_0_4": validation.get("ready_for_v3_4_0_4", False),
        "outputs": {
            "unique_gaps": UNIQUE_OUTPUT,
            "possible_new_schemes": SCHEME_CANDIDATES_OUTPUT,
            "possible_new_programmes": PROGRAMME_CANDIDATES_OUTPUT,
            "duplicates": DUPLICATES_OUTPUT,
            "non_scheme_pages": NON_ENTITY_OUTPUT,
            "existing_entity_matches": EXISTING_MATCHES_OUTPUT,
            "review_queue": REVIEW_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def write_outputs(output_dir: Path, result: ConsolidationResult, validation: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / UNIQUE_OUTPUT, result.unique_gaps)
    write_csv(output_dir / SCHEME_CANDIDATES_OUTPUT, result.scheme_candidates)
    write_csv(output_dir / PROGRAMME_CANDIDATES_OUTPUT, result.programme_candidates)
    write_csv(output_dir / DUPLICATES_OUTPUT, result.duplicates)
    write_csv(output_dir / NON_ENTITY_OUTPUT, result.non_entity)
    write_csv(output_dir / EXISTING_MATCHES_OUTPUT, result.existing_matches)
    write_csv(output_dir / REVIEW_OUTPUT, result.review)
    write_csv(output_dir / AUDIT_OUTPUT, result.audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)


def resolve_paths(project_root: Path) -> tuple[Path, Path, Path, Path, Path]:
    inventory_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3"
    classifier_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_2"
    crawl_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    output_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_1"
    link_graph = crawl_dir / LINK_GRAPH_INPUT
    return inventory_dir, classifier_dir, crawl_dir, output_dir, link_graph


def run_pipeline(project_root: Path, config: Mapping[str, Any], dry_run: bool = False) -> tuple[ConsolidationResult | None, dict[str, Any]]:
    inventory_dir, classifier_dir, _crawl_dir, output_dir, link_graph_path = resolve_paths(project_root)
    review_rows = read_csv(inventory_dir / REVIEW_INPUT)
    schemes = read_csv(inventory_dir / SCHEME_INPUT)
    programmes = read_csv(inventory_dir / PROGRAMME_INPUT)
    aliases = read_csv(inventory_dir / ALIAS_INPUT, required=False)
    pages = read_csv(classifier_dir / CLASSIFIED_PAGES_INPUT)
    links = read_csv(link_graph_path)

    if dry_run:
        gap_count = sum(upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP" for row in review_rows)
        payload = {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "network_access_used": False,
            "recrawl_performed": False,
            "files_written": False,
            "inputs": {
                "review_rows": len(review_rows),
                "category_gap_rows": gap_count,
                "provisional_schemes": len(schemes),
                "provisional_programmes": len(programmes),
                "alias_candidates": len(aliases),
                "classified_pages": len(pages),
                "link_graph_rows": len(links),
            },
            "output_dir": str(output_dir),
        }
        return None, payload

    result = consolidate(review_rows, schemes, programmes, aliases, pages, links, config)
    validation = validate(review_rows, result, config)
    summary = build_summary(result, validation, inventory_dir, output_dir, classifier_dir, link_graph_path)
    write_outputs(output_dir, result, validation, summary)
    return result, summary


def self_test() -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    review_rows = [
        {
            "review_id": "r1", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Existing Science Programme",
            "source_page_title": "Research & Development Programmes",
            "source_url": "https://dst.gov.in/existing-science-programme",
        },
        {
            "review_id": "r2", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Existing Programme",
            "source_page_title": "Programmes and Initiatives",
            "source_url": "https://dst.gov.in/existing-science-programme/",
        },
        {
            "review_id": "r3", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Young Scientist Fellowship Scheme",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/young-scientist-fellowship-scheme",
        },
        {
            "review_id": "r4", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "National Advanced Materials Programme",
            "source_page_title": "Research & Development Programmes",
            "source_url": "https://dst.gov.in/national-advanced-materials-programme",
        },
        {
            "review_id": "r5", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Call for Proposals 2026 under Existing Science Programme",
            "source_page_title": "Research & Development Programmes",
            "source_url": "https://dst.gov.in/callforproposals/existing-2026",
        },
        {
            "review_id": "r6", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Guidelines",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/guidelines",
        },
        {
            "review_id": "r7", "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Mystery Link",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/missing-page",
        },
        {"review_id": "p1", "review_type": "PROVISIONAL_IDENTITY"},
    ]
    schemes: list[dict[str, str]] = []
    programmes = [{
        "provisional_entity_id": "dst_programme_existing",
        "proposed_canonical_name": "Existing Science Programme",
        "official_source_url": "https://dst.gov.in/existing-science-programme",
    }]
    aliases: list[dict[str, str]] = []
    pages = [
        {
            "page_id": "category1", "final_url": "https://dst.gov.in/research-programmes",
            "page_title": "Research & Development Programmes", "page_role": "PROGRAMME_CATEGORY_INDEX",
            "page_role_confidence": "0.95", "main_text": "Programme index",
        },
        {
            "page_id": "category2", "final_url": "https://dst.gov.in/schemes",
            "page_title": "Schemes", "page_role": "SCHEME_CATEGORY_INDEX",
            "page_role_confidence": "0.95", "main_text": "Scheme index",
        },
        {
            "page_id": "existing", "final_url": "https://dst.gov.in/existing-science-programme",
            "page_title": "Existing Science Programme", "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.92", "scheme_evidence_score": "0.80",
            "main_text": "Objectives eligibility funding support how to apply scope researchers duration.",
        },
        {
            "page_id": "scheme", "final_url": "https://dst.gov.in/young-scientist-fellowship-scheme",
            "page_title": "Young Scientist Fellowship Scheme", "page_role": "UNKNOWN",
            "page_role_confidence": "0.60", "scheme_evidence_score": "0.82",
            "main_text": "Objectives eligibility financial assistance how to apply beneficiaries scope duration.",
        },
        {
            "page_id": "programme", "final_url": "https://dst.gov.in/national-advanced-materials-programme",
            "page_title": "National Advanced Materials Programme", "page_role": "UNKNOWN",
            "page_role_confidence": "0.62", "scheme_evidence_score": "0.84",
            "main_text": "Objective eligibility funding support application process scope institutions duration.",
        },
        {
            "page_id": "call", "final_url": "https://dst.gov.in/callforproposals/existing-2026",
            "page_title": "Call for Proposals 2026 under Existing Science Programme",
            "page_role": "CALL_FOR_PROPOSALS", "page_role_confidence": "0.98",
            "call_evidence_score": "0.95", "main_text": "Applications invited. Closing date.",
        },
        {
            "page_id": "guide", "final_url": "https://dst.gov.in/guidelines",
            "page_title": "Guidelines", "page_role": "GUIDELINE_PAGE",
            "page_role_confidence": "0.93", "main_text": "Guidelines and manuals.",
        },
    ]
    links = [
        {"to_url": row.get("source_url", ""), "normalized_to_url": row.get("source_url", "")}
        for row in review_rows if row.get("source_url")
    ]
    result = consolidate(review_rows, schemes, programmes, aliases, pages, links, config)
    validation = validate(review_rows, result, config)
    counts = Counter(row["gap_classification"] for row in result.unique_gaps)
    tests = {
        "duplicate_urls_consolidated": len(result.duplicates) == 1,
        "existing_entity_matched": counts["EXISTING_PROVISIONAL_ENTITY"] == 1,
        "possible_scheme_found": counts["POSSIBLE_NEW_SCHEME"] == 1,
        "possible_programme_found": counts["POSSIBLE_NEW_PROGRAMME"] == 1,
        "call_excluded": counts["CALL_OR_TEMPORARY_OPPORTUNITY"] == 1,
        "supporting_page_excluded": counts["SUPPORTING_PAGE"] == 1,
        "missing_target_reviewed": counts["BROKEN_OR_MISSING_TARGET"] == 1,
        "call_not_proposed_as_permanent": validation["quality"]["possible_call_contamination"] == 0,
        "identity_not_locked": validation["checks"]["identity_locked"] is False,
        "canonical_identity_not_created": validation["checks"]["canonical_scheme_identity_created"] is False,
        "validation_passed": validation["gap_validation_passed"] is True,
    }
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "tests": tests,
        "self_test_passed": all(tests.values()),
        "classification_counts": dict(sorted(counts.items())),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit 3 when validation does not pass.")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["self_test_passed"] else 2
    try:
        config = load_config(args.config)
        _result, payload = run_pipeline(args.project_root.resolve(), config, dry_run=args.dry_run)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.strict and not args.dry_run and not payload.get("gap_validation_passed", False):
            return 3
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "service_version": VERSION,
            "status": "ERROR",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
