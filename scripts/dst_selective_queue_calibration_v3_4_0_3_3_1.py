#!/usr/bin/env python3
"""
SSIP v3.4.0.3.3.1 — DST Selective Queue Calibration and Unresolved Target Triage.

This hotfix recalibrates unresolved DST category-gap targets from v3.4.0.3.3.
It performs deterministic non-entity triage first, then weighted entity scoring,
and only fetches a small resumable depth-0 queue of plausible named initiatives.

Safety guarantees
-----------------
* Existing v3.4.0.1–v3.4.0.3.3 outputs are read-only.
* No recursive crawl; each queued URL is fetched once at depth 0.
* Calls, deadlines, results, policy/report pages, press releases, recruitment,
  portals, institutions, administrative pages and global navigation cannot be
  promoted to permanent schemes/programmes.
* Existing corrected provisional inventories are preserved.
* New discoveries remain provisional and unlocked for v3.4.0.4 curation.
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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    BeautifulSoup = None  # type: ignore[assignment]

VERSION = "3.4.0.3.3.1"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"

CONTEXT_INPUT = "dst_gap_link_context_v3_4_0_3_3.csv"
REVIEW_INPUT = "dst_final_gap_review_queue_v3_4_0_3_3.csv"
SCHEMES_INPUT = "dst_final_corrected_schemes_v3_4_0_3_3.csv"
PROGRAMMES_INPUT = "dst_final_corrected_programmes_v3_4_0_3_3.csv"
SUMMARY_INPUT = "dst_gap_resolution_summary_v3_4_0_3_3.json"
USER_CALIBRATION_INPUT = "dst_calibrated_unresolved_targets.csv"

SCORES_OUTPUT = "dst_unresolved_target_scores_v3_4_0_3_3_1.csv"
QUEUE_OUTPUT = "dst_calibrated_selective_crawl_queue_v3_4_0_3_3_1.csv"
LOW_VALUE_OUTPUT = "dst_low_value_gap_closures_v3_4_0_3_3_1.csv"
CRAWLED_OUTPUT = "dst_selectively_crawled_targets_v3_4_0_3_3_1.csv"
NEW_SCHEMES_OUTPUT = "dst_possible_new_scheme_pages_v3_4_0_3_3_1.csv"
NEW_PROGRAMMES_OUTPUT = "dst_possible_new_programme_pages_v3_4_0_3_3_1.csv"
MANUAL_REVIEW_OUTPUT = "dst_manual_entity_review_candidates_v3_4_0_3_3_1.csv"
FINAL_CONTEXT_OUTPUT = "dst_final_gap_context_v3_4_0_3_3_1.csv"
FINAL_REVIEW_OUTPUT = "dst_final_unresolved_review_queue_v3_4_0_3_3_1.csv"
FINAL_SCHEMES_OUTPUT = "dst_final_corrected_schemes_v3_4_0_3_3_1.csv"
FINAL_PROGRAMMES_OUTPUT = "dst_final_corrected_programmes_v3_4_0_3_3_1.csv"
AUDIT_OUTPUT = "dst_calibration_audit_v3_4_0_3_3_1.csv"
VALIDATION_OUTPUT = "dst_calibration_validation_v3_4_0_3_3_1.json"
SUMMARY_OUTPUT = "dst_calibration_summary_v3_4_0_3_3_1.json"

FORBIDDEN_IDENTITY_FIELDS = {
    "canonical_scheme_name", "canonical_programme_name", "scheme_id",
    "programme_id", "locked_scheme_name", "locked_programme_name",
    "identity_lock_status",
}

ALLOWED_FINAL_CLASSES = {
    "EXISTING_RESOLUTION", "ACCESSIBILITY_LINK", "GLOBAL_NAVIGATION", "CATEGORY_OR_INDEX_PAGE",
    "SUPPORTING_INFORMATION", "POLICY_REPORT_OR_DOCUMENT",
    "NEWS_EVENT_OR_RECRUITMENT", "INSTITUTION_OR_RESOURCE",
    "CALL_OR_TEMPORARY_PAGE", "BROKEN_OFFICIAL_LINK",
    "MANUAL_ENTITY_REVIEW", "POSSIBLE_NEW_SCHEME",
    "POSSIBLE_NEW_PROGRAMME", "UNRESOLVED",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "allowed_domains": ["dst.gov.in", "www.dst.gov.in"],
    "high_queue_score": 45,
    "medium_queue_score": 30,
    "manual_review_score": 15,
    "minimum_queue_score_without_main_content": 35,
    "maximum_final_unresolved_rate": 0.05,
    "minimum_gap_resolution_rate": 0.95,
    "maximum_selective_queue_size": 20,
    "request_timeout_seconds": 30,
    "delay_seconds": 1.0,
    "maximum_response_bytes": 5_000_000,
    "maximum_text_length": 120_000,
    "maximum_excerpt_length": 1_000,
    "user_agent": "SSIP-DST-CalibratedSelectiveCrawler/3.4.0.3.3.1 (+government-scheme-indexing)",
    "tracking_query_parameters": [
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "_ga", "_gl",
    ],
    "known_category_urls": [
        "/national-missions", "/international-cooperation-mega-science",
        "/st-data-policy-and-training", "/seed-home",
    ],
    "known_supporting_urls": [
        "/brief-history", "/objectives-mandate", "/monitoring-and-evaluation",
        "/stakeholders-target-groups", "/highlights-achievements", "/about-ngcma",
        "/oecd-principles-glp", "/glp-certified-test-facilities",
        "/right-information", "/public-grievance", "/parliament-matters",
        "/parliament-qa", "/pension-grievance-redressal",
    ],
    "institution_url_terms": [
        "/attached-institutions", "/autonomous-st-attached-institutions",
        "/professional-bodies", "/statutory-board", "/international-bi-lateral-institutions",
        "/anusandhan-national-research-foundation",
    ],
    "document_url_terms": [
        "/document", "/reports/", "/report/", "/budget/", "/publication/", "/publications/",
    ],
    "resource_url_terms": ["/importantlinks/", "/important_link"],
    "news_url_terms": ["/pressrelease/", "/news/", "/whatsnew/", "/photo-gallery"],
    "call_terms": [
        "call for proposal", "call for proposals", "applications invited",
        "inviting applications", "expression of interest", "deadline",
        "last date", "corrigendum", "addendum", "selected proposals",
        "shortlisted", "apply now", "request for proposal", "result",
    ],
    "news_recruitment_terms": [
        "press release", "filling up", "post of", "deputation", "recruitment",
        "vacancy", "appointment", "inquiry officer", "tender", "award ceremony",
    ],
    "document_terms": [
        "policy", "report", "roadmap", "budget", "demands for grants",
        "guidebook", "coffee table book", "proforma", "publication",
        "statistics at a glance", "principles of glp", "vision document",
    ],
    "resource_terms": [
        "portal", "information retrieval system", "e-journal", "project management system",
        "science congress", "academicians abroad", "maps the", "resources",
    ],
    "supporting_terms": [
        "brief history", "objectives", "monitoring and evaluation", "stakeholders",
        "highlights and achievements", "about ngcma", "certified test facilities",
        "right to information", "public grievances", "parliament", "pension grievance",
        "read more", "view all", "open press release",
    ],
    "institution_terms": [
        "foundation", "statutory bodies", "professional bodies", "attached institutions",
        "autonomous institutions", "bilateral institutions", "test facilities",
    ],
    "permanent_terms": [
        "mission", "initiative", "programme", "program", "scheme", "facility",
        "fellowship", "research", "innovation", "technology", "capacity",
        "cooperation", "science", "development", "seed", "wings abroad",
    ],
    "scheme_terms": [
        "scheme", "fellowship", "scholarship", "grant", "award", "assistance",
        "financial support", "travel support",
    ],
    "programme_terms": [
        "programme", "program", "mission", "initiative", "platform", "network",
        "facility", "capacity building", "hub", "centre", "center", "cell",
        "wings abroad", "seed",
    ],
    "manual_review_names": ["Science Wings Abroad"],
    "selective_crawl_names": ["Science Wings Abroad"],
    "main_content_selectors": [
        "main", "article", "#content", ".main-content", ".region-content",
        ".node-content", ".field-name-body", ".content",
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
class Result:
    scores: list[dict[str, Any]]
    queue: list[dict[str, Any]]
    closures: list[dict[str, Any]]
    crawled: list[dict[str, Any]]
    new_schemes: list[dict[str, Any]]
    new_programmes: list[dict[str, Any]]
    manual_candidates: list[dict[str, Any]]
    final_context: list[dict[str, Any]]
    final_review: list[dict[str, Any]]
    final_schemes: list[dict[str, Any]]
    final_programmes: list[dict[str, Any]]
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
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_url(value: str, config: Mapping[str, Any]) -> str:
    value = collapse_ws(value).strip('"')
    if not value:
        return ""
    parts = urlsplit(value)
    scheme = (parts.scheme or "https").casefold()
    host = parts.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    tracking = {lower(item) for item in config.get("tracking_query_parameters", [])}
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if lower(k) not in tracking]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def contains_any(text: str, terms: Iterable[str]) -> list[str]:
    haystack = f" {lower(text)} "
    return [collapse_ws(term) for term in terms if lower(term) and lower(term) in haystack]


def is_internal_html(url: str, config: Mapping[str, Any]) -> bool:
    try:
        parts = urlsplit(collapse_ws(url).strip('"'))
    except ValueError:
        return False
    host = parts.netloc.casefold()
    allowed = {lower(item) for item in config.get("allowed_domains", [])}
    if host not in allowed:
        return False
    return not re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|jpg|jpeg|png|gif)(?:$|\?)", parts.path, re.I)


def read_csv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if len(rows) == 1 and first_value(rows[0], "record_status") == "NO_RECORDS":
        return []
    return rows


def read_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    output_rows: Sequence[Mapping[str, Any]] = rows
    if not fields:
        fields = ["record_status"]
        output_rows = [{"record_status": "NO_RECORDS"}]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in output_rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    temp.replace(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_config(path: Path | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path:
        loaded = read_json(path)
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def deterministic_triage(row: Mapping[str, Any], config: Mapping[str, Any]) -> tuple[str, float, list[str]] | None:
    name = first_value(row, "proposed_name", "proposed_canonical_name", "target_page_title")
    url = first_value(row, "target_url", "normalized_target_url", "source_url")
    combined = f"{name} {url}"
    url_l = lower(url)
    name_l = lower(name)
    sources = safe_int(first_value(row, "unique_source_pages"))
    main = safe_int(first_value(row, "main_content_occurrences"))

    if contains_any(combined, config.get("call_terms", [])):
        return "CALL_OR_TEMPORARY_PAGE", 0.98, ["CALL_OR_TEMPORARY_SIGNAL"]
    if contains_any(url_l, config.get("news_url_terms", [])) or contains_any(name_l, config.get("news_recruitment_terms", [])):
        return "NEWS_EVENT_OR_RECRUITMENT", 0.98, ["NEWS_OR_RECRUITMENT_PATTERN"]
    if contains_any(url_l, config.get("document_url_terms", [])) or contains_any(name_l, config.get("document_terms", [])):
        return "POLICY_REPORT_OR_DOCUMENT", 0.97, ["POLICY_REPORT_DOCUMENT_PATTERN"]
    if contains_any(url_l, config.get("resource_url_terms", [])) or contains_any(name_l, config.get("resource_terms", [])):
        return "INSTITUTION_OR_RESOURCE", 0.94, ["PORTAL_OR_RESOURCE_PATTERN"]
    if contains_any(url_l, config.get("institution_url_terms", [])) or contains_any(name_l, config.get("institution_terms", [])):
        return "INSTITUTION_OR_RESOURCE", 0.95, ["INSTITUTION_OR_STATUTORY_BODY_PATTERN"]
    if contains_any(url_l, config.get("known_supporting_urls", [])) or contains_any(name_l, config.get("supporting_terms", [])):
        return "SUPPORTING_INFORMATION", 0.95, ["KNOWN_SUPPORTING_INFORMATION"]
    if contains_any(url_l, config.get("known_category_urls", [])):
        return "CATEGORY_OR_INDEX_PAGE", 0.96, ["KNOWN_DST_CATEGORY_URL"]
    if sources >= 100 and main == 0:
        if contains_any(name_l, ["mission", "cooperation", "data", "policy", "training", "programmes", "programs"]):
            return "CATEGORY_OR_INDEX_PAGE", 0.96, ["SITE_WIDE_CATEGORY_MENU_LINK"]
        return "GLOBAL_NAVIGATION", 0.94, ["SITE_WIDE_MENU_LINK"]
    if url.endswith('"') or re.search(r"\.pdf(?:\"|$)", url, re.I):
        return "POLICY_REPORT_OR_DOCUMENT", 0.92, ["DOCUMENT_OR_MALFORMED_DOCUMENT_LINK"]
    return None


def score_target(row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    name = first_value(row, "proposed_name", "proposed_canonical_name", "target_page_title")
    url = first_value(row, "target_url", "normalized_target_url", "source_url")
    main = safe_int(first_value(row, "main_content_occurrences"))
    relevance = safe_float(first_value(row, "max_relevance_score", "CalibratedScore"))
    sources = safe_int(first_value(row, "unique_source_pages"))
    score = 0
    reasons: list[str] = []

    if is_internal_html(url, config):
        score += 20
        reasons.append("INTERNAL_DST_HTML_TARGET:+20")
    if main > 0:
        score += 25
        reasons.append("MAIN_CONTENT_LINK:+25")
    if relevance >= 40:
        score += 15
        reasons.append("RELEVANCE_GE_40:+15")
    elif relevance >= 20:
        score += 8
        reasons.append("RELEVANCE_GE_20:+8")
    if sources > 1:
        score += 5
        reasons.append("MULTIPLE_SOURCE_PAGES:+5")
    if contains_any(name, config.get("permanent_terms", [])):
        score += 15
        reasons.append("PERMANENT_ENTITY_NAME_SIGNAL:+15")
    if re.fullmatch(r"[A-Z][A-Z0-9&.-]{2,12}", collapse_ws(name)):
        score += 10
        reasons.append("NAMED_ACRONYM_SIGNAL:+10")

    triage = deterministic_triage(row, config)
    if triage:
        classification, confidence, triage_reasons = triage
        decision = "OFFLINE_CLOSE"
        queue_priority = ""
    else:
        high = safe_int(config.get("high_queue_score"), 45)
        medium = safe_int(config.get("medium_queue_score"), 30)
        manual = safe_int(config.get("manual_review_score"), 15)
        min_no_main = safe_int(config.get("minimum_queue_score_without_main_content"), 35)
        explicit_queue = normalize_name(name) in {normalize_name(item) for item in config.get("selective_crawl_names", [])}
        if score >= high and (main > 0 or score >= min_no_main or explicit_queue):
            decision, queue_priority = "SELECTIVE_CRAWL_HIGH", "HIGH"
            classification, confidence = "UNRESOLVED", 0.65
        elif score >= medium and (main > 0 or score >= min_no_main or explicit_queue):
            decision, queue_priority = "SELECTIVE_CRAWL_MEDIUM", "MEDIUM"
            classification, confidence = "UNRESOLVED", 0.58
        elif score >= manual or normalize_name(name) in {normalize_name(item) for item in config.get("manual_review_names", [])}:
            decision, queue_priority = "MANUAL_ENTITY_REVIEW", ""
            classification, confidence = "MANUAL_ENTITY_REVIEW", 0.55
        else:
            decision, queue_priority = "CLOSE_AS_LOW_VALUE", ""
            classification, confidence = "SUPPORTING_INFORMATION", 0.62
        triage_reasons = []

    return {
        **dict(row),
        "calibration_id": stable_id("dst_calibration", normalize_url(url, config), name),
        "calibrated_score": score,
        "calibrated_decision": decision,
        "queue_priority": queue_priority,
        "calibrated_classification": classification,
        "calibrated_confidence": f"{confidence:.4f}",
        "score_reasons": ";".join(reasons),
        "triage_reasons": ";".join(triage_reasons),
        "identity_safeguard": "NO_CANONICAL_IDENTITY_NO_LOCK",
    }


def extract_page(body: bytes, config: Mapping[str, Any]) -> tuple[str, str, str]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required")
    soup = BeautifulSoup(body, "html.parser")
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
        candidates.sort(reverse=True)
        return title, candidates[0][1][:safe_int(config.get("maximum_text_length"), 120_000)], "MAIN_CONTENT"
    body_node = soup.body or soup
    return title, collapse_ws(body_node.get_text(" ", strip=True))[:safe_int(config.get("maximum_text_length"), 120_000)], "BODY_FALLBACK"


def evidence_categories(text: str, config: Mapping[str, Any]) -> list[str]:
    return [
        category
        for category, terms in config.get("master_evidence_terms", {}).items()
        if contains_any(text, terms)
    ]


def classify_fetched(
    url: str,
    title: str,
    text: str,
    status: int,
    content_type: str,
    config: Mapping[str, Any],
) -> tuple[str, float, list[str], str, list[str]]:
    if status <= 0 or status >= 400:
        return "BROKEN_OFFICIAL_LINK", 0.99, [f"HTTP_STATUS_{status}"], "", []
    if "html" not in lower(content_type):
        return "POLICY_REPORT_OR_DOCUMENT", 0.95, ["NON_HTML_RESPONSE"], "", []

    synthetic = {
        "proposed_name": title,
        "target_url": url,
        "unique_source_pages": "1",
        "main_content_occurrences": "1",
    }
    triage = deterministic_triage(synthetic, config)
    if triage:
        cls, confidence, reasons = triage
        return cls, confidence, reasons, "", evidence_categories(text, config)

    evidence = evidence_categories(text, config)
    combined = f"{title} {text[:5000]}"
    scheme_hits = contains_any(combined, config.get("scheme_terms", []))
    programme_hits = contains_any(combined, config.get("programme_terms", []))
    authority = "authority" in evidence or "department of science and technology" in lower(text)
    master_strength = len(evidence)

    if master_strength >= 2 and scheme_hits:
        confidence = clamp(0.68 + 0.04 * min(master_strength, 6) + (0.05 if authority else 0.0))
        return "POSSIBLE_NEW_SCHEME", confidence, ["SCHEME_TITLE_SIGNAL", "MASTER_EVIDENCE"], "SCHEME", evidence
    if master_strength >= 2 and programme_hits:
        confidence = clamp(0.68 + 0.04 * min(master_strength, 6) + (0.05 if authority else 0.0))
        return "POSSIBLE_NEW_PROGRAMME", confidence, ["PROGRAMME_TITLE_SIGNAL", "MASTER_EVIDENCE"], "PROGRAMME", evidence
    if scheme_hits or programme_hits or master_strength >= 1:
        return "MANUAL_ENTITY_REVIEW", 0.58, ["AMBIGUOUS_ENTITY_EVIDENCE"], "", evidence
    return "SUPPORTING_INFORMATION", 0.66, ["INSUFFICIENT_PERMANENT_ENTITY_EVIDENCE"], "", evidence


def robot_allowed(url: str, user_agent: str, cache: dict[str, RobotFileParser | None], timeout: int) -> bool:
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in cache:
        parser = RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            if requests is None:
                cache[root] = None
            else:
                response = requests.get(
                    parser.url,
                    timeout=timeout,
                    headers={"User-Agent": user_agent},
                )
                if response.status_code < 400:
                    parser.parse(response.text.splitlines())
                    cache[root] = parser
                else:
                    cache[root] = None
        except Exception:
            cache[root] = None
    parser = cache[root]
    return True if parser is None else parser.can_fetch(user_agent, url)


def fetch_target(
    queue_row: Mapping[str, Any],
    output_dir: Path,
    config: Mapping[str, Any],
    session: Any,
    robots_cache: dict[str, RobotFileParser | None],
) -> dict[str, Any]:
    url = first_value(queue_row, "target_url", "normalized_target_url")
    result: dict[str, Any] = {
        **dict(queue_row),
        "crawl_depth": 0,
        "crawl_started_at": utc_now(),
        "crawl_status": "FAILED",
        "http_status": "0",
        "final_url": url,
        "content_type": "",
        "bytes_received": "0",
        "snapshot_path": "",
        "fetched_title": "",
        "page_title": "",
        "text_source": "",
        "text_excerpt": "",
        "master_evidence_categories": "",
        "fetched_classification": "BROKEN_OFFICIAL_LINK",
        "fetched_confidence": "0.0000",
        "fetched_reasons": "",
        "inferred_entity_type": "",
        "crawl_error": "",
    }
    if requests is None or BeautifulSoup is None:
        result["crawl_error"] = "Missing requests or beautifulsoup4 dependency"
        return result
    if not is_internal_html(url, config):
        result["crawl_error"] = "Target is outside the allowed DST HTML scope"
        return result

    timeout = safe_int(config.get("request_timeout_seconds"), 30)
    user_agent = collapse_ws(config.get("user_agent"))
    if not robot_allowed(url, user_agent, robots_cache, timeout):
        result["crawl_error"] = "ROBOTS_DENIED"
        result["fetched_classification"] = "BROKEN_OFFICIAL_LINK"
        return result

    try:
        response = session.get(
            url,
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            allow_redirects=True,
            stream=True,
        )
        max_bytes = safe_int(config.get("maximum_response_bytes"), 5_000_000)
        chunks: list[bytes] = []
        received = 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise ValueError(f"Response exceeds maximum_response_bytes={max_bytes}")
            chunks.append(chunk)
        body = b"".join(chunks)
        content_type = response.headers.get("Content-Type", "")
        final_url = str(response.url)
        result.update({
            "http_status": str(response.status_code),
            "final_url": final_url,
            "content_type": content_type,
            "bytes_received": str(len(body)),
        })

        title = ""
        text = ""
        text_source = ""
        if response.status_code < 400 and "html" in lower(content_type):
            title, text, text_source = extract_page(body, config)
        cls, confidence, reasons, entity_type, evidence = classify_fetched(
            final_url, title, text, response.status_code, content_type, config
        )
        snapshots = output_dir / "snapshots" / "html"
        snapshots.mkdir(parents=True, exist_ok=True)
        snapshot_name = stable_id("dst_calibrated_snapshot", normalize_url(final_url, config)) + ".html.gz"
        snapshot_path = snapshots / snapshot_name
        with gzip.open(snapshot_path, "wb") as handle:
            handle.write(body)
        result.update({
            "crawl_status": "FETCHED",
            "fetched_at": utc_now(),
            "snapshot_path": str(snapshot_path.relative_to(output_dir.parent.parent.parent.parent)),
            "fetched_title": title,
            "page_title": title,
            "text_source": text_source,
            "text_excerpt": text[:safe_int(config.get("maximum_excerpt_length"), 1_000)],
            "master_evidence_categories": ";".join(evidence),
            "fetched_classification": cls,
            "fetched_confidence": f"{confidence:.4f}",
            "fetched_reasons": ";".join(reasons),
            "inferred_entity_type": entity_type,
        })
    except Exception as exc:
        result["crawl_error"] = f"{type(exc).__name__}: {exc}"
    return result


def provisional_candidate(row: Mapping[str, Any], entity_type: str, config: Mapping[str, Any]) -> dict[str, Any]:
    name = first_value(row, "fetched_title", "page_title", "proposed_name")
    url = first_value(row, "final_url", "target_url")
    return {
        "provisional_entity_id": stable_id(f"dst_possible_new_{entity_type.casefold()}", normalize_url(url, config), name),
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "proposed_canonical_name": name,
        "provisional_entity_type": entity_type,
        "official_source_url": url,
        "source_page_title": name,
        "source_calibration_id": first_value(row, "calibration_id"),
        "source_crawl_queue_id": first_value(row, "crawl_queue_id"),
        "source_classification": first_value(row, "fetched_classification"),
        "source_confidence": first_value(row, "fetched_confidence"),
        "master_evidence_categories": first_value(row, "master_evidence_categories"),
        "identity_state": "PROVISIONAL_NOT_LOCKED",
        "identity_locked": "0",
        "review_status": "REQUIRES_V3_4_0_4_CURATION",
        "discovered_at": utc_now(),
    }


def process(
    contexts: Sequence[Mapping[str, Any]],
    input_review: Sequence[Mapping[str, Any]],
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    run_crawl: bool = False,
    output_dir: Path | None = None,
    max_targets: int = 0,
    existing_crawled: Sequence[Mapping[str, Any]] = (),
    fetcher: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> Result:
    scores: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    closures: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    final_context: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    unresolved_rows: list[Mapping[str, Any]] = []
    for row in contexts:
        classification = upper(first_value(row, "final_gap_classification", "offline_classification", "gap_classification"))
        if classification == "UNRESOLVED" or not classification:
            unresolved_rows.append(row)
        else:
            final_context.append({**dict(row), "final_gap_classification": classification, "selective_crawl_required": "0"})

    for row in unresolved_rows:
        scored = score_target(row, config)
        scores.append(scored)
        decision = first_value(scored, "calibrated_decision")
        cls = first_value(scored, "calibrated_classification")
        if decision.startswith("SELECTIVE_CRAWL"):
            queued = {
                **scored,
                "crawl_queue_id": stable_id(
                    "dst_calibrated_queue",
                    normalize_url(first_value(scored, "target_url", "normalized_target_url"), config),
                ),
                "crawl_depth": 0,
                "crawl_status": "QUEUED",
                "crawl_reason": first_value(scored, "score_reasons"),
            }
            queue.append(queued)
        elif cls == "MANUAL_ENTITY_REVIEW":
            manual_row = {**scored, "manual_review_reason": "CALIBRATED_ENTITY_POSSIBILITY_REQUIRES_CURATION"}
            manual.append(manual_row)
            final_context.append({
                **dict(row),
                "final_gap_classification": "MANUAL_ENTITY_REVIEW",
                "classification_confidence": first_value(scored, "calibrated_confidence"),
                "classification_reasons": first_value(scored, "score_reasons", "triage_reasons"),
                "selective_crawl_required": "0",
            })
        else:
            closures.append(scored)
            final_context.append({
                **dict(row),
                "final_gap_classification": cls,
                "classification_confidence": first_value(scored, "calibrated_confidence"),
                "classification_reasons": first_value(scored, "triage_reasons", "score_reasons"),
                "selective_crawl_required": "0",
            })
        audit.append({
            "audit_id": stable_id("dst_calibration_audit", first_value(row, "target_url", "source_url")),
            "audit_type": "UNRESOLVED_TARGET_CALIBRATION",
            "record_url": first_value(row, "target_url", "source_url"),
            "record_name": first_value(row, "proposed_name", "proposed_canonical_name"),
            "decision": decision,
            "classification": cls,
            "score": first_value(scored, "calibrated_score"),
            "reasons": first_value(scored, "triage_reasons", "score_reasons"),
            "created_at": utc_now(),
        })

    max_queue = safe_int(config.get("maximum_selective_queue_size"), 20)
    queue.sort(key=lambda row: (-safe_int(row.get("calibrated_score")), first_value(row, "proposed_name")))
    if len(queue) > max_queue:
        overflow = queue[max_queue:]
        queue = queue[:max_queue]
        for row in overflow:
            manual.append({**row, "manual_review_reason": "QUEUE_CAP_OVERFLOW"})
            final_context.append({
                **dict(row),
                "final_gap_classification": "MANUAL_ENTITY_REVIEW",
                "classification_confidence": "0.5000",
                "classification_reasons": "QUEUE_CAP_OVERFLOW",
                "selective_crawl_required": "0",
            })

    queue_urls = {normalize_url(first_value(row, "target_url"), config) for row in queue}
    crawled = [
        dict(row)
        for row in existing_crawled
        if normalize_url(first_value(row, "target_url", "final_url"), config) in queue_urls
        and first_value(row, "crawl_status") == "FETCHED"
    ]
    done_urls = {normalize_url(first_value(row, "target_url", "final_url"), config) for row in crawled}

    if run_crawl and queue:
        remaining = [row for row in queue if normalize_url(first_value(row, "target_url"), config) not in done_urls]
        selected = remaining[:max_targets] if max_targets > 0 else remaining
        if fetcher:
            crawled.extend(dict(fetcher(row)) for row in selected)
        else:
            if requests is None or output_dir is None:
                raise RuntimeError("requests/beautifulsoup4 and output_dir are required")
            session = requests.Session()
            robots_cache: dict[str, RobotFileParser | None] = {}
            for index, row in enumerate(selected):
                crawled.append(fetch_target(row, output_dir, config, session, robots_cache))
                if index + 1 < len(selected):
                    time.sleep(safe_float(config.get("delay_seconds"), 1.0))

    crawled_by_url = {
        normalize_url(first_value(row, "target_url", "final_url"), config): row
        for row in crawled
        if first_value(row, "crawl_status") == "FETCHED"
    }
    new_schemes: list[dict[str, Any]] = []
    new_programmes: list[dict[str, Any]] = []

    for queued in queue:
        normalized = normalize_url(first_value(queued, "target_url"), config)
        fetched = crawled_by_url.get(normalized)
        original_context = {
            key: value
            for key, value in queued.items()
            if key not in {"calibrated_classification", "calibrated_decision"}
        }
        if fetched is None:
            final_context.append({
                **original_context,
                "final_gap_classification": "UNRESOLVED",
                "classification_confidence": first_value(queued, "calibrated_confidence"),
                "classification_reasons": first_value(queued, "score_reasons"),
                "selective_crawl_required": "1",
            })
            continue

        cls = first_value(fetched, "fetched_classification")
        confidence = first_value(fetched, "fetched_confidence")
        reasons = first_value(fetched, "fetched_reasons")
        if cls == "POSSIBLE_NEW_SCHEME":
            new_schemes.append(provisional_candidate(fetched, "SCHEME", config))
        elif cls == "POSSIBLE_NEW_PROGRAMME":
            new_programmes.append(provisional_candidate(fetched, "PROGRAMME", config))
        elif cls == "MANUAL_ENTITY_REVIEW":
            manual.append({**dict(fetched), "manual_review_reason": "FETCHED_ENTITY_EVIDENCE_REQUIRES_CURATION"})
        final_context.append({
            **original_context,
            "final_gap_classification": cls,
            "classification_confidence": confidence,
            "classification_reasons": reasons,
            "selective_crawl_required": "0",
            "selective_crawl_status": first_value(fetched, "crawl_status"),
            "selective_crawl_http_status": first_value(fetched, "http_status"),
            "selective_crawl_final_url": first_value(fetched, "final_url"),
        })

    preserved_review = [
        dict(row)
        for row in input_review
        if upper(first_value(row, "review_type")) not in {"GAP_UNRESOLVED_OFFLINE", "GAP_UNRESOLVED"}
    ]
    final_review = list(preserved_review)
    for row in manual:
        final_review.append({
            "review_id": stable_id("dst_calibration_review", first_value(row, "target_url", "final_url")),
            "review_type": "CALIBRATED_MANUAL_ENTITY_REVIEW",
            "proposed_name": first_value(row, "proposed_name", "fetched_title", "page_title"),
            "confidence": first_value(row, "fetched_confidence", "calibrated_confidence"),
            "review_flags": first_value(row, "manual_review_reason"),
            "evidence": first_value(row, "fetched_reasons", "score_reasons", "triage_reasons"),
            "source_url": first_value(row, "final_url", "target_url"),
            "review_status": "PENDING",
            "created_at": utc_now(),
        })

    final_schemes = [dict(row) for row in schemes] + new_schemes
    final_programmes = [dict(row) for row in programmes] + new_programmes
    return Result(
        scores=scores,
        queue=queue,
        closures=closures,
        crawled=crawled,
        new_schemes=new_schemes,
        new_programmes=new_programmes,
        manual_candidates=manual,
        final_context=final_context,
        final_review=final_review,
        final_schemes=final_schemes,
        final_programmes=final_programmes,
        audit=audit,
    )


def validate(
    result: Result,
    input_context: Sequence[Mapping[str, Any]],
    input_review: Sequence[Mapping[str, Any]],
    schemes: Sequence[Mapping[str, Any]],
    programmes: Sequence[Mapping[str, Any]],
    summary_input: Mapping[str, Any],
    config: Mapping[str, Any],
    run_crawl: bool,
    max_targets: int,
) -> dict[str, Any]:
    final_classes = [upper(first_value(row, "final_gap_classification")) for row in result.final_context]
    invalid_classes = sorted({item for item in final_classes if item not in ALLOWED_FINAL_CLASSES})
    unresolved = sum(1 for item in final_classes if item == "UNRESOLVED")
    total = len(input_context)
    unresolved_rate = unresolved / total if total else 0.0
    resolution_rate = 1.0 - unresolved_rate if total else 1.0

    queue_urls = {normalize_url(first_value(row, "target_url"), config) for row in result.queue}
    processed_urls = {
        normalize_url(first_value(row, "target_url", "final_url"), config)
        for row in result.crawled
        if first_value(row, "crawl_status") == "FETCHED"
    }
    processed_queue_count = len(queue_urls & processed_urls)

    created_rows = [*result.new_schemes, *result.new_programmes]
    forbidden_created_fields = sorted({field for row in created_rows for field in row if field in FORBIDDEN_IDENTITY_FIELDS})
    identity_locked = any(first_value(row, "identity_locked") not in {"", "0", "false", "False"} for row in created_rows)

    contamination_terms = config.get("call_terms", [])
    call_contamination_rows = []
    for row in [*result.final_schemes, *result.final_programmes]:
        combined = " ".join([
            first_value(row, "proposed_canonical_name", "scheme_name", "programme_name"),
            first_value(row, "official_source_url", "final_url", "source_url"),
        ])
        if contains_any(combined, contamination_terms):
            call_contamination_rows.append(first_value(row, "provisional_entity_id", "master_id", "official_source_url"))

    checks = {
        "all_input_context_rows_preserved": len(result.final_context) == total,
        "all_final_classifications_valid": not invalid_classes,
        "selective_crawl_depth_zero": all(safe_int(row.get("crawl_depth"), 0) == 0 for row in result.queue),
        "selective_queue_within_limit": len(result.queue) <= safe_int(config.get("maximum_selective_queue_size"), 20),
        "all_queue_targets_processed": (not result.queue) or (run_crawl and processed_queue_count == len(result.queue)),
        "unresolved_rate_within_limit": unresolved_rate <= safe_float(config.get("maximum_final_unresolved_rate"), 0.05),
        "gap_resolution_rate_met": resolution_rate >= safe_float(config.get("minimum_gap_resolution_rate"), 0.95),
        "no_call_contamination": not call_contamination_rows,
        "no_forbidden_identity_fields_created": not forbidden_created_fields,
        "identity_locked": identity_locked,
        "existing_scheme_inventory_preserved": len(result.final_schemes) >= len(schemes),
        "existing_programme_inventory_preserved": len(result.final_programmes) >= len(programmes),
    }
    validation_passed = all(
        value
        for key, value in checks.items()
        if key != "identity_locked"
    ) and checks["identity_locked"] is False

    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "validated_at": utc_now(),
        "mode": "SELECTIVE_CRAWL" if run_crawl else "PREPARE_ONLY",
        "counts": {
            "input_gap_context_rows": total,
            "input_review_rows": len(input_review),
            "input_corrected_schemes": len(schemes),
            "input_corrected_programmes": len(programmes),
            "unresolved_targets_scored": len(result.scores),
            "offline_closures": len(result.closures),
            "selective_crawl_queue": len(result.queue),
            "processed_selective_targets": processed_queue_count,
            "manual_entity_reviews": len(result.manual_candidates),
            "possible_new_schemes": len(result.new_schemes),
            "possible_new_programmes": len(result.new_programmes),
            "final_corrected_schemes": len(result.final_schemes),
            "final_corrected_programmes": len(result.final_programmes),
            "final_unresolved": unresolved,
        },
        "rates": {
            "final_unresolved_rate": round(unresolved_rate, 6),
            "gap_resolution_rate": round(resolution_rate, 6),
            "maximum_final_unresolved_rate": safe_float(config.get("maximum_final_unresolved_rate"), 0.05),
            "minimum_gap_resolution_rate": safe_float(config.get("minimum_gap_resolution_rate"), 0.95),
        },
        "classification_counts": dict(Counter(final_classes)),
        "checks": checks,
        "quality": {
            "invalid_final_classifications": invalid_classes,
            "call_contamination": len(call_contamination_rows),
            "call_contamination_rows": call_contamination_rows,
            "forbidden_identity_fields_created": forbidden_created_fields,
        },
        "upstream_summary": {
            "service_version": summary_input.get("service_version", ""),
            "ready_for_v3_4_0_4": summary_input.get("ready_for_v3_4_0_4", False),
        },
        "calibration_validation_passed": validation_passed,
        "ready_for_v3_4_0_4": validation_passed,
        "partial_run": bool(max_targets > 0 and processed_queue_count < len(result.queue)),
    }


def build_summary(
    result: Result,
    validation: Mapping[str, Any],
    paths: Mapping[str, Path],
    run_crawl: bool,
) -> dict[str, Any]:
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "generated_at": utc_now(),
        "mode": "SELECTIVE_CRAWL" if run_crawl else "PREPARE_ONLY",
        "network_access_used": bool(run_crawl),
        "counts": dict(validation.get("counts", {})),
        "rates": dict(validation.get("rates", {})),
        "classification_counts": dict(validation.get("classification_counts", {})),
        "calibration_validation_passed": bool(validation.get("calibration_validation_passed", False)),
        "ready_for_v3_4_0_4": bool(validation.get("ready_for_v3_4_0_4", False)),
        "outputs": {
            "scores": SCORES_OUTPUT,
            "selective_queue": QUEUE_OUTPUT,
            "offline_closures": LOW_VALUE_OUTPUT,
            "crawled_targets": CRAWLED_OUTPUT,
            "possible_new_schemes": NEW_SCHEMES_OUTPUT,
            "possible_new_programmes": NEW_PROGRAMMES_OUTPUT,
            "manual_entity_reviews": MANUAL_REVIEW_OUTPUT,
            "final_gap_context": FINAL_CONTEXT_OUTPUT,
            "final_review_queue": FINAL_REVIEW_OUTPUT,
            "final_corrected_schemes": FINAL_SCHEMES_OUTPUT,
            "final_corrected_programmes": FINAL_PROGRAMMES_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
        "output_directory": str(paths["output_dir"]),
    }


def write_outputs(output_dir: Path, result: Result, validation: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    write_csv(output_dir / SCORES_OUTPUT, result.scores)
    write_csv(output_dir / QUEUE_OUTPUT, result.queue)
    write_csv(output_dir / LOW_VALUE_OUTPUT, result.closures)
    write_csv(output_dir / CRAWLED_OUTPUT, result.crawled)
    write_csv(output_dir / NEW_SCHEMES_OUTPUT, result.new_schemes)
    write_csv(output_dir / NEW_PROGRAMMES_OUTPUT, result.new_programmes)
    write_csv(output_dir / MANUAL_REVIEW_OUTPUT, result.manual_candidates)
    write_csv(output_dir / FINAL_CONTEXT_OUTPUT, result.final_context)
    write_csv(output_dir / FINAL_REVIEW_OUTPUT, result.final_review)
    write_csv(output_dir / FINAL_SCHEMES_OUTPUT, result.final_schemes)
    write_csv(output_dir / FINAL_PROGRAMMES_OUTPUT, result.final_programmes)
    write_csv(output_dir / AUDIT_OUTPUT, result.audit)
    write_json(output_dir / VALIDATION_OUTPUT, validation)
    write_json(output_dir / SUMMARY_OUTPUT, summary)


def resolve_paths(project_root: Path) -> dict[str, Path]:
    input_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_3"
    output_dir = project_root / "data" / "departments" / "dst" / "v3_4_0_3_3_1"
    return {
        "project_root": project_root,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "context": input_dir / CONTEXT_INPUT,
        "review": input_dir / REVIEW_INPUT,
        "schemes": input_dir / SCHEMES_INPUT,
        "programmes": input_dir / PROGRAMMES_INPUT,
        "summary_input": input_dir / SUMMARY_INPUT,
        "user_calibration": input_dir / USER_CALIBRATION_INPUT,
        "existing_crawled": output_dir / CRAWLED_OUTPUT,
    }


def merge_user_calibration(
    contexts: Sequence[Mapping[str, Any]],
    calibrated: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not calibrated:
        return [dict(row) for row in contexts]
    lookup = {
        normalize_url(first_value(row, "target_url", "normalized_target_url", "source_url"), config): row
        for row in calibrated
    }
    merged: list[dict[str, Any]] = []
    for row in contexts:
        key = normalize_url(first_value(row, "target_url", "normalized_target_url", "source_url"), config)
        extra = lookup.get(key, {})
        combined = dict(row)
        for source, target in [
            ("CalibratedScore", "max_relevance_score"),
            ("calibrated_score", "max_relevance_score"),
            ("CalibratedReasons", "user_calibration_reasons"),
            ("calibrated_reasons", "user_calibration_reasons"),
        ]:
            value = first_value(extra, source)
            if value and not first_value(combined, target):
                combined[target] = value
        merged.append(combined)
    return merged


def run_pipeline(
    project_root: Path,
    config: Mapping[str, Any],
    dry_run: bool = False,
    prepare_only: bool = False,
    run_selective_crawl: bool = False,
    max_targets: int = 0,
) -> tuple[Result, dict[str, Any]]:
    paths = resolve_paths(project_root)
    context = read_csv(paths["context"])
    review = read_csv(paths["review"])
    schemes = read_csv(paths["schemes"])
    programmes = read_csv(paths["programmes"])
    summary_input = read_json(paths["summary_input"], required=False)
    user_calibration = read_csv(paths["user_calibration"], required=False)
    context = merge_user_calibration(context, user_calibration, config)
    existing_crawled = read_csv(paths["existing_crawled"], required=False)

    if dry_run:
        preview = process(context, review, schemes, programmes, config, run_crawl=False)
        payload = {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "inputs": {
                "gap_context_rows": len(context),
                "unresolved_targets": len(preview.scores),
                "corrected_schemes": len(schemes),
                "corrected_programmes": len(programmes),
                "review_rows": len(review),
                "previously_crawled_targets": len(existing_crawled),
            },
            "preview": {
                "offline_closures": len(preview.closures),
                "selective_crawl_queue": len(preview.queue),
                "manual_entity_reviews": len(preview.manual_candidates),
            },
            "files_written": False,
            "network_access_used": False,
            "ready_for_v3_4_0_4": False,
        }
        return preview, payload

    run_crawl = run_selective_crawl and not prepare_only
    result = process(
        context,
        review,
        schemes,
        programmes,
        config,
        run_crawl=run_crawl,
        output_dir=paths["output_dir"],
        max_targets=max_targets,
        existing_crawled=existing_crawled,
    )
    validation = validate(
        result, context, review, schemes, programmes, summary_input, config, run_crawl, max_targets
    )
    summary = build_summary(result, validation, paths, run_crawl)
    write_outputs(paths["output_dir"], result, validation, summary)
    return result, summary


def self_test() -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    contexts = [
        {"target_url": "https://dst.gov.in/national-missions", "normalized_target_url": "https://dst.gov.in/national-missions", "proposed_name": "National Missions", "final_gap_classification": "UNRESOLVED", "unique_source_pages": "416", "main_content_occurrences": "0", "max_relevance_score": "75"},
        {"target_url": "https://dst.gov.in/st-system-india/science-and-technology-policy-2013", "normalized_target_url": "https://dst.gov.in/st-system-india/science-and-technology-policy-2013", "proposed_name": "Science, Technology & Innovation Policy 2013", "final_gap_classification": "UNRESOLVED", "unique_source_pages": "416", "main_content_occurrences": "0", "max_relevance_score": "75"},
        {"target_url": "https://dst.gov.in/pressrelease/example", "normalized_target_url": "https://dst.gov.in/pressrelease/example", "proposed_name": "Research breakthrough press release", "final_gap_classification": "UNRESOLVED", "unique_source_pages": "1", "main_content_occurrences": "0", "max_relevance_score": "55"},
        {"target_url": "https://dst.gov.in/anusandhan-national-research-foundation-anrf", "normalized_target_url": "https://dst.gov.in/anusandhan-national-research-foundation-anrf", "proposed_name": "Anusandhan National Research Foundation (ANRF)", "final_gap_classification": "UNRESOLVED", "unique_source_pages": "1", "main_content_occurrences": "0", "max_relevance_score": "55"},
        {"target_url": "https://dst.gov.in/science-wings-abroad-0", "normalized_target_url": "https://dst.gov.in/science-wings-abroad-0", "proposed_name": "Science Wings Abroad", "final_gap_classification": "UNRESOLVED", "unique_source_pages": "1", "main_content_occurrences": "0", "max_relevance_score": "0"},
        {"target_url": "https://dst.gov.in/already-resolved", "normalized_target_url": "https://dst.gov.in/already-resolved", "proposed_name": "Already Resolved", "final_gap_classification": "SUPPORTING_INFORMATION"},
    ]

    def fake_fetch(queue_row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            **dict(queue_row),
            "crawl_status": "FETCHED",
            "http_status": "200",
            "final_url": queue_row["target_url"],
            "content_type": "text/html",
            "fetched_title": "Science Wings Abroad Programme",
            "page_title": "Science Wings Abroad Programme",
            "fetched_classification": "POSSIBLE_NEW_PROGRAMME",
            "fetched_confidence": "0.9200",
            "fetched_reasons": "PROGRAMME_TITLE_SIGNAL;MASTER_EVIDENCE",
            "master_evidence_categories": "objective;eligibility;authority",
            "inferred_entity_type": "PROGRAMME",
        }

    schemes = [{"provisional_entity_id": "s1", "proposed_canonical_name": "Existing Scheme", "official_source_url": "https://dst.gov.in/existing-scheme"}]
    programmes = [{"provisional_entity_id": "p1", "proposed_canonical_name": "Existing Programme", "official_source_url": "https://dst.gov.in/existing-programme"}]
    review = [{"review_type": "PROVISIONAL_ENTITY_QUALITY", "provisional_entity_id": "q1", "proposed_name": "Ambiguous"}]
    result = process(contexts, review, schemes, programmes, config, True, Path("."), 0, fetcher=fake_fetch)
    validation = validate(
        result,
        contexts,
        review,
        schemes,
        programmes,
        {"counts": {"input_unique_gap_count": 6, "input_duplicate_gap_occurrences": 0}},
        config,
        True,
        0,
    )
    classes = {first_value(row, "proposed_name"): first_value(row, "final_gap_classification") for row in result.final_context}
    tests = {
        "sitewide_mission_closed_as_category": classes.get("National Missions") == "CATEGORY_OR_INDEX_PAGE",
        "policy_closed_as_document": classes.get("Science, Technology & Innovation Policy 2013") == "POLICY_REPORT_OR_DOCUMENT",
        "pressrelease_closed_as_news": classes.get("Research breakthrough press release") == "NEWS_EVENT_OR_RECRUITMENT",
        "foundation_closed_as_institution": classes.get("Anusandhan National Research Foundation (ANRF)") == "INSTITUTION_OR_RESOURCE",
        "named_initiative_queued": len(result.queue) == 1,
        "selective_fetch_created_programme": len(result.new_programmes) == 1,
        "existing_inventory_preserved": len(result.final_schemes) == 1 and len(result.final_programmes) == 2,
        "quality_review_preserved": any(first_value(row, "review_type") == "PROVISIONAL_ENTITY_QUALITY" for row in result.final_review),
        "no_call_contamination": validation["quality"]["call_contamination"] == 0,
        "no_identity_lock": validation["checks"]["identity_locked"] is False,
    }
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "tests": tests,
        "self_test_passed": all(tests.values()),
        "preview_counts": {
            "scores": len(result.scores),
            "queue": len(result.queue),
            "closures": len(result.closures),
            "new_programmes": len(result.new_programmes),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-selective-crawl", action="store_true")
    parser.add_argument("--max-targets", type=int, default=0)
    parser.add_argument("--strict", action="store_true")
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
            args.project_root.resolve(),
            config,
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
