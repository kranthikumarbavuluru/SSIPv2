#!/usr/bin/env python3
"""
SSIP v3.4.0.2 — DST Evidence-Based Page-Role Classifier

Purpose
-------
Classify DST source pages and discovered documents using deterministic evidence
from URL, title, recovered page text, crawler hints, call-pattern audit and link
context. This phase never creates canonical scheme identities.

Safety guarantees
-----------------
* No network access.
* No recrawl.
* No writes to v3.4.0.1 or v3.4.0.1.1 inputs.
* No scheme_id, canonical_scheme_name or locked_scheme_name output fields.
* Call titles are never promoted to permanent scheme names.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

VERSION = "3.4.0.2"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

PAGE_INPUT = "dst_crawled_pages_enriched_v3_4_0_1_1.csv"
DOCUMENT_INPUT = "dst_documents_enriched_v3_4_0_1_1.csv"
CALL_AUDIT_INPUT = "dst_call_pattern_audit_v3_4_0_1_1.csv"
LINK_GRAPH_INPUT = "dst_link_graph_v3_4_0_1.csv"

CLASSIFIED_PAGES_OUTPUT = "dst_classified_pages_v3_4_0_2.csv"
CLASSIFIED_DOCUMENTS_OUTPUT = "dst_classified_documents_v3_4_0_2.csv"
SCHEME_CANDIDATES_OUTPUT = "dst_scheme_master_page_candidates_v3_4_0_2.csv"
PROGRAMME_CANDIDATES_OUTPUT = "dst_programme_master_page_candidates_v3_4_0_2.csv"
CALL_PAGES_OUTPUT = "dst_call_pages_v3_4_0_2.csv"
SUPPORTING_PAGES_OUTPUT = "dst_supporting_pages_v3_4_0_2.csv"
NON_SCHEME_OUTPUT = "dst_non_scheme_pages_v3_4_0_2.csv"
UNKNOWN_REVIEW_OUTPUT = "dst_unknown_review_queue_v3_4_0_2.csv"
CLASSIFIER_AUDIT_OUTPUT = "dst_classifier_audit_v3_4_0_2.csv"
VALIDATION_OUTPUT = "dst_classifier_validation_v3_4_0_2.json"
SUMMARY_OUTPUT = "dst_classifier_summary_v3_4_0_2.json"

FORBIDDEN_IDENTITY_FIELDS = {
    "scheme_id",
    "canonical_scheme_name",
    "locked_scheme_name",
    "canonical_programme_name",
    "programme_id",
}

PAGE_ROLES = (
    "SCHEME_MASTER_CANDIDATE",
    "PROGRAMME_MASTER_CANDIDATE",
    "SCHEME_CATEGORY_INDEX",
    "PROGRAMME_CATEGORY_INDEX",
    "CALL_FOR_PROPOSALS",
    "APPLICATION_INVITATION",
    "EXPRESSION_OF_INTEREST",
    "DEADLINE_EXTENSION",
    "CALL_CORRIGENDUM",
    "CALL_RESULT",
    "CALL_ARCHIVE_INDEX",
    "CURRENT_CALL_INDEX",
    "GUIDELINE_PAGE",
    "APPLICATION_GUIDANCE",
    "SANCTIONED_PROJECT_EVIDENCE",
    "NOTIFICATION",
    "OFFICE_MEMORANDUM",
    "NEWS",
    "EVENT",
    "RECRUITMENT",
    "CONTACT_PAGE",
    "GENERAL_INFORMATION",
    "BROKEN_OFFICIAL_LINK",
    "NON_SCHEME",
    "UNKNOWN",
)

CALL_ROLES = {
    "CALL_FOR_PROPOSALS",
    "APPLICATION_INVITATION",
    "EXPRESSION_OF_INTEREST",
    "DEADLINE_EXTENSION",
    "CALL_CORRIGENDUM",
    "CALL_RESULT",
    "CALL_ARCHIVE_INDEX",
    "CURRENT_CALL_INDEX",
}

MASTER_CANDIDATE_ROLES = {
    "SCHEME_MASTER_CANDIDATE",
    "PROGRAMME_MASTER_CANDIDATE",
}

SUPPORTING_ROLES = {
    "GUIDELINE_PAGE",
    "APPLICATION_GUIDANCE",
    "SANCTIONED_PROJECT_EVIDENCE",
    "NOTIFICATION",
    "OFFICE_MEMORANDUM",
    "SCHEME_CATEGORY_INDEX",
    "PROGRAMME_CATEGORY_INDEX",
}

NON_SCHEME_ROLES = {
    "NEWS",
    "EVENT",
    "RECRUITMENT",
    "CONTACT_PAGE",
    "GENERAL_INFORMATION",
    "BROKEN_OFFICIAL_LINK",
    "NON_SCHEME",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "minimum_auto_confidence": 0.72,
    "minimum_master_candidate_confidence": 0.70,
    "review_margin_threshold": 0.08,
    "maximum_unknown_rate": 0.20,
    "body_fallback_review_word_threshold": 80,
    "category_min_relevant_internal_links": 5,
    "evidence_excerpt_length": 500,
    "scheme_evidence_phrases": {
        "objective": ["objective", "objectives", "aims to", "aim of the scheme", "purpose of the scheme"],
        "eligibility": ["eligibility", "eligible", "who can apply", "applicants should", "applicant must"],
        "benefit": ["financial assistance", "support provided", "funding support", "grant", "assistance", "benefits"],
        "application": ["how to apply", "application procedure", "apply online", "application process", "submit proposal"],
        "beneficiary": ["target group", "beneficiaries", "scientists", "researchers", "institutions", "universities"],
        "duration": ["duration", "tenure", "project period"],
        "scope": ["scope", "thrust areas", "focus areas", "areas of support"],
    },
    "programme_terms": [
        "programme", "program", "mission", "initiative", "platform", "network",
        "facility", "cooperation", "capacity building", "research council",
    ],
    "scheme_terms": [
        "scheme", "fellowship", "award", "grant", "fund", "support scheme",
    ],
    "call_terms": [
        "call for proposal", "call for proposals", "call for project proposal", "joint call",
        "special call", "inviting proposals", "proposal invited", "applications invited",
    ],
    "index_terms": ["schemes/programmes", "schemes and programmes", "programmes & initiatives", "programmes and initiatives"],
}


@dataclass
class Evidence:
    role: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class Classification:
    role: str
    confidence: float
    top_score: float
    second_role: str
    second_score: float
    reasons: list[str]
    review_flags: list[str]
    possible_parent_name_text: str
    scheme_evidence_score: float
    call_evidence_score: float
    evidence: dict[str, float]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def lower(value: Any) -> str:
    return collapse_ws(value).casefold()


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


def contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase.casefold() in text for phrase in phrases)


def count_phrase_groups(text: str, groups: Mapping[str, Sequence[str]]) -> tuple[int, list[str]]:
    matched: list[str] = []
    for group, phrases in groups.items():
        if contains_any(text, phrases):
            matched.append(group)
    return len(matched), matched


def extract_parent_name(title: str, text: str) -> str:
    """Extract only explicit parent-name text; never infer or canonicalize it."""
    combined = collapse_ws(f"{title}. {text[:5000]}")
    patterns = (
        r"(?i)\bunder\s+(?:the\s+)?(?:scheme|programme|program|mission|initiative)\s+[\"'“”]?([^.;:\n]{3,140})",
        r"(?i)\bunder\s+[\"'“”]?([^.;:\n]{3,120}?)\s+(?:scheme|programme|program|mission|initiative)\b",
        r"(?i)\bas\s+part\s+of\s+(?:the\s+)?[\"'“”]?([^.;:\n]{3,140})",
    )
    for pattern in patterns:
        match = re.search(pattern, combined)
        if not match:
            continue
        candidate = collapse_ws(match.group(1)).strip(" -–—'\"“”")
        candidate = re.sub(r"(?i)\b(?:for|dated|during|with|and applications?).*$", "", candidate).strip()
        if 3 <= len(candidate) <= 140:
            return candidate
    return ""


def classify_call_subtype(title: str, text: str, audit_pattern: str = "") -> str:
    t = lower(title)
    body = lower(text[:8000])
    combined = f"{t} {body} {lower(audit_pattern)}"
    if re.search(r"\b(corrigendum|addendum|amendment)\b", combined):
        return "CALL_CORRIGENDUM"
    if re.search(r"\b(last date|deadline|closing date).{0,80}\b(extended|extension)\b|\bextension of.{0,100}(date|deadline)", combined):
        return "DEADLINE_EXTENSION"
    if audit_pattern == "DEADLINE_EXTENSION":
        return "DEADLINE_EXTENSION"
    if re.search(r"\b(result|results|selected|recommended|shortlisted|selection list)\b", t):
        return "CALL_RESULT"
    if audit_pattern == "RESULT_OR_SELECTION":
        return "CALL_RESULT"
    if re.search(r"\bexpression of interest\b|\beoi\b", combined):
        return "EXPRESSION_OF_INTEREST"
    if audit_pattern == "EXPRESSION_OF_INTEREST":
        return "EXPRESSION_OF_INTEREST"
    # An explicit proposal-call title is the primary role even when the body
    # contains generic wording such as "applications are invited".
    if re.search(r"\bcall for (?:project )?proposals?\b|\bjoint call\b|\bspecial call\b", t):
        return "CALL_FOR_PROPOSALS"
    if audit_pattern == "CALL_FOR_PROPOSALS":
        return "CALL_FOR_PROPOSALS"
    if re.search(r"\bapplications? (?:are )?invited\b|\binviting applications?\b", combined):
        return "APPLICATION_INVITATION"
    if audit_pattern == "APPLICATION_INVITATION":
        return "APPLICATION_INVITATION"
    return "CALL_FOR_PROPOSALS"


def aggregate_links(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        source = collapse_ws(row.get("from_url"))
        if not source:
            continue
        c = stats[source]
        c["total"] += 1
        if safe_int(row.get("is_internal")) == 1:
            c["internal"] += 1
        else:
            c["external"] += 1
        if safe_int(row.get("is_document")) == 1:
            c["documents"] += 1
        if safe_int(row.get("in_main_content")) == 1:
            c["main_content"] += 1
        hint = upper(row.get("role_hint"))
        target = lower(row.get("to_url"))
        if "CALL" in hint or "call" in target:
            c["call_like"] += 1
        if "SCHEME" in hint or "PROGRAMME" in hint or re.search(r"scheme|programme|program", target):
            c["scheme_programme_like"] += 1
    return {key: dict(value) for key, value in stats.items()}


def upper(value: Any) -> str:
    return collapse_ws(value).upper()


def hard_role(row: Mapping[str, Any]) -> tuple[str, list[str]] | None:
    status = safe_int(row.get("http_status"))
    title = lower(row.get("page_title") or row.get("title"))
    url = lower(row.get("final_url") or row.get("requested_url"))
    source_hint = upper(row.get("source_role_hint"))
    page_hint = upper(row.get("page_role_hint"))

    if not (200 <= status < 300):
        return "BROKEN_OFFICIAL_LINK", [f"HTTP_STATUS_{status or 'UNKNOWN'}"]

    if "archive-call-for-proposals" in url or "CALL_INDEX_ARCHIVE" in page_hint or "CALL_ARCHIVE" in source_hint:
        return "CALL_ARCHIVE_INDEX", ["ARCHIVE_CALL_URL_OR_HINT"]
    if re.search(r"/call-for-proposals(?:\?|$)", url) or "CURRENT_CALL_INDEX" in source_hint:
        return "CURRENT_CALL_INDEX", ["CURRENT_CALL_INDEX_URL_OR_HINT"]
    if re.search(r"/schemes-programmes(?:\?|$)", url) or title in {"schemes/ programmes", "schemes/programmes", "schemes and programmes"}:
        return "SCHEME_CATEGORY_INDEX", ["SCHEME_PROGRAMME_ROOT_INDEX"]
    if "programmes & initiatives" in title or "programmes and initiatives" in title:
        return "PROGRAMME_CATEGORY_INDEX", ["PROGRAMME_INITIATIVES_INDEX"]

    if re.search(r"\bcontact(?: us)?\b", title) or re.search(r"/contact(?:-|/|$)", url):
        return "CONTACT_PAGE", ["CONTACT_TITLE_OR_URL"]
    if re.search(r"\brecruitment\b|\bvacanc(?:y|ies)\b|\bjob(?:s)?\b", title) or re.search(r"/recruitment|/vacanc", url):
        return "RECRUITMENT", ["RECRUITMENT_TITLE_OR_URL"]

    return None


def score_page(
    row: Mapping[str, Any],
    call_pattern: str,
    links: Mapping[str, int],
    config: Mapping[str, Any],
) -> Classification:
    title_raw = collapse_ws(row.get("page_title") or row.get("title"))
    title = title_raw.casefold()
    text_raw = collapse_ws(row.get("main_text"))
    text = text_raw[:30000].casefold()
    combined = f"{title} {text}"
    url = lower(row.get("final_url") or row.get("requested_url"))
    source_hint = upper(row.get("source_role_hint"))
    page_hint = upper(row.get("page_role_hint"))
    extraction_status = upper(row.get("text_extraction_status"))
    word_count = safe_int(row.get("word_count"))

    hard = hard_role(row)
    if hard:
        role, reasons = hard
        return Classification(
            role=role,
            confidence=0.99,
            top_score=100.0,
            second_role="UNKNOWN",
            second_score=0.0,
            reasons=reasons,
            review_flags=[],
            possible_parent_name_text="",
            scheme_evidence_score=0.0,
            call_evidence_score=0.0,
            evidence={role: 100.0},
        )

    scores: dict[str, float] = {role: 0.0 for role in PAGE_ROLES}
    reasons: dict[str, list[str]] = defaultdict(list)

    def add(role: str, points: float, reason: str) -> None:
        scores[role] += points
        reasons[role].append(reason)

    # Structural/crawler hints.
    if page_hint == "CALL_CANDIDATE":
        subtype = classify_call_subtype(title_raw, text_raw, call_pattern)
        add(subtype, 28, "CRAWLER_CALL_CANDIDATE")
    if page_hint == "GUIDELINE_OR_MANUAL_CANDIDATE":
        add("GUIDELINE_PAGE", 46, "CRAWLER_GUIDELINE_HINT")
    if page_hint == "SANCTIONED_PROJECTS_EVIDENCE":
        add("SANCTIONED_PROJECT_EVIDENCE", 70, "CRAWLER_SANCTIONED_PROJECT_HINT")
    if page_hint == "SCHEME_PROGRAMME_CANDIDATE":
        add("SCHEME_MASTER_CANDIDATE", 18, "CRAWLER_SCHEME_PROGRAMME_HINT")
        add("PROGRAMME_MASTER_CANDIDATE", 18, "CRAWLER_SCHEME_PROGRAMME_HINT")
    if page_hint == "SCHEME_PROGRAMME_SUPPORTING_PAGE":
        add("GENERAL_INFORMATION", 16, "CRAWLER_SUPPORTING_PAGE_HINT")
    if "SCHEME_PROGRAMME_INDEX" in source_hint:
        add("SCHEME_CATEGORY_INDEX", 22, "SOURCE_SCHEME_PROGRAMME_INDEX")
        add("PROGRAMME_CATEGORY_INDEX", 22, "SOURCE_SCHEME_PROGRAMME_INDEX")

    # Explicit call subtype evidence.
    subtype = classify_call_subtype(title_raw, text_raw, call_pattern)
    call_title_hit = bool(re.search(r"\bcall for (?:project )?proposals?\b|\bjoint call\b|\bspecial call\b", title))
    call_body_hit = bool(re.search(r"\bcall for (?:project )?proposals?\b|\bproposals? (?:are )?invited\b", text[:10000]))
    if call_title_hit:
        add(subtype, 45, "EXPLICIT_CALL_TITLE")
    elif call_body_hit:
        add(subtype, 24, "EXPLICIT_CALL_BODY")
    if re.search(r"/callforproposals/|/call-for-proposals/", url):
        add(subtype, 34, "CALL_DETAIL_URL_PATH")
    if call_pattern == "EVENT_RELATED" and not call_title_hit and not call_body_hit:
        add("EVENT", 78, "CALL_AUDIT_EVENT_RELATED")
        scores[subtype] = max(0, scores[subtype] - 20)
        reasons[subtype].append("EVENT_RELATED_PENALTY")
    elif call_pattern and call_pattern != "OTHER_CALL_PATTERN":
        add(subtype, 28, f"CALL_AUDIT_{call_pattern}")
    if re.search(r"\bopening date\b|\bclosing date\b|\blast date\b|\bsubmission deadline\b", combined):
        add(subtype, 12, "CALL_DATE_LANGUAGE")
    if re.search(r"\bproposal(?:s)?\b", combined) and re.search(r"\bsubmit|submission|invite|apply\b", combined):
        add(subtype, 10, "PROPOSAL_SUBMISSION_LANGUAGE")

    # Index/category evidence.
    index_terms = config.get("index_terms", [])
    relevant_links = safe_int(links.get("scheme_programme_like"))
    call_links = safe_int(links.get("call_like"))
    internal_links = safe_int(links.get("internal"))
    category_min = safe_int(config.get("category_min_relevant_internal_links"), 5)
    if contains_any(title, index_terms) or re.search(r"\bschemes?\s*/?\s*programmes?\b", title):
        add("SCHEME_CATEGORY_INDEX", 36, "SCHEME_PROGRAMME_INDEX_TITLE")
        add("PROGRAMME_CATEGORY_INDEX", 36, "SCHEME_PROGRAMME_INDEX_TITLE")
    if relevant_links >= category_min:
        add("SCHEME_CATEGORY_INDEX", min(28, relevant_links * 2), f"RELEVANT_INTERNAL_LINKS_{relevant_links}")
        add("PROGRAMME_CATEGORY_INDEX", min(28, relevant_links * 2), f"RELEVANT_INTERNAL_LINKS_{relevant_links}")
    if call_links >= category_min and "call" not in title:
        add("CURRENT_CALL_INDEX", min(20, call_links), f"CALL_LINK_HUB_{call_links}")
    if internal_links >= 20 and word_count < 400:
        add("GENERAL_INFORMATION", 10, "NAVIGATION_HEAVY_PAGE")

    # Scheme/programme master evidence.
    group_count, matched_groups = count_phrase_groups(combined, config.get("scheme_evidence_phrases", {}))
    scheme_evidence_score = min(100.0, group_count * 14.0)
    if matched_groups:
        for group in matched_groups:
            add("SCHEME_MASTER_CANDIDATE", 10, f"SCHEME_EVIDENCE_{group.upper()}")
            add("PROGRAMME_MASTER_CANDIDATE", 10, f"PROGRAMME_EVIDENCE_{group.upper()}")
    if group_count >= 3:
        add("SCHEME_MASTER_CANDIDATE", 16, f"MULTI_SECTION_SCHEME_EVIDENCE_{group_count}")
        add("PROGRAMME_MASTER_CANDIDATE", 16, f"MULTI_SECTION_PROGRAMME_EVIDENCE_{group_count}")
    if group_count >= 5:
        add("SCHEME_MASTER_CANDIDATE", 12, "STRONG_MASTER_PAGE_STRUCTURE")
        add("PROGRAMME_MASTER_CANDIDATE", 12, "STRONG_MASTER_PAGE_STRUCTURE")

    programme_terms = config.get("programme_terms", [])
    scheme_terms = config.get("scheme_terms", [])
    if contains_any(title, programme_terms):
        add("PROGRAMME_MASTER_CANDIDATE", 23, "PROGRAMME_TERM_IN_TITLE")
    if contains_any(title, scheme_terms):
        add("SCHEME_MASTER_CANDIDATE", 23, "SCHEME_TERM_IN_TITLE")
    if re.search(r"/programmes?|/initiatives?", url):
        add("PROGRAMME_MASTER_CANDIDATE", 12, "PROGRAMME_URL_PATH")
    if re.search(r"/schemes?", url):
        add("SCHEME_MASTER_CANDIDATE", 12, "SCHEME_URL_PATH")
    if re.search(r"\bprogramme\b|\bprogram\b", title) and not re.search(r"\bcall\b", title):
        add("PROGRAMME_MASTER_CANDIDATE", 12, "PROGRAMME_NOUN_IN_TITLE")
    if re.search(r"\bscheme\b", title) and not re.search(r"\bcall\b", title):
        add("SCHEME_MASTER_CANDIDATE", 12, "SCHEME_NOUN_IN_TITLE")

    # Suppress permanent-master scores when page is clearly a temporary call.
    call_evidence_score = min(100.0, max(scores[r] for r in CALL_ROLES))
    if call_evidence_score >= 40:
        scores["SCHEME_MASTER_CANDIDATE"] = max(0, scores["SCHEME_MASTER_CANDIDATE"] - 35)
        scores["PROGRAMME_MASTER_CANDIDATE"] = max(0, scores["PROGRAMME_MASTER_CANDIDATE"] - 35)
        reasons["SCHEME_MASTER_CANDIDATE"].append("TEMPORARY_CALL_PENALTY")
        reasons["PROGRAMME_MASTER_CANDIDATE"].append("TEMPORARY_CALL_PENALTY")

    # Supporting evidence.
    if re.search(r"\bguidelines?\b|\bmanual\b|\bhandbook\b", title):
        add("GUIDELINE_PAGE", 48, "GUIDELINE_TITLE")
    if re.search(r"\bguidelines?\b|\boperational guidelines?\b", text[:5000]):
        add("GUIDELINE_PAGE", 18, "GUIDELINE_BODY")
    if re.search(r"\bhow to apply\b|\bapplication procedure\b|\bapplication guidance\b", title):
        add("APPLICATION_GUIDANCE", 50, "APPLICATION_GUIDANCE_TITLE")
    if re.search(r"\bsanctioned projects?\b|\bsanction order\b", title):
        add("SANCTIONED_PROJECT_EVIDENCE", 58, "SANCTIONED_PROJECT_TITLE")
    if re.search(r"\boffice memorandum\b|\boms? and guidelines\b", title):
        add("OFFICE_MEMORANDUM", 54, "OFFICE_MEMORANDUM_TITLE")
    if re.search(r"\bnotification\b|\bnotice\b|\bcircular\b", title):
        add("NOTIFICATION", 36, "NOTIFICATION_TITLE")

    # Non-scheme/general evidence.
    if re.search(r"\bnews\b|\bpress release\b|\bwhat'?s new\b", title) or re.search(r"/news|/press-release|/whatsnew", url):
        add("NEWS", 50, "NEWS_TITLE_OR_URL")
    if re.search(r"\bworkshop\b|\bconference\b|\bwebinar\b|\bseminar\b|\bevent\b", title):
        add("EVENT", 52, "EVENT_TITLE")
    if re.search(r"\btender\b|\bprocurement\b|\bauction\b", title):
        add("NON_SCHEME", 60, "PROCUREMENT_CONTENT")
    if re.search(r"\babout us\b|\bwho is who\b|\borganisation\b|\borganization\b|\bdivision\b", title):
        add("GENERAL_INFORMATION", 42, "GENERAL_INFORMATION_TITLE")
    if word_count < 40 and max(scores.values()) < 40:
        add("UNKNOWN", 30, "LOW_INFORMATION_PAGE")
    if max(scores.values()) == 0:
        add("UNKNOWN", 25, "NO_ROLE_EVIDENCE")

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_role, top_score = ranked[0]
    second_role, second_score = ranked[1]

    # Evidence-score confidence: role strength plus separation from second role.
    strength = clamp(top_score / 90.0)
    margin_score = clamp((top_score - second_score) / 35.0)
    confidence = clamp(0.35 + 0.45 * strength + 0.20 * margin_score, 0.35, 0.99)

    review_flags: list[str] = []
    min_auto = safe_float(config.get("minimum_auto_confidence"), 0.72)
    margin_threshold = safe_float(config.get("review_margin_threshold"), 0.08)
    if confidence < min_auto:
        review_flags.append("LOW_CONFIDENCE")
    if confidence > 0 and (top_score - second_score) / max(top_score, 1.0) < margin_threshold:
        review_flags.append("SMALL_SCORE_MARGIN")
    if extraction_status == "SUCCESS_BODY_FALLBACK" and word_count < safe_int(config.get("body_fallback_review_word_threshold"), 80):
        review_flags.append("LOW_TEXT_BODY_FALLBACK")
    if top_role in MASTER_CANDIDATE_ROLES and group_count < 2:
        review_flags.append("WEAK_MASTER_PAGE_EVIDENCE")
    if top_role in CALL_ROLES and not extract_parent_name(title_raw, text_raw):
        review_flags.append("PARENT_NOT_EXPLICITLY_IDENTIFIED")
    if top_role == "UNKNOWN":
        review_flags.append("UNKNOWN_ROLE")

    # Never force a weak candidate into a master role.
    min_master = safe_float(config.get("minimum_master_candidate_confidence"), 0.70)
    if top_role in MASTER_CANDIDATE_ROLES and confidence < min_master:
        second_candidate = next((x for x in ranked if x[0] not in MASTER_CANDIDATE_ROLES), ("UNKNOWN", 0.0))
        if second_candidate[1] >= top_score * 0.75:
            top_role = "UNKNOWN"
            review_flags.extend(["MASTER_CANDIDATE_WITHHELD", "UNKNOWN_ROLE"])

    evidence = {role: round(score, 3) for role, score in ranked if score > 0}
    parent_text = extract_parent_name(title_raw, text_raw) if top_role in CALL_ROLES else ""
    selected_reasons = reasons.get(top_role, [])
    if not selected_reasons:
        selected_reasons = ["NO_DOMINANT_EVIDENCE"]

    return Classification(
        role=top_role,
        confidence=round(confidence, 4),
        top_score=round(top_score, 3),
        second_role=second_role,
        second_score=round(second_score, 3),
        reasons=selected_reasons,
        review_flags=sorted(set(review_flags)),
        possible_parent_name_text=parent_text,
        scheme_evidence_score=round(scheme_evidence_score, 3),
        call_evidence_score=round(call_evidence_score, 3),
        evidence=evidence,
    )


def classify_pages(
    pages: list[dict[str, str]],
    call_audit: list[dict[str, str]],
    link_stats: Mapping[str, Mapping[str, int]],
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    call_by_id = {row.get("page_id", ""): row.get("call_pattern", "") for row in call_audit}
    output: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for row in pages:
        page_id = collapse_ws(row.get("page_id")) or stable_id("dst_page", row.get("final_url", ""))
        final_url = collapse_ws(row.get("final_url") or row.get("requested_url"))
        classification = score_page(
            row,
            call_by_id.get(page_id, ""),
            link_stats.get(final_url, {}),
            config,
        )
        enriched: dict[str, Any] = dict(row)
        enriched.update({
            "classified_page_id": page_id,
            "page_role": classification.role,
            "page_role_confidence": f"{classification.confidence:.4f}",
            "page_role_score": f"{classification.top_score:.3f}",
            "second_best_role": classification.second_role,
            "second_best_score": f"{classification.second_score:.3f}",
            "scheme_evidence_score": f"{classification.scheme_evidence_score:.3f}",
            "call_evidence_score": f"{classification.call_evidence_score:.3f}",
            "possible_parent_name_text": classification.possible_parent_name_text,
            "classification_reasons": " | ".join(classification.reasons),
            "review_flags": " | ".join(classification.review_flags),
            "requires_admin_review": "1" if classification.review_flags else "0",
            "identity_safeguard": "NO_CANONICAL_SCHEME_IDENTITY_CREATED",
            "classified_at": utc_now(),
        })
        output.append(enriched)
        audit.append({
            "page_id": page_id,
            "final_url": final_url,
            "page_title": row.get("page_title") or row.get("title", ""),
            "page_role": classification.role,
            "confidence": f"{classification.confidence:.4f}",
            "top_score": f"{classification.top_score:.3f}",
            "second_best_role": classification.second_role,
            "second_best_score": f"{classification.second_score:.3f}",
            "possible_parent_name_text": classification.possible_parent_name_text,
            "classification_reasons": " | ".join(classification.reasons),
            "review_flags": " | ".join(classification.review_flags),
            "evidence_scores_json": json.dumps(classification.evidence, ensure_ascii=False, sort_keys=True),
            "identity_safeguard": "CALLS_NOT_PROMOTED_AND_NO_MASTER_IDENTITY_CREATED",
        })

    return output, audit


def classify_document(row: Mapping[str, Any], source_page_role: str) -> tuple[str, float, list[str], list[str]]:
    hint = upper(row.get("document_role_hint"))
    filename = lower(row.get("filename"))
    anchor = lower(row.get("anchor_text"))
    combined = f"{filename} {anchor}"
    reasons: list[str] = []
    flags: list[str] = []

    mapping = {
        "GUIDELINE": "GUIDELINE",
        "APPLICATION_FORMAT": "APPLICATION_FORMAT",
        "CORRIGENDUM": "CALL_CORRIGENDUM",
        "DEADLINE_EXTENSION": "DEADLINE_EXTENSION",
        "RESULT": "CALL_RESULT",
        "SANCTION_ORDER": "SANCTION_ORDER",
        "OFFICE_MEMORANDUM": "OFFICE_MEMORANDUM",
        "CALL_DOCUMENT": "CALL_DOCUMENT",
        "ANNUAL_REPORT": "ANNUAL_REPORT",
        "BROCHURE_OR_FLYER": "BROCHURE_OR_FLYER",
    }
    role = mapping.get(hint, "UNKNOWN_DOCUMENT")
    confidence = 0.78 if role != "UNKNOWN_DOCUMENT" else 0.42
    if role != "UNKNOWN_DOCUMENT":
        reasons.append(f"ENRICHED_HINT_{hint}")

    if re.search(r"corrigendum|addendum|amendment", combined):
        role, confidence = "CALL_CORRIGENDUM", 0.96
        reasons.append("FILENAME_OR_ANCHOR_CORRIGENDUM")
    elif re.search(r"extension|extended.{0,30}(date|deadline)|last.?date", combined):
        role, confidence = "DEADLINE_EXTENSION", 0.94
        reasons.append("FILENAME_OR_ANCHOR_EXTENSION")
    elif re.search(r"result|selected|recommended|shortlist", combined):
        role, confidence = "CALL_RESULT", 0.92
        reasons.append("FILENAME_OR_ANCHOR_RESULT")
    elif re.search(r"guideline|manual|handbook", combined):
        role, confidence = "GUIDELINE", 0.93
        reasons.append("FILENAME_OR_ANCHOR_GUIDELINE")
    elif re.search(r"application.?form|application.?format|proposal.?format|proforma|template", combined):
        role, confidence = "APPLICATION_FORMAT", 0.92
        reasons.append("FILENAME_OR_ANCHOR_APPLICATION_FORMAT")
    elif re.search(r"sanction|release.?order", combined):
        role, confidence = "SANCTION_ORDER", 0.92
        reasons.append("FILENAME_OR_ANCHOR_SANCTION")

    if role == "UNKNOWN_DOCUMENT" and source_page_role in CALL_ROLES:
        role, confidence = "CALL_DOCUMENT", 0.64
        reasons.append("SOURCE_PAGE_IS_CALL")
        flags.append("ROLE_INFERRED_FROM_SOURCE_PAGE")
    if role == "CALL_DOCUMENT" and source_page_role not in CALL_ROLES:
        flags.append("CALL_DOCUMENT_SOURCE_ROLE_MISMATCH")
    if role == "UNKNOWN_DOCUMENT":
        flags.append("UNKNOWN_DOCUMENT_ROLE")
    if not reasons:
        reasons.append("NO_DOCUMENT_ROLE_EVIDENCE")
    return role, confidence, sorted(set(reasons)), sorted(set(flags))


def classify_documents(
    documents: list[dict[str, str]],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_role_by_url = {
        collapse_ws(row.get("final_url") or row.get("requested_url")): collapse_ws(row.get("page_role"))
        for row in pages
    }
    output: list[dict[str, Any]] = []
    for row in documents:
        source_url = collapse_ws(row.get("source_page_url") or row.get("source_url"))
        source_role = page_role_by_url.get(source_url, "")
        role, confidence, reasons, flags = classify_document(row, source_role)
        item: dict[str, Any] = dict(row)
        item.update({
            "document_role": role,
            "document_role_confidence": f"{confidence:.4f}",
            "source_page_role": source_role,
            "classification_reasons": " | ".join(reasons),
            "review_flags": " | ".join(flags),
            "requires_admin_review": "1" if flags else "0",
            "identity_safeguard": "DOCUMENT_NOT_PROMOTED_TO_SCHEME",
            "classified_at": utc_now(),
        })
        output.append(item)
    return output


def validate_outputs(
    input_pages: list[dict[str, str]],
    pages: list[dict[str, Any]],
    input_documents: list[dict[str, str]],
    documents: list[dict[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    unknown_count = sum(row.get("page_role") == "UNKNOWN" for row in pages)
    unknown_rate = unknown_count / len(pages) if pages else 1.0
    missing_roles = sum(not collapse_ws(row.get("page_role")) for row in pages)
    invalid_roles = sum(row.get("page_role") not in PAGE_ROLES for row in pages)
    missing_confidence = sum(not collapse_ws(row.get("page_role_confidence")) for row in pages)
    forbidden_fields_found = sorted({field for row in pages + documents for field in FORBIDDEN_IDENTITY_FIELDS if field in row})
    call_promotions = sum(
        row.get("page_role") in MASTER_CANDIDATE_ROLES
        and upper(row.get("page_role_hint")) == "CALL_CANDIDATE"
        for row in pages
    )
    doc_missing_role = sum(not collapse_ws(row.get("document_role")) for row in documents)

    checks = {
        "page_rows_preserved": len(input_pages) == len(pages),
        "document_rows_preserved": len(input_documents) == len(documents),
        "page_role_complete": missing_roles == 0,
        "page_roles_valid": invalid_roles == 0,
        "page_confidence_complete": missing_confidence == 0,
        "unknown_rate_within_limit": unknown_rate <= safe_float(config.get("maximum_unknown_rate"), 0.20),
        "document_role_complete": doc_missing_role == 0,
        "forbidden_identity_fields_absent": not forbidden_fields_found,
        "call_candidates_not_promoted_to_master": call_promotions == 0,
        "canonical_scheme_identity_created": False,
        "call_titles_promoted_to_scheme_names": False,
    }
    pass_keys = [key for key in checks if key not in {"canonical_scheme_identity_created", "call_titles_promoted_to_scheme_names"}]
    passed = all(checks[key] for key in pass_keys) and not checks["canonical_scheme_identity_created"] and not checks["call_titles_promoted_to_scheme_names"]
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "generated_at": utc_now(),
        "counts": {
            "input_pages": len(input_pages),
            "output_pages": len(pages),
            "input_documents": len(input_documents),
            "output_documents": len(documents),
            "unknown_pages": unknown_count,
            "missing_page_role": missing_roles,
            "invalid_page_role": invalid_roles,
            "missing_page_confidence": missing_confidence,
            "documents_missing_role": doc_missing_role,
            "call_candidates_promoted_to_master": call_promotions,
        },
        "quality": {
            "unknown_rate": round(unknown_rate, 6),
            "maximum_unknown_rate": safe_float(config.get("maximum_unknown_rate"), 0.20),
            "forbidden_identity_fields_found": forbidden_fields_found,
        },
        "checks": checks,
        "classifier_validation_passed": passed,
        "ready_for_v3_4_0_3": passed,
    }


def page_subset(pages: list[dict[str, Any]], roles: set[str]) -> list[dict[str, Any]]:
    return [row for row in pages if row.get("page_role") in roles]


def build_summary(
    pages: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    validation: Mapping[str, Any],
    input_dir: Path,
    link_graph_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    role_counts = Counter(str(row.get("page_role", "UNKNOWN")) for row in pages)
    document_counts = Counter(str(row.get("document_role", "UNKNOWN_DOCUMENT")) for row in documents)
    review_pages = sum(row.get("requires_admin_review") == "1" for row in pages)
    review_documents = sum(row.get("requires_admin_review") == "1" for row in documents)
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "completed_at": utc_now(),
        "input_dir": str(input_dir),
        "link_graph": str(link_graph_path),
        "output_dir": str(output_dir),
        "network_access_used": False,
        "recrawl_performed": False,
        "identity_safeguard": {
            "canonical_scheme_identity_created": False,
            "call_titles_promoted_to_scheme_names": False,
            "forbidden_identity_fields": sorted(FORBIDDEN_IDENTITY_FIELDS),
            "description": "Page and document roles only; permanent DST scheme identity remains reserved for v3.4.0.3/v3.4.0.4.",
        },
        "counts": {
            "classified_pages": len(pages),
            "classified_documents": len(documents),
            "scheme_master_page_candidates": role_counts.get("SCHEME_MASTER_CANDIDATE", 0),
            "programme_master_page_candidates": role_counts.get("PROGRAMME_MASTER_CANDIDATE", 0),
            "call_pages": sum(role_counts.get(role, 0) for role in CALL_ROLES),
            "supporting_pages": sum(role_counts.get(role, 0) for role in SUPPORTING_ROLES),
            "non_scheme_pages": sum(role_counts.get(role, 0) for role in NON_SCHEME_ROLES),
            "unknown_pages": role_counts.get("UNKNOWN", 0),
            "pages_requiring_admin_review": review_pages,
            "documents_requiring_admin_review": review_documents,
        },
        "page_role_counts": dict(sorted(role_counts.items())),
        "document_role_counts": dict(sorted(document_counts.items())),
        "classifier_validation_passed": bool(validation.get("classifier_validation_passed")),
        "ready_for_v3_4_0_3": bool(validation.get("ready_for_v3_4_0_3")),
        "outputs": {
            "classified_pages": CLASSIFIED_PAGES_OUTPUT,
            "classified_documents": CLASSIFIED_DOCUMENTS_OUTPUT,
            "scheme_candidates": SCHEME_CANDIDATES_OUTPUT,
            "programme_candidates": PROGRAMME_CANDIDATES_OUTPUT,
            "call_pages": CALL_PAGES_OUTPUT,
            "supporting_pages": SUPPORTING_PAGES_OUTPUT,
            "non_scheme_pages": NON_SCHEME_OUTPUT,
            "unknown_review_queue": UNKNOWN_REVIEW_OUTPUT,
            "classifier_audit": CLASSIFIER_AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def run_classifier(
    input_dir: Path,
    link_graph_path: Path,
    output_dir: Path,
    config: Mapping[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    page_path = input_dir / PAGE_INPUT
    document_path = input_dir / DOCUMENT_INPUT
    call_audit_path = input_dir / CALL_AUDIT_INPUT
    for required in (page_path, document_path, call_audit_path, link_graph_path):
        if not required.exists():
            raise FileNotFoundError(f"Required input not found: {required}")

    input_pages = read_csv(page_path)
    input_documents = read_csv(document_path)
    call_audit = read_csv(call_audit_path)
    link_rows = read_csv(link_graph_path)

    if dry_run:
        return {
            "service_version": VERSION,
            "mode": "DRY_RUN",
            "input_dir": str(input_dir),
            "link_graph_path": str(link_graph_path),
            "output_dir": str(output_dir),
            "counts": {
                "pages": len(input_pages),
                "documents": len(input_documents),
                "call_audit_rows": len(call_audit),
                "link_graph_rows": len(link_rows),
            },
            "files_written": False,
            "network_access_used": False,
            "canonical_scheme_identity_created": False,
        }

    links = aggregate_links(link_rows)
    pages, audit = classify_pages(input_pages, call_audit, links, config)
    documents = classify_documents(input_documents, pages)
    validation = validate_outputs(input_pages, pages, input_documents, documents, config)
    summary = build_summary(pages, documents, validation, input_dir, link_graph_path, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / CLASSIFIED_PAGES_OUTPUT, pages)
    write_csv(output_dir / CLASSIFIED_DOCUMENTS_OUTPUT, documents)
    write_csv(output_dir / SCHEME_CANDIDATES_OUTPUT, page_subset(pages, {"SCHEME_MASTER_CANDIDATE"}))
    write_csv(output_dir / PROGRAMME_CANDIDATES_OUTPUT, page_subset(pages, {"PROGRAMME_MASTER_CANDIDATE"}))
    write_csv(output_dir / CALL_PAGES_OUTPUT, page_subset(pages, CALL_ROLES))
    write_csv(output_dir / SUPPORTING_PAGES_OUTPUT, page_subset(pages, SUPPORTING_ROLES))
    write_csv(output_dir / NON_SCHEME_OUTPUT, page_subset(pages, NON_SCHEME_ROLES))
    review_rows = [
        row for row in pages
        if row.get("requires_admin_review") == "1" or row.get("page_role") == "UNKNOWN"
    ]
    write_csv(output_dir / UNKNOWN_REVIEW_OUTPUT, review_rows)
    write_csv(output_dir / CLASSIFIER_AUDIT_OUTPUT, audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)
    return summary


def self_test() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    config = DEFAULT_CONFIG

    synthetic = [
        {
            "page_id": "call1",
            "final_url": "https://dst.gov.in/callforproposals/tdp-2026",
            "page_title": "Call for Project Proposals under Technology Development Programme 2026",
            "main_text": "Applications are invited. Closing date 31 August 2026. Under the programme Technology Development Programme.",
            "page_role_hint": "CALL_CANDIDATE",
            "source_role_hint": "CALL",
            "http_status": "200",
            "content_type": "text/html",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "word_count": "100",
        },
        {
            "page_id": "scheme1",
            "final_url": "https://dst.gov.in/women-scientist-scheme",
            "page_title": "Women Scientist Scheme",
            "main_text": "Objectives Eligibility Financial assistance Beneficiaries How to apply Duration Scope",
            "page_role_hint": "SCHEME_PROGRAMME_CANDIDATE",
            "source_role_hint": "SCHEME",
            "http_status": "200",
            "content_type": "text/html",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "word_count": "500",
        },
        {
            "page_id": "archive",
            "final_url": "https://dst.gov.in/archive-call-for-proposals",
            "page_title": "Archive Call for Proposals",
            "main_text": "Archived calls",
            "page_role_hint": "CALL_INDEX_ARCHIVE",
            "source_role_hint": "CALL_ARCHIVE",
            "http_status": "200",
            "content_type": "text/html",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "word_count": "50",
        },
        {
            "page_id": "broken",
            "final_url": "https://dst.gov.in/broken",
            "page_title": "",
            "main_text": "",
            "page_role_hint": "UNCLASSIFIED_SOURCE_PAGE",
            "source_role_hint": "UNKNOWN",
            "http_status": "404",
            "content_type": "text/html",
            "text_extraction_status": "HTTP_ERROR_PAGE",
            "word_count": "0",
        },
    ]
    call_audit = [{"page_id": "call1", "call_pattern": "CALL_FOR_PROPOSALS"}]
    pages, audit = classify_pages(synthetic, call_audit, {}, config)
    by_id = {row["page_id"]: row for row in pages}
    checks["call_classified"] = by_id["call1"]["page_role"] == "CALL_FOR_PROPOSALS"
    checks["call_not_master"] = by_id["call1"]["page_role"] not in MASTER_CANDIDATE_ROLES
    checks["parent_text_extracted"] = bool(by_id["call1"]["possible_parent_name_text"])
    checks["scheme_candidate_classified"] = by_id["scheme1"]["page_role"] == "SCHEME_MASTER_CANDIDATE"
    checks["archive_index_classified"] = by_id["archive"]["page_role"] == "CALL_ARCHIVE_INDEX"
    checks["broken_link_classified"] = by_id["broken"]["page_role"] == "BROKEN_OFFICIAL_LINK"
    checks["audit_row_count"] = len(audit) == 4

    docs = classify_documents([
        {
            "document_id": "d1",
            "source_page_url": synthetic[0]["final_url"],
            "filename": "TDP-Guidelines-2026.pdf",
            "anchor_text": "Guidelines",
            "document_role_hint": "GUIDELINE",
        },
    ], pages)
    checks["document_classified"] = docs[0]["document_role"] == "GUIDELINE"
    checks["no_forbidden_page_fields"] = not any(field in row for row in pages for field in FORBIDDEN_IDENTITY_FIELDS)
    checks["no_forbidden_document_fields"] = not any(field in row for row in docs for field in FORBIDDEN_IDENTITY_FIELDS)

    validation = validate_outputs(synthetic, pages, [dict(document_id="d1")], docs, config)
    checks["validation_passed"] = validation["classifier_validation_passed"]

    return {
        "service_version": VERSION,
        "department": DEPARTMENT_CODE,
        "tests": checks,
        "self_test_passed": all(checks.values()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--link-graph", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return exit code 3 when validation fails.")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        result = self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["self_test_passed"] else 2

    root = args.project_root.resolve()
    input_dir = (args.input_dir or root / "data" / "departments" / "dst" / "v3_4_0_1_1").resolve()
    link_graph = (args.link_graph or root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl" / LINK_GRAPH_INPUT).resolve()
    output_dir = (args.output_dir or root / "data" / "departments" / "dst" / "v3_4_0_2").resolve()
    config_path = args.config or root / "config" / "dst_page_role_classifier_rules_v3_4_0_2.json"
    config = load_config(config_path if config_path.exists() else None)

    try:
        result = run_classifier(input_dir, link_graph, output_dir, config, dry_run=args.dry_run)
    except (FileNotFoundError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        print(json.dumps({"service_version": VERSION, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.strict and not args.dry_run and not result.get("classifier_validation_passed", False):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
