from __future__ import annotations

"""SSIP Full Multi-Source Coverage Audit v2.6.

This module performs a read-only reconciliation of SSIP discovery, classification,
master-candidate, extraction, validation, staging and admin-review artifacts.
It intentionally uses only the Python standard library so it can run inside the
existing Windows virtual environment without new dependencies.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

AUDIT_VERSION = "2.6.0"
DEFAULT_SOURCES = (
    "Startup India",
    "MSME",
    "DST",
    "BIRAC",
    "MeitY Startup Hub",
)

FINAL_CATEGORIES = {
    "FULLY_PROCESSED",
    "AWAITING_EXTRACTION",
    "AWAITING_VALIDATION",
    "AWAITING_ADMIN_REVIEW",
    "FETCH_FAILED",
    "BLOCKED_OR_LOGIN_REQUIRED",
    "BROWSER_RENDER_REQUIRED",
    "DUPLICATE",
    "NON_SCHEME_CONTENT",
    "CLASSIFICATION_UNCERTAIN",
    "MISSING_FROM_MASTER",
    "MISSING_FROM_STAGING",
    "REJECTED",
}

SCHEME_LIKE_CLASSIFICATIONS = {
    "SCHEME",
    "PROGRAMME",
    "CALL",
    "FELLOWSHIP",
    "AWARD",
}
NON_SCHEME_CLASSIFICATIONS = {
    "DIRECTORY_PAGE",
    "RESULT_LIST",
    "GUIDELINE",
    "REFERENCE_DOCUMENT",
    "ARCHIVE_INDEX",
    "POLICY",
    "REFERENCE_DIRECTORY",
    "OTHER",
}
NON_MASTER_REVIEW_DECISIONS = {
    "HISTORICAL_CALL",
    "ATTACH_AS_SUPPORTING_EVIDENCE",
    "EXCLUDE_FROM_SCHEME_MASTER",
    "USE_FOR_FURTHER_DISCOVERY",
}
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "session",
    "sessionid",
    "phpsessid",
}

URL_REPORT_COLUMNS = [
    "source",
    "url",
    "normalized_url",
    "inventory_origin",
    "discovery_status",
    "fetch_status",
    "http_status",
    "browser_render_required",
    "classification",
    "classification_reason",
    "master_id",
    "canonical_name",
    "extraction_status",
    "validation_decision",
    "review_status",
    "staging_status",
    "failure_reason",
    "final_category",
    "recommended_action",
]

MASTER_BACKLOG_COLUMNS = [
    "master_id",
    "source",
    "canonical_name",
    "master_type",
    "current_status",
    "readiness",
    "best_available_url",
    "member_url_count",
    "extraction_status",
    "validation_decision",
    "database_status",
    "final_category",
    "recommended_action",
]

SOURCE_REPORT_COLUMNS = [
    "source",
    "total_discovered_urls",
    "unique_urls",
    "duplicate_urls",
    "current_v2_urls",
    "legacy_only_urls",
    "successful_fetches",
    "failed_fetches",
    "browser_render_required_pages",
    "scheme_programme_pages",
    "non_scheme_pages",
    "classification_uncertain_pages",
    "master_candidates",
    "extracted_records",
    "validated_records",
    "validation_approved_records",
    "staged_records",
    "admin_review_records",
    "awaiting_admin_review_records",
    "rejected_records",
    "missing_or_unprocessed_records",
    "terminal_master_records",
    "coverage_percentage",
    "publication_coverage_percentage",
    "coverage_status",
]

MISSING_CATEGORIES = {
    "AWAITING_EXTRACTION",
    "AWAITING_VALIDATION",
    "AWAITING_ADMIN_REVIEW",
    "FETCH_FAILED",
    "BLOCKED_OR_LOGIN_REQUIRED",
    "BROWSER_RENDER_REQUIRED",
    "CLASSIFICATION_UNCERTAIN",
    "MISSING_FROM_MASTER",
    "MISSING_FROM_STAGING",
}


@dataclass(frozen=True)
class AuditPaths:
    project_root: Path
    discovery_path: Path
    classified_path: Path
    masters_path: Path
    extracted_paths: tuple[Path, ...]
    validated_paths: tuple[Path, ...]
    staging_db_path: Path
    legacy_db_path: Path
    meity_discovery_summary_path: Path
    output_dir: Path

    @classmethod
    def from_project_root(cls, project_root: Path, output_dir: Path | None = None) -> "AuditPaths":
        root = project_root.resolve()
        data = root / "data"
        return cls(
            project_root=root,
            discovery_path=data / "discovery_results_v2.json",
            classified_path=data / "classified_candidates_v1.json",
            masters_path=data / "scheme_master_candidates_v1.json",
            extracted_paths=(
                data / "extracted_scheme_records_v2_3.json",
                data / "extracted_scheme_records_v1.json",
            ),
            validated_paths=(
                data / "validated_scheme_records_v2_4.json",
                data / "validated_scheme_records_v1.json",
            ),
            staging_db_path=root / "database" / "ssip_staging_v1.db",
            legacy_db_path=root / "database" / "ssip.db",
            meity_discovery_summary_path=data / "meity_discovery_summary_v2_1.json",
            output_dir=(output_dir or data / "audit").resolve(),
        )


@dataclass
class DiscoveryRecord:
    source: str
    url: str
    normalized_url: str
    inventory_origin: str
    discovery_status: str = "DISCOVERED"
    content_kind: str = ""
    discovery_method: str = ""
    title: str = ""
    http_status: str = ""
    explicit_fetch_status: str = ""
    ordinal: int = 0


@dataclass
class AuditRow:
    source: str
    url: str
    normalized_url: str
    inventory_origin: str
    discovery_status: str
    fetch_status: str
    http_status: str
    browser_render_required: bool
    classification: str
    classification_reason: str
    master_id: str
    canonical_name: str
    extraction_status: str
    validation_decision: str
    review_status: str
    staging_status: str
    failure_reason: str
    final_category: str
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["browser_render_required"] = bool(self.browser_render_required)
        return payload


@dataclass
class DatabaseState:
    staged: dict[str, dict[str, Any]] = field(default_factory=dict)
    review: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_evidence_urls: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    tables: list[str] = field(default_factory=list)


@dataclass
class AuditResult:
    generated_at: str
    rows: list[AuditRow]
    source_summary: list[dict[str, Any]]
    overall_summary: dict[str, Any]
    recommendations: list[dict[str, Any]]
    master_backlog: list[dict[str, Any]]
    input_manifest: dict[str, Any]


class CoverageAuditError(RuntimeError):
    """Raised when required audit inputs are invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_source(value: Any) -> str:
    raw = normalize_whitespace(value)
    key = raw.casefold()
    aliases = {
        "startup india": "Startup India",
        "startupindia": "Startup India",
        "ministry of msme": "MSME",
        "msme": "MSME",
        "ministry of micro small and medium enterprises": "MSME",
        "ministry of micro, small and medium enterprises": "MSME",
        "nidhi dst": "DST",
        "department of science and technology": "DST",
        "dst": "DST",
        "birac": "BIRAC",
        "meity startup hub": "MeitY Startup Hub",
        "meity": "MeitY Startup Hub",
        "msh": "MeitY Startup Hub",
    }
    return aliases.get(key, raw)


