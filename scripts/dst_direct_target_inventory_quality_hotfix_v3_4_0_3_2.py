#!/usr/bin/env python3
"""
SSIP v3.4.0.3.2 — DST Direct Target Matching and Provisional Inventory Quality Hotfix

Repairs the v3.4.0.3.1 category-gap join direction and performs a quality
review of every provisional DST scheme/programme before canonical identity
curation.

Safety guarantees
-----------------
* No network access and no DST recrawl.
* All source CSV files remain unchanged.
* CATEGORY_INDEX_DISCOVERY_GAP.source_url is treated as the target URL.
* Category lineage is recovered by reverse-matching link_graph.to_url.
* Call pages, years, rounds, results and temporary opportunities can never
  become permanent scheme/programme candidates.
* Generic, archive, index and supporting pages are removed from the corrected
  lock-candidate inventory.
* No canonical scheme/programme identity is created and no identity is locked.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERSION = "3.4.0.3.2"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

# Inputs
REVIEW_INPUT = "dst_identity_review_queue_v3_4_0_3.csv"
SCHEME_INPUT = "dst_provisional_scheme_inventory_v3_4_0_3.csv"
PROGRAMME_INPUT = "dst_provisional_programme_inventory_v3_4_0_3.csv"
ALIAS_INPUT = "dst_scheme_alias_candidates_v3_4_0_3.csv"
CLASSIFIED_PAGES_INPUT = "dst_classified_pages_v3_4_0_2.csv"
LINK_GRAPH_INPUT = "dst_link_graph_v3_4_0_1.csv"

# Outputs
DIRECT_TARGET_OUTPUT = "dst_direct_target_matches_v3_4_0_3_2.csv"
LINEAGE_OUTPUT = "dst_recovered_category_lineage_v3_4_0_3_2.csv"
EXISTING_GAP_OUTPUT = "dst_existing_entity_gap_matches_v3_4_0_3_2.csv"
NEW_SCHEME_OUTPUT = "dst_possible_new_scheme_pages_v3_4_0_3_2.csv"
NEW_PROGRAMME_OUTPUT = "dst_possible_new_programme_pages_v3_4_0_3_2.csv"
NON_ENTITY_OUTPUT = "dst_gap_non_entity_pages_v3_4_0_3_2.csv"
TRUE_BROKEN_OUTPUT = "dst_true_broken_targets_v3_4_0_3_2.csv"
DUPLICATES_OUTPUT = "dst_gap_duplicates_v3_4_0_3_2.csv"
CORRECTED_SCHEMES_OUTPUT = "dst_corrected_provisional_schemes_v3_4_0_3_2.csv"
CORRECTED_PROGRAMMES_OUTPUT = "dst_corrected_provisional_programmes_v3_4_0_3_2.csv"
DOWNGRADES_OUTPUT = "dst_provisional_entity_downgrades_v3_4_0_3_2.csv"
REVIEW_OUTPUT = "dst_identity_review_queue_v3_4_0_3_2.csv"
AUDIT_OUTPUT = "dst_hotfix_audit_v3_4_0_3_2.csv"
VALIDATION_OUTPUT = "dst_hotfix_validation_v3_4_0_3_2.json"
SUMMARY_OUTPUT = "dst_hotfix_summary_v3_4_0_3_2.json"

FORBIDDEN_IDENTITY_FIELDS = {
    "canonical_scheme_name",
    "canonical_programme_name",
    "locked_scheme_name",
    "locked_programme_name",
    "scheme_id",
    "programme_id",
    "identity_locked",
    "identity_lock_status",
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
INDEX_ROLES = {
    "SCHEME_CATEGORY_INDEX",
    "PROGRAMME_CATEGORY_INDEX",
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
NON_SCHEME_ROLES = {
    "NEWS",
    "EVENT",
    "RECRUITMENT",
    "NON_SCHEME",
}
MASTER_ROLES = {
    "SCHEME_MASTER_CANDIDATE",
    "PROGRAMME_MASTER_CANDIDATE",
}

GAP_CLASSIFICATIONS = {
    "EXISTING_PROVISIONAL_ENTITY",
    "POSSIBLE_NEW_SCHEME",
    "POSSIBLE_NEW_PROGRAMME",
    "CATEGORY_OR_INDEX_PAGE",
    "SUPPORTING_PAGE",
    "ACCESSIBILITY_OR_NAVIGATION_PAGE",
    "CALL_OR_TEMPORARY_OPPORTUNITY",
    "NEWS_EVENT_OR_RECRUITMENT",
    "BROKEN_OFFICIAL_LINK",
    "UNRESOLVED",
}

ENTITY_QUALITY_DECISIONS = {
    "KEEP_AS_PROVISIONAL_SCHEME",
    "KEEP_AS_PROVISIONAL_PROGRAMME",
    "RECLASSIFY_SCHEME_TO_PROGRAMME",
    "RECLASSIFY_PROGRAMME_TO_SCHEME",
    "DOWNGRADE_TO_CATEGORY_INDEX",
    "DOWNGRADE_TO_SUPPORTING_PAGE",
    "DOWNGRADE_TO_ARCHIVE",
    "DOWNGRADE_TO_CALL_OR_TEMPORARY_PAGE",
    "DOWNGRADE_TO_NON_SCHEME_PAGE",
    "ADMIN_REVIEW",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "minimum_direct_target_match_rate": 0.95,
    "maximum_unresolved_rate": 0.10,
    "possible_candidate_threshold": 0.68,
    "strong_candidate_threshold": 0.80,
    "entity_keep_threshold": 0.62,
    "entity_admin_review_threshold": 0.48,
    "fuzzy_existing_name_threshold": 0.97,
    "maximum_excerpt_length": 700,
    "maximum_lineage_rows_per_target": 30,
    "tracking_query_parameters": [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "_ga", "_gl",
    ],
    "generic_entity_names": [
        "archive",
        "about the schemes",
        "about schemes",
        "schemes programmes",
        "schemes programs",
        "funding mechanism",
        "introduction",
        "overview",
        "about dst",
        "mandate",
        "vision mission",
        "application guidance",
        "contact",
        "contact us",
        "screen reader access",
        "accessibility",
        "home",
        "site map",
        "sitemap",
    ],
    "ambiguous_index_names": [
        "fellowship opportunities for researchers",
        "funding opportunities",
        "research opportunities",
        "schemes for researchers",
        "programmes and initiatives",
    ],
    "archive_terms": ["archive", "archived", "old website", "previous years"],
    "accessibility_terms": [
        "screen reader", "accessibility", "skip to main content", "font size",
        "contrast", "language", "hindi", "english",
    ],
    "supporting_terms": [
        "about us", "about dst", "introduction", "mandate",
        "funding mechanism", "how to apply", "application guidance", "contact",
        "guidelines", "manual", "faq", "frequently asked", "office memorandum",
    ],
    "navigation_url_terms": [
        "/screen-reader-access", "/about_us", "/about-us/", "/introduction",
        "/vision-mission", "/contact", "/sitemap", "/archive", "/search",
        "/taxonomy/", "/whatsnew", "/news", "/event", "/recruitment",
    ],
    "call_terms": [
        "call for proposal", "call for proposals", "call for project proposals",
        "applications invited", "application invited", "inviting applications",
        "expression of interest", "eoi", "deadline extension", "last date extended",
        "corrigendum", "addendum", "result", "selected proposals", "shortlisted",
        "apply now", "submission deadline", "closing date", "open call", "special call",
        "joint call", "current call", "request for proposal", "rfp",
    ],
    "call_url_terms": [
        "/call-for-proposals", "/callforproposals/", "/archive-call-for-proposals",
        "/announcement/applications", "/results", "/corrigendum",
    ],
    "scheme_terms": [
        "scheme", "fellowship", "scholarship", "award", "grant", "assistance",
        "support scheme", "funding scheme", "research grant", "travel support",
    ],
    "programme_terms": [
        "programme", "program", "mission", "initiative", "platform", "network",
        "facility", "facilities", "cooperation", "capacity building", "research council",
        "hub", "centre", "center", "technology mission", "national programme",
    ],
    "master_evidence_terms": {
        "objective": ["objective", "objectives", "aims to", "purpose"],
        "eligibility": ["eligibility", "eligible", "who can apply"],
        "benefit": ["financial assistance", "funding support", "grant", "support provided"],
        "application": ["how to apply", "application process", "application procedure"],
        "scope": ["scope", "thrust areas", "focus areas", "areas of support"],
        "beneficiary": ["beneficiaries", "researchers", "scientists", "institutions"],
        "duration": ["duration", "tenure", "period of support"],
        "authority": ["department of science and technology", "division", "implemented by"],
    },
}


@dataclass
class GapGroup:
    normalized_target_url: str
    occurrences: list[dict[str, str]] = field(default_factory=list)


@dataclass
class HotfixResult:
    direct_targets: list[dict[str, Any]]
    lineage: list[dict[str, Any]]
    existing_matches: list[dict[str, Any]]
    new_schemes: list[dict[str, Any]]
    new_programmes: list[dict[str, Any]]
    non_entity: list[dict[str, Any]]
    true_broken: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
    corrected_schemes: list[dict[str, Any]]
    corrected_programmes: list[dict[str, Any]]
    downgrades: list[dict[str, Any]]
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
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def first_value(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = collapse_ws(row.get(name))
        if value:
            return value
    return ""


def normalize_name(value: str) -> str:
    text = html.unescape(collapse_ws(value)).casefold()
    text = text.replace("&", " and ")
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
    scheme = (parts.scheme or "https").casefold()
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
            writer.writerow({key: row.get(key, "") for key in fieldnames})
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


def page_text(row: Mapping[str, Any]) -> str:
    return first_value(row, "main_text", "text_excerpt")


def build_page_index(
    pages: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for row in pages:
        for field in ("requested_url", "normalized_url", "final_url", "canonical_url"):
            normalized = normalize_url(first_value(row, field), config)
            if normalized:
                index[normalized] = row
    return index


def provisional_entity_rows(
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source, entity_type in ((schemes, "SCHEME"), (programmes, "PROGRAMME")):
        for row in source:
            item = dict(row)
            item["_original_entity_type"] = entity_type
            output.append(item)
    return output


def entity_id(row: Mapping[str, Any]) -> str:
    return first_value(row, "provisional_entity_id")


def entity_name(row: Mapping[str, Any]) -> str:
    return first_value(row, "proposed_canonical_name")


def entity_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "official_source_url", "primary_source_url", "source_url")


def alias_text(row: Mapping[str, Any]) -> str:
    return first_value(row, "alias_text", "alias_name", "alias_candidate")


def build_entity_indexes(
    entities: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    by_url: dict[str, Mapping[str, Any]] = {}
    by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_id = {entity_id(row): row for row in entities if entity_id(row)}
    for row in entities:
        url = normalize_url(entity_url(row), config)
        if url:
            by_url[url] = row
        name_key = normalize_name(entity_name(row))
        if name_key:
            by_name[name_key].append(row)
        abbreviation = normalize_name(first_value(row, "official_abbreviation_candidate"))
        if abbreviation:
            by_name[abbreviation].append(row)
    for row in aliases:
        parent = by_id.get(first_value(row, "provisional_entity_id"))
        if not parent:
            continue
        key = normalize_name(alias_text(row))
        if key:
            by_name[key].append(parent)
    return by_url, by_name


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    haystack = lower(text)
    return [collapse_ws(term) for term in terms if lower(term) and lower(term) in haystack]


def has_call_evidence(title: str, url: str, text: str, role: str, config: Mapping[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    head = f"{title} {url}"
    title_matches = contains_any(head, config.get("call_terms", []))
    url_matches = contains_any(url, config.get("call_url_terms", []))
    text_matches = contains_any(text[:3500], config.get("call_terms", []))
    if role in CALL_ROLES:
        score += 0.78
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    if title_matches:
        score += min(0.44, 0.13 * len(title_matches))
        reasons.append("CALL_TERMS_IN_TITLE_OR_URL:" + ",".join(title_matches[:5]))
    if url_matches:
        score += min(0.30, 0.11 * len(url_matches))
        reasons.append("CALL_URL_PATTERN:" + ",".join(url_matches[:4]))
    if text_matches:
        score += min(0.20, 0.05 * len(text_matches))
        reasons.append("CALL_TERMS_IN_TEXT:" + ",".join(text_matches[:4]))
    if re.search(r"\b20(?:1\d|2\d)\b", head) and (title_matches or role in CALL_ROLES):
        score += 0.08
        reasons.append("TEMPORAL_YEAR_WITH_CALL_EVIDENCE")
    return clamp(score), reasons


def evidence_categories(text: str, config: Mapping[str, Any]) -> tuple[int, dict[str, int], list[str]]:
    categories: dict[str, int] = {}
    reasons: list[str] = []
    for category, terms in config.get("master_evidence_terms", {}).items():
        count = sum(1 for term in terms if lower(term) in lower(text))
        categories[category] = count
        if count:
            reasons.append(f"MASTER_EVIDENCE_{category.upper()}")
    present = sum(1 for count in categories.values() if count > 0)
    return present, categories, reasons


def is_generic_name(name: str, config: Mapping[str, Any]) -> bool:
    normalized = normalize_name(name)
    return normalized in {normalize_name(item) for item in config.get("generic_entity_names", [])}


def is_ambiguous_index_name(name: str, config: Mapping[str, Any]) -> bool:
    normalized = normalize_name(name)
    return normalized in {normalize_name(item) for item in config.get("ambiguous_index_names", [])}


def is_archive_page(name: str, url: str, role: str, config: Mapping[str, Any]) -> bool:
    if role == "CALL_ARCHIVE_INDEX":
        return True
    combined = f"{name} {url}"
    return bool(contains_any(combined, config.get("archive_terms", [])))


def classify_supporting_or_navigation(name: str, url: str, role: str, text: str, config: Mapping[str, Any]) -> tuple[str | None, float, list[str]]:
    reasons: list[str] = []
    combined = f"{name} {url} {text[:1200]}"
    head = f"{name} {url}"
    accessibility = contains_any(combined, config.get("accessibility_terms", []))
    # Supporting-page terms are evaluated against the title/URL only. Permanent
    # scheme pages legitimately contain phrases such as "how to apply" and
    # must not be downgraded merely because those phrases occur in body text.
    supporting = contains_any(head, config.get("supporting_terms", []))
    nav_url = contains_any(url, config.get("navigation_url_terms", []))
    if accessibility:
        reasons.append("ACCESSIBILITY_OR_NAVIGATION_EVIDENCE:" + ",".join(accessibility[:4]))
        return "ACCESSIBILITY_OR_NAVIGATION_PAGE", 0.96, reasons
    if role in INDEX_ROLES:
        reasons.append(f"CLASSIFIER_ROLE_{role}")
        return "CATEGORY_OR_INDEX_PAGE", 0.97, reasons
    if role in SUPPORTING_ROLES:
        reasons.append(f"CLASSIFIER_ROLE_{role}")
        return "SUPPORTING_PAGE", 0.94, reasons
    if is_archive_page(name, url, role, config):
        reasons.append("ARCHIVE_PAGE_EVIDENCE")
        return "CATEGORY_OR_INDEX_PAGE", 0.94, reasons
    if is_generic_name(name, config):
        reasons.append("GENERIC_NON_ENTITY_TITLE")
        if "archive" in lower(name):
            return "CATEGORY_OR_INDEX_PAGE", 0.95, reasons
        return "SUPPORTING_PAGE", 0.92, reasons
    if supporting:
        reasons.append("SUPPORTING_PAGE_TERMS:" + ",".join(supporting[:4]))
        return "SUPPORTING_PAGE", 0.84, reasons
    if nav_url:
        reasons.append("NAVIGATION_URL_PATTERN:" + ",".join(nav_url[:4]))
        return "ACCESSIBILITY_OR_NAVIGATION_PAGE", 0.83, reasons
    return None, 0.0, reasons


def infer_entity_scores(
    title: str,
    url: str,
    text: str,
    role: str,
    lineage_roles: Sequence[str],
    prior_scheme_score: float,
    config: Mapping[str, Any],
) -> tuple[float, float, list[str], int]:
    reasons: list[str] = []
    scheme_score = 0.08
    programme_score = 0.08
    title_block = f"{title} {url}"
    scheme_terms = contains_any(title_block, config.get("scheme_terms", []))
    programme_terms = contains_any(title_block, config.get("programme_terms", []))
    if role == "SCHEME_MASTER_CANDIDATE":
        scheme_score += 0.52
        reasons.append("CLASSIFIER_SCHEME_MASTER_CANDIDATE")
    if role == "PROGRAMME_MASTER_CANDIDATE":
        programme_score += 0.52
        reasons.append("CLASSIFIER_PROGRAMME_MASTER_CANDIDATE")
    if scheme_terms:
        scheme_score += min(0.30, 0.11 * len(scheme_terms))
        reasons.append("SCHEME_TERMS:" + ",".join(scheme_terms[:4]))
    if programme_terms:
        programme_score += min(0.30, 0.11 * len(programme_terms))
        reasons.append("PROGRAMME_TERMS:" + ",".join(programme_terms[:4]))
    if "SCHEME_CATEGORY_INDEX" in lineage_roles:
        scheme_score += 0.10
        reasons.append("INBOUND_FROM_SCHEME_CATEGORY_INDEX")
    if "PROGRAMME_CATEGORY_INDEX" in lineage_roles:
        programme_score += 0.10
        reasons.append("INBOUND_FROM_PROGRAMME_CATEGORY_INDEX")
    present, _categories, evidence_reasons = evidence_categories(text, config)
    evidence_bonus = min(0.44, present * 0.065)
    scheme_score += evidence_bonus
    programme_score += evidence_bonus
    reasons.extend(evidence_reasons)
    prior_bonus = min(0.16, max(0.0, prior_scheme_score) * 0.16)
    scheme_score += prior_bonus
    programme_score += prior_bonus
    return clamp(scheme_score), clamp(programme_score), reasons, present


def match_existing_entity(
    target_url: str,
    names: Sequence[str],
    by_url: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str, float]:
    if target_url in by_url:
        return by_url[target_url], "OFFICIAL_SOURCE_URL_EXACT_MATCH", 1.0
    normalized_names = [normalize_name(name) for name in names if normalize_name(name)]
    for name in normalized_names:
        candidates = by_name.get(name, [])
        if candidates:
            return candidates[0], "CANONICAL_ABBREVIATION_OR_ALIAS_EXACT_MATCH", 0.98
    threshold = safe_float(config.get("fuzzy_existing_name_threshold"), 0.97)
    best_score = 0.0
    best_entity: Mapping[str, Any] | None = None
    for name in normalized_names:
        if len(name) < 10:
            continue
        for known, candidates in by_name.items():
            if len(known) < 10 or not candidates:
                continue
            ratio = SequenceMatcher(None, name, known).ratio()
            if ratio > best_score:
                best_score = ratio
                best_entity = candidates[0]
    if best_entity is not None and best_score >= threshold:
        return best_entity, "CANONICAL_OR_ALIAS_HIGH_SIMILARITY", round(best_score, 4)
    return None, "", 0.0


def aggregate_gap_rows(
    review_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[list[GapGroup], list[dict[str, Any]]]:
    groups: dict[str, GapGroup] = {}
    duplicates: list[dict[str, Any]] = []
    gap_rows = [row for row in review_rows if upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP"]
    for raw in gap_rows:
        target_url = first_value(raw, "source_url", "target_url")
        normalized = normalize_url(target_url, config)
        if not normalized:
            normalized = f"missing://{stable_id('gap_missing', first_value(raw, 'review_id'))}"
        item = dict(raw)
        item["interpreted_target_url"] = target_url
        item["normalized_target_url"] = normalized
        if normalized not in groups:
            groups[normalized] = GapGroup(normalized_target_url=normalized)
        else:
            duplicates.append({
                "duplicate_id": stable_id("dst_gap_duplicate", first_value(raw, "review_id"), normalized),
                "review_id": first_value(raw, "review_id"),
                "normalized_target_url": normalized,
                "target_url": target_url,
                "proposed_name": first_value(raw, "proposed_canonical_name"),
                "source_page_title": first_value(raw, "source_page_title"),
                "duplicate_reason": "NORMALIZED_TARGET_URL_ALREADY_SEEN",
            })
        groups[normalized].occurrences.append(item)
    return list(groups.values()), duplicates


def build_reverse_link_index(
    links: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in links:
        target = normalize_url(first_value(row, "normalized_to_url", "to_url"), config)
        if target:
            index[target].append(row)
    return index


def recover_lineage(
    group: GapGroup,
    reverse_links: Mapping[str, Sequence[Mapping[str, Any]]],
    page_index: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    roles: list[str] = []
    category_urls: list[str] = []
    expected_titles = {
        normalize_name(first_value(item, "source_page_title"))
        for item in group.occurrences
        if first_value(item, "source_page_title")
    }
    links = list(reverse_links.get(group.normalized_target_url, []))
    links.sort(key=lambda row: (
        0 if normalize_name(first_value(page_index.get(normalize_url(first_value(row, "from_url"), config), {}), "page_title", "title")) in expected_titles else 1,
        0 if upper(first_value(page_index.get(normalize_url(first_value(row, "from_url"), config), {}), "page_role")) in INDEX_ROLES else 1,
        lower(first_value(row, "from_url")),
    ))
    maximum = safe_int(config.get("maximum_lineage_rows_per_target"), 30)
    for link in links[:maximum]:
        source_url = normalize_url(first_value(link, "from_url"), config)
        source_page = page_index.get(source_url, {})
        source_title = page_title(source_page) or first_value(link, "from_url")
        source_role = upper(first_value(source_page, "page_role"))
        if source_role:
            roles.append(source_role)
        if source_url:
            category_urls.append(source_url)
        rows.append({
            "lineage_id": stable_id("dst_gap_lineage", group.normalized_target_url, source_url, first_value(link, "anchor_text")),
            "normalized_target_url": group.normalized_target_url,
            "target_url": first_value(group.occurrences[0], "source_url"),
            "source_page_url": source_url,
            "source_page_title": source_title,
            "source_page_role": source_role,
            "anchor_text": first_value(link, "anchor_text"),
            "role_hint": first_value(link, "role_hint"),
            "in_main_content": first_value(link, "in_main_content"),
            "is_internal": first_value(link, "is_internal"),
            "enqueue_decision": first_value(link, "enqueue_decision"),
            "source_title_matches_review_context": "1" if normalize_name(source_title) in expected_titles else "0",
        })
    return rows, sorted(set(roles)), sorted(set(category_urls))


def classify_gap(
    group: GapGroup,
    page_index: Mapping[str, Mapping[str, Any]],
    reverse_links: Mapping[str, Sequence[Mapping[str, Any]]],
    entity_by_url: Mapping[str, Mapping[str, Any]],
    entity_by_name: Mapping[str, Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    occurrence = group.occurrences[0]
    raw_target_url = first_value(occurrence, "source_url", "target_url")
    proposed_names = sorted({
        first_value(row, "proposed_canonical_name")
        for row in group.occurrences
        if first_value(row, "proposed_canonical_name")
    })
    context_titles = sorted({
        first_value(row, "source_page_title")
        for row in group.occurrences
        if first_value(row, "source_page_title")
    })
    page = page_index.get(group.normalized_target_url)
    lineage_rows, lineage_roles, lineage_urls = recover_lineage(group, reverse_links, page_index, config)
    title = page_title(page or {}) or (proposed_names[0] if proposed_names else "")
    role = upper(first_value(page or {}, "page_role"))
    text = page_text(page or {})
    role_confidence = safe_float(first_value(page or {}, "page_role_confidence"), 0.0)
    prior_scheme_score = safe_float(first_value(page or {}, "scheme_evidence_score"), 0.0)
    prior_call_score = safe_float(first_value(page or {}, "call_evidence_score"), 0.0)
    reasons: list[str] = ["SOURCE_URL_INTERPRETED_AS_TARGET_URL"]
    review_flags: list[str] = []
    entity, entity_method, entity_confidence = match_existing_entity(
        group.normalized_target_url,
        [title, *proposed_names],
        entity_by_url,
        entity_by_name,
        config,
    )

    if entity:
        classification = "EXISTING_PROVISIONAL_ENTITY"
        proposed_type = first_value(entity, "_original_entity_type")
        confidence = entity_confidence
        reasons.append(entity_method)
    elif not page:
        classification = "UNRESOLVED"
        proposed_type = "UNRESOLVED"
        confidence = 0.30
        reasons.append("TARGET_URL_NOT_FOUND_IN_CLASSIFIED_PAGE_INVENTORY")
        review_flags.append("VERIFY_UNCRAWLED_OR_NORMALIZATION_VARIANT")
    elif role == "BROKEN_OFFICIAL_LINK" or safe_int(first_value(page, "http_status"), 200) >= 400:
        classification = "BROKEN_OFFICIAL_LINK"
        proposed_type = "BROKEN"
        confidence = max(0.95, role_confidence)
        reasons.append("CLASSIFIED_OR_HTTP_BROKEN_OFFICIAL_LINK")
    elif role in CALL_ROLES:
        classification = "CALL_OR_TEMPORARY_OPPORTUNITY"
        proposed_type = "CALL"
        confidence = max(0.96, role_confidence, prior_call_score)
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    elif role in NON_SCHEME_ROLES:
        classification = "NEWS_EVENT_OR_RECRUITMENT"
        proposed_type = "NON_SCHEME"
        confidence = max(0.94, role_confidence)
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    else:
        supporting_class, supporting_confidence, supporting_reasons = classify_supporting_or_navigation(
            title, raw_target_url, role, text, config
        )
        if supporting_class:
            classification = supporting_class
            proposed_type = "INDEX" if supporting_class == "CATEGORY_OR_INDEX_PAGE" else "SUPPORTING"
            confidence = max(supporting_confidence, role_confidence)
            reasons.extend(supporting_reasons)
        else:
            call_score, call_reasons = has_call_evidence(title, raw_target_url, text, role, config)
            reasons.extend(call_reasons)
            if max(call_score, prior_call_score) >= 0.62:
                classification = "CALL_OR_TEMPORARY_OPPORTUNITY"
                proposed_type = "CALL"
                confidence = max(call_score, prior_call_score, 0.72)
            else:
                scheme_score, programme_score, score_reasons, evidence_count = infer_entity_scores(
                    title,
                    raw_target_url,
                    text,
                    role,
                    lineage_roles,
                    prior_scheme_score,
                    config,
                )
                reasons.extend(score_reasons)
                top_score = max(scheme_score, programme_score)
                threshold = safe_float(config.get("possible_candidate_threshold"), 0.68)
                margin = abs(scheme_score - programme_score)
                if top_score >= threshold and evidence_count >= 2:
                    if role == "SCHEME_MASTER_CANDIDATE":
                        classification = "POSSIBLE_NEW_SCHEME"
                        proposed_type = "SCHEME"
                    elif role == "PROGRAMME_MASTER_CANDIDATE":
                        classification = "POSSIBLE_NEW_PROGRAMME"
                        proposed_type = "PROGRAMME"
                    elif margin < 0.08:
                        if "PROGRAMME_CATEGORY_INDEX" in lineage_roles or contains_any(title, config.get("programme_terms", [])):
                            classification = "POSSIBLE_NEW_PROGRAMME"
                            proposed_type = "PROGRAMME"
                        elif "SCHEME_CATEGORY_INDEX" in lineage_roles or contains_any(title, config.get("scheme_terms", [])):
                            classification = "POSSIBLE_NEW_SCHEME"
                            proposed_type = "SCHEME"
                        else:
                            classification = "UNRESOLVED"
                            proposed_type = "UNRESOLVED"
                            review_flags.append("SCHEME_PROGRAMME_TYPE_AMBIGUOUS")
                    elif scheme_score > programme_score:
                        classification = "POSSIBLE_NEW_SCHEME"
                        proposed_type = "SCHEME"
                    else:
                        classification = "POSSIBLE_NEW_PROGRAMME"
                        proposed_type = "PROGRAMME"
                    confidence = top_score
                    if classification.startswith("POSSIBLE_NEW"):
                        review_flags.append("REQUIRES_V3_4_0_4_IDENTITY_CURATION")
                else:
                    classification = "UNRESOLVED"
                    proposed_type = "UNRESOLVED"
                    confidence = max(0.30, top_score)
                    review_flags.append("INSUFFICIENT_PERMANENT_ENTITY_EVIDENCE")
                reasons.extend([
                    f"SCHEME_SCORE={scheme_score:.3f}",
                    f"PROGRAMME_SCORE={programme_score:.3f}",
                    f"MASTER_EVIDENCE_CATEGORIES={evidence_count}",
                ])

    if classification not in GAP_CLASSIFICATIONS:
        classification = "UNRESOLVED"
        proposed_type = "UNRESOLVED"
        confidence = 0.25
        review_flags.append("INVALID_CLASSIFICATION_RECOVERED")

    row = {
        "unique_gap_id": stable_id("dst_gap_target", group.normalized_target_url),
        "target_url": raw_target_url,
        "normalized_target_url": group.normalized_target_url,
        "direct_target_match": "1" if page else "0",
        "target_page_id": first_value(page or {}, "classified_page_id", "page_id"),
        "target_page_title": title,
        "target_page_role": role,
        "target_page_role_confidence": f"{role_confidence:.4f}",
        "review_proposed_name": proposed_names[0] if proposed_names else "",
        "review_proposed_name_variants": " | ".join(proposed_names),
        "review_context_titles": " | ".join(context_titles),
        "occurrence_count": len(group.occurrences),
        "reverse_inbound_link_count": len(reverse_links.get(group.normalized_target_url, [])),
        "recovered_source_urls": " | ".join(lineage_urls),
        "recovered_source_roles": " | ".join(lineage_roles),
        "gap_classification": classification,
        "proposed_entity_type": proposed_type,
        "classification_confidence": f"{clamp(confidence):.4f}",
        "classification_reasons": " | ".join(dict.fromkeys(reasons)),
        "review_flags": " | ".join(sorted(set(review_flags))),
        "requires_admin_review": "1" if classification in {"POSSIBLE_NEW_SCHEME", "POSSIBLE_NEW_PROGRAMME", "UNRESOLVED"} else "0",
        "existing_provisional_entity_id": entity_id(entity or {}),
        "existing_provisional_entity_name": entity_name(entity or {}),
        "existing_provisional_entity_type": first_value(entity or {}, "_original_entity_type"),
        "main_text_excerpt": collapse_ws(text)[:safe_int(config.get("maximum_excerpt_length"), 700)],
        "identity_safeguard": "NO_CANONICAL_IDENTITY_CREATED_NO_IDENTITY_LOCKED",
        "processed_at": utc_now(),
    }
    return row, lineage_rows


def audit_entity_quality(
    entity: Mapping[str, Any],
    page_index: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    original_type = first_value(entity, "_original_entity_type")
    name = entity_name(entity)
    url = normalize_url(entity_url(entity), config)
    page = page_index.get(url)
    role = upper(first_value(page or {}, "page_role", "primary_source_page_role"))
    title = page_title(page or {}) or first_value(entity, "primary_source_page_title") or name
    text = page_text(page or {})
    prior_confidence = safe_float(first_value(entity, "identity_confidence"), 0.0)
    prior_evidence = safe_float(first_value(entity, "master_evidence_score"), 0.0)
    reasons: list[str] = []
    flags: list[str] = []
    present, categories, evidence_reasons = evidence_categories(text, config)
    reasons.extend(evidence_reasons)
    call_score, call_reasons = has_call_evidence(name, url, text, role, config)
    reasons.extend(call_reasons)
    generic = is_generic_name(name, config) or is_generic_name(title, config)
    ambiguous_index = is_ambiguous_index_name(name, config)
    archive = is_archive_page(name, url, role, config)
    support_class, support_confidence, support_reasons = classify_supporting_or_navigation(name, url, role, text, config)

    if archive:
        decision = "DOWNGRADE_TO_ARCHIVE"
        final_type = "NON_ENTITY"
        confidence = max(0.96, prior_confidence)
        reasons.append("ARCHIVE_TITLE_OR_ROLE")
    elif role in CALL_ROLES or call_score >= 0.62:
        decision = "DOWNGRADE_TO_CALL_OR_TEMPORARY_PAGE"
        final_type = "NON_ENTITY"
        confidence = max(0.96, call_score, prior_confidence)
        reasons.append("CALL_OR_TEMPORARY_EVIDENCE")
    elif role in NON_SCHEME_ROLES:
        decision = "DOWNGRADE_TO_NON_SCHEME_PAGE"
        final_type = "NON_ENTITY"
        confidence = max(0.94, prior_confidence)
        reasons.append(f"CLASSIFIER_ROLE_{role}")
    elif role in INDEX_ROLES or support_class == "CATEGORY_OR_INDEX_PAGE":
        decision = "DOWNGRADE_TO_CATEGORY_INDEX"
        final_type = "NON_ENTITY"
        confidence = max(0.94, support_confidence, prior_confidence)
        reasons.extend(support_reasons)
    elif generic or support_class in {"SUPPORTING_PAGE", "ACCESSIBILITY_OR_NAVIGATION_PAGE"}:
        decision = "DOWNGRADE_TO_SUPPORTING_PAGE"
        final_type = "NON_ENTITY"
        confidence = max(0.90, support_confidence, prior_confidence)
        reasons.extend(support_reasons)
        reasons.append("GENERIC_OR_SUPPORTING_ENTITY_NAME")
    elif ambiguous_index:
        decision = "ADMIN_REVIEW"
        final_type = original_type
        confidence = max(0.50, prior_confidence)
        flags.append("POSSIBLE_OPPORTUNITY_INDEX_NOT_STANDALONE_SCHEME")
        reasons.append("AMBIGUOUS_OPPORTUNITY_INDEX_NAME")
    elif not page:
        decision = "ADMIN_REVIEW"
        final_type = original_type
        confidence = max(0.40, prior_confidence)
        flags.append("PRIMARY_SOURCE_NOT_FOUND_IN_CLASSIFIED_PAGES")
        reasons.append("NO_DIRECT_PAGE_MATCH")
    else:
        scheme_score, programme_score, score_reasons, _evidence_count = infer_entity_scores(
            title,
            url,
            text,
            role,
            [],
            safe_float(first_value(page, "scheme_evidence_score"), prior_evidence),
            config,
        )
        reasons.extend(score_reasons)
        evidence_strength = max(prior_evidence, min(1.0, present / 6.0))
        quality_score = clamp(
            0.32 * prior_confidence
            + 0.28 * evidence_strength
            + 0.22 * max(scheme_score, programme_score)
            + (0.18 if role in MASTER_ROLES else 0.0)
        )
        keep_threshold = safe_float(config.get("entity_keep_threshold"), 0.62)
        review_threshold = safe_float(config.get("entity_admin_review_threshold"), 0.48)
        explicit_scheme = bool(contains_any(name, config.get("scheme_terms", [])))
        explicit_programme = bool(contains_any(name, config.get("programme_terms", [])))
        if original_type == "SCHEME" and (role == "PROGRAMME_MASTER_CANDIDATE" or (explicit_programme and not explicit_scheme and programme_score > scheme_score + 0.08)):
            decision = "RECLASSIFY_SCHEME_TO_PROGRAMME"
            final_type = "PROGRAMME"
            confidence = max(quality_score, 0.70)
            reasons.append("PROGRAMME_EVIDENCE_OUTWEIGHS_SCHEME_LABEL")
        elif original_type == "PROGRAMME" and (role == "SCHEME_MASTER_CANDIDATE" or (explicit_scheme and not explicit_programme and scheme_score > programme_score + 0.08)):
            decision = "RECLASSIFY_PROGRAMME_TO_SCHEME"
            final_type = "SCHEME"
            confidence = max(quality_score, 0.70)
            reasons.append("SCHEME_EVIDENCE_OUTWEIGHS_PROGRAMME_LABEL")
        elif quality_score >= keep_threshold and present >= 2:
            decision = "KEEP_AS_PROVISIONAL_SCHEME" if original_type == "SCHEME" else "KEEP_AS_PROVISIONAL_PROGRAMME"
            final_type = original_type
            confidence = quality_score
        elif quality_score >= review_threshold:
            decision = "ADMIN_REVIEW"
            final_type = original_type
            confidence = quality_score
            flags.append("PERMANENT_ENTITY_EVIDENCE_REQUIRES_MANUAL_CONFIRMATION")
        else:
            decision = "DOWNGRADE_TO_SUPPORTING_PAGE"
            final_type = "NON_ENTITY"
            confidence = max(0.64, 1.0 - quality_score)
            reasons.append("INSUFFICIENT_PERMANENT_ENTITY_EVIDENCE")
        reasons.extend([
            f"QUALITY_SCORE={quality_score:.3f}",
            f"SCHEME_SCORE={scheme_score:.3f}",
            f"PROGRAMME_SCORE={programme_score:.3f}",
            f"MASTER_EVIDENCE_CATEGORIES={present}",
        ])

    if decision not in ENTITY_QUALITY_DECISIONS:
        decision = "ADMIN_REVIEW"
        final_type = original_type
        confidence = 0.25
        flags.append("INVALID_QUALITY_DECISION_RECOVERED")

    return {
        **{key: value for key, value in entity.items() if not key.startswith("_")},
        "original_proposed_entity_type": original_type,
        "quality_decision": decision,
        "quality_final_entity_type": final_type,
        "quality_confidence": f"{clamp(confidence):.4f}",
        "quality_source_page_match": "1" if page else "0",
        "quality_source_page_role": role,
        "quality_source_page_title": title,
        "quality_master_evidence_category_count": present,
        "quality_master_evidence_categories": json.dumps(categories, ensure_ascii=False, sort_keys=True),
        "quality_reasons": " | ".join(dict.fromkeys(reasons)),
        "quality_review_flags": " | ".join(sorted(set(flags))),
        "quality_requires_admin_review": "1" if decision == "ADMIN_REVIEW" else "0",
        "identity_state": "PROVISIONAL_NOT_LOCKED",
        "identity_safeguard": "QUALITY_AUDITED_NO_CANONICAL_IDENTITY_CREATED_NO_LOCK",
        "quality_audited_at": utc_now(),
    }


def corrected_entity_row(audit_row: Mapping[str, Any], final_type: str) -> dict[str, Any]:
    output = dict(audit_row)
    output["proposed_entity_type"] = final_type
    output["curation_status"] = "QUALITY_AUDITED_REQUIRES_V3_4_0_4"
    output["identity_state"] = "PROVISIONAL_NOT_LOCKED"
    return output


def process_hotfix(
    review_rows: Sequence[Mapping[str, Any]],
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
    pages: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> HotfixResult:
    page_index = build_page_index(pages, config)
    entities = provisional_entity_rows(schemes, programmes)
    entity_by_url, entity_by_name = build_entity_indexes(entities, aliases, config)
    reverse_links = build_reverse_link_index(links, config)
    groups, duplicates = aggregate_gap_rows(review_rows, config)

    direct_targets: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    existing_matches: list[dict[str, Any]] = []
    new_schemes: list[dict[str, Any]] = []
    new_programmes: list[dict[str, Any]] = []
    non_entity: list[dict[str, Any]] = []
    true_broken: list[dict[str, Any]] = []
    corrected_schemes: list[dict[str, Any]] = []
    corrected_programmes: list[dict[str, Any]] = []
    downgrades: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for group in groups:
        row, lineage_rows = classify_gap(
            group,
            page_index,
            reverse_links,
            entity_by_url,
            entity_by_name,
            config,
        )
        direct_targets.append(row)
        lineage.extend(lineage_rows)
        classification = first_value(row, "gap_classification")
        if classification == "EXISTING_PROVISIONAL_ENTITY":
            existing_matches.append(row)
        elif classification == "POSSIBLE_NEW_SCHEME":
            new_schemes.append(row)
        elif classification == "POSSIBLE_NEW_PROGRAMME":
            new_programmes.append(row)
        elif classification == "BROKEN_OFFICIAL_LINK":
            true_broken.append(row)
        elif classification in {
            "CATEGORY_OR_INDEX_PAGE",
            "SUPPORTING_PAGE",
            "ACCESSIBILITY_OR_NAVIGATION_PAGE",
            "CALL_OR_TEMPORARY_OPPORTUNITY",
            "NEWS_EVENT_OR_RECRUITMENT",
        }:
            non_entity.append(row)
        if first_value(row, "requires_admin_review") == "1":
            action = {
                "POSSIBLE_NEW_SCHEME": "VERIFY_AND_ADD_TO_V3_4_0_4_SCHEME_CURATION",
                "POSSIBLE_NEW_PROGRAMME": "VERIFY_AND_ADD_TO_V3_4_0_4_PROGRAMME_CURATION",
                "UNRESOLVED": "REVIEW_TARGET_PAGE_AND_CATEGORY_CONTEXT",
            }.get(classification, "REVIEW")
            review.append({
                "review_id": stable_id("dst_gap_review", first_value(row, "unique_gap_id")),
                "review_type": f"GAP_{classification}",
                "provisional_entity_id": "",
                "proposed_name": first_value(row, "target_page_title", "review_proposed_name"),
                "proposed_entity_type": first_value(row, "proposed_entity_type"),
                "confidence": first_value(row, "classification_confidence"),
                "review_flags": first_value(row, "review_flags"),
                "evidence": first_value(row, "classification_reasons"),
                "source_url": first_value(row, "target_url"),
                "recommended_action": action,
            })
        audit.append({
            "audit_id": stable_id("dst_hotfix_gap_audit", first_value(row, "unique_gap_id")),
            "audit_type": "CATEGORY_GAP_DIRECT_TARGET",
            "record_id": first_value(row, "unique_gap_id"),
            "record_name": first_value(row, "target_page_title"),
            "record_url": first_value(row, "target_url"),
            "decision": classification,
            "confidence": first_value(row, "classification_confidence"),
            "reasons": first_value(row, "classification_reasons"),
            "identity_safeguard": first_value(row, "identity_safeguard"),
        })

    for entity in entities:
        quality = audit_entity_quality(entity, page_index, config)
        decision = first_value(quality, "quality_decision")
        final_type = first_value(quality, "quality_final_entity_type")
        if decision in {"KEEP_AS_PROVISIONAL_SCHEME", "RECLASSIFY_PROGRAMME_TO_SCHEME"}:
            corrected_schemes.append(corrected_entity_row(quality, "SCHEME"))
        elif decision in {"KEEP_AS_PROVISIONAL_PROGRAMME", "RECLASSIFY_SCHEME_TO_PROGRAMME"}:
            corrected_programmes.append(corrected_entity_row(quality, "PROGRAMME"))
        elif decision == "ADMIN_REVIEW":
            review.append({
                "review_id": stable_id("dst_entity_quality_review", entity_id(quality)),
                "review_type": "PROVISIONAL_ENTITY_QUALITY",
                "provisional_entity_id": entity_id(quality),
                "proposed_name": entity_name(quality),
                "proposed_entity_type": first_value(quality, "original_proposed_entity_type"),
                "confidence": first_value(quality, "quality_confidence"),
                "review_flags": first_value(quality, "quality_review_flags"),
                "evidence": first_value(quality, "quality_reasons"),
                "source_url": entity_url(quality),
                "recommended_action": "CONFIRM_PERMANENT_ENTITY_OR_DOWNGRADE_BEFORE_IDENTITY_LOCK",
            })
        else:
            downgrades.append(quality)
        audit.append({
            "audit_id": stable_id("dst_hotfix_entity_audit", entity_id(quality)),
            "audit_type": "PROVISIONAL_ENTITY_QUALITY",
            "record_id": entity_id(quality),
            "record_name": entity_name(quality),
            "record_url": entity_url(quality),
            "decision": decision,
            "confidence": first_value(quality, "quality_confidence"),
            "reasons": first_value(quality, "quality_reasons"),
            "identity_safeguard": first_value(quality, "identity_safeguard"),
        })

    return HotfixResult(
        direct_targets=direct_targets,
        lineage=lineage,
        existing_matches=existing_matches,
        new_schemes=new_schemes,
        new_programmes=new_programmes,
        non_entity=non_entity,
        true_broken=true_broken,
        duplicates=duplicates,
        corrected_schemes=corrected_schemes,
        corrected_programmes=corrected_programmes,
        downgrades=downgrades,
        review=review,
        audit=audit,
    )


def validate(
    review_rows: Sequence[Mapping[str, Any]],
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    result: HotfixResult,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    gap_rows = [row for row in review_rows if upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP"]
    unique = result.direct_targets
    input_entity_count = len(schemes) + len(programmes)
    audited_entity_ids = {
        first_value(row, "record_id")
        for row in result.audit
        if first_value(row, "audit_type") == "PROVISIONAL_ENTITY_QUALITY"
    }
    direct_matches = sum(first_value(row, "direct_target_match") == "1" for row in unique)
    match_rate = direct_matches / len(unique) if unique else 0.0
    unresolved = sum(first_value(row, "gap_classification") == "UNRESOLVED" for row in unique)
    unresolved_rate = unresolved / len(unique) if unique else 0.0
    classifications = [first_value(row, "gap_classification") for row in unique]
    invalid_classifications = sorted({value for value in classifications if value not in GAP_CLASSIFICATIONS})
    corrected_entities = result.corrected_schemes + result.corrected_programmes
    generic_lock_candidates = [
        entity_name(row) for row in corrected_entities if is_generic_name(entity_name(row), config)
    ]
    call_contamination = sum(
        upper(first_value(row, "target_page_role")) in CALL_ROLES
        or first_value(row, "gap_classification") == "CALL_OR_TEMPORARY_OPPORTUNITY"
        for row in result.new_schemes + result.new_programmes
    )
    forbidden_fields = sorted({
        field
        for row in [*unique, *corrected_entities, *result.downgrades]
        for field in row
        if field in FORBIDDEN_IDENTITY_FIELDS
    })
    occurrence_total = sum(safe_int(row.get("occurrence_count")) for row in unique)
    entity_output_ids = {
        entity_id(row) for row in [*corrected_entities, *result.downgrades]
        if entity_id(row)
    }
    entity_review_ids = {
        first_value(row, "provisional_entity_id")
        for row in result.review
        if first_value(row, "review_type") == "PROVISIONAL_ENTITY_QUALITY"
    }
    accounted_entity_ids = entity_output_ids | entity_review_ids
    input_entity_ids = {
        first_value(row, "provisional_entity_id") for row in [*schemes, *programmes]
        if first_value(row, "provisional_entity_id")
    }

    checks = {
        "all_gap_occurrences_accounted_for": occurrence_total == len(gap_rows),
        "unique_gap_urls_unique": len(unique) == len({first_value(row, "normalized_target_url") for row in unique}),
        "duplicate_gap_occurrences_accounted_for": len(result.duplicates) == max(0, len(gap_rows) - len(unique)),
        "direct_target_match_rate_passed": match_rate >= safe_float(config.get("minimum_direct_target_match_rate"), 0.95),
        "unresolved_rate_within_limit": unresolved_rate <= safe_float(config.get("maximum_unresolved_rate"), 0.10),
        "gap_classifications_valid": not invalid_classifications,
        "all_provisional_entities_audited": len(audited_entity_ids) == input_entity_count,
        "all_provisional_entities_accounted_for": input_entity_ids == accounted_entity_ids,
        "generic_pages_excluded_from_corrected_inventory": not generic_lock_candidates,
        "call_pages_not_proposed_as_permanent_entities": call_contamination == 0,
        "forbidden_identity_fields_absent": not forbidden_fields,
        "canonical_scheme_identity_created": False,
        "identity_locked": False,
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
            "input_category_gap_rows": len(gap_rows),
            "unique_category_gaps": len(unique),
            "duplicate_gap_occurrences": len(result.duplicates),
            "direct_target_matches": direct_matches,
            "unresolved_unique_gaps": unresolved,
            "existing_entity_gap_matches": len(result.existing_matches),
            "possible_new_schemes": len(result.new_schemes),
            "possible_new_programmes": len(result.new_programmes),
            "gap_non_entity_pages": len(result.non_entity),
            "true_broken_targets": len(result.true_broken),
            "input_provisional_entities": input_entity_count,
            "corrected_provisional_schemes": len(result.corrected_schemes),
            "corrected_provisional_programmes": len(result.corrected_programmes),
            "provisional_entity_downgrades": len(result.downgrades),
            "admin_review_rows": len(result.review),
        },
        "quality": {
            "direct_target_match_rate": round(match_rate, 6),
            "minimum_direct_target_match_rate": safe_float(config.get("minimum_direct_target_match_rate"), 0.95),
            "unresolved_rate": round(unresolved_rate, 6),
            "maximum_unresolved_rate": safe_float(config.get("maximum_unresolved_rate"), 0.10),
            "invalid_gap_classifications": invalid_classifications,
            "generic_lock_candidates": generic_lock_candidates,
            "call_contamination": call_contamination,
            "forbidden_identity_fields_found": forbidden_fields,
        },
        "checks": checks,
        "hotfix_validation_passed": validation_passed,
        "ready_for_v3_4_0_4": validation_passed,
    }


def build_summary(
    result: HotfixResult,
    validation: Mapping[str, Any],
    input_dir: Path,
    classifier_dir: Path,
    link_graph_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    gap_counts = Counter(first_value(row, "gap_classification") for row in result.direct_targets)
    entity_decisions = Counter(
        first_value(row, "decision")
        for row in result.audit
        if first_value(row, "audit_type") == "PROVISIONAL_ENTITY_QUALITY"
    )
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
        "corrected_semantics": {
            "category_gap_source_url_interpretation": "TARGET_URL",
            "category_lineage_join": "REVERSE_LINK_GRAPH_TO_URL_TO_FROM_URL",
        },
        "identity_safeguard": {
            "canonical_scheme_identity_created": False,
            "identity_locked": False,
            "call_pages_used_as_permanent_candidates": False,
            "generic_pages_allowed_in_corrected_inventory": False,
            "description": "Direct target and quality decisions only; v3.4.0.4 must curate and lock permanent identities.",
        },
        "counts": validation.get("counts", {}),
        "gap_classification_counts": dict(sorted(gap_counts.items())),
        "provisional_entity_quality_decision_counts": dict(sorted(entity_decisions.items())),
        "hotfix_validation_passed": validation.get("hotfix_validation_passed", False),
        "ready_for_v3_4_0_4": validation.get("ready_for_v3_4_0_4", False),
        "outputs": {
            "direct_target_matches": DIRECT_TARGET_OUTPUT,
            "category_lineage": LINEAGE_OUTPUT,
            "existing_entity_gap_matches": EXISTING_GAP_OUTPUT,
            "possible_new_schemes": NEW_SCHEME_OUTPUT,
            "possible_new_programmes": NEW_PROGRAMME_OUTPUT,
            "gap_non_entity_pages": NON_ENTITY_OUTPUT,
            "true_broken_targets": TRUE_BROKEN_OUTPUT,
            "gap_duplicates": DUPLICATES_OUTPUT,
            "corrected_schemes": CORRECTED_SCHEMES_OUTPUT,
            "corrected_programmes": CORRECTED_PROGRAMMES_OUTPUT,
            "entity_downgrades": DOWNGRADES_OUTPUT,
            "review_queue": REVIEW_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def write_outputs(
    output_dir: Path,
    result: HotfixResult,
    validation: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / DIRECT_TARGET_OUTPUT, result.direct_targets)
    write_csv(output_dir / LINEAGE_OUTPUT, result.lineage)
    write_csv(output_dir / EXISTING_GAP_OUTPUT, result.existing_matches)
    write_csv(output_dir / NEW_SCHEME_OUTPUT, result.new_schemes)
    write_csv(output_dir / NEW_PROGRAMME_OUTPUT, result.new_programmes)
    write_csv(output_dir / NON_ENTITY_OUTPUT, result.non_entity)
    write_csv(output_dir / TRUE_BROKEN_OUTPUT, result.true_broken)
    write_csv(output_dir / DUPLICATES_OUTPUT, result.duplicates)
    write_csv(output_dir / CORRECTED_SCHEMES_OUTPUT, result.corrected_schemes)
    write_csv(output_dir / CORRECTED_PROGRAMMES_OUTPUT, result.corrected_programmes)
    write_csv(output_dir / DOWNGRADES_OUTPUT, result.downgrades)
    write_csv(output_dir / REVIEW_OUTPUT, result.review)
    write_csv(output_dir / AUDIT_OUTPUT, result.audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)


def resolve_paths(project_root: Path) -> dict[str, Path]:
    input_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3"
    classifier_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_2"
    crawl_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    output_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_2"
    return {
        "input_dir": input_dir,
        "classifier_dir": classifier_dir,
        "crawl_dir": crawl_dir,
        "output_dir": output_dir,
        "review": input_dir / REVIEW_INPUT,
        "schemes": input_dir / SCHEME_INPUT,
        "programmes": input_dir / PROGRAMME_INPUT,
        "aliases": input_dir / ALIAS_INPUT,
        "pages": classifier_dir / CLASSIFIED_PAGES_INPUT,
        "links": crawl_dir / LINK_GRAPH_INPUT,
    }


def run_pipeline(
    project_root: Path,
    config: Mapping[str, Any],
    dry_run: bool = False,
) -> tuple[HotfixResult | None, dict[str, Any]]:
    paths = resolve_paths(project_root)
    review_rows = read_csv(paths["review"])
    schemes = read_csv(paths["schemes"])
    programmes = read_csv(paths["programmes"])
    aliases = read_csv(paths["aliases"], required=False)
    pages = read_csv(paths["pages"])
    links = read_csv(paths["links"])
    gap_rows = [row for row in review_rows if upper(row.get("review_type")) == "CATEGORY_INDEX_DISCOVERY_GAP"]
    groups, duplicates = aggregate_gap_rows(review_rows, config)
    direct_match_preview = sum(
        normalize_url(first_value(group.occurrences[0], "source_url"), config)
        in build_page_index(pages, config)
        for group in groups
    )
    if dry_run:
        return None, {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "inputs": {
                "review_rows": len(review_rows),
                "category_gap_rows": len(gap_rows),
                "unique_category_gaps": len(groups),
                "duplicate_gap_occurrences": len(duplicates),
                "provisional_schemes": len(schemes),
                "provisional_programmes": len(programmes),
                "alias_rows": len(aliases),
                "classified_pages": len(pages),
                "link_graph_rows": len(links),
                "direct_target_match_preview": direct_match_preview,
            },
            "corrected_semantics": {
                "source_url": "TARGET_URL",
                "lineage": "REVERSE_MATCH_LINK_GRAPH_TO_URL",
            },
            "files_written": False,
        }
    result = process_hotfix(review_rows, schemes, programmes, aliases, pages, links, config)
    validation = validate(review_rows, schemes, programmes, result, config)
    summary = build_summary(
        result,
        validation,
        paths["input_dir"],
        paths["classifier_dir"],
        paths["links"],
        paths["output_dir"],
    )
    write_outputs(paths["output_dir"], result, validation, summary)
    return result, summary


def self_test() -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    review = [
        {
            "review_id": "g1",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Screen Reader Access",
            "source_page_title": "Schemes/ Programmes",
            "source_url": "https://dst.gov.in/screen-reader-access",
        },
        {
            "review_id": "g2",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Existing Mission",
            "source_page_title": "Programmes",
            "source_url": "https://dst.gov.in/existing-mission",
        },
        {
            "review_id": "g2dup",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Existing Mission",
            "source_page_title": "Schemes/ Programmes",
            "source_url": "https://DST.gov.in/existing-mission/",
        },
        {
            "review_id": "g3",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Young Scientist Fellowship Scheme",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/young-scientist-fellowship-scheme",
        },
        {
            "review_id": "g4",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Advanced Materials Programme",
            "source_page_title": "Programmes",
            "source_url": "https://dst.gov.in/advanced-materials-programme",
        },
        {
            "review_id": "g5",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Call for Proposals 2026 under Existing Mission",
            "source_page_title": "Programmes",
            "source_url": "https://dst.gov.in/callforproposals/existing-2026",
        },
        {
            "review_id": "g6",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Guidelines",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/guidelines",
        },
        {
            "review_id": "g7",
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "proposed_canonical_name": "Old Resource",
            "source_page_title": "Schemes",
            "source_url": "https://dst.gov.in/old-resource",
        },
    ]
    schemes = [
        {
            "provisional_entity_id": "scheme_valid",
            "proposed_canonical_name": "Valid Research Scheme",
            "proposed_entity_type": "SCHEME",
            "official_source_url": "https://dst.gov.in/valid-research-scheme",
            "identity_confidence": "0.86",
            "master_evidence_score": "0.82",
        },
        {
            "provisional_entity_id": "scheme_about",
            "proposed_canonical_name": "About the Schemes",
            "proposed_entity_type": "SCHEME",
            "official_source_url": "https://dst.gov.in/about-schemes",
            "identity_confidence": "0.77",
            "master_evidence_score": "0.55",
        },
        {
            "provisional_entity_id": "scheme_funding",
            "proposed_canonical_name": "Funding Mechanism",
            "proposed_entity_type": "SCHEME",
            "official_source_url": "https://dst.gov.in/funding-mechanism",
            "identity_confidence": "0.75",
            "master_evidence_score": "0.50",
        },
    ]
    programmes = [
        {
            "provisional_entity_id": "programme_existing",
            "proposed_canonical_name": "Existing Mission",
            "proposed_entity_type": "PROGRAMME",
            "official_source_url": "https://dst.gov.in/existing-mission",
            "identity_confidence": "0.90",
            "master_evidence_score": "0.86",
        },
        {
            "provisional_entity_id": "programme_archive",
            "proposed_canonical_name": "Archive",
            "proposed_entity_type": "PROGRAMME",
            "official_source_url": "https://dst.gov.in/archive",
            "identity_confidence": "0.75",
            "master_evidence_score": "0.40",
        },
    ]
    pages = [
        {
            "page_id": "category_schemes",
            "final_url": "https://dst.gov.in/schemes",
            "page_title": "Schemes",
            "page_role": "SCHEME_CATEGORY_INDEX",
            "page_role_confidence": "0.98",
            "main_text": "Scheme index",
        },
        {
            "page_id": "category_programmes",
            "final_url": "https://dst.gov.in/programmes",
            "page_title": "Programmes",
            "page_role": "PROGRAMME_CATEGORY_INDEX",
            "page_role_confidence": "0.98",
            "main_text": "Programme index",
        },
        {
            "page_id": "screen",
            "final_url": "https://dst.gov.in/screen-reader-access",
            "page_title": "Screen Reader Access",
            "page_role": "UNKNOWN",
            "page_role_confidence": "0.55",
            "main_text": "Accessibility instructions for screen reader users.",
        },
        {
            "page_id": "existing",
            "final_url": "https://dst.gov.in/existing-mission",
            "page_title": "Existing Mission",
            "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.94",
            "scheme_evidence_score": "0.88",
            "main_text": "Objectives eligibility funding support application process scope institutions duration Department of Science and Technology.",
        },
        {
            "page_id": "new_scheme",
            "final_url": "https://dst.gov.in/young-scientist-fellowship-scheme",
            "page_title": "Young Scientist Fellowship Scheme",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.90",
            "scheme_evidence_score": "0.86",
            "main_text": "Objectives eligibility financial assistance how to apply beneficiaries scope duration Department of Science and Technology.",
        },
        {
            "page_id": "new_programme",
            "final_url": "https://dst.gov.in/advanced-materials-programme",
            "page_title": "Advanced Materials Programme",
            "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.90",
            "scheme_evidence_score": "0.86",
            "main_text": "Objectives eligibility funding support application process scope institutions duration Department of Science and Technology.",
        },
        {
            "page_id": "call",
            "final_url": "https://dst.gov.in/callforproposals/existing-2026",
            "page_title": "Call for Proposals 2026 under Existing Mission",
            "page_role": "CALL_FOR_PROPOSALS",
            "page_role_confidence": "0.98",
            "call_evidence_score": "0.98",
            "main_text": "Applications invited. Closing date.",
        },
        {
            "page_id": "guidelines",
            "final_url": "https://dst.gov.in/guidelines",
            "page_title": "Guidelines",
            "page_role": "GUIDELINE_PAGE",
            "page_role_confidence": "0.96",
            "main_text": "Guidelines and manuals.",
        },
        {
            "page_id": "broken",
            "final_url": "https://dst.gov.in/old-resource",
            "page_title": "Old Resource",
            "page_role": "BROKEN_OFFICIAL_LINK",
            "page_role_confidence": "0.99",
            "http_status": "404",
        },
        {
            "page_id": "valid_scheme",
            "final_url": "https://dst.gov.in/valid-research-scheme",
            "page_title": "Valid Research Scheme",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.94",
            "scheme_evidence_score": "0.88",
            "main_text": "Objectives eligibility financial assistance how to apply beneficiaries scope duration Department of Science and Technology.",
        },
        {
            "page_id": "about_schemes",
            "final_url": "https://dst.gov.in/about-schemes",
            "page_title": "About the Schemes",
            "page_role": "GENERAL_INFORMATION",
            "page_role_confidence": "0.90",
            "main_text": "About DST schemes and funding opportunities.",
        },
        {
            "page_id": "funding",
            "final_url": "https://dst.gov.in/funding-mechanism",
            "page_title": "Funding Mechanism",
            "page_role": "GENERAL_INFORMATION",
            "page_role_confidence": "0.88",
            "main_text": "General explanation of funding mechanism.",
        },
        {
            "page_id": "archive",
            "final_url": "https://dst.gov.in/archive",
            "page_title": "Archive",
            "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.65",
            "main_text": "Archived information.",
        },
    ]
    links = [
        {"from_url": "https://dst.gov.in/schemes", "to_url": "https://dst.gov.in/screen-reader-access", "normalized_to_url": "https://dst.gov.in/screen-reader-access", "anchor_text": "Screen Reader Access"},
        {"from_url": "https://dst.gov.in/programmes", "to_url": "https://dst.gov.in/existing-mission", "normalized_to_url": "https://dst.gov.in/existing-mission", "anchor_text": "Existing Mission"},
        {"from_url": "https://dst.gov.in/schemes", "to_url": "https://dst.gov.in/young-scientist-fellowship-scheme", "normalized_to_url": "https://dst.gov.in/young-scientist-fellowship-scheme", "anchor_text": "Young Scientist Fellowship Scheme"},
        {"from_url": "https://dst.gov.in/programmes", "to_url": "https://dst.gov.in/advanced-materials-programme", "normalized_to_url": "https://dst.gov.in/advanced-materials-programme", "anchor_text": "Advanced Materials Programme"},
        {"from_url": "https://dst.gov.in/programmes", "to_url": "https://dst.gov.in/callforproposals/existing-2026", "normalized_to_url": "https://dst.gov.in/callforproposals/existing-2026", "anchor_text": "Call for Proposals"},
        {"from_url": "https://dst.gov.in/schemes", "to_url": "https://dst.gov.in/guidelines", "normalized_to_url": "https://dst.gov.in/guidelines", "anchor_text": "Guidelines"},
        {"from_url": "https://dst.gov.in/schemes", "to_url": "https://dst.gov.in/old-resource", "normalized_to_url": "https://dst.gov.in/old-resource", "anchor_text": "Old Resource"},
    ]
    result = process_hotfix(review, schemes, programmes, [], pages, links, config)
    validation = validate(review, schemes, programmes, result, config)
    gap_counts = Counter(first_value(row, "gap_classification") for row in result.direct_targets)
    downgrade_names = {entity_name(row) for row in result.downgrades}
    corrected_names = {entity_name(row) for row in [*result.corrected_schemes, *result.corrected_programmes]}
    tests = {
        "source_url_used_as_direct_target": validation["quality"]["direct_target_match_rate"] == 1.0,
        "duplicates_preserved": len(result.duplicates) == 1,
        "reverse_lineage_recovered": len(result.lineage) >= 7,
        "existing_entity_matched": gap_counts["EXISTING_PROVISIONAL_ENTITY"] == 1,
        "new_scheme_found": gap_counts["POSSIBLE_NEW_SCHEME"] == 1,
        "new_programme_found": gap_counts["POSSIBLE_NEW_PROGRAMME"] == 1,
        "accessibility_page_excluded": gap_counts["ACCESSIBILITY_OR_NAVIGATION_PAGE"] == 1,
        "call_excluded": gap_counts["CALL_OR_TEMPORARY_OPPORTUNITY"] == 1,
        "guideline_excluded": gap_counts["SUPPORTING_PAGE"] == 1,
        "broken_page_recognized": gap_counts["BROKEN_OFFICIAL_LINK"] == 1,
        "valid_scheme_retained": "Valid Research Scheme" in corrected_names,
        "valid_programme_retained": "Existing Mission" in corrected_names,
        "generic_entities_downgraded": {"About the Schemes", "Funding Mechanism", "Archive"}.issubset(downgrade_names),
        "generic_entities_not_in_corrected_inventory": not ({"About the Schemes", "Funding Mechanism", "Archive"} & corrected_names),
        "validation_passed": validation["hotfix_validation_passed"] is True,
        "identity_not_locked": validation["checks"]["identity_locked"] is False,
        "canonical_identity_not_created": validation["checks"]["canonical_scheme_identity_created"] is False,
    }
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "tests": tests,
        "gap_classification_counts": dict(sorted(gap_counts.items())),
        "entity_downgrade_names": sorted(downgrade_names),
        "self_test_passed": all(tests.values()),
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
        payload = self_test()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["self_test_passed"] else 2
    try:
        config = load_config(args.config)
        _result, payload = run_pipeline(args.project_root.resolve(), config, dry_run=args.dry_run)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.strict and not args.dry_run and not payload.get("hotfix_validation_passed", False):
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
