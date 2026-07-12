#!/usr/bin/env python3
"""
SSIP v3.4.0.1.1 — DST Snapshot Text Recovery and Classification-Ready Export Hotfix

This hotfix is intentionally non-destructive:
* It never crawls the network.
* It reads v3.4.0.1 CSV exports and compressed HTML snapshots.
* It writes enriched outputs to a separate v3_4_0_1_1 directory.
* It does not create canonical scheme identities or promote call titles to schemes.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from bs4 import BeautifulSoup, Tag
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: beautifulsoup4. Install with: "
        "python -m pip install beautifulsoup4"
    ) from exc

VERSION = "3.4.0.1.1"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"
EMPTY_TEXT_SHA256 = hashlib.sha256(b"").hexdigest()

PAGE_INPUT = "dst_crawled_pages_v3_4_0_1.csv"
DOCUMENT_INPUT = "dst_discovered_documents_v3_4_0_1.csv"
EXTERNAL_INPUT = "dst_external_official_links_v3_4_0_1.csv"
LINK_INPUT = "dst_link_graph_v3_4_0_1.csv"

PAGE_OUTPUT = "dst_crawled_pages_enriched_v3_4_0_1_1.csv"
DOCUMENT_OUTPUT = "dst_documents_enriched_v3_4_0_1_1.csv"
EXTERNAL_OUTPUT = "dst_external_links_enriched_v3_4_0_1_1.csv"
DOMAIN_OUTPUT = "dst_external_domains_v3_4_0_1_1.csv"
CALL_AUDIT_OUTPUT = "dst_call_pattern_audit_v3_4_0_1_1.csv"
FAILURE_OUTPUT = "dst_text_extraction_failures_v3_4_0_1_1.csv"
VALIDATION_OUTPUT = "dst_schema_validation_v3_4_0_1_1.json"
SUMMARY_OUTPUT = "dst_hotfix_summary_v3_4_0_1_1.json"

MAIN_SELECTORS = (
    "main",
    "[role='main']",
    "article",
    ".region-content",
    ".main-content",
    "#main-content",
    "#content",
    ".node__content",
    ".node-content",
    ".field--name-body",
    ".field-name-body",
    ".view-content",
    ".page-content",
    ".content-area",
    ".content",
)

NOISE_SELECTORS = (
    "script", "style", "noscript", "template", "svg", "canvas", "form",
    "nav", "header", "footer", "aside",
    ".breadcrumb", ".breadcrumbs", ".social-media", ".social-links",
    ".accessibility", ".skip-link", ".language-switcher",
    ".region-header", ".region-footer", ".region-sidebar-first",
    ".region-sidebar-second", ".sidebar", ".menu", ".pager",
    ".tabs", ".contextual", ".block-search", ".search-form",
    "[aria-label='breadcrumb']", "[role='navigation']", "[role='banner']",
    "[role='contentinfo']",
)

BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd",
    "blockquote", "caption", "th", "td", "pre",
}

SOCIAL_DOMAINS = {
    "facebook.com", "www.facebook.com", "twitter.com", "www.twitter.com",
    "x.com", "www.x.com", "instagram.com", "www.instagram.com",
    "linkedin.com", "www.linkedin.com", "youtube.com", "www.youtube.com",
    "youtu.be", "telegram.me", "t.me",
}
TECHNICAL_DOMAINS = {
    "google.com", "www.google.com", "fonts.googleapis.com", "gstatic.com",
    "www.gstatic.com", "ajax.googleapis.com", "schema.org", "w3.org",
    "www.w3.org", "addthis.com", "www.addthis.com",
}
DST_RELATED_DOMAINS = {
    "onlinedst.gov.in", "www.onlinedst.gov.in", "dst.gov.in", "www.dst.gov.in",
}

BROKEN_URL_REPLACEMENTS = {
    "https://dst.gov.in/promotion-university-research-and-scientific-excellencepurse": {
        "status": "BROKEN_URL_REPLACED",
        "replacement_url": "https://dst.gov.in/promotion-university-research-and-scientific-excellence-purse",
        "note": "Malformed legacy PURSE slug; separator before 'purse' was missing.",
    },
    "https://dst.gov.in/sites/default/files/agriculture.htm": {
        "status": "BROKEN_LEGACY_RESOURCE",
        "replacement_url": "",
        "note": "Legacy static resource retained as evidence; must not create a scheme identity.",
    },
}


@dataclass(frozen=True)
class ExtractionResult:
    title: str
    main_text: str
    text_excerpt: str
    word_count: int
    main_text_length: int
    text_sha256: str
    status: str
    method: str
    selected_selector: str
    candidate_count: int
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_url(url: str) -> str:
    raw = collapse_ws(url)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if parts.scheme.lower() not in {"http", "https"}:
        return raw
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not host:
        return raw
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in {"fbclid", "gclid", "ref", "source", "campaign"}:
            continue
        kept.append((key, value))
    query = urlencode(sorted(kept))
    return urlunsplit((scheme, netloc, path, query, ""))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required input not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = [dict(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not materialized:
        atomic_write_text(path, "")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in materialized:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    os.replace(tmp, path)


def decode_html(payload: bytes, charset: str = "") -> str:
    attempts = [charset.strip(), "utf-8", "utf-8-sig", "windows-1252", "latin-1"]
    seen: set[str] = set()
    for encoding in attempts:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _remove_noise(root: Tag | BeautifulSoup) -> None:
    for selector in NOISE_SELECTORS:
        for node in list(root.select(selector)):
            node.decompose()


def _structured_text(root: Tag | BeautifulSoup) -> str:
    lines: list[str] = []
    seen_consecutive = ""
    for node in root.find_all(BLOCK_TAGS):
        text = collapse_ws(node.get_text(" ", strip=True))
        if not text or text == seen_consecutive:
            continue
        # Skip tiny UI fragments but preserve meaningful list markers and headings.
        if len(text) <= 2 and not re.search(r"\d", text):
            continue
        lines.append(text)
        seen_consecutive = text
    if not lines:
        return collapse_ws(root.get_text(" ", strip=True))
    # Deduplicate exact repeated lines globally while preserving order.
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(line)
    return "\n".join(output).strip()


def _candidate_score(node: Tag, text: str) -> float:
    text_len = len(text)
    words = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
    paragraphs = len(node.find_all("p"))
    headings = len(node.find_all(re.compile(r"^h[1-6]$")))
    lists = len(node.find_all("li"))
    links = node.find_all("a")
    link_text_len = sum(len(collapse_ws(a.get_text(" ", strip=True))) for a in links)
    link_density = (link_text_len / text_len) if text_len else 1.0
    score = (
        text_len
        + min(words, 3000) * 1.5
        + paragraphs * 90
        + headings * 120
        + min(lists, 100) * 25
        - link_density * text_len * 0.75
    )
    # Very short shell containers must not beat actual content elsewhere.
    if text_len < 80:
        score -= 1000
    return score


def extract_snapshot_text(payload: bytes, charset: str = "") -> ExtractionResult:
    try:
        html = decode_html(payload, charset)
        soup = BeautifulSoup(html, "html.parser")
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = collapse_ws(h1.get_text(" ", strip=True))
        if not title and soup.title:
            title = collapse_ws(soup.title.get_text(" ", strip=True))

        _remove_noise(soup)
        candidates: list[tuple[float, str, str]] = []
        seen_nodes: set[int] = set()
        for selector in MAIN_SELECTORS:
            for node in soup.select(selector):
                node_id = id(node)
                if node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                text = _structured_text(node)
                candidates.append((_candidate_score(node, text), selector, text))

        body = soup.body or soup
        body_text = _structured_text(body)
        body_score = _candidate_score(body, body_text)
        candidates.append((body_score, "body_fallback", body_text))
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, selector, text = candidates[0]

        # If a selected region is suspiciously short, force body fallback.
        if len(text) < 80 and len(body_text) > len(text):
            selector = "body_fallback"
            text = body_text

        text = text.strip()
        if not text:
            return ExtractionResult(
                title=title,
                main_text="",
                text_excerpt="",
                word_count=0,
                main_text_length=0,
                text_sha256=EMPTY_TEXT_SHA256,
                status="EMPTY_HTML",
                method="BEAUTIFULSOUP_REGION_SCORING",
                selected_selector=selector,
                candidate_count=len(candidates),
            )

        word_count = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
        status = "SUCCESS_BODY_FALLBACK" if selector == "body_fallback" else "SUCCESS_MAIN_CONTENT"
        return ExtractionResult(
            title=title,
            main_text=text,
            text_excerpt=text[:2000],
            word_count=word_count,
            main_text_length=len(text),
            text_sha256=stable_hash(text),
            status=status,
            method="BEAUTIFULSOUP_REGION_SCORING",
            selected_selector=selector,
            candidate_count=len(candidates),
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            title="",
            main_text="",
            text_excerpt="",
            word_count=0,
            main_text_length=0,
            text_sha256=EMPTY_TEXT_SHA256,
            status="PARSE_FAILED",
            method="BEAUTIFULSOUP_REGION_SCORING",
            selected_selector="",
            candidate_count=0,
            error=f"{type(exc).__name__}: {exc}"[:1000],
        )


def resolve_snapshot(input_dir: Path, snapshot_path: str) -> Path:
    raw = (snapshot_path or "").strip().replace("\\", os.sep)
    path = Path(raw)
    if path.is_absolute():
        return path
    return input_dir / path


def classify_call_pattern(title: str, main_text: str = "") -> str:
    title_low = collapse_ws(title).lower()
    text_low = collapse_ws(main_text[:4000]).lower()
    combined = f"{title_low} {text_low}"
    if re.search(r"\b(corrigendum|addendum|amendment)\b", combined):
        return "CORRIGENDUM_OR_ADDENDUM"
    if re.search(r"\b(last date|deadline|closing date).{0,60}\b(extended|extension)\b|\bextension of.{0,80}(date|deadline)", combined):
        return "DEADLINE_EXTENSION"
    if re.search(r"\b(result|results|selected|recommended|shortlisted)\b", title_low):
        return "RESULT_OR_SELECTION"
    if re.search(r"\bexpression of interest\b|\beoi\b", combined):
        return "EXPRESSION_OF_INTEREST"
    if re.search(r"\bapplications? (?:are )?invited\b|\binviting applications?\b", combined):
        return "APPLICATION_INVITATION"
    if re.search(r"\bcall for (?:project )?proposals?\b|\bcall for proposals?\b|\bjoint call\b|\bspecial call\b", combined):
        return "CALL_FOR_PROPOSALS"
    if re.search(r"\bwebinar\b|\bworkshop\b|\bconference\b", title_low):
        return "EVENT_RELATED"
    return "OTHER_CALL_PATTERN"


def derive_document_role(filename: str, anchor_text: str, source_url: str, role_hint: str) -> str:
    text = " ".join([filename, anchor_text, source_url, role_hint]).lower()
    if re.search(r"corrigendum|addendum|amendment", text):
        return "CORRIGENDUM"
    if re.search(r"extension|extended.*(?:date|deadline)|last.date", text):
        return "DEADLINE_EXTENSION"
    if re.search(r"result|selected|recommended|shortlist", text):
        return "RESULT"
    if re.search(r"guideline|manual|handbook|operational guideline", text):
        return "GUIDELINE"
    if re.search(r"application.form|application.format|proposal.format|proforma|template", text):
        return "APPLICATION_FORMAT"
    if re.search(r"sanction|sanctioned|release.order", text):
        return "SANCTION_ORDER"
    if re.search(r"annual.report|year.book", text):
        return "ANNUAL_REPORT"
    if re.search(r"office.memorandum|\bom\b", text):
        return "OFFICE_MEMORANDUM"
    if re.search(r"call|proposal|advertisement|announcement", text):
        return "CALL_DOCUMENT"
    if re.search(r"brochure|flyer|leaflet|booklet", text):
        return "BROCHURE_OR_FLYER"
    return "UNKNOWN_DOCUMENT"


def infer_year(*values: str) -> str:
    text = " ".join(values)
    matches = re.findall(r"(?<!\d)(20(?:0\d|1\d|2\d|3\d))(?!\d)", text)
    return matches[0] if matches else ""


def classify_external_domain(domain: str, existing_class: str = "") -> tuple[str, str]:
    d = domain.lower().strip(".")
    current = existing_class.upper().strip()
    if d in DST_RELATED_DOMAINS or d.endswith(".dst.gov.in"):
        return "DST_RELATED_PORTAL", "RECORD_AND_REVIEW"
    if d in SOCIAL_DOMAINS or any(d.endswith("." + x) for x in SOCIAL_DOMAINS):
        return "SOCIAL_MEDIA", "DO_NOT_CRAWL"
    if d in TECHNICAL_DOMAINS or any(d.endswith("." + x) for x in TECHNICAL_DOMAINS):
        return "TECHNICAL_LINK", "DO_NOT_CRAWL"
    if d.endswith(".gov.in") or d.endswith(".nic.in") or current in {"GOVERNMENT_PORTAL", "GOVERNMENT"}:
        return "GOVERNMENT_PORTAL", "RECORD_AND_REVIEW"
    if d.endswith(".ac.in") or d.endswith(".edu.in"):
        return "ACADEMIC_INSTITUTION", "RECORD_ONLY"
    if d.endswith(".gov") or ".gov." in d:
        return "INTERNATIONAL_GOVERNMENT", "RECORD_ONLY"
    if "apply" in d or "portal" in d or "epms" in d:
        return "APPLICATION_PORTAL", "RECORD_AND_REVIEW"
    return "UNCLASSIFIED_EXTERNAL", "RECORD_ONLY"


def enrich_pages(rows: list[dict[str, str]], input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in rows:
        output: dict[str, Any] = dict(row)
        output["page_title"] = row.get("title", "")
        output["discovered_from_url"] = row.get("parent_url", "")
        output["crawl_depth"] = row.get("depth", "")
        output["error_message"] = row.get("error", "")
        output["main_text"] = ""
        output["main_text_length"] = 0
        output["text_extraction_status"] = "NOT_ATTEMPTED"
        output["text_extraction_method"] = ""
        output["text_selected_selector"] = ""
        output["text_candidate_count"] = 0
        output["text_extraction_error"] = ""
        output["url_resolution_status"] = "CURRENT_OR_UNRESOLVED"
        output["replacement_url"] = ""
        output["url_resolution_note"] = ""

        final_url = normalize_url(row.get("final_url", ""))
        resolution = BROKEN_URL_REPLACEMENTS.get(final_url)
        if resolution:
            output["url_resolution_status"] = resolution["status"]
            output["replacement_url"] = resolution["replacement_url"]
            output["url_resolution_note"] = resolution["note"]

        status = safe_int(row.get("http_status"))
        content_type = row.get("content_type", "").lower()
        if not (200 <= status < 300):
            output["text_extraction_status"] = "HTTP_ERROR_PAGE"
            enriched.append(output)
            continue
        if "html" not in content_type:
            output["text_extraction_status"] = "UNSUPPORTED_CONTENT_TYPE"
            enriched.append(output)
            continue
        snapshot_path = resolve_snapshot(input_dir, row.get("snapshot_path", ""))
        if not snapshot_path.exists():
            output["text_extraction_status"] = "SNAPSHOT_MISSING"
            output["text_extraction_error"] = str(snapshot_path)
            failures.append({
                "page_id": row.get("page_id", ""),
                "final_url": row.get("final_url", ""),
                "snapshot_path": str(snapshot_path),
                "failure_type": "SNAPSHOT_MISSING",
                "error": "Snapshot file not found",
            })
            enriched.append(output)
            continue
        try:
            if snapshot_path.suffix.lower() == ".gz":
                with gzip.open(snapshot_path, "rb") as handle:
                    payload = handle.read()
            else:
                payload = snapshot_path.read_bytes()
        except Exception as exc:  # noqa: BLE001
            output["text_extraction_status"] = "DECOMPRESSION_FAILED"
            output["text_extraction_error"] = f"{type(exc).__name__}: {exc}"[:1000]
            failures.append({
                "page_id": row.get("page_id", ""),
                "final_url": row.get("final_url", ""),
                "snapshot_path": str(snapshot_path),
                "failure_type": "DECOMPRESSION_FAILED",
                "error": output["text_extraction_error"],
            })
            enriched.append(output)
            continue

        result = extract_snapshot_text(payload, row.get("charset", ""))
        output["page_title"] = row.get("title", "") or result.title
        output["main_text"] = result.main_text
        output["main_text_length"] = result.main_text_length
        output["text_excerpt"] = result.text_excerpt
        output["word_count"] = result.word_count
        output["text_sha256"] = result.text_sha256
        output["text_extraction_status"] = result.status
        output["text_extraction_method"] = result.method
        output["text_selected_selector"] = result.selected_selector
        output["text_candidate_count"] = result.candidate_count
        output["text_extraction_error"] = result.error
        if not result.status.startswith("SUCCESS"):
            failures.append({
                "page_id": row.get("page_id", ""),
                "final_url": row.get("final_url", ""),
                "snapshot_path": str(snapshot_path),
                "failure_type": result.status,
                "error": result.error,
            })
        enriched.append(output)
    return enriched, failures


def enrich_documents(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = dict(row)
        url = row.get("url", "")
        parsed = urlsplit(url)
        extension = row.get("extension", "") or Path(parsed.path).suffix.lower()
        item["document_url"] = url
        item["normalized_url"] = normalize_url(url)
        item["source_page_url"] = row.get("source_url", "")
        item["file_extension"] = extension.lower()
        item["document_role_hint"] = derive_document_role(
            row.get("filename", ""), row.get("anchor_text", ""),
            row.get("source_url", ""), row.get("role_hint", ""),
        )
        item["document_year"] = infer_year(row.get("filename", ""), row.get("anchor_text", ""), url)
        item["possible_call_document"] = "1" if item["document_role_hint"] in {
            "CALL_DOCUMENT", "DEADLINE_EXTENSION", "CORRIGENDUM", "RESULT", "APPLICATION_FORMAT"
        } else "0"
        item["possible_scheme_guideline"] = "1" if item["document_role_hint"] == "GUIDELINE" else "0"
        output.append(item)
    return output


def enrich_external_links(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    domain_urls: dict[str, set[str]] = defaultdict(set)
    domain_sources: dict[str, set[str]] = defaultdict(set)
    domain_occurrences: Counter[str] = Counter()
    domain_tier: dict[str, str] = {}
    domain_recommendation: dict[str, str] = {}

    for row in rows:
        item: dict[str, Any] = dict(row)
        url = row.get("external_url", "")
        normalized = normalize_url(url)
        domain = (urlsplit(normalized).hostname or "").lower()
        tier, recommendation = classify_external_domain(domain, row.get("authority_class", ""))
        item["normalized_external_url"] = normalized
        item["external_domain"] = domain
        item["authority_tier"] = tier
        item["crawl_recommendation"] = recommendation
        enriched.append(item)
        domain_occurrences[domain] += 1
        domain_urls[domain].add(normalized)
        domain_sources[domain].add(row.get("source_url", ""))
        domain_tier[domain] = tier
        domain_recommendation[domain] = recommendation

    domains: list[dict[str, Any]] = []
    for domain, count in domain_occurrences.most_common():
        samples = sorted(x for x in domain_urls[domain] if x)[:3]
        domains.append({
            "external_domain": domain,
            "occurrence_count": count,
            "unique_url_count": len(domain_urls[domain]),
            "source_page_count": len({x for x in domain_sources[domain] if x}),
            "authority_tier": domain_tier[domain],
            "crawl_recommendation": domain_recommendation[domain],
            "sample_urls": " | ".join(samples),
        })
    return enriched, domains


def build_call_audit(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in pages:
        if row.get("page_role_hint") != "CALL_CANDIDATE":
            continue
        pattern = classify_call_pattern(str(row.get("page_title", "")), str(row.get("main_text", "")))
        rows.append({
            "page_id": row.get("page_id", ""),
            "final_url": row.get("final_url", ""),
            "page_title": row.get("page_title", ""),
            "call_pattern": pattern,
            "text_extraction_status": row.get("text_extraction_status", ""),
            "word_count": row.get("word_count", 0),
            "identity_safeguard": "CALL_NOT_PROMOTED_TO_SCHEME",
        })
    return rows


def validate(
    input_pages: list[dict[str, str]],
    pages: list[dict[str, Any]],
    input_documents: list[dict[str, str]],
    documents: list[dict[str, Any]],
    input_external: list[dict[str, str]],
    external: list[dict[str, Any]],
    minimum_success_rate: float,
) -> dict[str, Any]:
    successful_html = [
        row for row in pages
        if 200 <= safe_int(row.get("http_status")) < 300
        and "html" in str(row.get("content_type", "")).lower()
    ]
    extracted = [
        row for row in successful_html
        if str(row.get("text_extraction_status", "")).startswith("SUCCESS")
        and safe_int(row.get("word_count")) > 0
        and row.get("text_sha256") not in {"", EMPTY_TEXT_SHA256}
    ]
    rate = len(extracted) / len(successful_html) if successful_html else 0.0
    missing_page_title = sum(not collapse_ws(str(row.get("page_title", ""))) for row in pages)
    empty_hash_success = sum(
        row.get("text_sha256") in {"", EMPTY_TEXT_SHA256} for row in extracted
    )
    missing_document_url = sum(not collapse_ws(str(row.get("document_url", ""))) for row in documents)
    missing_source_page = sum(not collapse_ws(str(row.get("source_page_url", ""))) for row in documents)
    missing_extension = sum(not collapse_ws(str(row.get("file_extension", ""))) for row in documents)
    missing_external_url = sum(not collapse_ws(str(row.get("external_url", ""))) for row in external)
    missing_domain = sum(not collapse_ws(str(row.get("external_domain", ""))) for row in external)

    checks = {
        "page_rows_preserved": len(input_pages) == len(pages),
        "document_rows_preserved": len(input_documents) == len(documents),
        "external_link_rows_preserved": len(input_external) == len(external),
        "page_title_complete": missing_page_title == 0,
        "text_extraction_rate_passed": rate >= minimum_success_rate,
        "no_empty_hash_on_extracted_pages": empty_hash_success == 0,
        "document_url_complete": missing_document_url == 0,
        "document_source_complete": missing_source_page == 0,
        "document_extension_complete": missing_extension == 0,
        "external_url_complete": missing_external_url == 0,
        "external_domain_complete": missing_domain == 0,
        "canonical_scheme_identity_created": False,
        "call_titles_promoted_to_scheme_names": False,
    }
    schema_pass = all(value for key, value in checks.items() if key not in {
        "canonical_scheme_identity_created", "call_titles_promoted_to_scheme_names"
    }) and not checks["canonical_scheme_identity_created"] and not checks["call_titles_promoted_to_scheme_names"]

    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "generated_at": utc_now(),
        "minimum_text_extraction_success_rate": minimum_success_rate,
        "counts": {
            "input_pages": len(input_pages),
            "output_pages": len(pages),
            "successful_html_pages": len(successful_html),
            "text_extraction_success": len(extracted),
            "text_extraction_failure": len(successful_html) - len(extracted),
            "input_documents": len(input_documents),
            "output_documents": len(documents),
            "input_external_links": len(input_external),
            "output_external_links": len(external),
        },
        "completeness": {
            "missing_page_title": missing_page_title,
            "text_extraction_success_rate": round(rate, 6),
            "empty_hash_on_extracted_pages": empty_hash_success,
            "missing_document_url": missing_document_url,
            "missing_document_source_page": missing_source_page,
            "missing_document_extension": missing_extension,
            "missing_external_url": missing_external_url,
            "missing_external_domain": missing_domain,
        },
        "checks": checks,
        "schema_validation_passed": schema_pass,
        "ready_for_v3_4_0_2": schema_pass,
    }


def build_summary(
    validation: dict[str, Any],
    pages: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    external: list[dict[str, Any]],
    domains: list[dict[str, Any]],
    call_audit: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    input_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    extraction_counts = Counter(str(x.get("text_extraction_status", "UNKNOWN")) for x in pages)
    document_role_counts = Counter(str(x.get("document_role_hint", "UNKNOWN")) for x in documents)
    call_counts = Counter(str(x.get("call_pattern", "UNKNOWN")) for x in call_audit)
    authority_counts = Counter(str(x.get("authority_tier", "UNKNOWN")) for x in external)
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "started_from": str(input_dir),
        "output_dir": str(output_dir),
        "completed_at": utc_now(),
        "network_access_used": False,
        "recrawl_performed": False,
        "identity_safeguard": {
            "canonical_scheme_identity_created": False,
            "call_titles_promoted_to_scheme_names": False,
            "description": "This hotfix enriches source evidence only; scheme identity remains reserved for later phases.",
        },
        "counts": {
            "pages": len(pages),
            "documents": len(documents),
            "external_link_occurrences": len(external),
            "external_domains": len(domains),
            "call_candidates_audited": len(call_audit),
            "text_extraction_failures": len(failures),
        },
        "text_extraction_status_counts": dict(sorted(extraction_counts.items())),
        "document_role_counts": dict(sorted(document_role_counts.items())),
        "call_pattern_counts": dict(sorted(call_counts.items())),
        "external_authority_counts": dict(sorted(authority_counts.items())),
        "schema_validation_passed": validation["schema_validation_passed"],
        "ready_for_v3_4_0_2": validation["ready_for_v3_4_0_2"],
        "outputs": {
            "pages": PAGE_OUTPUT,
            "documents": DOCUMENT_OUTPUT,
            "external_links": EXTERNAL_OUTPUT,
            "external_domains": DOMAIN_OUTPUT,
            "call_pattern_audit": CALL_AUDIT_OUTPUT,
            "text_extraction_failures": FAILURE_OUTPUT,
            "schema_validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
    }


def run_hotfix(input_dir: Path, output_dir: Path, minimum_success_rate: float, dry_run: bool = False) -> dict[str, Any]:
    page_path = input_dir / PAGE_INPUT
    document_path = input_dir / DOCUMENT_INPUT
    external_path = input_dir / EXTERNAL_INPUT
    link_path = input_dir / LINK_INPUT
    for required in (page_path, document_path, external_path, link_path):
        if not required.exists():
            raise FileNotFoundError(f"Required v3.4.0.1 input is missing: {required}")

    input_pages = read_csv(page_path)
    input_documents = read_csv(document_path)
    input_external = read_csv(external_path)
    if dry_run:
        snapshots = sum(resolve_snapshot(input_dir, row.get("snapshot_path", "")).exists() for row in input_pages)
        return {
            "service_version": VERSION,
            "mode": "DRY_RUN",
            "input_dir": str(input_dir),
            "output_dir": str(output_dir),
            "counts": {
                "pages": len(input_pages),
                "snapshots_found": snapshots,
                "documents": len(input_documents),
                "external_links": len(input_external),
            },
            "network_access_used": False,
            "files_written": False,
        }

    pages, failures = enrich_pages(input_pages, input_dir)
    documents = enrich_documents(input_documents)
    external, domains = enrich_external_links(input_external)
    call_audit = build_call_audit(pages)
    validation = validate(
        input_pages, pages, input_documents, documents, input_external, external,
        minimum_success_rate,
    )
    summary = build_summary(
        validation, pages, documents, external, domains, call_audit, failures,
        input_dir, output_dir,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / PAGE_OUTPUT, pages)
    write_csv(output_dir / DOCUMENT_OUTPUT, documents)
    write_csv(output_dir / EXTERNAL_OUTPUT, external)
    write_csv(output_dir / DOMAIN_OUTPUT, domains)
    write_csv(output_dir / CALL_AUDIT_OUTPUT, call_audit)
    write_csv(output_dir / FAILURE_OUTPUT, failures)
    atomic_write_text(output_dir / VALIDATION_OUTPUT, json.dumps(validation, indent=2, ensure_ascii=False))
    atomic_write_text(output_dir / SUMMARY_OUTPUT, json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def run_self_test() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="ssip_dst_34011_") as temp:
        root = Path(temp)
        input_dir = root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
        snapshots = input_dir / "snapshots" / "html"
        output_dir = root / "data" / "departments" / "dst" / "v3_4_0_1_1"
        snapshots.mkdir(parents=True)

        html = b"""<!doctype html><html lang='en'><head><title>Example DST Call</title></head>
        <body><header><a>Home</a></header><main></main>
        <div class='region-content'><article><h1>Call for Proposals under Standard Programme</h1>
        <p>Applications are invited under the existing programme.</p>
        <h2>Eligibility</h2><p>Recognised institutions may apply.</p></article></div>
        <footer>Repeated navigation</footer></body></html>"""
        snap = snapshots / "example.html.gz"
        with gzip.open(snap, "wb") as handle:
            handle.write(html)

        page_rows = [{
            "page_id": "dst_page_test",
            "requested_url": "https://dst.gov.in/test-call",
            "normalized_url": "https://dst.gov.in/test-call",
            "final_url": "https://dst.gov.in/test-call",
            "canonical_url": "https://dst.gov.in/test-call",
            "parent_url": "https://dst.gov.in/call-for-proposals",
            "depth": "1",
            "source_role_hint": "CALL_INDEX_CURRENT",
            "page_role_hint": "CALL_CANDIDATE",
            "http_status": "200",
            "content_type": "text/html",
            "charset": "utf-8",
            "title": "Call for Proposals under Standard Programme",
            "language": "en",
            "fetched_at": utc_now(),
            "last_modified_header": "",
            "etag": "",
            "last_updated_text": "",
            "content_length_header": str(len(html)),
            "bytes_received": str(len(html)),
            "content_sha256": hashlib.sha256(html).hexdigest(),
            "text_sha256": EMPTY_TEXT_SHA256,
            "word_count": "0",
            "link_count": "0",
            "text_excerpt": "",
            "snapshot_path": "snapshots\\html\\example.html.gz",
            "duplicate_of_page_id": "",
            "robots_decision": "ALLOW",
            "fetch_duration_ms": "1",
            "error": "",
        }]
        doc_rows = [{
            "document_id": "dst_doc_test",
            "url": "https://dst.gov.in/files/guidelines-2026.pdf",
            "final_url": "",
            "source_url": "https://dst.gov.in/test-call",
            "anchor_text": "Programme Guidelines",
            "role_hint": "DOCUMENT",
            "filename": "guidelines-2026.pdf",
            "extension": ".pdf",
            "authority_class": "DST_OFFICIAL",
            "status": "DISCOVERED",
            "http_status": "",
            "content_type": "",
            "content_length_header": "",
            "bytes_received": "",
            "content_sha256": "",
            "snapshot_path": "",
            "discovered_at": utc_now(),
            "fetched_at": "",
            "error": "",
        }]
        ext_rows = [{
            "external_id": "dst_ext_test",
            "source_url": "https://dst.gov.in/test-call",
            "external_url": "https://onlinedst.gov.in/apply",
            "anchor_text": "Apply",
            "authority_class": "GOVERNMENT_PORTAL",
            "role_hint": "APPLICATION_PORTAL",
            "discovered_at": utc_now(),
        }]
        link_rows = [{
            "from_url": "https://dst.gov.in/test-call",
            "to_url": "https://onlinedst.gov.in/apply",
            "normalized_to_url": "https://onlinedst.gov.in/apply",
            "anchor_text": "Apply",
            "rel": "",
            "in_main_content": "1",
            "is_internal": "0",
            "is_document": "0",
            "authority_class": "GOVERNMENT_PORTAL",
            "role_hint": "APPLICATION_PORTAL",
            "relevance_score": "90",
            "enqueue_decision": "EXTERNAL_RECORDED",
            "discovered_at": utc_now(),
        }]
        write_csv(input_dir / PAGE_INPUT, page_rows)
        write_csv(input_dir / DOCUMENT_INPUT, doc_rows)
        write_csv(input_dir / EXTERNAL_INPUT, ext_rows)
        write_csv(input_dir / LINK_INPUT, link_rows)

        result = run_hotfix(input_dir, output_dir, 1.0)
        enriched_pages = read_csv(output_dir / PAGE_OUTPUT)
        enriched_docs = read_csv(output_dir / DOCUMENT_OUTPUT)
        enriched_ext = read_csv(output_dir / EXTERNAL_OUTPUT)
        calls = read_csv(output_dir / CALL_AUDIT_OUTPUT)

        checks["main_text_recovered"] = safe_int(enriched_pages[0]["word_count"]) > 5
        checks["empty_main_shell_not_selected"] = enriched_pages[0]["text_selected_selector"] != "main"
        checks["text_hash_recovered"] = enriched_pages[0]["text_sha256"] != EMPTY_TEXT_SHA256
        checks["page_aliases_added"] = enriched_pages[0]["page_title"] == page_rows[0]["title"]
        checks["call_not_promoted_to_scheme"] = calls[0]["identity_safeguard"] == "CALL_NOT_PROMOTED_TO_SCHEME"
        checks["call_pattern_detected"] = calls[0]["call_pattern"] == "APPLICATION_INVITATION"
        checks["document_role_derived"] = enriched_docs[0]["document_role_hint"] == "GUIDELINE"
        checks["document_year_derived"] = enriched_docs[0]["document_year"] == "2026"
        checks["external_domain_derived"] = enriched_ext[0]["external_domain"] == "onlinedst.gov.in"
        checks["dst_portal_classified"] = enriched_ext[0]["authority_tier"] == "DST_RELATED_PORTAL"
        checks["schema_validation_passed"] = bool(result["schema_validation_passed"])
        checks["no_network_or_recrawl"] = not result["network_access_used"] and not result["recrawl_performed"]
        checks["no_scheme_identity_fields"] = all(
            "canonical_scheme_name" not in row and "scheme_id" not in row
            for row in enriched_pages
        )

    passed = all(checks.values())
    return {
        "service_version": VERSION,
        "department": DEPARTMENT_CODE,
        "self_test_passed": passed,
        "tests": checks,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--minimum-success-rate", type=float, default=0.98)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if validation fails.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        result = run_self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["self_test_passed"] else 1
    if not 0.0 <= args.minimum_success_rate <= 1.0:
        raise SystemExit("--minimum-success-rate must be between 0 and 1")
    project_root = args.project_root.resolve()
    input_dir = (args.input_dir or project_root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl").resolve()
    output_dir = (args.output_dir or project_root / "data" / "departments" / "dst" / "v3_4_0_1_1").resolve()
    try:
        result = run_hotfix(input_dir, output_dir, args.minimum_success_rate, args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({
            "service_version": VERSION,
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.strict and not args.dry_run and not result.get("schema_validation_passed", False):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