def normalize_url(url: Any) -> str:
    raw = normalize_whitespace(url)
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")

    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))
    query_items.sort(key=lambda item: (item[0].casefold(), item[1]))
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def source_from_url(url: Any) -> str:
    normalized = normalize_url(url)
    if not normalized:
        return ""
    try:
        host = (urlsplit(normalized).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]

    if host == "startupindia.gov.in" or host.endswith(".startupindia.gov.in"):
        return "Startup India"
    if (
        host == "msme.gov.in"
        or host.endswith(".msme.gov.in")
        or host == "dcmsme.gov.in"
        or host.endswith(".dcmsme.gov.in")
        or host == "champions.gov.in"
        or host.endswith(".champions.gov.in")
    ):
        return "MSME"
    if (
        host == "dst.gov.in"
        or host.endswith(".dst.gov.in")
        or host == "nstedb.com"
        or host.endswith(".nstedb.com")
    ):
        return "DST"
    if host == "birac.nic.in" or host.endswith(".birac.nic.in") or host == "biracrdif.org":
        return "BIRAC"
    if (
        host == "msh.meity.gov.in"
        or host.endswith(".msh.meity.gov.in")
        or host == "meity.gov.in"
        or host.endswith(".meity.gov.in")
    ):
        return "MeitY Startup Hub"
    return ""


