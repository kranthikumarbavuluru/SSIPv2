#!/usr/bin/env python3
"""
SSIP v3.4.0.3 — Permanent DST Scheme and Programme Inventory Builder

Purpose
-------
Build a provisional inventory of permanent DST schemes and programmes from
v3.4.0.2 evidence-based page-role classifications. This phase proposes
identities for curation; it does not lock canonical names and it never creates
permanent entities from calls, deadline extensions, results, events or other
transient pages.

Safety guarantees
-----------------
* No network access and no recrawl.
* Input files are never modified.
* Only SCHEME_MASTER_CANDIDATE and PROGRAMME_MASTER_CANDIDATE pages can seed
  provisional permanent entities.
* Call-like and time-bound titles are rejected from the permanent inventory.
* All identities remain PROVISIONAL and require v3.4.0.4 curation/locking.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

VERSION = "3.4.0.3"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

CLASSIFIED_PAGES_INPUT = "dst_classified_pages_v3_4_0_2.csv"
CLASSIFIED_DOCUMENTS_INPUT = "dst_classified_documents_v3_4_0_2.csv"
LINK_GRAPH_INPUT = "dst_link_graph_v3_4_0_1.csv"

SCHEME_OUTPUT = "dst_provisional_scheme_inventory_v3_4_0_3.csv"
PROGRAMME_OUTPUT = "dst_provisional_programme_inventory_v3_4_0_3.csv"
ALIAS_OUTPUT = "dst_scheme_alias_candidates_v3_4_0_3.csv"
HIERARCHY_OUTPUT = "dst_programme_hierarchy_candidates_v3_4_0_3.csv"
EVIDENCE_OUTPUT = "dst_master_source_evidence_v3_4_0_3.csv"
REJECTED_OUTPUT = "dst_rejected_master_candidates_v3_4_0_3.csv"
REVIEW_OUTPUT = "dst_identity_review_queue_v3_4_0_3.csv"
AUDIT_OUTPUT = "dst_inventory_audit_v3_4_0_3.csv"
VALIDATION_OUTPUT = "dst_inventory_validation_v3_4_0_3.json"
SUMMARY_OUTPUT = "dst_inventory_summary_v3_4_0_3.json"

ALLOWED_SEED_ROLES = {
    "SCHEME_MASTER_CANDIDATE": "SCHEME",
    "PROGRAMME_MASTER_CANDIDATE": "PROGRAMME",
}

CALL_AND_TRANSIENT_ROLES = {
    "CALL_FOR_PROPOSALS",
    "APPLICATION_INVITATION",
    "EXPRESSION_OF_INTEREST",
    "DEADLINE_EXTENSION",
    "CALL_CORRIGENDUM",
    "CALL_RESULT",
    "CALL_ARCHIVE_INDEX",
    "CURRENT_CALL_INDEX",
    "NEWS",
    "EVENT",
    "RECRUITMENT",
    "BROKEN_OFFICIAL_LINK",
}

CATEGORY_ROLES = {"SCHEME_CATEGORY_INDEX", "PROGRAMME_CATEGORY_INDEX"}
SUPPORTING_ROLES = {
    "GUIDELINE_PAGE",
    "APPLICATION_GUIDANCE",
    "SANCTIONED_PROJECT_EVIDENCE",
    "NOTIFICATION",
    "OFFICE_MEMORANDUM",
}

FORBIDDEN_LOCK_FIELDS = {
    "locked_scheme_name",
    "locked_programme_name",
    "identity_locked",
    "canonical_identity_locked",
    "publication_ready",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "minimum_inventory_confidence": 0.62,
    "minimum_auto_review_free_confidence": 0.82,
    "minimum_index_candidate_anchor_length": 4,
    "maximum_index_candidate_anchor_length": 160,
    "maximum_identity_name_length": 220,
    "maximum_unknown_index_candidates": 500,
    "evidence_excerpt_length": 600,
    "generic_titles": [
        "home",
        "schemes/programmes",
        "schemes and programmes",
        "programmes and initiatives",
        "programme",
        "programmes",
        "scheme",
        "schemes",
        "overview",
        "about us",
        "what's new",
        "announcements",
        "guidelines",
        "call for proposals",
    ],
    "site_title_suffixes": [
        "department of science and technology",
        "department of science & technology",
        "ministry of science and technology",
        "government of india",
        "dst",
    ],
    "call_like_terms": [
        "call for proposal",
        "call for proposals",
        "call for project proposal",
        "applications invited",
        "application invited",
        "inviting applications",
        "expression of interest",
        "deadline extension",
        "last date extended",
        "corrigendum",
        "result of",
        "selected proposals",
        "shortlisted",
    ],
    "temporary_tokens": [
        "round",
        "cycle",
        "cohort",
        "special call",
        "joint call",
        "open call",
        "current call",
        "phase i",
        "phase ii",
        "phase iii",
    ],
    "scheme_terms": [
        "scheme",
        "fellowship",
        "award",
        "grant",
        "support",
        "assistance",
        "fund",
    ],
    "programme_terms": [
        "programme",
        "program",
        "mission",
        "initiative",
        "platform",
        "network",
        "facility",
        "cooperation",
        "capacity building",
        "research council",
    ],
    "master_evidence_terms": {
        "objective": ["objective", "objectives", "aims to", "purpose"],
        "eligibility": ["eligibility", "eligible", "who can apply"],
        "benefits": ["financial assistance", "funding support", "grant", "support provided"],
        "application": ["how to apply", "application process", "apply online", "application procedure"],
        "beneficiaries": ["beneficiaries", "target group", "researchers", "scientists", "institutions"],
        "scope": ["scope", "thrust areas", "focus areas", "areas of support"],
    },
    "historical_terms": [
        "formerly known as",
        "renamed as",
        "renamed to",
        "restructured into",
        "merged into",
        "replaced by",
    ],
    "curated_url_replacements": {
        "https://dst.gov.in/promotion-university-research-and-scientific-excellencepurse":
            "https://dst.gov.in/promotion-university-research-and-scientific-excellence-purse"
    },
}


@dataclass
class Candidate:
    source_page_id: str
    source_page_role: str
    source_page_title: str
    source_url: str
    entity_type: str
    proposed_name: str
    raw_title: str
    abbreviation: str
    confidence: float
    evidence_score: float
    subtype: str
    parent_name_text: str
    identity_evidence: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    document_counts: dict[str, int] = field(default_factory=dict)
    category_contexts: list[dict[str, str]] = field(default_factory=list)
    main_text_excerpt: str = ""


@dataclass
class BuildResult:
    schemes: list[dict[str, Any]]
    programmes: list[dict[str, Any]]
    aliases: list[dict[str, Any]]
    hierarchy: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
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


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(collapse_ws(x) for x in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def normalize_key(value: str) -> str:
    value = html.unescape(collapse_ws(value)).casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def read_csv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    materialized = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields_list: list[str] = []
        seen: set[str] = set()
        for row in materialized:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields_list.append(key)
        fields = fields_list
    if not fields:
        atomic_write_text(path, "")
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    os.replace(tmp, path)


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and path.exists():
        override = json.loads(path.read_text(encoding="utf-8-sig"))
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def first_value(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = collapse_ws(row.get(name))
        if value:
            return value
    return ""


def clean_title(raw_title: str, config: Mapping[str, Any]) -> str:
    title = html.unescape(collapse_ws(raw_title))
    title = re.sub(r"(?i)^\s*(scheme|programme|program|initiative)\s*[:\-–—]\s*", "", title)
    suffixes = [re.escape(x) for x in config.get("site_title_suffixes", [])]
    if suffixes:
        suffix_group = "|".join(suffixes)
        title = re.sub(rf"\s*(?:\||-|–|—|:)\s*(?:{suffix_group})\s*$", "", title, flags=re.I)
    return collapse_ws(title).strip(" -–—|:")


def extract_trailing_abbreviation(title: str) -> tuple[str, str]:
    """Return name without a trailing acronym and the acronym candidate."""
    match = re.search(r"\s*\(([A-Z][A-Z0-9&./\-]{1,19})\)\s*$", title)
    if not match:
        return title, ""
    acronym = collapse_ws(match.group(1)).strip("./")
    name = collapse_ws(title[: match.start()])
    if len(name) < 3:
        return title, ""
    return name, acronym


def extract_body_abbreviation(name: str, text: str) -> str:
    sample = collapse_ws(text[:6000])
    patterns = (
        r"(?i)\b(?:abbreviated as|acronym|known as|referred to as)\s+[\"'“”]?([A-Z][A-Z0-9&./\-]{1,19})\b",
        r"(?i)\b" + re.escape(name[:80]) + r"\s*\(([A-Z][A-Z0-9&./\-]{1,19})\)",
    )
    for pattern in patterns:
        match = re.search(pattern, sample)
        if match:
            return collapse_ws(match.group(1)).strip("./")
    return ""


def contains_any(text: str, phrases: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(collapse_ws(phrase).casefold() in folded for phrase in phrases)


def has_temporal_identity_token(name: str, config: Mapping[str, Any]) -> bool:
    folded = name.casefold()
    if re.search(r"\b(?:19|20)\d{2}\b", name):
        return True
    if re.search(r"\bfy\s*\d{2,4}(?:\s*[-/]\s*\d{2,4})?\b", folded):
        return True
    return contains_any(folded, config.get("temporary_tokens", []))


def looks_call_like(title: str, config: Mapping[str, Any]) -> bool:
    folded = title.casefold()
    return contains_any(folded, config.get("call_like_terms", [])) or bool(
        re.search(r"\b(call|deadline|corrigendum|addendum|result|selected|shortlisted)\b", folded)
    )


def is_generic_title(title: str, config: Mapping[str, Any]) -> bool:
    key = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    generic = {
        re.sub(r"[^a-z0-9]+", " ", str(x).casefold()).strip()
        for x in config.get("generic_titles", [])
    }
    return not key or key in generic


def infer_subtype(entity_type: str, title: str, text: str, config: Mapping[str, Any]) -> str:
    combined = f"{title} {text[:5000]}".casefold()
    if contains_any(combined, config.get("historical_terms", [])):
        return "HISTORICAL_PROGRAMME" if entity_type == "PROGRAMME" else "HISTORICAL_SCHEME"
    if entity_type == "PROGRAMME":
        if re.search(r"\b(mission|umbrella|national programme|national program)\b", combined):
            return "UMBRELLA_PROGRAMME"
        return "STANDARD_PROGRAMME"
    if re.search(r"\b(component|sub.?scheme|vertical)\b", combined):
        return "SCHEME_COMPONENT"
    return "STANDARD_SCHEME"


def extract_parent_name(title: str, text: str) -> tuple[str, str]:
    combined = collapse_ws(f"{title}. {text[:10000]}")
    patterns = (
        (r"(?i)\b(?:implemented|operated|supported|launched)\s+under\s+(?:the\s+)?[\"'“”]?([^.;:\n]{4,180})", "POSSIBLE_COMPONENT_OF"),
        (r"(?i)\bunder\s+(?:the\s+)?(?:umbrella\s+)?(?:scheme|programme|program|mission|initiative)\s+[\"'“”]?([^.;:\n]{4,180})", "POSSIBLE_COMPONENT_OF"),
        (r"(?i)\bas\s+(?:a\s+)?(?:component|part|vertical)\s+of\s+(?:the\s+)?[\"'“”]?([^.;:\n]{4,180})", "POSSIBLE_COMPONENT_OF"),
    )
    for pattern, relationship in patterns:
        match = re.search(pattern, combined)
        if not match:
            continue
        parent = collapse_ws(match.group(1)).strip(" -–—'\"“”")
        parent = re.sub(r"(?i)\b(?:for|dated|during|with|which|and applications?).*$", "", parent).strip()
        if 4 <= len(parent) <= 180:
            return parent, relationship
    return "", ""


def evidence_groups(text: str, config: Mapping[str, Any]) -> list[str]:
    matched: list[str] = []
    folded = text.casefold()
    for group, terms in config.get("master_evidence_terms", {}).items():
        if contains_any(folded, terms):
            matched.append(group)
    return matched


def page_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "final_url", "canonical_url", "requested_url")


def page_title(row: Mapping[str, Any]) -> str:
    return first_value(row, "page_title", "title")


def page_id(row: Mapping[str, Any]) -> str:
    return first_value(row, "classified_page_id", "page_id") or stable_id("dst_page", page_url(row))


def document_source_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "source_page_url", "source_url")


def document_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "document_url", "url", "final_url")


def aggregate_documents(documents: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in documents:
        source = document_source_url(row)
        if source:
            by_source[source].append(row)
    return by_source


def build_page_maps(pages: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_url: dict[str, dict[str, str]] = {}
    by_id: dict[str, dict[str, str]] = {}
    for row in pages:
        url = page_url(row)
        if url:
            by_url[url] = row
        by_id[page_id(row)] = row
    return by_url, by_id


def build_category_contexts(
    pages_by_url: Mapping[str, Mapping[str, str]],
    links: list[dict[str, str]],
    config: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    contexts: dict[str, list[dict[str, str]]] = defaultdict(list)
    index_review_candidates: list[dict[str, str]] = []
    seen_review: set[tuple[str, str]] = set()

    for link in links:
        source = first_value(link, "from_url", "source_page_url")
        target = first_value(link, "to_url", "normalized_to_url", "target_url")
        if not source or not target:
            continue
        source_page = pages_by_url.get(source)
        if not source_page or upper(source_page.get("page_role")) not in CATEGORY_ROLES:
            continue
        target_page = pages_by_url.get(target)
        anchor = collapse_ws(link.get("anchor_text"))
        if target_page and upper(target_page.get("page_role")) in ALLOWED_SEED_ROLES:
            contexts[target].append({
                "category_page_id": page_id(source_page),
                "category_page_title": page_title(source_page),
                "category_page_url": source,
                "anchor_text": anchor,
            })
            continue

        # Surface potentially missed permanent entities for curation, but never
        # create inventory records from them automatically.
        if safe_int(link.get("is_internal")) != 1 or safe_int(link.get("is_document")) == 1:
            continue
        if not anchor or len(anchor) < 4 or len(anchor) > 160:
            continue
        target_role = upper(target_page.get("page_role")) if target_page else ""
        if target_role in CALL_AND_TRANSIENT_ROLES or looks_call_like(anchor, config):
            continue
        if is_generic_title(anchor, config):
            continue
        key = (source, target)
        if key in seen_review:
            continue
        seen_review.add(key)
        index_review_candidates.append({
            "source_category_url": source,
            "source_category_title": page_title(source_page),
            "target_url": target,
            "anchor_text": anchor,
            "target_page_role": target_role,
            "reason": "CATEGORY_LINK_NOT_CLASSIFIED_AS_MASTER",
        })

    return contexts, index_review_candidates


def score_candidate(
    row: Mapping[str, Any],
    proposed_name: str,
    entity_type: str,
    groups: Sequence[str],
    documents: Sequence[Mapping[str, Any]],
    contexts: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[float, list[str], list[str], dict[str, int]]:
    role_confidence = safe_float(row.get("page_role_confidence"), 0.5)
    classifier_evidence = safe_float(row.get("scheme_evidence_score"), 0.0)
    doc_counts = Counter(upper(doc.get("document_role")) for doc in documents)
    reasons = [f"CLASSIFIER_ROLE_{upper(row.get('page_role'))}", f"MASTER_EVIDENCE_GROUPS_{len(groups)}"]
    flags: list[str] = []

    score = 0.50 * role_confidence
    score += min(0.20, classifier_evidence / 500.0)
    score += min(0.12, len(groups) * 0.025)
    if contexts:
        score += min(0.08, len(contexts) * 0.025)
        reasons.append(f"CATEGORY_INDEX_REFERENCES_{len(contexts)}")
    guideline_count = doc_counts.get("GUIDELINE", 0) + doc_counts.get("OFFICE_MEMORANDUM", 0)
    if guideline_count:
        score += min(0.08, guideline_count * 0.025)
        reasons.append(f"OFFICIAL_GUIDELINE_DOCUMENTS_{guideline_count}")
    if document_source_url(documents[0]) if documents else False:
        reasons.append(f"LINKED_DOCUMENTS_{len(documents)}")
    if first_value(row, "text_extraction_status") == "SUCCESS_BODY_FALLBACK":
        flags.append("BODY_FALLBACK_TEXT_USED")
    if len(groups) < 2:
        flags.append("LIMITED_MASTER_PAGE_SECTION_EVIDENCE")
    if not contexts:
        flags.append("NO_CATEGORY_INDEX_CONTEXT")
    if entity_type == "SCHEME" and not contains_any(proposed_name, config.get("scheme_terms", DEFAULT_CONFIG["scheme_terms"])):
        flags.append("SCHEME_TYPE_REQUIRES_CURATION")
    if entity_type == "PROGRAMME" and not contains_any(proposed_name, config.get("programme_terms", DEFAULT_CONFIG["programme_terms"])):
        flags.append("PROGRAMME_TYPE_REQUIRES_CURATION")

    return clamp(score, 0.35, 0.99), reasons, flags, dict(doc_counts)


def candidate_from_page(
    row: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    contexts: Sequence[Mapping[str, str]],
    config: Mapping[str, Any],
) -> tuple[Candidate | None, str, list[str]]:
    role = upper(row.get("page_role"))
    if role not in ALLOWED_SEED_ROLES:
        return None, "ROLE_NOT_ALLOWED_TO_SEED_PERMANENT_ENTITY", []

    raw_title = page_title(row)
    cleaned = clean_title(raw_title, config)
    cleaned, title_acronym = extract_trailing_abbreviation(cleaned)
    text = first_value(row, "main_text", "text_excerpt")
    body_acronym = extract_body_abbreviation(cleaned, text) if cleaned else ""
    acronym = title_acronym or body_acronym
    reject_flags: list[str] = []

    if not cleaned or is_generic_title(cleaned, config):
        return None, "GENERIC_OR_EMPTY_MASTER_TITLE", reject_flags
    if len(cleaned) > safe_int(config.get("maximum_identity_name_length"), 220):
        return None, "MASTER_TITLE_TOO_LONG", reject_flags
    if role in CALL_AND_TRANSIENT_ROLES or looks_call_like(raw_title, config):
        return None, "CALL_LIKE_TITLE_BLOCKED_FROM_PERMANENT_INVENTORY", reject_flags
    if has_temporal_identity_token(cleaned, config):
        return None, "TEMPORAL_MASTER_TITLE_REQUIRES_MANUAL_IDENTITY_REVIEW", ["TEMPORAL_TOKEN_IN_TITLE"]

    entity_type = ALLOWED_SEED_ROLES[role]
    groups = evidence_groups(text, config)
    confidence, reasons, flags, doc_counts = score_candidate(
        row, cleaned, entity_type, groups, documents, contexts, config
    )
    parent_name, _relationship = extract_parent_name(cleaned, text)
    subtype = infer_subtype(entity_type, cleaned, text, config)

    if safe_float(row.get("call_evidence_score"), 0.0) > safe_float(row.get("scheme_evidence_score"), 0.0):
        flags.append("CALL_EVIDENCE_EXCEEDS_MASTER_EVIDENCE")
    if upper(row.get("requires_admin_review")) in {"1", "TRUE", "YES"}:
        flags.append("UPSTREAM_ADMIN_REVIEW_FLAG")
    if confidence < safe_float(config.get("minimum_inventory_confidence"), 0.62):
        flags.append("LOW_IDENTITY_CONFIDENCE")
    if not acronym:
        flags.append("OFFICIAL_ABBREVIATION_NOT_CONFIRMED")
    if parent_name:
        flags.append("PARENT_HIERARCHY_REQUIRES_RESOLUTION")

    excerpt_len = safe_int(config.get("evidence_excerpt_length"), 600)
    return Candidate(
        source_page_id=page_id(row),
        source_page_role=role,
        source_page_title=raw_title,
        source_url=page_url(row),
        entity_type=entity_type,
        proposed_name=cleaned,
        raw_title=raw_title,
        abbreviation=acronym,
        confidence=confidence,
        evidence_score=safe_float(row.get("scheme_evidence_score"), 0.0),
        subtype=subtype,
        parent_name_text=parent_name,
        identity_evidence=reasons + [f"PAGE_EVIDENCE_{g.upper()}" for g in groups],
        review_flags=sorted(set(flags)),
        document_counts=doc_counts,
        category_contexts=[dict(x) for x in contexts],
        main_text_excerpt=collapse_ws(text[:excerpt_len]),
    ), "", reject_flags


def candidate_priority(candidate: Candidate) -> tuple[float, int, int, str]:
    return (
        candidate.confidence,
        len(candidate.category_contexts),
        sum(candidate.document_counts.values()),
        candidate.source_url,
    )


def entity_row(candidate: Candidate, entity_id: str) -> dict[str, Any]:
    doc_counts = candidate.document_counts
    return {
        "provisional_entity_id": entity_id,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "proposed_canonical_name": candidate.proposed_name,
        "proposed_entity_type": candidate.entity_type,
        "proposed_subtype": candidate.subtype,
        "official_abbreviation_candidate": candidate.abbreviation,
        "primary_source_page_id": candidate.source_page_id,
        "primary_source_page_role": candidate.source_page_role,
        "primary_source_page_title": candidate.source_page_title,
        "official_source_url": candidate.source_url,
        "identity_confidence": f"{candidate.confidence:.4f}",
        "master_evidence_score": f"{candidate.evidence_score:.3f}",
        "identity_evidence": " | ".join(candidate.identity_evidence),
        "possible_parent_name_text": candidate.parent_name_text,
        "category_context_count": len(candidate.category_contexts),
        "linked_document_count": sum(doc_counts.values()),
        "guideline_document_count": doc_counts.get("GUIDELINE", 0),
        "office_memorandum_count": doc_counts.get("OFFICE_MEMORANDUM", 0),
        "sanction_order_count": doc_counts.get("SANCTION_ORDER", 0),
        "review_flags": " | ".join(candidate.review_flags),
        "requires_admin_review": "1" if candidate.review_flags else "0",
        "curation_status": "PROVISIONAL_REQUIRES_V3_4_0_4",
        "identity_state": "PROVISIONAL_NOT_LOCKED",
        "created_at": utc_now(),
    }


def build_inventory(
    pages: list[dict[str, str]],
    documents: list[dict[str, str]],
    links: list[dict[str, str]],
    config: Mapping[str, Any],
) -> BuildResult:
    pages_by_url, _pages_by_id = build_page_maps(pages)
    docs_by_source = aggregate_documents(documents)
    category_contexts, index_review_candidates = build_category_contexts(pages_by_url, links, config)

    raw_candidates: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for row in pages:
        role = upper(row.get("page_role"))
        if role not in ALLOWED_SEED_ROLES:
            continue
        url = page_url(row)
        candidate, rejection_reason, rejection_flags = candidate_from_page(
            row,
            docs_by_source.get(url, []),
            category_contexts.get(url, []),
            config,
        )
        if candidate is None:
            rejected_row = {
                "candidate_page_id": page_id(row),
                "page_title": page_title(row),
                "page_role": role,
                "final_url": url,
                "rejection_reason": rejection_reason,
                "review_flags": " | ".join(rejection_flags),
                "review_required": "1",
                "details": "Permanent identity not created; manual curation may restore the candidate.",
            }
            rejected.append(rejected_row)
            audit.append({
                "source_page_id": page_id(row),
                "page_title": page_title(row),
                "page_role": role,
                "action": "REJECTED_FROM_PROVISIONAL_INVENTORY",
                "provisional_entity_id": "",
                "reason": rejection_reason,
            })
            continue
        raw_candidates.append(candidate)

    # Exact normalized-name deduplication inside the same proposed entity type.
    grouped: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in raw_candidates:
        grouped[(candidate.entity_type, normalize_key(candidate.proposed_name))].append(candidate)

    selected: list[tuple[Candidate, str, list[Candidate]]] = []
    for (entity_type, key), group in grouped.items():
        ranked = sorted(group, key=candidate_priority, reverse=True)
        primary = ranked[0]
        entity_id = stable_id(
            "dst_provisional_scheme" if entity_type == "SCHEME" else "dst_provisional_programme",
            DEPARTMENT_CODE,
            entity_type,
            key,
        )
        duplicates = ranked[1:]
        selected.append((primary, entity_id, duplicates))
        for duplicate in duplicates:
            rejected.append({
                "candidate_page_id": duplicate.source_page_id,
                "page_title": duplicate.source_page_title,
                "page_role": duplicate.source_page_role,
                "final_url": duplicate.source_url,
                "rejection_reason": "DUPLICATE_NAME_MERGED_AS_ADDITIONAL_SOURCE",
                "review_flags": "",
                "review_required": "0",
                "details": f"Merged into {entity_id}",
            })
            audit.append({
                "source_page_id": duplicate.source_page_id,
                "page_title": duplicate.source_page_title,
                "page_role": duplicate.source_page_role,
                "action": "MERGED_AS_ADDITIONAL_SOURCE",
                "provisional_entity_id": entity_id,
                "reason": "EXACT_NORMALIZED_NAME_MATCH",
            })

    schemes: list[dict[str, Any]] = []
    programmes: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    hierarchy: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    # Detect cross-type name collisions; do not merge automatically.
    cross_types: dict[str, set[str]] = defaultdict(set)
    for primary, _entity_id, _dupes in selected:
        cross_types[normalize_key(primary.proposed_name)].add(primary.entity_type)

    for primary, entity_id, duplicates in selected:
        if len(cross_types[normalize_key(primary.proposed_name)]) > 1:
            primary.review_flags.append("SCHEME_PROGRAMME_TYPE_COLLISION")

        row = entity_row(primary, entity_id)
        if primary.entity_type == "SCHEME":
            schemes.append(row)
        else:
            programmes.append(row)

        audit.append({
            "source_page_id": primary.source_page_id,
            "page_title": primary.source_page_title,
            "page_role": primary.source_page_role,
            "action": "PROVISIONAL_ENTITY_CREATED",
            "provisional_entity_id": entity_id,
            "reason": "ALLOWED_MASTER_ROLE_WITH_PERMANENT_IDENTITY_EVIDENCE",
        })

        # Primary and duplicate page evidence.
        all_sources = [primary] + duplicates
        for source in all_sources:
            evidence.append({
                "evidence_id": stable_id("dst_identity_evidence", entity_id, "PAGE", source.source_page_id),
                "provisional_entity_id": entity_id,
                "evidence_type": "OFFICIAL_MASTER_PAGE",
                "source_id": source.source_page_id,
                "source_url": source.source_url,
                "source_title": source.source_page_title,
                "evidence_text": source.main_text_excerpt,
                "evidence_confidence": f"{source.confidence:.4f}",
            })

        # Alias candidates.
        alias_seen: set[tuple[str, str]] = set()
        if primary.abbreviation:
            alias_seen.add((primary.abbreviation.casefold(), "OFFICIAL_ABBREVIATION_CANDIDATE"))
            aliases.append({
                "alias_candidate_id": stable_id("dst_alias", entity_id, primary.abbreviation, "ABBREVIATION"),
                "provisional_entity_id": entity_id,
                "proposed_canonical_name": primary.proposed_name,
                "alias_text": primary.abbreviation,
                "alias_type": "OFFICIAL_ABBREVIATION_CANDIDATE",
                "source_page_id": primary.source_page_id,
                "source_url": primary.source_url,
                "alias_confidence": "0.9000",
                "evidence": "TRAILING_TITLE_OR_BODY_ACRONYM",
                "curation_status": "PROVISIONAL",
            })
        if collapse_ws(primary.raw_title) != collapse_ws(primary.proposed_name):
            key = (primary.raw_title.casefold(), "OFFICIAL_PAGE_TITLE_VARIANT")
            if key not in alias_seen:
                alias_seen.add(key)
                aliases.append({
                    "alias_candidate_id": stable_id("dst_alias", entity_id, primary.raw_title, "TITLE_VARIANT"),
                    "provisional_entity_id": entity_id,
                    "proposed_canonical_name": primary.proposed_name,
                    "alias_text": primary.raw_title,
                    "alias_type": "OFFICIAL_PAGE_TITLE_VARIANT",
                    "source_page_id": primary.source_page_id,
                    "source_url": primary.source_url,
                    "alias_confidence": "0.7800",
                    "evidence": "RAW_OFFICIAL_PAGE_TITLE_DIFFERS_AFTER_SITE_SUFFIX_OR_ACRONYM_EXTRACTION",
                    "curation_status": "PROVISIONAL",
                })

        # Category-index evidence.
        for context in primary.category_contexts:
            evidence.append({
                "evidence_id": stable_id("dst_identity_evidence", entity_id, "CATEGORY", context.get("category_page_id", ""), context.get("anchor_text", "")),
                "provisional_entity_id": entity_id,
                "evidence_type": "CATEGORY_INDEX_LINK",
                "source_id": context.get("category_page_id", ""),
                "source_url": context.get("category_page_url", ""),
                "source_title": context.get("category_page_title", ""),
                "evidence_text": context.get("anchor_text", ""),
                "evidence_confidence": "0.8500",
            })

        # Document evidence attached to the source page.
        for doc in docs_by_source.get(primary.source_url, []):
            role = upper(doc.get("document_role"))
            if role not in {"GUIDELINE", "OFFICE_MEMORANDUM", "BROCHURE_OR_FLYER", "SANCTION_ORDER", "APPLICATION_FORMAT"}:
                continue
            evidence.append({
                "evidence_id": stable_id("dst_identity_evidence", entity_id, "DOCUMENT", first_value(doc, "document_id"), document_url(doc)),
                "provisional_entity_id": entity_id,
                "evidence_type": f"OFFICIAL_DOCUMENT_{role}",
                "source_id": first_value(doc, "document_id"),
                "source_url": document_url(doc),
                "source_title": first_value(doc, "filename", "anchor_text"),
                "evidence_text": first_value(doc, "anchor_text", "filename"),
                "evidence_confidence": first_value(doc, "document_role_confidence") or "0.7000",
            })

        if primary.parent_name_text:
            hierarchy.append({
                "relationship_candidate_id": stable_id("dst_hierarchy", entity_id, primary.parent_name_text),
                "child_provisional_entity_id": entity_id,
                "child_name": primary.proposed_name,
                "child_entity_type": primary.entity_type,
                "parent_name_text": primary.parent_name_text,
                "relationship_type": "POSSIBLE_COMPONENT_OF",
                "relationship_confidence": "0.6500",
                "evidence_text": primary.main_text_excerpt,
                "source_page_id": primary.source_page_id,
                "source_url": primary.source_url,
                "resolution_status": "UNRESOLVED_PARENT_TEXT",
                "curation_status": "PROVISIONAL",
            })

        if primary.review_flags or primary.confidence < safe_float(config.get("minimum_auto_review_free_confidence"), 0.82):
            flags = sorted(set(primary.review_flags + (["IDENTITY_CONFIDENCE_BELOW_REVIEW_FREE_THRESHOLD"] if primary.confidence < safe_float(config.get("minimum_auto_review_free_confidence"), 0.82) else [])))
            review.append({
                "review_id": stable_id("dst_identity_review", entity_id),
                "review_type": "PROVISIONAL_IDENTITY",
                "provisional_entity_id": entity_id,
                "proposed_canonical_name": primary.proposed_name,
                "proposed_entity_type": primary.entity_type,
                "official_abbreviation_candidate": primary.abbreviation,
                "identity_confidence": f"{primary.confidence:.4f}",
                "review_flags": " | ".join(flags),
                "source_page_title": primary.source_page_title,
                "source_url": primary.source_url,
                "recommended_action": "VERIFY_OFFICIAL_NAME_TYPE_ABBREVIATION_AND_PARENT_BEFORE_V3_4_0_4_LOCK",
            })

    # Surface unclassified internal category links as discovery review items only.
    limit = safe_int(config.get("maximum_unknown_index_candidates"), 500)
    for item in index_review_candidates[:limit]:
        review.append({
            "review_id": stable_id("dst_identity_review", "INDEX_LINK", item["source_category_url"], item["target_url"]),
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "provisional_entity_id": "",
            "proposed_canonical_name": item["anchor_text"],
            "proposed_entity_type": "UNRESOLVED",
            "official_abbreviation_candidate": "",
            "identity_confidence": "0.3500",
            "review_flags": "CATEGORY_LINK_NOT_CLASSIFIED_AS_MASTER",
            "source_page_title": item["source_category_title"],
            "source_url": item["target_url"],
            "recommended_action": "CHECK_WHETHER_TARGET_IS_A_PERMANENT_SCHEME_PROGRAMME_OR_SUPPORTING_PAGE",
        })

    return BuildResult(
        schemes=schemes,
        programmes=programmes,
        aliases=aliases,
        hierarchy=hierarchy,
        evidence=evidence,
        rejected=rejected,
        review=review,
        audit=audit,
    )


def validate_outputs(
    input_pages: list[dict[str, str]],
    result: BuildResult,
    config: Mapping[str, Any] = DEFAULT_CONFIG,
) -> dict[str, Any]:
    entities = result.schemes + result.programmes
    input_seed_count = sum(upper(row.get("page_role")) in ALLOWED_SEED_ROLES for row in input_pages)
    entity_ids = [collapse_ws(row.get("provisional_entity_id")) for row in entities]
    scheme_names = [normalize_key(collapse_ws(row.get("proposed_canonical_name"))) for row in result.schemes]
    programme_names = [normalize_key(collapse_ws(row.get("proposed_canonical_name"))) for row in result.programmes]
    forbidden_fields_found = sorted({field for row in entities for field in row if field in FORBIDDEN_LOCK_FIELDS})

    call_seeded_entities = sum(
        upper(row.get("primary_source_page_role")) in CALL_AND_TRANSIENT_ROLES for row in entities
    )
    call_like_names = sum(looks_call_like(collapse_ws(row.get("proposed_canonical_name")), config) for row in entities)
    temporal_names = sum(has_temporal_identity_token(collapse_ws(row.get("proposed_canonical_name")), config) for row in entities)
    locked_entities = sum(upper(row.get("identity_state")) != "PROVISIONAL_NOT_LOCKED" for row in entities)
    missing_names = sum(not collapse_ws(row.get("proposed_canonical_name")) for row in entities)
    missing_sources = sum(not collapse_ws(row.get("official_source_url")) for row in entities)
    missing_confidence = sum(not collapse_ws(row.get("identity_confidence")) for row in entities)
    duplicate_ids = len(entity_ids) - len(set(entity_ids))
    duplicate_scheme_names = len(scheme_names) - len(set(scheme_names))
    duplicate_programme_names = len(programme_names) - len(set(programme_names))

    checks = {
        "input_master_candidates_accounted_for": len(entities) + len(result.rejected) >= input_seed_count,
        "at_least_one_provisional_entity_created": len(entities) > 0,
        "entity_ids_unique": duplicate_ids == 0,
        "scheme_names_unique_within_inventory": duplicate_scheme_names == 0,
        "programme_names_unique_within_inventory": duplicate_programme_names == 0,
        "entity_names_complete": missing_names == 0,
        "source_urls_complete": missing_sources == 0,
        "identity_confidence_complete": missing_confidence == 0,
        "call_pages_not_used_as_entity_seeds": call_seeded_entities == 0,
        "call_like_names_absent": call_like_names == 0,
        "temporal_names_absent": temporal_names == 0,
        "identity_not_locked": locked_entities == 0,
        "forbidden_lock_fields_absent": not forbidden_fields_found,
    }
    passed = all(checks.values())
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "generated_at": utc_now(),
        "counts": {
            "input_pages": len(input_pages),
            "input_master_candidates": input_seed_count,
            "provisional_schemes": len(result.schemes),
            "provisional_programmes": len(result.programmes),
            "total_provisional_entities": len(entities),
            "rejected_or_merged_candidates": len(result.rejected),
            "alias_candidates": len(result.aliases),
            "hierarchy_candidates": len(result.hierarchy),
            "evidence_rows": len(result.evidence),
            "identity_review_rows": len(result.review),
        },
        "quality": {
            "duplicate_entity_ids": duplicate_ids,
            "duplicate_scheme_names": duplicate_scheme_names,
            "duplicate_programme_names": duplicate_programme_names,
            "call_seeded_entities": call_seeded_entities,
            "call_like_names": call_like_names,
            "temporal_names": temporal_names,
            "locked_entities": locked_entities,
            "missing_names": missing_names,
            "missing_sources": missing_sources,
            "missing_confidence": missing_confidence,
            "forbidden_lock_fields_found": forbidden_fields_found,
        },
        "checks": checks,
        "inventory_validation_passed": passed,
        "ready_for_v3_4_0_4": passed,
    }


def build_summary(
    pages: list[dict[str, str]],
    documents: list[dict[str, str]],
    links: list[dict[str, str]],
    result: BuildResult,
    validation: Mapping[str, Any],
    input_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    entities = result.schemes + result.programmes
    subtype_counts = Counter(collapse_ws(row.get("proposed_subtype")) for row in entities)
    review_type_counts = Counter(collapse_ws(row.get("review_type")) for row in result.review)
    rejection_counts = Counter(collapse_ws(row.get("rejection_reason")) for row in result.rejected)
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "completed_at": utc_now(),
        "input_dir": str(input_dir),
        "link_graph": str(input_dir.parent / "v3_4_0_1" / "crawl" / LINK_GRAPH_INPUT),
        "output_dir": str(output_dir),
        "network_access_used": False,
        "recrawl_performed": False,
        "identity_safeguard": {
            "identity_state": "PROVISIONAL_NOT_LOCKED",
            "call_pages_used_as_entity_seeds": False,
            "call_titles_promoted_to_scheme_names": False,
            "temporal_call_tokens_allowed_in_identity": False,
            "description": "Permanent identities are proposed for curation only; v3.4.0.4 must approve and lock them.",
        },
        "counts": {
            "classified_pages_read": len(pages),
            "classified_documents_read": len(documents),
            "link_graph_rows_read": len(links),
            "scheme_master_page_candidates": sum(upper(row.get("page_role")) == "SCHEME_MASTER_CANDIDATE" for row in pages),
            "programme_master_page_candidates": sum(upper(row.get("page_role")) == "PROGRAMME_MASTER_CANDIDATE" for row in pages),
            "provisional_schemes": len(result.schemes),
            "provisional_programmes": len(result.programmes),
            "provisional_entities_total": len(entities),
            "alias_candidates": len(result.aliases),
            "hierarchy_candidates": len(result.hierarchy),
            "master_source_evidence_rows": len(result.evidence),
            "rejected_or_merged_candidates": len(result.rejected),
            "identity_review_rows": len(result.review),
        },
        "provisional_subtype_counts": dict(sorted(subtype_counts.items())),
        "review_type_counts": dict(sorted(review_type_counts.items())),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "inventory_validation_passed": bool(validation.get("inventory_validation_passed")),
        "ready_for_v3_4_0_4": bool(validation.get("ready_for_v3_4_0_4")),
        "outputs": {
            "schemes": SCHEME_OUTPUT,
            "programmes": PROGRAMME_OUTPUT,
            "aliases": ALIAS_OUTPUT,
            "hierarchy": HIERARCHY_OUTPUT,
            "evidence": EVIDENCE_OUTPUT,
            "rejected": REJECTED_OUTPUT,
            "review": REVIEW_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path | None]:
    root = Path(args.project_root).resolve()
    input_dir = Path(args.input_dir).resolve() if args.input_dir else root / "data" / "departments" / "dst" / "v3_4_0_2"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else root / "data" / "departments" / "dst" / "v3_4_0_3"
    link_graph = Path(args.link_graph).resolve() if args.link_graph else root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl" / LINK_GRAPH_INPUT
    config_path = Path(args.config).resolve() if args.config else None
    return input_dir, output_dir, link_graph, config_path


def run_builder(args: argparse.Namespace) -> int:
    input_dir, output_dir, link_graph_path, config_path = resolve_paths(args)
    config = load_config(config_path)
    pages = read_csv(input_dir / CLASSIFIED_PAGES_INPUT)
    documents = read_csv(input_dir / CLASSIFIED_DOCUMENTS_INPUT)
    links = read_csv(link_graph_path)

    if args.dry_run:
        payload = {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "classified_pages": len(pages),
            "classified_documents": len(documents),
            "link_graph_rows": len(links),
            "scheme_master_candidates": sum(upper(row.get("page_role")) == "SCHEME_MASTER_CANDIDATE" for row in pages),
            "programme_master_candidates": sum(upper(row.get("page_role")) == "PROGRAMME_MASTER_CANDIDATE" for row in pages),
            "network_access_used": False,
            "files_written": False,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    result = build_inventory(pages, documents, links, config)
    validation = validate_outputs(pages, result, config)
    summary = build_summary(pages, documents, links, result, validation, input_dir, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / SCHEME_OUTPUT, result.schemes)
    write_csv(output_dir / PROGRAMME_OUTPUT, result.programmes)
    write_csv(output_dir / ALIAS_OUTPUT, result.aliases)
    write_csv(output_dir / HIERARCHY_OUTPUT, result.hierarchy)
    write_csv(output_dir / EVIDENCE_OUTPUT, result.evidence)
    write_csv(output_dir / REJECTED_OUTPUT, result.rejected)
    write_csv(output_dir / REVIEW_OUTPUT, result.review)
    write_csv(output_dir / AUDIT_OUTPUT, result.audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.strict and not validation["inventory_validation_passed"]:
        return 3
    return 0


def self_test() -> dict[str, Any]:
    pages = [
        {
            "classified_page_id": "scheme1",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.91",
            "scheme_evidence_score": "84",
            "call_evidence_score": "0",
            "page_title": "Promotion of University Research and Scientific Excellence (PURSE)",
            "final_url": "https://dst.gov.in/purse",
            "main_text": "Objectives Eligibility Financial assistance Who can apply Application process Beneficiaries Scope.",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "requires_admin_review": "0",
        },
        {
            "classified_page_id": "programme1",
            "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.90",
            "scheme_evidence_score": "70",
            "call_evidence_score": "0",
            "page_title": "Technology Development Programme (TDP)",
            "final_url": "https://dst.gov.in/tdp",
            "main_text": "The programme objectives include technology support. Eligibility and application procedure are described.",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "requires_admin_review": "0",
        },
        {
            "classified_page_id": "call1",
            "page_role": "CALL_FOR_PROPOSALS",
            "page_role_confidence": "0.98",
            "scheme_evidence_score": "20",
            "call_evidence_score": "95",
            "page_title": "Call for Proposals under Technology Development Programme 2026",
            "final_url": "https://dst.gov.in/call/tdp-2026",
            "main_text": "Applications are invited.",
        },
        {
            "classified_page_id": "category1",
            "page_role": "SCHEME_CATEGORY_INDEX",
            "page_title": "Schemes/Programmes",
            "final_url": "https://dst.gov.in/schemes-programmes",
        },
    ]
    documents = [
        {
            "document_id": "doc1",
            "source_page_url": "https://dst.gov.in/purse",
            "document_url": "https://dst.gov.in/purse-guidelines.pdf",
            "filename": "PURSE Guidelines.pdf",
            "document_role": "GUIDELINE",
            "document_role_confidence": "0.95",
        }
    ]
    links = [
        {
            "from_url": "https://dst.gov.in/schemes-programmes",
            "to_url": "https://dst.gov.in/purse",
            "anchor_text": "Promotion of University Research and Scientific Excellence",
            "is_internal": "1",
            "is_document": "0",
        },
        {
            "from_url": "https://dst.gov.in/schemes-programmes",
            "to_url": "https://dst.gov.in/tdp",
            "anchor_text": "Technology Development Programme",
            "is_internal": "1",
            "is_document": "0",
        },
    ]
    result = build_inventory(pages, documents, links, DEFAULT_CONFIG)
    validation = validate_outputs(pages, result)
    tests = {
        "scheme_created": len(result.schemes) == 1,
        "programme_created": len(result.programmes) == 1,
        "call_not_created_as_entity": len(result.schemes) + len(result.programmes) == 2,
        "scheme_name_preserved_without_acronym_suffix": result.schemes[0]["proposed_canonical_name"] == "Promotion of University Research and Scientific Excellence",
        "programme_name_preserved_without_call_year": result.programmes[0]["proposed_canonical_name"] == "Technology Development Programme",
        "abbreviation_extracted": any(row.get("alias_text") == "PURSE" for row in result.aliases),
        "category_context_used": safe_int(result.schemes[0].get("category_context_count")) == 1,
        "guideline_evidence_attached": any(row.get("evidence_type") == "OFFICIAL_DOCUMENT_GUIDELINE" for row in result.evidence),
        "identity_remains_provisional": all(row.get("identity_state") == "PROVISIONAL_NOT_LOCKED" for row in result.schemes + result.programmes),
        "validation_passed": bool(validation.get("inventory_validation_passed")),
    }
    return {
        "service_version": VERSION,
        "department": DEPARTMENT_CODE,
        "tests": tests,
        "self_test_passed": all(tests.values()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="SSIP project root")
    parser.add_argument("--input-dir", help="Override v3.4.0.2 input directory")
    parser.add_argument("--output-dir", help="Override v3.4.0.3 output directory")
    parser.add_argument("--link-graph", help="Override v3.4.0.1 link graph path")
    parser.add_argument("--config", help="Optional JSON configuration override")
    parser.add_argument("--dry-run", action="store_true", help="Validate input discovery without writing outputs")
    parser.add_argument("--strict", action="store_true", help="Return exit code 3 when validation fails")
    parser.add_argument("--self-test", action="store_true", help="Run offline built-in tests")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        payload = self_test()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload["self_test_passed"] else 2
    try:
        return run_builder(args)
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(json.dumps({
            "service_version": VERSION,
            "department": DEPARTMENT_CODE,
            "error": type(exc).__name__,
            "message": str(exc),
        }, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
