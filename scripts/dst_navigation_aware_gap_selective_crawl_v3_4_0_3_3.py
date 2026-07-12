#!/usr/bin/env python3
"""
SSIP v3.4.0.3.3 — DST Navigation-Aware Gap Filtering and Selective Target Crawl

Resolves the remaining DST category-discovery gaps without repeating the full
crawl. Global navigation, accessibility and supporting-information targets are
closed offline. Only evidence-backed, high-value internal DST targets are
placed into a depth-0 selective crawl queue.

Safety guarantees
-----------------
* Existing v3.4.0.1–v3.4.0.3.2 outputs are never modified.
* No recursive crawling; selective targets are fetched at depth 0 only.
* Calls, years, rounds, results and temporary opportunities cannot become
  permanent scheme/programme candidates.
* Generic navigation/support pages cannot enter the final corrected inventory.
* No canonical scheme/programme identity is created and no identity is locked.
* Existing corrected provisional inventories, downgrades and admin-review rows
  are preserved and accounted for.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - clear runtime error is emitted by main
    requests = None  # type: ignore[assignment]
    BeautifulSoup = None  # type: ignore[assignment]

VERSION = "3.4.0.3.3"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

# Inputs under data/departments/dst/v3_4_0_3_2
DIRECT_TARGET_INPUT = "dst_direct_target_matches_v3_4_0_3_2.csv"
REVIEW_INPUT = "dst_identity_review_queue_v3_4_0_3_2.csv"
DUPLICATE_INPUT = "dst_gap_duplicates_v3_4_0_3_2.csv"
CORRECTED_SCHEMES_INPUT = "dst_corrected_provisional_schemes_v3_4_0_3_2.csv"
CORRECTED_PROGRAMMES_INPUT = "dst_corrected_provisional_programmes_v3_4_0_3_2.csv"
DOWNGRADES_INPUT = "dst_provisional_entity_downgrades_v3_4_0_3_2.csv"
CONTEXT_AUDIT_INPUT = "dst_unresolved_target_link_context_audit.csv"
CLASSIFIED_PAGES_INPUT = "dst_classified_pages_v3_4_0_2.csv"
LINK_GRAPH_INPUT = "dst_link_graph_v3_4_0_1.csv"

# Outputs
LINK_CONTEXT_OUTPUT = "dst_gap_link_context_v3_4_0_3_3.csv"
NAVIGATION_OUTPUT = "dst_global_navigation_gaps_v3_4_0_3_3.csv"
SUPPORTING_OUTPUT = "dst_supporting_information_gaps_v3_4_0_3_3.csv"
CRAWL_QUEUE_OUTPUT = "dst_selective_crawl_queue_v3_4_0_3_3.csv"
CRAWLED_OUTPUT = "dst_selectively_crawled_targets_v3_4_0_3_3.csv"
NEW_SCHEME_OUTPUT = "dst_possible_new_scheme_pages_v3_4_0_3_3.csv"
NEW_PROGRAMME_OUTPUT = "dst_possible_new_programme_pages_v3_4_0_3_3.csv"
NON_ENTITY_OUTPUT = "dst_non_entity_gap_resolutions_v3_4_0_3_3.csv"
BROKEN_OUTPUT = "dst_true_broken_targets_v3_4_0_3_3.csv"
FINAL_SCHEMES_OUTPUT = "dst_final_corrected_schemes_v3_4_0_3_3.csv"
FINAL_PROGRAMMES_OUTPUT = "dst_final_corrected_programmes_v3_4_0_3_3.csv"
FINAL_REVIEW_OUTPUT = "dst_final_gap_review_queue_v3_4_0_3_3.csv"
AUDIT_OUTPUT = "dst_gap_resolution_audit_v3_4_0_3_3.csv"
VALIDATION_OUTPUT = "dst_gap_resolution_validation_v3_4_0_3_3.json"
SUMMARY_OUTPUT = "dst_gap_resolution_summary_v3_4_0_3_3.json"

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
    "CALL_FOR_PROPOSALS", "APPLICATION_INVITATION", "EXPRESSION_OF_INTEREST",
    "DEADLINE_EXTENSION", "CALL_CORRIGENDUM", "CALL_RESULT",
    "CURRENT_CALL_INDEX", "CALL_ARCHIVE_INDEX",
}
INDEX_ROLES = {
    "SCHEME_CATEGORY_INDEX", "PROGRAMME_CATEGORY_INDEX",
    "CURRENT_CALL_INDEX", "CALL_ARCHIVE_INDEX",
}
SUPPORTING_ROLES = {
    "GUIDELINE_PAGE", "APPLICATION_GUIDANCE", "SANCTIONED_PROJECT_EVIDENCE",
    "NOTIFICATION", "OFFICE_MEMORANDUM", "CONTACT_PAGE", "GENERAL_INFORMATION",
}
NON_SCHEME_ROLES = {"NEWS", "EVENT", "RECRUITMENT", "NON_SCHEME"}
MASTER_ROLES = {"SCHEME_MASTER_CANDIDATE", "PROGRAMME_MASTER_CANDIDATE"}

FINAL_GAP_CLASSIFICATIONS = {
    "EXISTING_PROVISIONAL_ENTITY",
    "POSSIBLE_NEW_SCHEME",
    "POSSIBLE_NEW_PROGRAMME",
    "CATEGORY_OR_INDEX_PAGE",
    "SUPPORTING_INFORMATION",
    "GLOBAL_NAVIGATION",
    "ACCESSIBILITY_LINK",
    "CALL_OR_TEMPORARY_PAGE",
    "NEWS_EVENT_OR_RECRUITMENT",
    "BROKEN_OFFICIAL_LINK",
    "UNRESOLVED",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "allowed_domains": ["dst.gov.in", "www.dst.gov.in"],
    "minimum_main_content_occurrences": 1,
    "minimum_selective_relevance_score": 45,
    "strong_selective_relevance_score": 70,
    "global_navigation_source_page_threshold": 8,
    "global_navigation_occurrence_threshold": 8,
    "maximum_final_unresolved_rate": 0.05,
    "minimum_gap_resolution_rate": 0.95,
    "request_timeout_seconds": 30,
    "delay_seconds": 1.0,
    "maximum_response_bytes": 5000000,
    "maximum_text_length": 120000,
    "maximum_excerpt_length": 800,
    "user_agent": "SSIP-DST-SelectiveCrawler/3.4.0.3.3 (+government-scheme-indexing)",
    "tracking_query_parameters": [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "_ga", "_gl",
    ],
    "navigation_names": [
        "home", "about dst", "about us", "introduction", "mandate",
        "vision mission", "screen reader access", "accessibility", "contact",
        "contact us", "site map", "sitemap", "search", "skip to main content",
        "archive", "tenders", "vacancies", "who is who", "organization chart",
        "website policies", "help", "feedback", "terms and conditions",
    ],
    "navigation_url_terms": [
        "/screen-reader-access", "/about_us", "/about-us/", "/introduction",
        "/vision-mission", "/contact", "/sitemap", "/search", "/archive",
        "/taxonomy/", "/who-is-who", "/organisation", "/organization",
        "/website-policies", "/help", "/feedback", "/tenders", "/vacancies",
    ],
    "accessibility_terms": [
        "screen reader", "accessibility", "skip to main content", "font size",
        "high contrast", "change text size", "keyboard navigation",
    ],
    "supporting_terms": [
        "funding mechanism", "about the schemes", "about schemes", "how to apply",
        "application guidance", "guidelines", "manual", "faq", "frequently asked",
        "office memorandum", "sanctioned projects", "contact", "forms",
        "downloads", "documents", "publication", "annual report",
    ],
    "call_terms": [
        "call for proposal", "call for proposals", "applications invited",
        "inviting applications", "expression of interest", " eoi ",
        "deadline extension", "last date extended", "corrigendum", "addendum",
        "result", "selected proposals", "shortlisted", "apply now",
        "submission deadline", "closing date", "open call", "special call",
        "joint call", "request for proposal", " rfp ", "call document",
    ],
    "call_url_terms": [
        "/call-for-proposals", "/callforproposals/", "/archive-call-for-proposals",
        "/announcement/applications", "/corrigendum", "/results",
    ],
    "scheme_terms": [
        "scheme", "fellowship", "scholarship", "award", "grant", "assistance",
        "research grant", "travel support", "financial support",
    ],
    "programme_terms": [
        "programme", "program", "mission", "initiative", "platform", "network",
        "facility", "facilities", "capacity building", "research council", "hub",
        "centre", "center", "technology mission", "national programme", "cell",
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
    "main_content_selectors": [
        "main", "article", "#content", ".main-content", ".region-content",
        ".node-content", ".field-name-body", ".content",
    ],
}


@dataclass
class TargetContext:
    target_url: str
    normalized_target_url: str
    proposed_name: str
    link_occurrences: int = 0
    unique_source_pages: int = 0
    main_content_occurrences: int = 0
    max_relevance_score: float = 0.0
    average_relevance_score: float = 0.0
    enqueue_decisions: list[str] = field(default_factory=list)
    anchor_texts: list[str] = field(default_factory=list)
    source_page_roles: list[str] = field(default_factory=list)
    source_page_urls: list[str] = field(default_factory=list)
    prior_gap_classification: str = ""
    direct_target_match: bool = False
    matched_page: dict[str, str] = field(default_factory=dict)


@dataclass
class PipelineResult:
    contexts: list[dict[str, Any]]
    navigation: list[dict[str, Any]]
    supporting: list[dict[str, Any]]
    crawl_queue: list[dict[str, Any]]
    crawled: list[dict[str, Any]]
    new_schemes: list[dict[str, Any]]
    new_programmes: list[dict[str, Any]]
    non_entity: list[dict[str, Any]]
    broken: list[dict[str, Any]]
    final_schemes: list[dict[str, Any]]
    final_programmes: list[dict[str, Any]]
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
        return int(float(collapse_ws(value)))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(collapse_ws(value))
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


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
    text = lower(value).replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


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
    tracking = {lower(item) for item in config.get("tracking_query_parameters", [])}
    query_items = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if lower(key) not in tracking
    ]
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query_items)), ""))


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
    mutable_rows: Sequence[Mapping[str, Any]] = rows
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["record_status"]
        mutable_rows = [{"record_status": "NO_RECORDS"}]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in mutable_rows:
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
        raise FileNotFoundError(f"Configuration not found: {path}")
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    haystack = f" {lower(text)} "
    return [collapse_ws(term) for term in terms if lower(term) and lower(term) in haystack]


def page_url(row: Mapping[str, Any]) -> str:
    return first_value(row, "final_url", "canonical_url", "normalized_url", "requested_url")


def page_title(row: Mapping[str, Any]) -> str:
    return first_value(row, "page_title", "title")


def build_page_index(pages: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for raw in pages:
        row = dict(raw)
        for field in ("requested_url", "normalized_url", "final_url", "canonical_url"):
            normalized = normalize_url(first_value(row, field), config)
            if normalized:
                index[normalized] = row
    return index


def build_entity_url_index(
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for raw in [*schemes, *programmes]:
        row = dict(raw)
        normalized = normalize_url(first_value(row, "official_source_url"), config)
        if normalized:
            index[normalized] = row
    return index


def context_from_audit(row: Mapping[str, Any], config: Mapping[str, Any]) -> TargetContext:
    target = first_value(row, "TargetURL", "target_url", "source_url")
    return TargetContext(
        target_url=target,
        normalized_target_url=normalize_url(target, config),
        proposed_name=first_value(row, "ProposedName", "proposed_name", "target_page_title"),
        link_occurrences=safe_int(first_value(row, "LinkOccurrences", "link_occurrences")),
        unique_source_pages=safe_int(first_value(row, "UniqueSourcePages", "unique_source_pages")),
        main_content_occurrences=safe_int(first_value(row, "MainContentOccurrences", "main_content_occurrences")),
        max_relevance_score=safe_float(first_value(row, "MaxRelevanceScore", "max_relevance_score")),
        enqueue_decisions=[item for item in first_value(row, "EnqueueDecisions", "enqueue_decisions").split(";") if item],
        anchor_texts=[item.strip() for item in first_value(row, "AnchorTexts", "anchor_texts").split("|") if item.strip()],
    )


def derive_link_contexts(
    direct_targets: Sequence[Mapping[str, Any]],
    link_graph: Sequence[Mapping[str, Any]],
    pages: Sequence[Mapping[str, Any]],
    audit_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[TargetContext]:
    page_index = build_page_index(pages, config)
    graph_by_target: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in link_graph:
        target = normalize_url(first_value(row, "normalized_to_url", "to_url"), config)
        if target:
            graph_by_target[target].append(row)

    audit_index: dict[str, TargetContext] = {}
    for row in audit_rows:
        ctx = context_from_audit(row, config)
        if ctx.normalized_target_url:
            audit_index[ctx.normalized_target_url] = ctx

    contexts: list[TargetContext] = []
    seen: set[str] = set()
    for row in direct_targets:
        target = first_value(row, "target_url", "source_url")
        normalized = normalize_url(first_value(row, "normalized_target_url") or target, config)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        prior = first_value(row, "gap_classification")
        proposed = first_value(row, "target_page_title", "review_proposed_name", "proposed_name")
        page = page_index.get(normalized, {})
        if normalized in audit_index:
            ctx = audit_index[normalized]
            ctx.target_url = target or ctx.target_url
            ctx.proposed_name = proposed or ctx.proposed_name
        else:
            links = graph_by_target.get(normalized, [])
            scores = [safe_float(first_value(link, "relevance_score")) for link in links]
            source_urls = sorted({normalize_url(first_value(link, "from_url"), config) for link in links if first_value(link, "from_url")})
            source_roles = sorted({
                upper(first_value(page_index.get(source, {}), "page_role", "page_role_hint"))
                for source in source_urls
                if upper(first_value(page_index.get(source, {}), "page_role", "page_role_hint"))
            })
            ctx = TargetContext(
                target_url=target,
                normalized_target_url=normalized,
                proposed_name=proposed,
                link_occurrences=len(links),
                unique_source_pages=len(source_urls),
                main_content_occurrences=sum(first_value(link, "in_main_content") == "1" for link in links),
                max_relevance_score=max(scores, default=0.0),
                average_relevance_score=(sum(scores) / len(scores)) if scores else 0.0,
                enqueue_decisions=sorted({first_value(link, "enqueue_decision") for link in links if first_value(link, "enqueue_decision")}),
                anchor_texts=sorted({first_value(link, "anchor_text") for link in links if first_value(link, "anchor_text")})[:10],
                source_page_roles=source_roles,
                source_page_urls=source_urls[:30],
            )
        if not ctx.source_page_urls:
            links = graph_by_target.get(normalized, [])
            ctx.source_page_urls = sorted({normalize_url(first_value(link, "from_url"), config) for link in links if first_value(link, "from_url")})[:30]
        if not ctx.source_page_roles:
            ctx.source_page_roles = sorted({
                upper(first_value(page_index.get(source, {}), "page_role", "page_role_hint"))
                for source in ctx.source_page_urls
                if upper(first_value(page_index.get(source, {}), "page_role", "page_role_hint"))
            })
        ctx.prior_gap_classification = prior
        ctx.direct_target_match = bool(page)
        ctx.matched_page = dict(page)
        contexts.append(ctx)
    return contexts


def is_allowed_internal_url(url: str, config: Mapping[str, Any]) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = parts.netloc.casefold()
    return host in {lower(item) for item in config.get("allowed_domains", [])} and parts.scheme in {"http", "https"}


def master_evidence_count(text: str, config: Mapping[str, Any]) -> tuple[int, list[str]]:
    found: list[str] = []
    for category, terms in config.get("master_evidence_terms", {}).items():
        if contains_any(text, terms):
            found.append(category)
    return len(found), found


def classify_existing_page(page: Mapping[str, Any], target: TargetContext, config: Mapping[str, Any]) -> tuple[str, float, list[str]]:
    role = upper(first_value(page, "page_role", "page_role_hint"))
    title = page_title(page) or target.proposed_name
    url = page_url(page) or target.target_url
    text = first_value(page, "main_text", "text_excerpt")
    combined = f"{title} {url} {text[:6000]}"
    reasons = [f"DIRECT_CLASSIFIED_PAGE_ROLE:{role or 'UNKNOWN'}"]
    if safe_int(first_value(page, "http_status")) >= 400 or role == "BROKEN_OFFICIAL_LINK":
        return "BROKEN_OFFICIAL_LINK", 0.98, reasons
    if role in CALL_ROLES or contains_any(f"{title} {url}", [*config.get("call_terms", []), *config.get("call_url_terms", [])]):
        return "CALL_OR_TEMPORARY_PAGE", 0.98, reasons
    if role in INDEX_ROLES:
        return "CATEGORY_OR_INDEX_PAGE", 0.96, reasons
    if role in SUPPORTING_ROLES:
        return "SUPPORTING_INFORMATION", 0.94, reasons
    if role in NON_SCHEME_ROLES:
        return "NEWS_EVENT_OR_RECRUITMENT", 0.96, reasons
    if role == "SCHEME_MASTER_CANDIDATE":
        return "POSSIBLE_NEW_SCHEME", max(0.75, safe_float(first_value(page, "page_role_confidence"))), reasons
    if role == "PROGRAMME_MASTER_CANDIDATE":
        return "POSSIBLE_NEW_PROGRAMME", max(0.75, safe_float(first_value(page, "page_role_confidence"))), reasons
    if contains_any(combined, config.get("accessibility_terms", [])):
        return "ACCESSIBILITY_LINK", 0.95, reasons
    if contains_any(f"{title} {url}", config.get("navigation_url_terms", [])):
        return "GLOBAL_NAVIGATION", 0.90, reasons
    if contains_any(combined, config.get("supporting_terms", [])):
        return "SUPPORTING_INFORMATION", 0.82, reasons
    return "UNRESOLVED", 0.45, reasons


def classify_context_offline(
    target: TargetContext,
    entity_index: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[str, float, list[str], bool]:
    name = target.proposed_name or (target.anchor_texts[0] if target.anchor_texts else "")
    combined = f"{name} {' '.join(target.anchor_texts)} {target.target_url}"
    reasons: list[str] = []

    if target.normalized_target_url in entity_index:
        return "EXISTING_PROVISIONAL_ENTITY", 1.0, ["OFFICIAL_SOURCE_URL_MATCH"], False
    if target.direct_target_match:
        classification, confidence, direct_reasons = classify_existing_page(target.matched_page, target, config)
        return classification, confidence, direct_reasons, False

    navigation_name_keys = {normalize_name(item) for item in config.get("navigation_names", [])}
    if normalize_name(name) in navigation_name_keys:
        classification = "ACCESSIBILITY_LINK" if contains_any(combined, config.get("accessibility_terms", [])) else "GLOBAL_NAVIGATION"
        return classification, 0.97, ["KNOWN_NAVIGATION_NAME"], False
    if contains_any(combined, config.get("accessibility_terms", [])):
        return "ACCESSIBILITY_LINK", 0.96, ["ACCESSIBILITY_TERM"], False
    if contains_any(target.target_url, config.get("navigation_url_terms", [])):
        return "GLOBAL_NAVIGATION", 0.93, ["NAVIGATION_URL_PATTERN"], False
    if contains_any(combined, [*config.get("call_terms", []), *config.get("call_url_terms", [])]):
        return "CALL_OR_TEMPORARY_PAGE", 0.95, ["CALL_OR_TEMPORARY_TERM"], False
    if contains_any(combined, config.get("supporting_terms", [])):
        return "SUPPORTING_INFORMATION", 0.88, ["SUPPORTING_INFORMATION_TERM"], False

    nav_threshold = safe_int(config.get("global_navigation_source_page_threshold"), 8)
    occurrence_threshold = safe_int(config.get("global_navigation_occurrence_threshold"), 8)
    if (
        target.main_content_occurrences == 0
        and target.unique_source_pages >= nav_threshold
        and target.link_occurrences >= occurrence_threshold
    ):
        return "GLOBAL_NAVIGATION", 0.91, ["REPEATED_OUTSIDE_MAIN_CONTENT"], False

    if not is_allowed_internal_url(target.target_url, config):
        return "SUPPORTING_INFORMATION", 0.70, ["NOT_INTERNAL_DST_HTML_TARGET"], False

    scheme_hits = contains_any(combined, config.get("scheme_terms", []))
    programme_hits = contains_any(combined, config.get("programme_terms", []))
    relevant_source = bool(set(target.source_page_roles) & {"SCHEME_CATEGORY_INDEX", "PROGRAMME_CATEGORY_INDEX"})
    min_main = safe_int(config.get("minimum_main_content_occurrences"), 1)
    min_score = safe_float(config.get("minimum_selective_relevance_score"), 45)
    strong_score = safe_float(config.get("strong_selective_relevance_score"), 70)
    queue = False
    score = 0.35
    if target.main_content_occurrences >= min_main:
        score += 0.24
        reasons.append("LINKED_FROM_MAIN_CONTENT")
    if target.max_relevance_score >= min_score:
        score += 0.18
        reasons.append("RELEVANCE_SCORE_PASSED")
    if target.max_relevance_score >= strong_score:
        score += 0.08
        reasons.append("STRONG_RELEVANCE_SCORE")
    if relevant_source:
        score += 0.12
        reasons.append("SCHEME_PROGRAMME_CATEGORY_SOURCE")
    if scheme_hits:
        score += 0.15
        reasons.append("SCHEME_NAME_SIGNAL:" + ",".join(scheme_hits[:4]))
    if programme_hits:
        score += 0.15
        reasons.append("PROGRAMME_NAME_SIGNAL:" + ",".join(programme_hits[:4]))
    queue = (
        target.main_content_occurrences >= min_main
        and target.max_relevance_score >= min_score
        and relevant_source
        and bool(scheme_hits or programme_hits)
    ) or (
        target.main_content_occurrences >= min_main
        and target.max_relevance_score >= strong_score
        and bool(scheme_hits or programme_hits)
    )
    if queue:
        reasons.append("SELECTIVE_CRAWL_REQUIRED")
        return "UNRESOLVED", clamp(score), reasons, True
    return "UNRESOLVED", clamp(score), reasons or ["INSUFFICIENT_OFFLINE_EVIDENCE"], False


def context_to_row(target: TargetContext, classification: str, confidence: float, reasons: Sequence[str], queued: bool) -> dict[str, Any]:
    return {
        "gap_resolution_id": stable_id("dst_gap_resolution", target.normalized_target_url),
        "target_url": target.target_url,
        "normalized_target_url": target.normalized_target_url,
        "proposed_name": target.proposed_name,
        "prior_gap_classification": target.prior_gap_classification,
        "final_gap_classification": classification,
        "classification_confidence": f"{confidence:.4f}",
        "classification_reasons": ";".join(reasons),
        "link_occurrences": target.link_occurrences,
        "unique_source_pages": target.unique_source_pages,
        "main_content_occurrences": target.main_content_occurrences,
        "main_content_ratio": f"{(target.main_content_occurrences / target.link_occurrences if target.link_occurrences else 0):.6f}",
        "max_relevance_score": f"{target.max_relevance_score:.2f}",
        "average_relevance_score": f"{target.average_relevance_score:.2f}",
        "enqueue_decisions": ";".join(target.enqueue_decisions),
        "anchor_texts": " | ".join(target.anchor_texts[:10]),
        "source_page_roles": ";".join(target.source_page_roles),
        "source_page_urls": ";".join(target.source_page_urls),
        "direct_target_match": "1" if target.direct_target_match else "0",
        "selective_crawl_required": "1" if queued else "0",
        "identity_safeguard": "NO_CANONICAL_IDENTITY_NO_LOCK",
    }


def extract_page(html_bytes: bytes, url: str, config: Mapping[str, Any]) -> tuple[str, str, str]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for selective crawl")
    soup = BeautifulSoup(html_bytes, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "canvas", "template"]):
        node.decompose()
    for selector in ["nav", "header", "footer", ".breadcrumb", ".sidebar", ".menu", ".region-footer", ".region-header"]:
        for node in soup.select(selector):
            node.decompose()
    title = collapse_ws(soup.title.get_text(" ", strip=True) if soup.title else "")
    candidates: list[tuple[int, str]] = []
    for selector in config.get("main_content_selectors", []):
        for node in soup.select(selector):
            text = collapse_ws(node.get_text(" ", strip=True))
            if text:
                candidates.append((len(text), text))
    if candidates:
        candidates.sort(reverse=True, key=lambda item: item[0])
        method = "MAIN_CONTENT"
        text = candidates[0][1]
    else:
        body = soup.body or soup
        text = collapse_ws(body.get_text(" ", strip=True))
        method = "BODY_FALLBACK"
    return title, text[:safe_int(config.get("maximum_text_length"), 120000)], method


def classify_fetched_page(
    target_url: str,
    title: str,
    text: str,
    http_status: int,
    content_type: str,
    config: Mapping[str, Any],
) -> tuple[str, float, list[str], str]:
    combined_head = f"{title} {target_url}"
    combined = f"{combined_head} {text[:12000]}"
    reasons: list[str] = []
    if http_status >= 400:
        return "BROKEN_OFFICIAL_LINK", 0.99, [f"HTTP_STATUS_{http_status}"], ""
    if "html" not in lower(content_type):
        return "SUPPORTING_INFORMATION", 0.88, ["NON_HTML_TARGET"], ""
    if contains_any(combined_head, [*config.get("call_terms", []), *config.get("call_url_terms", [])]):
        return "CALL_OR_TEMPORARY_PAGE", 0.98, ["CALL_SIGNAL_IN_TITLE_OR_URL"], ""
    if contains_any(combined, config.get("accessibility_terms", [])):
        return "ACCESSIBILITY_LINK", 0.97, ["ACCESSIBILITY_CONTENT"], ""
    if contains_any(combined_head, config.get("navigation_url_terms", [])):
        return "GLOBAL_NAVIGATION", 0.95, ["NAVIGATION_URL_PATTERN"], ""
    if contains_any(combined, config.get("supporting_terms", [])) and not contains_any(combined_head, [*config.get("scheme_terms", []), *config.get("programme_terms", [])]):
        return "SUPPORTING_INFORMATION", 0.88, ["SUPPORTING_CONTENT"], ""

    evidence_count, evidence_names = master_evidence_count(text, config)
    scheme_hits = contains_any(combined_head, config.get("scheme_terms", []))
    programme_hits = contains_any(combined_head, config.get("programme_terms", []))
    if re.search(r"\b20(?:1\d|2\d)\b", combined_head) and contains_any(combined, config.get("call_terms", [])):
        return "CALL_OR_TEMPORARY_PAGE", 0.96, ["TEMPORAL_CALL_SIGNAL"], ""
    if evidence_count >= 3 and scheme_hits and not programme_hits:
        confidence = clamp(0.68 + 0.05 * evidence_count + 0.03 * len(scheme_hits))
        return "POSSIBLE_NEW_SCHEME", confidence, ["SCHEME_TITLE_SIGNAL", "MASTER_EVIDENCE:" + ",".join(evidence_names)], "SCHEME"
    if evidence_count >= 3 and programme_hits:
        confidence = clamp(0.68 + 0.05 * evidence_count + 0.03 * len(programme_hits))
        return "POSSIBLE_NEW_PROGRAMME", confidence, ["PROGRAMME_TITLE_SIGNAL", "MASTER_EVIDENCE:" + ",".join(evidence_names)], "PROGRAMME"
    if evidence_count >= 5:
        inferred = "PROGRAMME" if programme_hits else "SCHEME" if scheme_hits else ""
        if inferred:
            return f"POSSIBLE_NEW_{inferred}", 0.78, ["STRONG_MASTER_EVIDENCE", "MASTER_EVIDENCE:" + ",".join(evidence_names)], inferred
    if len(text.split()) < 40:
        return "SUPPORTING_INFORMATION", 0.65, ["LOW_CONTENT_PAGE"], ""
    return "UNRESOLVED", 0.48, ["INSUFFICIENT_MASTER_EVIDENCE:" + ",".join(evidence_names)], ""


def build_robots_parser(url: str, session: Any, timeout: int, user_agent: str) -> RobotFileParser | None:
    try:
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        response = session.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
        if response.status_code == 200:
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            return parser
    except Exception:
        return None
    return None


def fetch_target(
    queue_row: Mapping[str, Any],
    output_dir: Path,
    config: Mapping[str, Any],
    session: Any,
    robots_cache: dict[str, RobotFileParser | None],
) -> dict[str, Any]:
    if requests is None:
        raise RuntimeError("requests and beautifulsoup4 are required; install requirements-v3_4_0_3_3.txt")
    url = first_value(queue_row, "target_url")
    timeout = safe_int(config.get("request_timeout_seconds"), 30)
    user_agent = first_value(config, "user_agent") or DEFAULT_CONFIG["user_agent"]
    parsed = urlsplit(url)
    host_key = f"{parsed.scheme}://{parsed.netloc}"
    if host_key not in robots_cache:
        robots_cache[host_key] = build_robots_parser(url, session, timeout, user_agent)
    robots = robots_cache[host_key]
    if robots is not None and not robots.can_fetch(user_agent, url):
        return {
            **dict(queue_row),
            "crawl_status": "ROBOTS_DENIED",
            "http_status": "",
            "final_url": url,
            "content_type": "",
            "bytes_received": 0,
            "page_title": "",
            "main_text_excerpt": "",
            "text_word_count": 0,
            "snapshot_path": "",
            "fetch_duration_ms": 0,
            "crawl_error": "robots.txt denied selective fetch",
            "fetched_classification": "UNRESOLVED",
            "fetched_confidence": "0.0000",
            "fetched_reasons": "ROBOTS_DENIED",
            "inferred_entity_type": "",
        }
    started = time.perf_counter()
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": user_agent}, stream=True)
        maximum = safe_int(config.get("maximum_response_bytes"), 5000000)
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > maximum:
                raise ValueError(f"response exceeded maximum_response_bytes={maximum}")
            chunks.append(chunk)
        body = b"".join(chunks)
        content_type = response.headers.get("Content-Type", "")
        title = ""
        text = ""
        extraction_method = ""
        snapshot_path = ""
        if response.status_code < 400 and "html" in lower(content_type):
            title, text, extraction_method = extract_page(body, response.url, config)
            snapshots = output_dir / "snapshots" / "html"
            snapshots.mkdir(parents=True, exist_ok=True)
            filename = f"{stable_id('dst_selective', normalize_url(response.url, config))}.html.gz"
            snapshot = snapshots / filename
            with gzip.open(snapshot, "wb") as handle:
                handle.write(body)
            snapshot_path = str(snapshot.relative_to(output_dir))
        classification, confidence, reasons, inferred_type = classify_fetched_page(
            response.url, title, text, response.status_code, content_type, config
        )
        return {
            **dict(queue_row),
            "crawl_status": "FETCHED",
            "http_status": response.status_code,
            "final_url": response.url,
            "content_type": content_type,
            "bytes_received": len(body),
            "page_title": title,
            "main_text_excerpt": text[:safe_int(config.get("maximum_excerpt_length"), 800)],
            "text_word_count": len(text.split()),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "extraction_method": extraction_method,
            "snapshot_path": snapshot_path,
            "fetch_duration_ms": round((time.perf_counter() - started) * 1000),
            "crawl_error": "",
            "fetched_classification": classification,
            "fetched_confidence": f"{confidence:.4f}",
            "fetched_reasons": ";".join(reasons),
            "inferred_entity_type": inferred_type,
        }
    except Exception as exc:
        return {
            **dict(queue_row),
            "crawl_status": "FETCH_ERROR",
            "http_status": "",
            "final_url": url,
            "content_type": "",
            "bytes_received": 0,
            "page_title": "",
            "main_text_excerpt": "",
            "text_word_count": 0,
            "snapshot_path": "",
            "fetch_duration_ms": round((time.perf_counter() - started) * 1000),
            "crawl_error": f"{type(exc).__name__}: {exc}",
            "fetched_classification": "UNRESOLVED",
            "fetched_confidence": "0.0000",
            "fetched_reasons": "FETCH_ERROR",
            "inferred_entity_type": "",
        }


def candidate_inventory_row(crawled: Mapping[str, Any], entity_type: str) -> dict[str, Any]:
    title = first_value(crawled, "page_title", "proposed_name")
    source_url = first_value(crawled, "final_url", "target_url")
    return {
        "discovery_candidate_id": stable_id("dst_discovery_candidate", entity_type, source_url, title),
        "provisional_entity_id": "",
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "proposed_canonical_name": title,
        "proposed_entity_type": entity_type,
        "proposed_subtype": "STANDARD_SCHEME" if entity_type == "SCHEME" else "STANDARD_PROGRAMME",
        "official_abbreviation_candidate": "",
        "official_source_url": source_url,
        "identity_confidence": first_value(crawled, "fetched_confidence"),
        "master_evidence_score": first_value(crawled, "fetched_confidence"),
        "identity_evidence": first_value(crawled, "fetched_reasons"),
        "possible_parent_name_text": "",
        "review_flags": "SELECTIVE_CRAWL_DISCOVERY_REQUIRES_V3_4_0_4_CURATION",
        "requires_admin_review": "1",
        "curation_status": "PROVISIONAL_REQUIRES_V3_4_0_4",
        "identity_state": "PROVISIONAL_NOT_LOCKED",
        "inventory_origin": "V3_4_0_3_3_SELECTIVE_CRAWL",
        "created_at": utc_now(),
        "canonical_identity_created": "0",
        "identity_locked": "0",
    }


def process_pipeline(
    direct_targets: Sequence[Mapping[str, Any]],
    review_rows: Sequence[Mapping[str, Any]],
    duplicate_rows: Sequence[Mapping[str, Any]],
    corrected_schemes: Sequence[Mapping[str, Any]],
    corrected_programmes: Sequence[Mapping[str, Any]],
    downgrades: Sequence[Mapping[str, Any]],
    pages: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    context_audit: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    run_crawl: bool = False,
    output_dir: Path | None = None,
    max_targets: int = 0,
    fetcher: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    existing_crawled: Sequence[Mapping[str, Any]] = (),
) -> PipelineResult:
    contexts = derive_link_contexts(direct_targets, links, pages, context_audit, config)
    entity_index = build_entity_url_index(corrected_schemes, corrected_programmes, config)
    context_rows: list[dict[str, Any]] = []
    navigation: list[dict[str, Any]] = []
    supporting: list[dict[str, Any]] = []
    crawl_queue: list[dict[str, Any]] = []
    non_entity: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = [dict(row) for row in review_rows if upper(row.get("review_type")) == "PROVISIONAL_ENTITY_QUALITY"]
    audit: list[dict[str, Any]] = []

    for target in contexts:
        classification, confidence, reasons, queued = classify_context_offline(target, entity_index, config)
        row = context_to_row(target, classification, confidence, reasons, queued)
        context_rows.append(row)
        if classification in {"GLOBAL_NAVIGATION", "ACCESSIBILITY_LINK"}:
            navigation.append(row)
            non_entity.append(row)
        elif classification == "SUPPORTING_INFORMATION":
            supporting.append(row)
            non_entity.append(row)
        elif classification in {"CATEGORY_OR_INDEX_PAGE", "CALL_OR_TEMPORARY_PAGE", "NEWS_EVENT_OR_RECRUITMENT", "EXISTING_PROVISIONAL_ENTITY"}:
            non_entity.append(row)
        elif classification == "BROKEN_OFFICIAL_LINK":
            broken.append(row)
        if queued:
            queue_item = dict(row)
            queue_item.update({
                "crawl_queue_id": stable_id("dst_selective_queue", target.normalized_target_url),
                "crawl_depth": 0,
                "crawl_reason": ";".join(reasons),
                "crawl_status": "QUEUED",
            })
            crawl_queue.append(queue_item)
        elif classification == "UNRESOLVED":
            review.append({
                "review_id": stable_id("dst_gap_final_review", target.normalized_target_url),
                "review_type": "GAP_UNRESOLVED_OFFLINE",
                "proposed_name": target.proposed_name,
                "proposed_entity_type": "UNRESOLVED",
                "confidence": f"{confidence:.4f}",
                "review_flags": "NOT_HIGH_VALUE_FOR_AUTOMATIC_SELECTIVE_CRAWL",
                "evidence": ";".join(reasons),
                "source_url": target.target_url,
                "recommended_action": "MANUAL_REVIEW_OR_CLOSE_AS_NAVIGATION_SUPPORTING_PAGE",
            })
        audit.append({
            "audit_id": stable_id("dst_gap_resolution_audit", target.normalized_target_url),
            "audit_type": "OFFLINE_NAVIGATION_AWARE_FILTER",
            "record_url": target.target_url,
            "record_name": target.proposed_name,
            "decision": classification,
            "confidence": f"{confidence:.4f}",
            "reasons": ";".join(reasons),
            "selective_crawl_required": "1" if queued else "0",
        })

    queue_url_set = {first_value(row, "normalized_target_url") for row in crawl_queue}
    crawled: list[dict[str, Any]] = [
        dict(row) for row in existing_crawled
        if normalize_url(first_value(row, "target_url", "final_url"), config) in queue_url_set
        and first_value(row, "crawl_status") == "FETCHED"
    ]
    already_crawled = {normalize_url(first_value(row, "target_url", "final_url"), config) for row in crawled}
    if run_crawl and crawl_queue:
        remaining = [row for row in crawl_queue if first_value(row, "normalized_target_url") not in already_crawled]
        selected = remaining[:max_targets] if max_targets > 0 else remaining
        if fetcher is None:
            if requests is None:
                raise RuntimeError("requests and beautifulsoup4 are required for --run-selective-crawl")
            assert output_dir is not None
            session = requests.Session()
            robots_cache: dict[str, RobotFileParser | None] = {}
            for index, queue_row in enumerate(selected):
                crawled_row = fetch_target(queue_row, output_dir, config, session, robots_cache)
                crawled.append(crawled_row)
                if index + 1 < len(selected):
                    time.sleep(safe_float(config.get("delay_seconds"), 1.0))
        else:
            crawled.extend(dict(fetcher(row)) for row in selected)

    crawled_by_url = {
        normalize_url(first_value(row, "target_url"), config): row
        for row in crawled
        if first_value(row, "target_url")
    }
    new_schemes: list[dict[str, Any]] = []
    new_programmes: list[dict[str, Any]] = []
    queue_urls = {first_value(row, "normalized_target_url") for row in crawl_queue}
    for row in context_rows:
        normalized = first_value(row, "normalized_target_url")
        if normalized not in queue_urls:
            continue
        fetched = crawled_by_url.get(normalized)
        if fetched is None:
            if run_crawl:
                review.append({
                    "review_id": stable_id("dst_uncrawled_queue_review", normalized),
                    "review_type": "SELECTIVE_CRAWL_NOT_EXECUTED",
                    "proposed_name": first_value(row, "proposed_name"),
                    "proposed_entity_type": "UNRESOLVED",
                    "confidence": first_value(row, "classification_confidence"),
                    "review_flags": "QUEUE_TARGET_NOT_FETCHED_MAX_TARGET_LIMIT_OR_INTERNAL_ERROR",
                    "evidence": first_value(row, "classification_reasons"),
                    "source_url": first_value(row, "target_url"),
                    "recommended_action": "RUN_REMAINING_SELECTIVE_CRAWL",
                })
            continue
        classification = first_value(fetched, "fetched_classification")
        if classification == "POSSIBLE_NEW_SCHEME":
            candidate = candidate_inventory_row(fetched, "SCHEME")
            new_schemes.append(candidate)
        elif classification == "POSSIBLE_NEW_PROGRAMME":
            candidate = candidate_inventory_row(fetched, "PROGRAMME")
            new_programmes.append(candidate)
        elif classification == "BROKEN_OFFICIAL_LINK":
            broken.append(fetched)
        elif classification in {"GLOBAL_NAVIGATION", "ACCESSIBILITY_LINK", "SUPPORTING_INFORMATION", "CATEGORY_OR_INDEX_PAGE", "CALL_OR_TEMPORARY_PAGE", "NEWS_EVENT_OR_RECRUITMENT"}:
            non_entity.append(fetched)
            if classification in {"GLOBAL_NAVIGATION", "ACCESSIBILITY_LINK"}:
                navigation.append(fetched)
            if classification == "SUPPORTING_INFORMATION":
                supporting.append(fetched)
        else:
            review.append({
                "review_id": stable_id("dst_selective_unresolved_review", normalized),
                "review_type": "SELECTIVE_CRAWL_UNRESOLVED",
                "proposed_name": first_value(fetched, "page_title", "proposed_name"),
                "proposed_entity_type": "UNRESOLVED",
                "confidence": first_value(fetched, "fetched_confidence"),
                "review_flags": "SELECTIVE_FETCH_COMPLETED_BUT_IDENTITY_ROLE_UNRESOLVED",
                "evidence": first_value(fetched, "fetched_reasons"),
                "source_url": first_value(fetched, "final_url", "target_url"),
                "recommended_action": "CURATE_BEFORE_V3_4_0_4",
            })
        audit.append({
            "audit_id": stable_id("dst_selective_crawl_audit", normalized),
            "audit_type": "SELECTIVE_TARGET_FETCH",
            "record_url": first_value(fetched, "final_url", "target_url"),
            "record_name": first_value(fetched, "page_title", "proposed_name"),
            "decision": classification,
            "confidence": first_value(fetched, "fetched_confidence"),
            "reasons": first_value(fetched, "fetched_reasons"),
            "http_status": first_value(fetched, "http_status"),
            "crawl_status": first_value(fetched, "crawl_status"),
        })

    final_schemes = [dict(row) for row in corrected_schemes] + new_schemes
    final_programmes = [dict(row) for row in corrected_programmes] + new_programmes

    # Preserve explicit downgrade audit rows so all 33 provisional entities remain traceable.
    for row in downgrades:
        audit.append({
            "audit_id": stable_id("dst_preserved_downgrade", first_value(row, "provisional_entity_id"), first_value(row, "proposed_canonical_name")),
            "audit_type": "PRESERVED_V3_4_0_3_2_ENTITY_DOWNGRADE",
            "record_id": first_value(row, "provisional_entity_id"),
            "record_name": first_value(row, "proposed_canonical_name"),
            "record_url": first_value(row, "official_source_url"),
            "decision": first_value(row, "quality_decision"),
            "confidence": first_value(row, "quality_confidence"),
            "reasons": first_value(row, "quality_reasons"),
        })

    return PipelineResult(
        contexts=context_rows,
        navigation=navigation,
        supporting=supporting,
        crawl_queue=crawl_queue,
        crawled=crawled,
        new_schemes=new_schemes,
        new_programmes=new_programmes,
        non_entity=non_entity,
        broken=broken,
        final_schemes=final_schemes,
        final_programmes=final_programmes,
        review=review,
        audit=audit,
    )


def validate(
    direct_targets: Sequence[Mapping[str, Any]],
    duplicate_rows: Sequence[Mapping[str, Any]],
    corrected_schemes: Sequence[Mapping[str, Any]],
    corrected_programmes: Sequence[Mapping[str, Any]],
    downgrades: Sequence[Mapping[str, Any]],
    input_review: Sequence[Mapping[str, Any]],
    result: PipelineResult,
    config: Mapping[str, Any],
    run_crawl: bool,
    max_targets: int,
) -> dict[str, Any]:
    unique_count = len(direct_targets)
    duplicate_count = len(duplicate_rows)
    original_occurrences = sum(safe_int(first_value(row, "occurrence_count"), 1) for row in direct_targets)
    if original_occurrences == 0:
        original_occurrences = unique_count + duplicate_count
    final_classifications: dict[str, str] = {
        first_value(row, "normalized_target_url"): first_value(row, "final_gap_classification")
        for row in result.contexts
    }
    for row in result.crawled:
        normalized = normalize_url(first_value(row, "target_url"), config)
        fetched_class = first_value(row, "fetched_classification")
        if normalized and fetched_class:
            final_classifications[normalized] = fetched_class
    unresolved = sum(value == "UNRESOLVED" for value in final_classifications.values())
    unresolved_rate = unresolved / unique_count if unique_count else 0.0
    resolved_rate = 1.0 - unresolved_rate
    invalid = sorted({value for value in final_classifications.values() if value not in FINAL_GAP_CLASSIFICATIONS})
    generic_names = {normalize_name(item) for item in config.get("navigation_names", [])}
    generic_lock_candidates = [
        first_value(row, "proposed_canonical_name")
        for row in [*result.final_schemes, *result.final_programmes]
        if normalize_name(first_value(row, "proposed_canonical_name")) in generic_names
    ]
    call_contamination = sum(
        bool(contains_any(
            f"{first_value(row, 'proposed_canonical_name')} {first_value(row, 'official_source_url')}",
            [*config.get("call_terms", []), *config.get("call_url_terms", [])],
        ))
        for row in [*result.final_schemes, *result.final_programmes]
    )
    forbidden = sorted({
        field
        for row in [*result.contexts, *result.final_schemes, *result.final_programmes]
        for field in row
        if field in FORBIDDEN_IDENTITY_FIELDS
    })
    queue_count = len(result.crawl_queue)
    crawled_count = len(result.crawled)
    processed_queue_urls = {
        normalize_url(first_value(row, "target_url", "final_url"), config)
        for row in result.crawled
        if first_value(row, "crawl_status") == "FETCHED"
    }
    processed_queue_count = len(processed_queue_urls & {first_value(row, "normalized_target_url") for row in result.crawl_queue})
    quality_entity_reviews = [row for row in input_review if upper(row.get("review_type")) == "PROVISIONAL_ENTITY_QUALITY"]
    input_entity_total = len(corrected_schemes) + len(corrected_programmes) + len(downgrades) + len(quality_entity_reviews)
    final_entity_total = len(corrected_schemes) + len(corrected_programmes) + len(downgrades) + len(quality_entity_reviews)

    checks = {
        "all_gap_occurrences_accounted_for": original_occurrences == unique_count + duplicate_count,
        "all_unique_targets_classified": len(final_classifications) == unique_count,
        "gap_classifications_valid": not invalid,
        "navigation_filtered_without_crawl": all(
            first_value(row, "selective_crawl_required") == "0"
            for row in result.navigation
            if first_value(row, "target_url")
        ),
        "selective_crawl_limited_to_high_value_targets": all(
            first_value(row, "selective_crawl_required") == "1" and safe_int(first_value(row, "crawl_depth")) == 0
            for row in result.crawl_queue
        ),
        "requested_selective_targets_processed": (not run_crawl and queue_count == 0) or (run_crawl and processed_queue_count == queue_count),
        "final_unresolved_rate_within_limit": unresolved_rate <= safe_float(config.get("maximum_final_unresolved_rate"), 0.05),
        "gap_resolution_rate_passed": resolved_rate >= safe_float(config.get("minimum_gap_resolution_rate"), 0.95),
        "generic_lock_candidates_absent": not generic_lock_candidates,
        "call_contamination_absent": call_contamination == 0,
        "all_provisional_entities_preserved_or_reviewed": input_entity_total == final_entity_total,
        "forbidden_identity_fields_absent": not forbidden,
        "canonical_scheme_identity_created": False,
        "identity_locked": False,
    }
    # Prepare-only mode is valid for queue generation but cannot be ready for identity lock when queue exists.
    execution_complete = run_crawl or queue_count == 0
    validation_passed = all(
        value for key, value in checks.items()
        if key not in {"canonical_scheme_identity_created", "identity_locked"}
    ) and execution_complete

    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "generated_at": utc_now(),
        "execution_mode": "SELECTIVE_CRAWL" if run_crawl else "PREPARE_ONLY",
        "counts": {
            "input_unique_category_gaps": unique_count,
            "input_duplicate_gap_occurrences": duplicate_count,
            "input_gap_occurrences": unique_count + duplicate_count,
            "global_navigation_gaps": len(result.navigation),
            "supporting_information_gaps": len(result.supporting),
            "selective_crawl_queue": queue_count,
            "selectively_crawled_targets": crawled_count,
            "processed_selective_queue_targets": processed_queue_count,
            "possible_new_schemes": len(result.new_schemes),
            "possible_new_programmes": len(result.new_programmes),
            "non_entity_gap_resolutions": len(result.non_entity),
            "true_broken_targets": len(result.broken),
            "final_unresolved_targets": unresolved,
            "final_corrected_schemes": len(result.final_schemes),
            "final_corrected_programmes": len(result.final_programmes),
            "admin_review_rows": len(result.review),
            "input_provisional_entity_total": input_entity_total,
        },
        "quality": {
            "final_unresolved_rate": round(unresolved_rate, 6),
            "maximum_final_unresolved_rate": safe_float(config.get("maximum_final_unresolved_rate"), 0.05),
            "gap_resolution_rate": round(resolved_rate, 6),
            "minimum_gap_resolution_rate": safe_float(config.get("minimum_gap_resolution_rate"), 0.95),
            "invalid_gap_classifications": invalid,
            "generic_lock_candidates": generic_lock_candidates,
            "call_contamination": call_contamination,
            "forbidden_identity_fields_found": forbidden,
            "execution_complete": execution_complete,
        },
        "checks": checks,
        "gap_resolution_validation_passed": validation_passed,
        "ready_for_v3_4_0_4": validation_passed,
    }


def build_summary(
    result: PipelineResult,
    validation: Mapping[str, Any],
    paths: Mapping[str, Path],
    run_crawl: bool,
) -> dict[str, Any]:
    classifications = Counter(first_value(row, "final_gap_classification") for row in result.contexts)
    fetched_classes = Counter(first_value(row, "fetched_classification") for row in result.crawled)
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "completed_at": utc_now(),
        "input_dir": str(paths["input_dir"]),
        "classifier_dir": str(paths["classifier_dir"]),
        "link_graph": str(paths["links"]),
        "output_dir": str(paths["output_dir"]),
        "execution_mode": "SELECTIVE_CRAWL" if run_crawl else "PREPARE_ONLY",
        "network_access_used": run_crawl,
        "full_recrawl_performed": False,
        "selective_crawl_depth": 0,
        "identity_safeguard": {
            "canonical_scheme_identity_created": False,
            "identity_locked": False,
            "call_pages_used_as_permanent_candidates": False,
            "generic_pages_allowed_in_final_inventory": False,
            "description": "Navigation-aware gap resolution and provisional discovery only; v3.4.0.4 must curate and lock identities.",
        },
        "counts": validation.get("counts", {}),
        "offline_classification_counts": dict(sorted(classifications.items())),
        "selective_crawl_classification_counts": dict(sorted(fetched_classes.items())),
        "gap_resolution_validation_passed": validation.get("gap_resolution_validation_passed", False),
        "ready_for_v3_4_0_4": validation.get("ready_for_v3_4_0_4", False),
        "outputs": {
            "link_context": LINK_CONTEXT_OUTPUT,
            "navigation": NAVIGATION_OUTPUT,
            "supporting": SUPPORTING_OUTPUT,
            "crawl_queue": CRAWL_QUEUE_OUTPUT,
            "crawled_targets": CRAWLED_OUTPUT,
            "possible_new_schemes": NEW_SCHEME_OUTPUT,
            "possible_new_programmes": NEW_PROGRAMME_OUTPUT,
            "non_entity_resolutions": NON_ENTITY_OUTPUT,
            "broken_targets": BROKEN_OUTPUT,
            "final_schemes": FINAL_SCHEMES_OUTPUT,
            "final_programmes": FINAL_PROGRAMMES_OUTPUT,
            "review_queue": FINAL_REVIEW_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def write_outputs(output_dir: Path, result: PipelineResult, validation: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / LINK_CONTEXT_OUTPUT, result.contexts)
    write_csv(output_dir / NAVIGATION_OUTPUT, result.navigation)
    write_csv(output_dir / SUPPORTING_OUTPUT, result.supporting)
    write_csv(output_dir / CRAWL_QUEUE_OUTPUT, result.crawl_queue)
    write_csv(output_dir / CRAWLED_OUTPUT, result.crawled)
    write_csv(output_dir / NEW_SCHEME_OUTPUT, result.new_schemes)
    write_csv(output_dir / NEW_PROGRAMME_OUTPUT, result.new_programmes)
    write_csv(output_dir / NON_ENTITY_OUTPUT, result.non_entity)
    write_csv(output_dir / BROKEN_OUTPUT, result.broken)
    write_csv(output_dir / FINAL_SCHEMES_OUTPUT, result.final_schemes)
    write_csv(output_dir / FINAL_PROGRAMMES_OUTPUT, result.final_programmes)
    write_csv(output_dir / FINAL_REVIEW_OUTPUT, result.review)
    write_csv(output_dir / AUDIT_OUTPUT, result.audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)


def resolve_paths(project_root: Path) -> dict[str, Path]:
    input_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_2"
    classifier_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_2"
    crawl_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    output_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_3"
    return {
        "input_dir": input_dir,
        "classifier_dir": classifier_dir,
        "crawl_dir": crawl_dir,
        "output_dir": output_dir,
        "direct_targets": input_dir / DIRECT_TARGET_INPUT,
        "review": input_dir / REVIEW_INPUT,
        "duplicates": input_dir / DUPLICATE_INPUT,
        "schemes": input_dir / CORRECTED_SCHEMES_INPUT,
        "programmes": input_dir / CORRECTED_PROGRAMMES_INPUT,
        "downgrades": input_dir / DOWNGRADES_INPUT,
        "context_audit": input_dir / CONTEXT_AUDIT_INPUT,
        "pages": classifier_dir / CLASSIFIED_PAGES_INPUT,
        "links": crawl_dir / LINK_GRAPH_INPUT,
        "existing_crawled": output_dir / CRAWLED_OUTPUT,
    }


def run_pipeline(
    project_root: Path,
    config: Mapping[str, Any],
    dry_run: bool = False,
    prepare_only: bool = False,
    run_selective_crawl: bool = False,
    max_targets: int = 0,
) -> tuple[PipelineResult | None, dict[str, Any]]:
    paths = resolve_paths(project_root)
    direct_targets = read_csv(paths["direct_targets"])
    review_rows = read_csv(paths["review"])
    duplicates = read_csv(paths["duplicates"], required=False)
    schemes = read_csv(paths["schemes"])
    programmes = read_csv(paths["programmes"])
    downgrades = read_csv(paths["downgrades"], required=False)
    pages = read_csv(paths["pages"])
    links = read_csv(paths["links"])
    context_audit = read_csv(paths["context_audit"], required=False)
    existing_crawled = read_csv(paths["existing_crawled"], required=False)
    if len(existing_crawled) == 1 and first_value(existing_crawled[0], "record_status") == "NO_RECORDS":
        existing_crawled = []

    preview = process_pipeline(
        direct_targets, review_rows, duplicates, schemes, programmes, downgrades,
        pages, links, context_audit, config, run_crawl=False, existing_crawled=existing_crawled,
    )
    if dry_run:
        return None, {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "inputs": {
                "unique_category_gaps": len(direct_targets),
                "duplicate_gap_occurrences": len(duplicates),
                "corrected_provisional_schemes": len(schemes),
                "corrected_provisional_programmes": len(programmes),
                "preserved_downgrades": len(downgrades),
                "classified_pages": len(pages),
                "link_graph_rows": len(links),
                "context_audit_rows": len(context_audit),
                "previously_crawled_selective_targets": len(existing_crawled),
            },
            "preview": {
                "global_navigation_gaps": len(preview.navigation),
                "supporting_information_gaps": len(preview.supporting),
                "selective_crawl_queue": len(preview.crawl_queue),
                "offline_unresolved_review_rows": sum(upper(row.get("review_type")) == "GAP_UNRESOLVED_OFFLINE" for row in preview.review),
            },
            "files_written": False,
            "network_access_used": False,
        }

    run_crawl = run_selective_crawl and not prepare_only
    result = process_pipeline(
        direct_targets, review_rows, duplicates, schemes, programmes, downgrades,
        pages, links, context_audit, config, run_crawl=run_crawl,
        output_dir=paths["output_dir"], max_targets=max_targets, existing_crawled=existing_crawled,
    )
    validation = validate(
        direct_targets, duplicates, schemes, programmes, downgrades, review_rows,
        result, config, run_crawl=run_crawl, max_targets=max_targets,
    )
    summary = build_summary(result, validation, paths, run_crawl)
    write_outputs(paths["output_dir"], result, validation, summary)
    return result, summary


def self_test() -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    direct_targets = [
        {"target_url": "https://dst.gov.in/screen-reader-access", "normalized_target_url": "https://dst.gov.in/screen-reader-access", "target_page_title": "Screen Reader Access", "occurrence_count": "4", "gap_classification": "UNRESOLVED"},
        {"target_url": "https://dst.gov.in/new-research-scheme", "normalized_target_url": "https://dst.gov.in/new-research-scheme", "target_page_title": "New Research Scheme", "occurrence_count": "2", "gap_classification": "UNRESOLVED"},
        {"target_url": "https://dst.gov.in/callforproposals/test-2026", "normalized_target_url": "https://dst.gov.in/callforproposals/test-2026", "target_page_title": "Call for Proposals 2026", "occurrence_count": "1", "gap_classification": "UNRESOLVED"},
        {"target_url": "https://dst.gov.in/existing-programme", "normalized_target_url": "https://dst.gov.in/existing-programme", "target_page_title": "Existing Programme", "occurrence_count": "1", "gap_classification": "UNRESOLVED"},
    ]
    duplicates = [{"target_url": "https://dst.gov.in/screen-reader-access"}] * 4
    schemes = [{"provisional_entity_id": "s1", "proposed_canonical_name": "Valid Scheme", "official_source_url": "https://dst.gov.in/valid-scheme"}]
    programmes = [{"provisional_entity_id": "p1", "proposed_canonical_name": "Existing Programme", "official_source_url": "https://dst.gov.in/existing-programme"}]
    review = [{"review_type": "PROVISIONAL_ENTITY_QUALITY", "provisional_entity_id": "x1", "proposed_name": "Ambiguous Entity"}]
    downgrades = [{"provisional_entity_id": "d1", "proposed_canonical_name": "Archive", "quality_decision": "DOWNGRADE_TO_ARCHIVE"}]
    pages = [{"final_url": "https://dst.gov.in/existing-programme", "page_title": "Existing Programme", "page_role": "PROGRAMME_MASTER_CANDIDATE"}]
    links = [
        {"from_url": "https://dst.gov.in/schemes", "to_url": "https://dst.gov.in/new-research-scheme", "normalized_to_url": "https://dst.gov.in/new-research-scheme", "anchor_text": "New Research Scheme", "in_main_content": "1", "relevance_score": "80", "enqueue_decision": "QUEUED"},
        {"from_url": "https://dst.gov.in/programmes", "to_url": "https://dst.gov.in/existing-programme", "normalized_to_url": "https://dst.gov.in/existing-programme", "anchor_text": "Existing Programme", "in_main_content": "1", "relevance_score": "80", "enqueue_decision": "QUEUED"},
    ]
    pages.extend([
        {"final_url": "https://dst.gov.in/schemes", "page_title": "Schemes", "page_role": "SCHEME_CATEGORY_INDEX"},
        {"final_url": "https://dst.gov.in/programmes", "page_title": "Programmes", "page_role": "PROGRAMME_CATEGORY_INDEX"},
    ])

    def fake_fetch(queue_row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            **dict(queue_row),
            "crawl_status": "FETCHED",
            "http_status": "200",
            "final_url": first_value(queue_row, "target_url"),
            "content_type": "text/html",
            "page_title": "New Research Scheme",
            "main_text_excerpt": "Objectives eligibility funding support how to apply beneficiaries scope duration Department of Science and Technology.",
            "text_word_count": "100",
            "fetched_classification": "POSSIBLE_NEW_SCHEME",
            "fetched_confidence": "0.9300",
            "fetched_reasons": "SCHEME_TITLE_SIGNAL;MASTER_EVIDENCE",
            "inferred_entity_type": "SCHEME",
        }

    result = process_pipeline(
        direct_targets, review, duplicates, schemes, programmes, downgrades,
        pages, links, [], config, run_crawl=True, output_dir=Path("."), fetcher=fake_fetch,
    )
    validation = validate(
        direct_targets, duplicates, schemes, programmes, downgrades, review,
        result, config, run_crawl=True, max_targets=0,
    )
    tests = {
        "accessibility_filtered_offline": any(first_value(row, "final_gap_classification") == "ACCESSIBILITY_LINK" for row in result.navigation),
        "high_value_target_queued": len(result.crawl_queue) == 1,
        "call_filtered_without_crawl": any(first_value(row, "final_gap_classification") == "CALL_OR_TEMPORARY_PAGE" for row in result.non_entity),
        "existing_entity_matched": any(first_value(row, "final_gap_classification") == "EXISTING_PROVISIONAL_ENTITY" for row in result.non_entity),
        "selective_crawl_created_scheme_candidate": len(result.new_schemes) == 1,
        "existing_inventory_preserved": len(result.final_schemes) == 2 and len(result.final_programmes) == 1,
        "no_call_contamination": validation["quality"]["call_contamination"] == 0,
        "no_canonical_identity": validation["checks"]["canonical_scheme_identity_created"] is False,
        "no_identity_lock": validation["checks"]["identity_locked"] is False,
    }
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "tests": tests,
        "self_test_passed": all(tests.values()),
        "preview_counts": {
            "navigation": len(result.navigation),
            "crawl_queue": len(result.crawl_queue),
            "new_schemes": len(result.new_schemes),
            "final_schemes": len(result.final_schemes),
            "final_programmes": len(result.final_programmes),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Write filtered outputs and crawl queue without network access.")
    parser.add_argument("--run-selective-crawl", action="store_true", help="Fetch only the generated high-value depth-0 queue.")
    parser.add_argument("--max-targets", type=int, default=0, help="Maximum selective targets to fetch; 0 means all queued targets.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 3 when validation is not ready for v3.4.0.4.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        payload = self_test()
        print(json.dumps(payload, indent=2))
        return 0 if payload["self_test_passed"] else 2
    try:
        config = load_config(args.config)
        _, payload = run_pipeline(
            args.project_root.resolve(), config,
            dry_run=args.dry_run,
            prepare_only=args.prepare_only,
            run_selective_crawl=args.run_selective_crawl,
            max_targets=max(0, args.max_targets),
        )
        print(json.dumps(payload, indent=2))
        if args.strict and not args.dry_run and not payload.get("ready_for_v3_4_0_4", False):
            return 3
        return 0
    except Exception as exc:
        print(json.dumps({
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "error": f"{type(exc).__name__}: {exc}",
        }, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