def load_json(path: Path, *, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise CoverageAuditError(f"Required JSON file not found: {path}")
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageAuditError(f"Could not read JSON file {path}: {exc}") from exc


def load_json_list(path: Path, *, required: bool = False) -> list[dict[str, Any]]:
    payload = load_json(path, required=required)
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise CoverageAuditError(f"Expected a JSON list in {path}")
    records: list[dict[str, Any]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise CoverageAuditError(f"Expected object at {path}[{index}]")
        records.append(item)
    return records


def file_manifest_entry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
    }


def open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    safe = table.replace('"', '""')
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{safe}")')}


def read_table(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    safe = table.replace('"', '""')
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{safe}"').fetchall()]


def iter_urls_from_value(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("http://") or stripped.startswith("https://") or stripped.startswith("//"):
            yield stripped
    elif isinstance(value, Mapping):
        for key, child in value.items():
            key_lower = str(key).casefold()
            if "url" in key_lower or key_lower in {"href", "link"}:
                yield from iter_urls_from_value(child)
            elif isinstance(child, (Mapping, list, tuple)):
                yield from iter_urls_from_value(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from iter_urls_from_value(child)


def record_urls(record: Mapping[str, Any]) -> set[str]:
    urls: set[str] = set()
    url_keys = {
        "url",
        "canonical_url",
        "official_page_url",
        "best_available_url",
        "application_url",
        "source_url",
        "pdf_url",
        "guideline_urls",
        "all_member_urls",
        "source_evidence",
        "active_calls",
        "supporting_documents",
        "core_pages",
        "field_evidence",
        "validated_record",
    }
    for key, value in record.items():
        if key in url_keys or "url" in key.casefold():
            for candidate in iter_urls_from_value(value):
                normalized = normalize_url(candidate)
                if normalized:
                    urls.add(normalized)
    return urls


def merge_records_by_master_id(paths: Sequence[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Merge preferred-to-fallback files; first occurrence wins."""
    merged: dict[str, dict[str, Any]] = {}
    provenance: dict[str, str] = {}
    for path in paths:
        for record in load_json_list(path):
            master_id = normalize_whitespace(record.get("master_id"))
            if not master_id or master_id in merged:
                continue
            merged[master_id] = record
            provenance[master_id] = str(path)
    return merged, provenance


def load_database_state(path: Path) -> DatabaseState:
    state = DatabaseState()
    if not path.exists():
        return state
    connection = open_sqlite_readonly(path)
    try:
        state.tables = table_names(connection)
        if "scheme_staging" in state.tables:
            for row in read_table(connection, "scheme_staging"):
                master_id = normalize_whitespace(row.get("master_id"))
                if master_id:
                    state.staged[master_id] = row
                    raw = row.get("raw_record_json")
                    if raw:
                        try:
                            payload = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            payload = {}
                        for url in record_urls(payload):
                            state.source_evidence_urls[master_id].add(url)
        if "admin_review_queue" in state.tables:
            for row in read_table(connection, "admin_review_queue"):
                master_id = normalize_whitespace(row.get("master_id"))
                if master_id:
                    state.review[master_id] = row
                    raw = row.get("validated_record_json")
                    if raw:
                        try:
                            payload = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            payload = {}
                        for url in record_urls(payload):
                            state.source_evidence_urls[master_id].add(url)
        if "rejected_scheme_records" in state.tables:
            for row in read_table(connection, "rejected_scheme_records"):
                master_id = normalize_whitespace(row.get("master_id"))
                if master_id:
                    state.rejected[master_id] = row
                    raw = row.get("raw_record_json")
                    if raw:
                        try:
                            payload = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            payload = {}
                        for url in record_urls(payload):
                            state.source_evidence_urls[master_id].add(url)
        if "scheme_sources" in state.tables:
            for row in read_table(connection, "scheme_sources"):
                master_id = normalize_whitespace(row.get("master_id"))
                url = normalize_url(row.get("source_url"))
                if master_id and url:
                    state.source_evidence_urls[master_id].add(url)
    finally:
        connection.close()
    return state


def load_legacy_discovery(path: Path) -> list[DiscoveryRecord]:
    if not path.exists():
        return []
    connection = open_sqlite_readonly(path)
    records: list[DiscoveryRecord] = []
    try:
        tables = table_names(connection)
        if "discovered_links" not in tables:
            return []
        columns = table_columns(connection, "discovered_links")
        select_columns = [
            column
            for column in (
                "id",
                "url",
                "title",
                "page_type",
                "crawl_status",
                "classification_status",
                "source_url",
                "discovered_date",
            )
            if column in columns
        ]
        safe_columns = ", ".join(f'"{column}"' for column in select_columns)
        query = f'SELECT {safe_columns} FROM "discovered_links" ORDER BY "id"'
        for row in connection.execute(query):
            payload = dict(row)
            url = normalize_whitespace(payload.get("url"))
            normalized = normalize_url(url)
            if not normalized:
                continue
            source = source_from_url(url) or source_from_url(payload.get("source_url"))
            if source not in DEFAULT_SOURCES:
                continue
            records.append(
                DiscoveryRecord(
                    source=source,
                    url=url,
                    normalized_url=normalized,
                    inventory_origin="legacy_ssip_db",
                    discovery_status=normalize_whitespace(payload.get("crawl_status")) or "DISCOVERED",
                    content_kind=normalize_whitespace(payload.get("page_type")),
                    discovery_method="legacy-discovered-links",
                    title=normalize_whitespace(payload.get("title")),
                    explicit_fetch_status="",
                    ordinal=int(payload.get("id") or 0),
                )
            )
    finally:
        connection.close()
    return records


def load_primary_discovery(path: Path) -> list[DiscoveryRecord]:
    records: list[DiscoveryRecord] = []
    for index, item in enumerate(load_json_list(path, required=True), start=1):
        url = normalize_whitespace(item.get("url"))
        normalized = normalize_url(item.get("canonical_url") or url)
        if not normalized:
            continue
        source = normalize_source(item.get("source")) or source_from_url(url)
        if source not in DEFAULT_SOURCES:
            continue
        records.append(
            DiscoveryRecord(
                source=source,
                url=url,
                normalized_url=normalized,
                inventory_origin="discovery_results_v2",
                discovery_status=normalize_whitespace(item.get("status")) or "DISCOVERED",
                content_kind=normalize_whitespace(item.get("content_kind")),
                discovery_method=normalize_whitespace(item.get("discovery_method")),
                title=normalize_whitespace(item.get("title")),
                http_status=normalize_whitespace(item.get("http_status")),
                explicit_fetch_status=normalize_whitespace(item.get("fetch_status")),
                ordinal=index,
            )
        )
    return records


def classification_index(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        candidates = [record.get("canonical_url"), record.get("url")]
        for candidate in candidates:
            normalized = normalize_url(candidate)
            if normalized:
                index[normalized] = record
    return index


def master_indexes(
    masters: Sequence[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for master in masters:
        master_id = normalize_whitespace(master.get("master_id"))
        if not master_id:
            continue
        by_id[master_id] = master
        for url in record_urls(master):
            by_url[url].append(master)
    return by_id, by_url


def master_for_url(
    normalized_url: str,
    source: str,
    by_url: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    matches = list(by_url.get(normalized_url, []))
    if not matches:
        return None
    same_source = [m for m in matches if normalize_source(m.get("source")) == source]
    candidates = same_source or matches
    candidates.sort(
        key=lambda m: (
            float(m.get("best_relevance_score") or 0.0),
            normalize_whitespace(m.get("canonical_name")),
        ),
        reverse=True,
    )
    return candidates[0]


def meity_browser_render_urls(summary_path: Path, discovery: Sequence[DiscoveryRecord]) -> set[str]:
    summary = load_json(summary_path)
    if not isinstance(summary, dict):
        return set()
    network_stats = summary.get("network_stats")
    if not isinstance(network_stats, dict):
        return set()
    rendered_count = 0
    for value in network_stats.values():
        if isinstance(value, dict):
            rendered_count += int(value.get("browser_renders") or 0)
    if rendered_count <= 0:
        return set()
    meity_urls = [
        item.normalized_url
        for item in discovery
        if item.source == "MeitY Startup Hub" and "meity-hotfix" in item.discovery_method.casefold()
    ]
    if rendered_count >= len(meity_urls):
        return set(meity_urls)
    return set(meity_urls[:rendered_count])


def url_looks_blocked_or_login(url: str, title: str = "") -> bool:
    text = f"{url} {title}".casefold()
    return bool(re.search(r"(?:^|[/_.?=&-])(login|signin|sign-in|register|captcha)(?:$|[/_.?=&-])", text))


def fetch_status_for(
    discovery: DiscoveryRecord,
    classified: dict[str, Any] | None,
    extracted_url_set: set[str],
    browser_urls: set[str],
) -> tuple[str, bool, str]:
    browser_required = discovery.normalized_url in browser_urls
    explicit = discovery.explicit_fetch_status.upper()
    if explicit:
        if explicit in {"FAILED", "ERROR", "FETCH_FAILED"}:
            return "FETCH_FAILED", browser_required, "Discovery artifact records a fetch failure."
        if explicit in {"BLOCKED", "LOGIN_REQUIRED", "FORBIDDEN"}:
            return "BLOCKED_OR_LOGIN_REQUIRED", browser_required, "Discovery artifact records a blocked/login page."
        if explicit in {"SUCCESS", "FETCHED", "OK"}:
            return "FETCHED", browser_required, ""
    if discovery.normalized_url in extracted_url_set:
        return "FETCHED_FOR_EXTRACTION", browser_required, ""
    if classified is not None:
        return "FETCHED_INFERRED_FROM_CLASSIFICATION", browser_required, ""
    if url_looks_blocked_or_login(discovery.url, discovery.title):
        return "BLOCKED_OR_LOGIN_REQUIRED", browser_required, "Login or registration URL has no downstream processing evidence."
    if browser_required:
        return "BROWSER_RENDERED", True, ""
    return "FETCH_NOT_RECORDED", False, "No fetch result was found in current audit artifacts."


def final_category_for(
    *,
    duplicate: bool,
    fetch_status: str,
    browser_required: bool,
    classified: dict[str, Any] | None,
    master: dict[str, Any] | None,
    extracted: dict[str, Any] | None,
    validated: dict[str, Any] | None,
    staged: dict[str, Any] | None,
    review: dict[str, Any] | None,
    rejected: dict[str, Any] | None,
) -> tuple[str, str, str]:
    if duplicate:
        return "DUPLICATE", "Duplicate normalized URL already represented by a preferred inventory record.", "No pipeline action; retain only for audit traceability."
    if fetch_status == "FETCH_FAILED":
        return "FETCH_FAILED", "Page fetch failed.", "Retry with bounded backoff and record HTTP/error details."
    if fetch_status == "BLOCKED_OR_LOGIN_REQUIRED":
        return "BLOCKED_OR_LOGIN_REQUIRED", "Page appears blocked or requires authentication.", "Use an official public page, browser-assisted fetch, or manual evidence capture."

    if rejected is not None:
        return "REJECTED", "Record reached the rejected-records table.", "No automatic repair. Review rejection notes before any explicit backfill."
    if staged is not None:
        return "FULLY_PROCESSED", "", "No action required."

    if review is not None:
        review_status = normalize_whitespace(review.get("review_status")).upper()
        if review_status in {"PENDING", "OPEN", "IN_REVIEW", "NEEDS_REVIEW", ""}:
            return "AWAITING_ADMIN_REVIEW", "Record is present in the admin review queue.", "Complete the admin review decision."
        if review_status == "APPROVED":
            return "MISSING_FROM_STAGING", "Admin review approved the record, but no staging row exists.", "Run a targeted, explicit staging backfill for this master_id."
        if review_status == "REJECTED":
            return "REJECTED", "Admin review rejected the record.", "No automatic repair. Review the rejection before reconsideration."

    if validated is not None:
        decision = normalize_whitespace(
            validated.get("decision")
            or validated.get("validation_decision")
            or (validated.get("validation") or {}).get("decision")
        ).upper()
        if decision == "APPROVED_FOR_DATABASE":
            return "MISSING_FROM_STAGING", "Validation approved the record, but no staging row exists.", "Run a targeted, explicit staging backfill for this master_id."
        if decision in {"NEEDS_ADMIN_REVIEW", "NEEDS_MORE_EVIDENCE"}:
            return "AWAITING_ADMIN_REVIEW", "Validation requires admin review, but no terminal database decision exists.", "Load or restore the record in the admin review queue."
        if decision == "REJECTED":
            return "REJECTED", "Validation rejected the record.", "No automatic repair."
        return "MISSING_FROM_STAGING", "Validated record has no recognized terminal database destination.", "Inspect validation decision and perform an explicit repair."

    if extracted is not None:
        return "AWAITING_VALIDATION", "Extraction exists without a validated record.", "Run the validation agent for this master_id."
    if master is not None:
        return "AWAITING_EXTRACTION", "Master candidate exists without an extracted record.", "Run incremental extraction for this master_id."

    if classified is None:
        if browser_required:
            return "BROWSER_RENDER_REQUIRED", "No classification exists and browser rendering is required.", "Fetch with browser rendering, then classify."
        return "CLASSIFICATION_UNCERTAIN", "Discovered URL has no classification record.", "Classify the URL or mark it as an intentional duplicate/exclusion."

    classification = normalize_whitespace(classified.get("classification")).upper()
    review_decision = normalize_whitespace(classified.get("review_decision")).upper()
    if classification in NON_SCHEME_CLASSIFICATIONS or review_decision in NON_MASTER_REVIEW_DECISIONS:
        return "NON_SCHEME_CONTENT", "Classifier treated this as supporting, historical, directory, policy, result, or reference content.", "No master is required unless manual review identifies a distinct live scheme."
    if classification in SCHEME_LIKE_CLASSIFICATIONS:
        return "MISSING_FROM_MASTER", "Scheme-like classified page is not linked to a master candidate.", "Review classification grouping and create or attach a master candidate explicitly."
    return "CLASSIFICATION_UNCERTAIN", "Classification does not clearly resolve scheme relevance.", "Perform targeted classification review."


def record_decision(record: Mapping[str, Any] | None) -> str:
    if not record:
        return ""
    validation = record.get("validation") if isinstance(record, Mapping) else None
    if not isinstance(validation, Mapping):
        validation = {}
    return normalize_whitespace(
        record.get("decision")
        or record.get("validation_decision")
        or validation.get("decision")
    )


def build_rows(
    discoveries: Sequence[DiscoveryRecord],
    classified_records: Sequence[dict[str, Any]],
    masters: Sequence[dict[str, Any]],
    extracted_by_id: Mapping[str, dict[str, Any]],
    validated_by_id: Mapping[str, dict[str, Any]],
    db_state: DatabaseState,
    browser_urls: set[str],
) -> list[AuditRow]:
    class_by_url = classification_index(classified_records)
    masters_by_id, masters_by_url = master_indexes(masters)

    extracted_url_set: set[str] = set()
    for master_id, record in extracted_by_id.items():
        extracted_url_set.update(record_urls(record))
        extracted_url_set.update(db_state.source_evidence_urls.get(master_id, set()))

    preferred_rank = {"discovery_results_v2": 0, "legacy_ssip_db": 1}
    ordered = sorted(
        discoveries,
        key=lambda item: (
            item.source,
            item.normalized_url,
            preferred_rank.get(item.inventory_origin, 9),
            item.ordinal,
        ),
    )
    seen_urls: set[str] = set()
    rows: list[AuditRow] = []

    for discovery in ordered:
        duplicate = discovery.normalized_url in seen_urls
        if not duplicate:
            seen_urls.add(discovery.normalized_url)

        classified = class_by_url.get(discovery.normalized_url)
        master = master_for_url(discovery.normalized_url, discovery.source, masters_by_url)
        master_id = normalize_whitespace(master.get("master_id")) if master else ""
        extracted = extracted_by_id.get(master_id) if master_id else None
        validated = validated_by_id.get(master_id) if master_id else None
        staged = db_state.staged.get(master_id) if master_id else None
        review = db_state.review.get(master_id) if master_id else None
        rejected = db_state.rejected.get(master_id) if master_id else None

        fetch_status, browser_required, fetch_failure = fetch_status_for(
            discovery,
            classified,
            extracted_url_set,
            browser_urls,
        )
        final_category, category_failure, action = final_category_for(
            duplicate=duplicate,
            fetch_status=fetch_status,
            browser_required=browser_required,
            classified=classified,
            master=master,
            extracted=extracted,
            validated=validated,
            staged=staged,
            review=review,
            rejected=rejected,
        )
        if final_category not in FINAL_CATEGORIES:
            raise CoverageAuditError(f"Unsupported final category: {final_category}")

        classification = normalize_whitespace(classified.get("classification")) if classified else ""
        reasons = classified.get("classification_reasons") if classified else []
        if isinstance(reasons, list):
            classification_reason = "; ".join(normalize_whitespace(item) for item in reasons if normalize_whitespace(item))
        else:
            classification_reason = normalize_whitespace(reasons)

        review_status = normalize_whitespace(review.get("review_status")) if review else ""
        if staged is not None:
            staging_status = normalize_whitespace(staged.get("publication_status")) or "STAGED"
        elif rejected is not None:
            staging_status = "REJECTED"
        elif review is not None:
            staging_status = "ADMIN_REVIEW_QUEUE"
        else:
            staging_status = "NOT_PRESENT"

        failure_reason = category_failure or fetch_failure
        rows.append(
            AuditRow(
                source=discovery.source,
                url=discovery.url,
                normalized_url=discovery.normalized_url,
                inventory_origin=discovery.inventory_origin,
                discovery_status=discovery.discovery_status,
                fetch_status=fetch_status,
                http_status=discovery.http_status,
                browser_render_required=browser_required,
                classification=classification,
                classification_reason=classification_reason,
                master_id=master_id,
                canonical_name=normalize_whitespace(master.get("canonical_name")) if master else "",
                extraction_status="EXTRACTED" if extracted is not None else ("NOT_EXTRACTED" if master else "NOT_APPLICABLE"),
                validation_decision=record_decision(validated),
                review_status=review_status,
                staging_status=staging_status,
                failure_reason=failure_reason,
                final_category=final_category,
                recommended_action=action,
            )
        )
    return rows


def unique_master_source_map(masters: Sequence[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for master in masters:
        master_id = normalize_whitespace(master.get("master_id"))
        source = normalize_source(master.get("source"))
        if master_id:
            result[master_id] = source
    return result


def source_summary(
    rows: Sequence[AuditRow],
    masters: Sequence[dict[str, Any]],
    extracted_by_id: Mapping[str, dict[str, Any]],
    validated_by_id: Mapping[str, dict[str, Any]],
    db_state: DatabaseState,
) -> list[dict[str, Any]]:
    master_source = unique_master_source_map(masters)
    masters_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, source in master_source.items():
        masters_by_source[source].add(master_id)

    extracted_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, record in extracted_by_id.items():
        source = normalize_source(record.get("source")) or master_source.get(master_id, "")
        extracted_by_source[source].add(master_id)

    validated_by_source: dict[str, set[str]] = defaultdict(set)
    validation_approved_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, record in validated_by_id.items():
        source = normalize_source(record.get("source")) or master_source.get(master_id, "")
        validated_by_source[source].add(master_id)
        if record_decision(record).upper() == "APPROVED_FOR_DATABASE":
            validation_approved_by_source[source].add(master_id)

    staged_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, record in db_state.staged.items():
        staged_by_source[normalize_source(record.get("source")) or master_source.get(master_id, "")].add(master_id)
    review_by_source: dict[str, set[str]] = defaultdict(set)
    pending_review_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, record in db_state.review.items():
        source = normalize_source(record.get("source")) or master_source.get(master_id, "")
        review_by_source[source].add(master_id)
        status = normalize_whitespace(record.get("review_status")).upper()
        if status in {"", "PENDING", "OPEN", "IN_REVIEW", "NEEDS_REVIEW"}:
            pending_review_by_source[source].add(master_id)
    rejected_by_source: dict[str, set[str]] = defaultdict(set)
    for master_id, record in db_state.rejected.items():
        rejected_by_source[normalize_source(record.get("source")) or master_source.get(master_id, "")].add(master_id)

    summary: list[dict[str, Any]] = []
    for source in DEFAULT_SOURCES:
        source_rows = [row for row in rows if row.source == source]
        unique_rows = [row for row in source_rows if row.final_category != "DUPLICATE"]
        unique_urls = {row.normalized_url for row in unique_rows}
        master_ids = masters_by_source.get(source, set())
        terminal_master_ids = (staged_by_source.get(source, set()) | rejected_by_source.get(source, set())) & master_ids
        staged_master_ids = staged_by_source.get(source, set()) & master_ids
        if master_ids:
            coverage = round(100.0 * len(terminal_master_ids) / len(master_ids), 2)
            publication_coverage = round(100.0 * len(staged_master_ids) / len(master_ids), 2)
            if coverage >= 95:
                status = "COMPLETE_OR_NEAR_COMPLETE"
            elif coverage >= 70:
                status = "GOOD_WITH_GAPS"
            elif coverage >= 40:
                status = "PARTIAL"
            else:
                status = "LOW_COVERAGE"
        else:
            coverage = 0.0
            publication_coverage = 0.0
            status = "NO_MASTER_CANDIDATES" if unique_urls else "SOURCE_NOT_DISCOVERED"

        missing_count = sum(1 for row in unique_rows if row.final_category in MISSING_CATEGORIES)
        summary.append(
            {
                "source": source,
                "total_discovered_urls": len(source_rows),
                "unique_urls": len(unique_urls),
                "duplicate_urls": len(source_rows) - len(unique_urls),
                "current_v2_urls": sum(1 for row in source_rows if row.inventory_origin == "discovery_results_v2"),
                "legacy_only_urls": sum(1 for row in source_rows if row.inventory_origin == "legacy_ssip_db" and row.final_category != "DUPLICATE"),
                "successful_fetches": sum(
                    1
                    for row in unique_rows
                    if row.fetch_status in {"FETCHED", "FETCHED_FOR_EXTRACTION", "FETCHED_INFERRED_FROM_CLASSIFICATION", "BROWSER_RENDERED"}
                ),
                "failed_fetches": sum(1 for row in unique_rows if row.final_category == "FETCH_FAILED"),
                "browser_render_required_pages": sum(1 for row in unique_rows if row.browser_render_required),
                "scheme_programme_pages": sum(
                    1
                    for row in unique_rows
                    if row.classification.upper() in SCHEME_LIKE_CLASSIFICATIONS or bool(row.master_id)
                ),
                "non_scheme_pages": sum(1 for row in unique_rows if row.final_category == "NON_SCHEME_CONTENT"),
                "classification_uncertain_pages": sum(1 for row in unique_rows if row.final_category == "CLASSIFICATION_UNCERTAIN"),
                "master_candidates": len(master_ids),
                "extracted_records": len(extracted_by_source.get(source, set()) & master_ids),
                "validated_records": len(validated_by_source.get(source, set()) & master_ids),
                "validation_approved_records": len(validation_approved_by_source.get(source, set()) & master_ids),
                "staged_records": len(staged_master_ids),
                "admin_review_records": len(review_by_source.get(source, set()) & master_ids),
                "awaiting_admin_review_records": len(pending_review_by_source.get(source, set()) & master_ids),
                "rejected_records": len(rejected_by_source.get(source, set()) & master_ids),
                "missing_or_unprocessed_records": missing_count,
                "terminal_master_records": len(terminal_master_ids),
                "coverage_percentage": coverage,
                "publication_coverage_percentage": publication_coverage,
                "coverage_status": status,
            }
        )
    return summary



def build_master_backlog(
    masters: Sequence[dict[str, Any]],
    extracted_by_id: Mapping[str, dict[str, Any]],
    validated_by_id: Mapping[str, dict[str, Any]],
    db_state: DatabaseState,
) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    for master in masters:
        master_id = normalize_whitespace(master.get("master_id"))
        if not master_id:
            continue
        extracted = extracted_by_id.get(master_id)
        validated = validated_by_id.get(master_id)
        staged = db_state.staged.get(master_id)
        review = db_state.review.get(master_id)
        rejected = db_state.rejected.get(master_id)
        category, _, action = final_category_for(
            duplicate=False,
            fetch_status="FETCHED_INFERRED_FROM_CLASSIFICATION",
            browser_required=False,
            classified={"classification": "SCHEME"},
            master=master,
            extracted=extracted,
            validated=validated,
            staged=staged,
            review=review,
            rejected=rejected,
        )
        if category in {"FULLY_PROCESSED", "REJECTED"}:
            continue
        if staged is not None:
            database_status = "STAGED"
        elif rejected is not None:
            database_status = "REJECTED"
        elif review is not None:
            database_status = f"ADMIN_REVIEW_{normalize_whitespace(review.get('review_status')).upper() or 'PENDING'}"
        else:
            database_status = "NOT_PRESENT"
        backlog.append(
            {
                "master_id": master_id,
                "source": normalize_source(master.get("source")),
                "canonical_name": normalize_whitespace(master.get("canonical_name")),
                "master_type": normalize_whitespace(master.get("master_type")),
                "current_status": normalize_whitespace(master.get("current_status")),
                "readiness": normalize_whitespace(master.get("readiness")),
                "best_available_url": normalize_whitespace(master.get("best_available_url") or master.get("official_page_url")),
                "member_url_count": len(record_urls(master)),
                "extraction_status": "EXTRACTED" if extracted is not None else "NOT_EXTRACTED",
                "validation_decision": record_decision(validated),
                "database_status": database_status,
                "final_category": category,
                "recommended_action": action,
            }
        )
    backlog.sort(key=lambda row: (row["source"], row["final_category"], row["canonical_name"]))
    return backlog

def build_recommendations(
    source_rows: Sequence[dict[str, Any]],
    audit_rows: Sequence[AuditRow],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    priority = 1

    for source_summary_row in source_rows:
        if source_summary_row["coverage_status"] == "SOURCE_NOT_DISCOVERED":
            recommendations.append(
                {
                    "priority": priority,
                    "severity": "CRITICAL",
                    "source": source_summary_row["source"],
                    "action": "Add and execute an official source seed before claiming multi-source coverage.",
                    "reason": "No auditable discovery URLs or master candidates exist for this required source.",
                }
            )
            priority += 1

    category_counts = Counter(row.final_category for row in audit_rows if row.final_category != "DUPLICATE")
    action_templates = [
        ("MISSING_FROM_STAGING", "CRITICAL", "Run a targeted staging consistency repair after reviewing the affected master IDs."),
        ("AWAITING_ADMIN_REVIEW", "HIGH", "Complete or restore pending admin review records."),
        ("MISSING_FROM_MASTER", "HIGH", "Review scheme-like classified URLs and attach or create master candidates."),
        ("AWAITING_EXTRACTION", "HIGH", "Run source-prioritized incremental extraction for unextracted master candidates."),
        ("AWAITING_VALIDATION", "MEDIUM", "Run validation for extracted records with no validation output."),
        ("FETCH_FAILED", "MEDIUM", "Retry failed URLs and persist HTTP/error metadata."),
        ("BLOCKED_OR_LOGIN_REQUIRED", "MEDIUM", "Replace protected URLs with public official evidence or use browser-assisted capture."),
        ("BROWSER_RENDER_REQUIRED", "MEDIUM", "Use browser rendering and re-enter the classification pipeline."),
        ("CLASSIFICATION_UNCERTAIN", "MEDIUM", "Classify the unresolved discovery backlog or explicitly exclude it."),
    ]
    for category, severity, action in action_templates:
        count = category_counts.get(category, 0)
        if not count:
            continue
        affected_sources = sorted({row.source for row in audit_rows if row.final_category == category})
        recommendations.append(
            {
                "priority": priority,
                "severity": severity,
                "source": ", ".join(affected_sources),
                "category": category,
                "affected_url_count": count,
                "action": action,
                "reason": f"{count} unique URL(s) currently fall in {category}.",
            }
        )
        priority += 1

    low_coverage = sorted(
        (
            row
            for row in source_rows
            if row["master_candidates"] > 0 and row["coverage_percentage"] < 70
        ),
        key=lambda row: row["coverage_percentage"],
    )
    for row in low_coverage:
        recommendations.append(
            {
                "priority": priority,
                "severity": "HIGH",
                "source": row["source"],
                "action": "Process remaining master candidates in descending relevance/readiness order.",
                "reason": (
                    f"Terminal master coverage is {row['coverage_percentage']:.2f}% "
                    f"({row['terminal_master_records']}/{row['master_candidates']})."
                ),
            }
        )
        priority += 1
    return recommendations


def overall_summary(
    rows: Sequence[AuditRow],
    source_rows: Sequence[dict[str, Any]],
    masters: Sequence[dict[str, Any]],
    extracted_by_id: Mapping[str, dict[str, Any]],
    validated_by_id: Mapping[str, dict[str, Any]],
    db_state: DatabaseState,
) -> dict[str, Any]:
    master_ids = {normalize_whitespace(master.get("master_id")) for master in masters if normalize_whitespace(master.get("master_id"))}
    staged_ids = set(db_state.staged) & master_ids
    rejected_ids = set(db_state.rejected) & master_ids
    terminal_ids = staged_ids | rejected_ids
    unique_rows = [row for row in rows if row.final_category != "DUPLICATE"]
    category_counts = Counter(row.final_category for row in rows)
    coverage = round(100.0 * len(terminal_ids) / len(master_ids), 2) if master_ids else 0.0
    publication_coverage = round(100.0 * len(staged_ids) / len(master_ids), 2) if master_ids else 0.0
    return {
        "audit_version": AUDIT_VERSION,
        "required_sources": list(DEFAULT_SOURCES),
        "source_count": len(DEFAULT_SOURCES),
        "source_summary": list(source_rows),
        "total_discovery_occurrences": len(rows),
        "unique_discovered_urls": len({row.normalized_url for row in unique_rows}),
        "duplicate_occurrences": category_counts.get("DUPLICATE", 0),
        "classified_unique_urls": sum(1 for row in unique_rows if row.classification),
        "master_candidate_count": len(master_ids),
        "extracted_master_count": len(set(extracted_by_id) & master_ids),
        "validated_master_count": len(set(validated_by_id) & master_ids),
        "staged_master_count": len(staged_ids),
        "rejected_master_count": len(rejected_ids),
        "admin_review_queue_count": len(set(db_state.review) & master_ids),
        "awaiting_admin_review_count": sum(
            1
            for master_id, record in db_state.review.items()
            if master_id in master_ids
            and normalize_whitespace(record.get("review_status")).upper()
            in {"", "PENDING", "OPEN", "IN_REVIEW", "NEEDS_REVIEW"}
        ),
        "terminal_master_count": len(terminal_ids),
        "overall_coverage_percentage": coverage,
        "publication_coverage_percentage": publication_coverage,
        "final_category_counts": dict(sorted(category_counts.items())),
        "missing_or_unprocessed_unique_url_count": sum(1 for row in unique_rows if row.final_category in MISSING_CATEGORIES),
        "coverage_definition": (
            "Terminal master coverage = unique master candidates present in scheme_staging or "
            "rejected_scheme_records divided by all master candidates. Publication coverage uses "
            "scheme_staging only. Closed historical calls and supporting documents are not treated "
            "as missing solely because their application window is closed."
        ),
    }


def build_input_manifest(paths: AuditPaths, include_legacy: bool) -> dict[str, Any]:
    entries = {
        "discovery": file_manifest_entry(paths.discovery_path),
        "classified": file_manifest_entry(paths.classified_path),
        "masters": file_manifest_entry(paths.masters_path),
        "staging_database": file_manifest_entry(paths.staging_db_path),
        "meity_discovery_summary": file_manifest_entry(paths.meity_discovery_summary_path),
        "extracted_candidates": [file_manifest_entry(path) for path in paths.extracted_paths],
        "validated_candidates": [file_manifest_entry(path) for path in paths.validated_paths],
        "legacy_database": file_manifest_entry(paths.legacy_db_path) if include_legacy else {"included": False},
    }
    return entries


def run_audit(paths: AuditPaths, *, include_legacy: bool = True) -> AuditResult:
    discoveries = load_primary_discovery(paths.discovery_path)
    if include_legacy:
        discoveries.extend(load_legacy_discovery(paths.legacy_db_path))

    classified = load_json_list(paths.classified_path, required=True)
    masters = load_json_list(paths.masters_path, required=True)
    extracted_by_id, _ = merge_records_by_master_id(paths.extracted_paths)
    validated_by_id, _ = merge_records_by_master_id(paths.validated_paths)
    db_state = load_database_state(paths.staging_db_path)
    browser_urls = meity_browser_render_urls(paths.meity_discovery_summary_path, discoveries)

    rows = build_rows(
        discoveries,
        classified,
        masters,
        extracted_by_id,
        validated_by_id,
        db_state,
        browser_urls,
    )
    source_rows = source_summary(rows, masters, extracted_by_id, validated_by_id, db_state)
    recommendations = build_recommendations(source_rows, rows)
    master_backlog = build_master_backlog(masters, extracted_by_id, validated_by_id, db_state)
    summary = overall_summary(rows, source_rows, masters, extracted_by_id, validated_by_id, db_state)
    generated_at = utc_now()
    summary["generated_at"] = generated_at
    return AuditResult(
        generated_at=generated_at,
        rows=rows,
        source_summary=source_rows,
        overall_summary=summary,
        recommendations=recommendations,
        master_backlog=master_backlog,
        input_manifest=build_input_manifest(paths, include_legacy),
    )


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "url_json": output_dir / "multi_source_coverage_audit_v2_6.json",
        "url_csv": output_dir / "multi_source_coverage_audit_v2_6.csv",
        "source_csv": output_dir / "source_coverage_summary_v2_6.csv",
        "missing_csv": output_dir / "missing_pipeline_records_v2_6.csv",
        "summary_json": output_dir / "coverage_audit_summary_v2_6.json",
        "summary_txt": output_dir / "coverage_audit_summary_v2_6.txt",
        "master_backlog_csv": output_dir / "master_pipeline_backlog_v2_6.csv",
    }


def render_console_summary(result: AuditResult) -> str:
    lines = [
        "=" * 76,
        "SSIP Full Multi-Source Coverage Audit v2.6",
        "=" * 76,
        "",
        f"{'Source':26} {'Discovered':>10} {'Masters':>8} {'Terminal':>9} {'Missing':>8} {'Coverage':>9}",
        "-" * 76,
    ]
    for row in result.source_summary:
        lines.append(
            f"{row['source'][:26]:26} "
            f"{row['unique_urls']:>10} "
            f"{row['master_candidates']:>8} "
            f"{row['terminal_master_records']:>9} "
            f"{row['missing_or_unprocessed_records']:>8} "
            f"{row['coverage_percentage']:>8.2f}%"
        )
    summary = result.overall_summary
    counts = summary["final_category_counts"]
    lines.extend(
        [
            "",
            f"Overall Terminal Master Coverage: {summary['overall_coverage_percentage']:.2f}%",
            f"Publication Coverage:             {summary['publication_coverage_percentage']:.2f}%",
            f"Master Candidates:                {summary['master_candidate_count']}",
            f"Extracted / Validated:            {summary['extracted_master_count']} / {summary['validated_master_count']}",
            f"Staged / Rejected:                {summary['staged_master_count']} / {summary['rejected_master_count']}",
            "",
            f"Fully Processed URLs:             {counts.get('FULLY_PROCESSED', 0)}",
            f"Awaiting Extraction URLs:         {counts.get('AWAITING_EXTRACTION', 0)}",
            f"Awaiting Validation URLs:         {counts.get('AWAITING_VALIDATION', 0)}",
            f"Awaiting Admin Review URLs:       {counts.get('AWAITING_ADMIN_REVIEW', 0)}",
            f"Missing from Master URLs:         {counts.get('MISSING_FROM_MASTER', 0)}",
            f"Missing from Staging URLs:        {counts.get('MISSING_FROM_STAGING', 0)}",
            f"Fetch Failed URLs:                {counts.get('FETCH_FAILED', 0)}",
            f"Blocked/Login Required URLs:      {counts.get('BLOCKED_OR_LOGIN_REQUIRED', 0)}",
            f"Browser Render Required URLs:     {counts.get('BROWSER_RENDER_REQUIRED', 0)}",
            f"Classification Uncertain URLs:    {counts.get('CLASSIFICATION_UNCERTAIN', 0)}",
            f"Non-Scheme Content URLs:          {counts.get('NON_SCHEME_CONTENT', 0)}",
            f"Rejected URLs:                    {counts.get('REJECTED', 0)}",
            f"Duplicate Occurrences:            {counts.get('DUPLICATE', 0)}",
            "",
            "Audit completed successfully in read-only mode.",
        ]
    )
    return "\n".join(lines)


def write_outputs(result: AuditResult, output_dir: Path) -> dict[str, str]:
    paths = output_paths(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    row_dicts = [row.to_dict() for row in result.rows]
    url_payload = {
        "audit_version": AUDIT_VERSION,
        "generated_at": result.generated_at,
        "read_only": True,
        "records": row_dicts,
    }
    paths["url_json"].write_text(json.dumps(url_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(paths["url_csv"], row_dicts, URL_REPORT_COLUMNS)
    write_csv(paths["source_csv"], result.source_summary, SOURCE_REPORT_COLUMNS)
    missing_rows = [row for row in row_dicts if row["final_category"] in MISSING_CATEGORIES]
    write_csv(paths["missing_csv"], missing_rows, URL_REPORT_COLUMNS)
    write_csv(paths["master_backlog_csv"], result.master_backlog, MASTER_BACKLOG_COLUMNS)

    summary_payload = dict(result.overall_summary)
    summary_payload["read_only"] = True
    summary_payload["recommendations"] = result.recommendations
    summary_payload["master_pipeline_backlog"] = result.master_backlog
    summary_payload["input_manifest"] = result.input_manifest
    summary_payload["output_files"] = {key: str(value) for key, value in paths.items()}
    paths["summary_json"].write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary_txt"].write_text(render_console_summary(result) + "\n", encoding="utf-8")
    return {key: str(value) for key, value in paths.items()}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only SSIP Full Multi-Source Coverage Audit v2.6")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="SSIP project root (default: current directory)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Report directory (default: <project-root>/data/audit)",
    )
    parser.add_argument(
        "--no-legacy-discovery",
        action="store_true",
        help="Exclude legacy database/ssip.db discovered_links from the URL audit universe.",
    )
    parser.add_argument(
        "--json-console",
        action="store_true",
        help="Print the overall summary as JSON instead of the human-readable table.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = AuditPaths.from_project_root(args.project_root, args.output_dir)
    try:
        result = run_audit(paths, include_legacy=not args.no_legacy_discovery)
        written = write_outputs(result, paths.output_dir)
    except (CoverageAuditError, FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"Coverage audit failed: {exc}", file=sys.stderr)
        return 2

    if args.json_console:
        print(json.dumps(result.overall_summary, ensure_ascii=False, indent=2))
    else:
        print(render_console_summary(result))
        print("\nReports:")
        for key, value in written.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
