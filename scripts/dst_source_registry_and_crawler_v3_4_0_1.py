#!/usr/bin/env python3
"""
SSIP v3.4.0.1 — DST Source Registry and Department Crawler

Purpose
-------
Build a curated Department of Science & Technology (DST) source registry and
crawl relevant official DST pages without promoting page titles into canonical
scheme identities. The output is source evidence for later page-role
classification and scheme/call relationship resolution.

Key safeguards
--------------
* Permanent scheme identity is NOT created or renamed in this phase.
* Time-bound calls remain source pages with CALL_* hints.
* The crawler stays on dst.gov.in for HTML traversal.
* External official/implementing portals are recorded, not recursively crawled.
* Crawl state is resumable and idempotent through SQLite.
* robots.txt is respected; in "respect" mode, an unavailable robots file is
  logged and crawling proceeds conservatively. Use "strict" to deny instead.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as exc:  # pragma: no cover - clear operator message
    missing = getattr(exc, "name", "dependency")
    raise SystemExit(
        f"Missing Python dependency: {missing}. Install with: "
        "python -m pip install requests beautifulsoup4"
    ) from exc


VERSION = "3.4.0.1"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"
BASE_URL = "https://dst.gov.in/"
DEFAULT_USER_AGENT = (
    "SSIP-DST-Crawler/3.4.0.1 "
    "(government-scheme source registry; respectful research crawler)"
)

DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".txt", ".rtf", ".odt", ".ods", ".odp",
}
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".zip", ".rar",
    ".7z", ".tar", ".gz",
}
TRACKING_QUERY_PREFIXES = (
    "utm_", "fbclid", "gclid", "mc_", "ref", "source", "campaign"
)
ALLOWED_QUERY_KEYS = {"page"}

# These patterns are crawl filters, not final page-role classifications.
STRONG_RELEVANCE_TERMS = (
    "scheme", "schemes", "programme", "programmes", "program", "initiative",
    "fellowship", "mission", "fund", "grant", "proposal", "call", "guideline",
    "eligibility", "application", "support", "innovation", "technology",
    "research", "capacity", "infrastructure", "startup", "start-up",
    "scientist", "sanctioned project", "funding mechanism",
)
NON_SCHEME_HINT_TERMS = (
    "recruitment", "tender", "vacancy", "press release", "newsletter",
    "award", "result", "parliament", "pension", "vigilance", "directory",
    "contact us", "feedback", "terms", "privacy", "accessibility",
)


DEFAULT_SEEDS: list[dict[str, Any]] = [
    {
        "seed_id": "DST-ROOT-001",
        "source_group": "DEPARTMENT_ROOT",
        "source_role_hint": "DEPARTMENT_HOME",
        "url": "https://dst.gov.in/",
        "priority": 70,
        "crawl_depth": 1,
        "rationale": "Official DST department root; used for ownership and top-level discovery.",
    },
    {
        "seed_id": "DST-SCHEME-INDEX-001",
        "source_group": "SCHEMES_AND_PROGRAMMES",
        "source_role_hint": "SCHEME_PROGRAMME_INDEX",
        "url": "https://dst.gov.in/schemes-programmes",
        "priority": 100,
        "crawl_depth": 5,
        "rationale": "Primary official index for permanent DST schemes and programmes.",
    },
    {
        "seed_id": "DST-RDI-001",
        "source_group": "SCHEMES_AND_PROGRAMMES",
        "source_role_hint": "SCHEME_PROGRAMME_CANDIDATE",
        "url": "https://dst.gov.in/rdi-scheme/research-development-and-innovation-rdi-cell",
        "priority": 95,
        "crawl_depth": 3,
        "rationale": "Official RDI scheme page and related implementation evidence.",
    },
    {
        "seed_id": "DST-CAPACITY-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/human-capacity-building-programmes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official S&T capacity-building category page.",
    },
    {
        "seed_id": "DST-INSTITUTION-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/institutional-capacity-building-programmes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official institutional capacity-building scheme category.",
    },
    {
        "seed_id": "DST-RD-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/research-development-programmes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official research and development programme category.",
    },
    {
        "seed_id": "DST-INNOVATION-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/innovation-and-technology-development-programmes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official innovation and technology-development category.",
    },
    {
        "seed_id": "DST-SOCIETY-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/science-society-programmes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official science-for-society programme category.",
    },
    {
        "seed_id": "DST-MISSIONS-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/national-missions",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official national missions category.",
    },
    {
        "seed_id": "DST-INTL-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/international-cooperation-mega-science",
        "priority": 92,
        "crawl_depth": 4,
        "rationale": "Official international cooperation and mega-science category.",
    },
    {
        "seed_id": "DST-DATA-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/st-data-policy-and-training",
        "priority": 92,
        "crawl_depth": 4,
        "rationale": "Official S&T data, policy and training category.",
    },
    {
        "seed_id": "DST-STATE-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/state-st",
        "priority": 92,
        "crawl_depth": 4,
        "rationale": "Official state science and technology initiatives category.",
    },
    {
        "seed_id": "DST-GLP-001",
        "source_group": "SCHEME_CATEGORIES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/ngcma",
        "priority": 88,
        "crawl_depth": 3,
        "rationale": "Official Good Laboratory Practice / NGCMA programme source.",
    },
    {
        "seed_id": "DST-CALL-CURRENT-001",
        "source_group": "CALLS_FOR_PROPOSALS",
        "source_role_hint": "CALL_INDEX_CURRENT",
        "url": "https://dst.gov.in/call-for-proposals",
        "priority": 100,
        "crawl_depth": 4,
        "rationale": "Current time-bound DST calls; must remain separate from scheme identity.",
    },
    {
        "seed_id": "DST-CALL-ARCHIVE-001",
        "source_group": "CALLS_FOR_PROPOSALS",
        "source_role_hint": "CALL_INDEX_ARCHIVE",
        "url": "https://dst.gov.in/archive-call-for-proposals",
        "priority": 100,
        "crawl_depth": 5,
        "rationale": "Paginated archive used to reconstruct recurring calls and parent schemes.",
    },
    {
        "seed_id": "DST-GUIDELINES-001",
        "source_group": "GUIDELINES_AND_OMS",
        "source_role_hint": "GUIDELINES_INDEX",
        "url": "https://dst.gov.in/oms-and-guidelines",
        "priority": 90,
        "crawl_depth": 4,
        "rationale": "Official OMs and guidelines supporting scheme and call evidence.",
    },
    {
        "seed_id": "DST-SEED-PROGRAMMES-001",
        "source_group": "DIVISIONAL_PROGRAMMES",
        "source_role_hint": "PROGRAMME_CATEGORY",
        "url": "https://dst.gov.in/programmes-innitiatives",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official SEED programmes and initiatives page (official URL spelling retained).",
    },
    {
        "seed_id": "DST-SEED-SCHEMES-001",
        "source_group": "DIVISIONAL_PROGRAMMES",
        "source_role_hint": "SCHEME_PROGRAMME_INDEX",
        "url": "https://dst.gov.in/about-schemes",
        "priority": 95,
        "crawl_depth": 4,
        "rationale": "Official SEED operational scheme inventory and eligibility evidence.",
    },
    {
        "seed_id": "DST-SEED-APPLY-001",
        "source_group": "APPLICATION_SUPPORT",
        "source_role_hint": "APPLICATION_GUIDANCE",
        "url": "https://dst.gov.in/how-apply-project-support",
        "priority": 85,
        "crawl_depth": 3,
        "rationale": "Official application process guidance and e-PMS linkage.",
    },
    {
        "seed_id": "DST-SANCTIONED-001",
        "source_group": "HISTORICAL_EVIDENCE",
        "source_role_hint": "SANCTIONED_PROJECTS_INDEX",
        "url": "https://dst.gov.in/sanctioned-projects",
        "priority": 82,
        "crawl_depth": 3,
        "rationale": "Historical programme, renaming and implementation evidence.",
    },
    {
        "seed_id": "DST-ARCHIVE-001",
        "source_group": "HISTORICAL_EVIDENCE",
        "source_role_hint": "DIVISION_ARCHIVE",
        "url": "https://dst.gov.in/archive",
        "priority": 78,
        "crawl_depth": 3,
        "rationale": "Division-level archived programme evidence; not a generic site archive.",
    },
    {
        "seed_id": "DST-ANNOUNCEMENT-001",
        "source_group": "SUPPORTING_ANNOUNCEMENTS",
        "source_role_hint": "ANNOUNCEMENT_INDEX",
        "url": "https://dst.gov.in/whatsnew/announcement",
        "priority": 68,
        "crawl_depth": 2,
        "rationale": "Mixed announcements used only for supporting evidence and exclusions.",
    },
]

KNOWN_OFFICIAL_EXTERNAL_DOMAINS = {
    "onlinedst.gov.in": "DST_APPLICATION_PORTAL",
    "nidhi.dst.gov.in": "DST_PROGRAMME_PORTAL",
    "rdifund.anrf.gov.in": "IMPLEMENTING_AGENCY_PORTAL",
    "anrf.gov.in": "IMPLEMENTING_AGENCY_PORTAL",
    "tdb.gov.in": "IMPLEMENTING_AGENCY_PORTAL",
    "aistic.gov.in": "GOVERNMENT_COOPERATION_PORTAL",
    "india.gov.in": "GOVERNMENT_PORTAL",
    "nic.in": "GOVERNMENT_TECHNICAL_HOST",
}


@dataclass(frozen=True)
class CrawlerConfig:
    project_root: Path
    output_dir: Path
    state_db: Path
    user_agent: str = DEFAULT_USER_AGENT
    connect_timeout: float = 12.0
    read_timeout: float = 45.0
    delay_seconds: float = 0.75
    max_pages: int = 0
    max_depth: int = 5
    retries: int = 3
    max_html_bytes: int = 12 * 1024 * 1024
    max_document_bytes: int = 60 * 1024 * 1024
    save_html_snapshots: bool = True
    download_documents: bool = False
    max_documents: int = 0
    include_hindi: bool = False
    robots_mode: str = "respect"
    config_path: Optional[Path] = None


@dataclass(frozen=True)
class ParsedPage:
    title: str
    canonical_url: str
    language: str
    text_content: str
    text_excerpt: str
    word_count: int
    page_role_hint: str
    last_updated_text: str
    links: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(prefix: str, value: str, length: int = 20) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def ascii_slug(value: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return (slug or "item")[:max_length]


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def is_document_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return Path(path).suffix in DOCUMENT_EXTENSIONS


def should_skip_extension(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return Path(path).suffix in SKIP_EXTENSIONS


def canonical_host(hostname: str) -> str:
    host = (hostname or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(raw_url: str, base_url: str = BASE_URL) -> Optional[str]:
    if not raw_url:
        return None
    raw_url = raw_url.strip()
    if raw_url.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    absolute = urljoin(base_url, raw_url)
    parts = urlsplit(absolute)
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    host = canonical_host(parts.hostname or "")
    if not host:
        return None
    scheme = "https"
    port = parts.port
    netloc = host
    if port and port not in {80, 443}:
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = re.sub(r"/+$", "", path) or "/"
    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower in ALLOWED_QUERY_KEYS:
            query_items.append((key_lower, value.strip()))
        elif any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
    query_items.sort()
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def is_internal_dst_url(url: str) -> bool:
    host = canonical_host(urlsplit(url).hostname or "")
    return host == "dst.gov.in"


def classify_external_authority(url: str) -> str:
    host = canonical_host(urlsplit(url).hostname or "")
    if host in KNOWN_OFFICIAL_EXTERNAL_DOMAINS:
        return KNOWN_OFFICIAL_EXTERNAL_DOMAINS[host]
    for known_host, authority in KNOWN_OFFICIAL_EXTERNAL_DOMAINS.items():
        if host.endswith("." + known_host):
            return authority
    if host.endswith(".gov.in"):
        return "OTHER_GOVERNMENT_PORTAL"
    if host.endswith(".nic.in"):
        return "GOVERNMENT_TECHNICAL_HOST"
    return "OTHER_EXTERNAL"


def infer_role_hint(url: str, title_or_anchor: str = "", inherited_hint: str = "") -> str:
    value = f"{urlsplit(url).path} {title_or_anchor}".lower()
    if is_document_url(url):
        return "DOCUMENT"
    if "archive-call-for-proposals" in value:
        return "CALL_INDEX_ARCHIVE"
    if "/callforproposals" in value or "call for proposal" in value or "call for proposals" in value:
        return "CALL_CANDIDATE"
    if "oms-and-guidelines" in value or "guideline" in value or "manual" in value:
        return "GUIDELINE_OR_MANUAL_CANDIDATE"
    if "sanctioned-project" in value:
        return "SANCTIONED_PROJECTS_EVIDENCE"
    if "scheme" in value or "programme" in value or "program" in value or "initiative" in value:
        return "SCHEME_PROGRAMME_CANDIDATE"
    if any(term in value for term in NON_SCHEME_HINT_TERMS):
        return "NON_SCHEME_HINT"
    if inherited_hint.startswith("CALL_"):
        return "CALL_SUPPORTING_PAGE"
    if inherited_hint in {"SCHEME_PROGRAMME_INDEX", "PROGRAMME_CATEGORY"}:
        return "SCHEME_PROGRAMME_SUPPORTING_PAGE"
    return "UNCLASSIFIED_SOURCE_PAGE"


def relevance_score(url: str, anchor_text: str, source_hint: str, in_main_content: bool) -> int:
    text = f"{urlsplit(url).path} {anchor_text}".lower()
    score = 0
    if in_main_content:
        score += 30
    if any(term in text for term in STRONG_RELEVANCE_TERMS):
        score += 55
    if source_hint in {
        "SCHEME_PROGRAMME_INDEX", "PROGRAMME_CATEGORY", "CALL_INDEX_CURRENT",
        "CALL_INDEX_ARCHIVE", "GUIDELINES_INDEX", "DIVISION_ARCHIVE",
        "SANCTIONED_PROJECTS_INDEX",
    }:
        score += 20
    if "page=" in url and source_hint in {"CALL_INDEX_ARCHIVE", "CALL_INDEX_CURRENT", "ANNOUNCEMENT_INDEX"}:
        score += 70
    if any(term in text for term in NON_SCHEME_HINT_TERMS):
        score -= 50
    return score


def should_enqueue_internal(
    url: str,
    anchor_text: str,
    source_hint: str,
    depth: int,
    max_depth: int,
    include_hindi: bool,
    in_main_content: bool,
) -> tuple[bool, str, int]:
    if depth > max_depth:
        return False, "MAX_DEPTH", -999
    path = urlsplit(url).path.lower()
    if not include_hindi and (path == "/hi" or path.startswith("/hi/")):
        return False, "HINDI_EXCLUDED", -999
    if should_skip_extension(url):
        return False, "STATIC_ASSET", -999
    if is_document_url(url):
        return False, "DOCUMENT_RECORDED_SEPARATELY", 100
    blocked_prefixes = (
        "/user", "/admin", "/search", "/node/add", "/rss", "/feed",
        "/print", "/sitemap", "/contact-us", "/feedback", "/website-policy",
        "/terms", "/help", "/screen-reader-access",
    )
    if path.startswith(blocked_prefixes):
        return False, "BLOCKED_PATH", -999
    score = relevance_score(url, anchor_text, source_hint, in_main_content)
    # Main-content links from curated seeds are valuable even if their slugs do
    # not contain obvious keywords (e.g., /purse, /ngp, /sathi).
    threshold = 30 if in_main_content else 70
    return score >= threshold, ("RELEVANT" if score >= threshold else "LOW_RELEVANCE"), score


class StateDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_registry (
                seed_id TEXT PRIMARY KEY,
                department_code TEXT NOT NULL,
                department_name TEXT NOT NULL,
                source_group TEXT NOT NULL,
                source_role_hint TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                normalized_url TEXT NOT NULL,
                priority INTEGER NOT NULL,
                crawl_depth INTEGER NOT NULL,
                rationale TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS frontier (
                normalized_url TEXT PRIMARY KEY,
                requested_url TEXT NOT NULL,
                parent_url TEXT,
                anchor_text TEXT,
                depth INTEGER NOT NULL,
                max_depth INTEGER NOT NULL,
                source_role_hint TEXT NOT NULL,
                priority INTEGER NOT NULL,
                relevance_score INTEGER NOT NULL DEFAULT 0,
                discovery_reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                discovered_at TEXT NOT NULL,
                last_attempt_at TEXT,
                completed_at TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS pages (
                page_id TEXT PRIMARY KEY,
                requested_url TEXT NOT NULL,
                normalized_url TEXT NOT NULL UNIQUE,
                final_url TEXT NOT NULL,
                canonical_url TEXT,
                parent_url TEXT,
                depth INTEGER NOT NULL,
                source_role_hint TEXT NOT NULL,
                page_role_hint TEXT NOT NULL,
                http_status INTEGER,
                content_type TEXT,
                charset TEXT,
                title TEXT,
                language TEXT,
                fetched_at TEXT NOT NULL,
                last_modified_header TEXT,
                etag TEXT,
                last_updated_text TEXT,
                content_length_header INTEGER,
                bytes_received INTEGER NOT NULL,
                content_sha256 TEXT,
                text_sha256 TEXT,
                word_count INTEGER NOT NULL DEFAULT 0,
                link_count INTEGER NOT NULL DEFAULT 0,
                text_excerpt TEXT,
                snapshot_path TEXT,
                duplicate_of_page_id TEXT,
                robots_decision TEXT,
                fetch_duration_ms INTEGER,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS links (
                from_url TEXT NOT NULL,
                to_url TEXT NOT NULL,
                normalized_to_url TEXT,
                anchor_text TEXT,
                rel TEXT,
                in_main_content INTEGER NOT NULL DEFAULT 0,
                is_internal INTEGER NOT NULL,
                is_document INTEGER NOT NULL,
                authority_class TEXT,
                role_hint TEXT,
                relevance_score INTEGER NOT NULL DEFAULT 0,
                enqueue_decision TEXT,
                discovered_at TEXT NOT NULL,
                PRIMARY KEY (from_url, to_url, anchor_text)
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                final_url TEXT,
                source_url TEXT,
                anchor_text TEXT,
                role_hint TEXT,
                filename TEXT,
                extension TEXT,
                authority_class TEXT,
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                http_status INTEGER,
                content_type TEXT,
                content_length_header INTEGER,
                bytes_received INTEGER,
                content_sha256 TEXT,
                snapshot_path TEXT,
                discovered_at TEXT NOT NULL,
                fetched_at TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS external_links (
                external_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                external_url TEXT NOT NULL,
                anchor_text TEXT,
                authority_class TEXT NOT NULL,
                role_hint TEXT,
                discovered_at TEXT NOT NULL,
                UNIQUE(source_url, external_url, anchor_text)
            );

            CREATE TABLE IF NOT EXISTS errors (
                error_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                stage TEXT NOT NULL,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                occurred_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_frontier_status_priority
                ON frontier(status, priority DESC, depth ASC, discovered_at ASC);
            CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages(content_sha256);
            CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
            CREATE INDEX IF NOT EXISTS idx_links_from ON links(from_url);
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('service_version', ?)",
            (VERSION,),
        )
        self.conn.commit()

    def recover_interrupted(self) -> None:
        self.conn.execute(
            "UPDATE frontier SET status='PENDING', last_error='Recovered after interrupted run' "
            "WHERE status='FETCHING'"
        )
        self.conn.execute(
            "UPDATE documents SET status='DISCOVERED', error='Recovered after interrupted run' "
            "WHERE status='FETCHING'"
        )
        self.conn.commit()

    def reset_crawl_state(self) -> None:
        self.conn.executescript(
            """
            DELETE FROM frontier;
            DELETE FROM pages;
            DELETE FROM links;
            DELETE FROM documents;
            DELETE FROM external_links;
            DELETE FROM errors;
            """
        )
        self.conn.commit()

    def refresh_pages(self) -> None:
        self.conn.execute(
            "UPDATE frontier SET status='PENDING', attempts=0, completed_at=NULL, "
            "last_error=NULL WHERE status IN ('DONE','FAILED','ROBOTS_DENIED')"
        )
        self.conn.commit()

    def upsert_seed(self, seed: Mapping[str, Any]) -> None:
        normalized = normalize_url(str(seed["url"]))
        if not normalized:
            raise ValueError(f"Invalid seed URL: {seed['url']}")
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO source_registry(
                seed_id, department_code, department_name, source_group,
                source_role_hint, url, normalized_url, priority, crawl_depth,
                rationale, active, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(seed_id) DO UPDATE SET
                source_group=excluded.source_group,
                source_role_hint=excluded.source_role_hint,
                url=excluded.url,
                normalized_url=excluded.normalized_url,
                priority=excluded.priority,
                crawl_depth=excluded.crawl_depth,
                rationale=excluded.rationale,
                active=1
            """,
            (
                seed["seed_id"], DEPARTMENT_CODE, DEPARTMENT_NAME,
                seed["source_group"], seed["source_role_hint"], seed["url"],
                normalized, int(seed["priority"]), int(seed["crawl_depth"]),
                seed["rationale"], now,
            ),
        )
        self.enqueue(
            requested_url=str(seed["url"]),
            parent_url=None,
            anchor_text=str(seed["source_role_hint"]),
            depth=0,
            max_depth=int(seed["crawl_depth"]),
            source_role_hint=str(seed["source_role_hint"]),
            priority=int(seed["priority"]),
            relevance=100,
            discovery_reason="CURATED_SEED",
        )
        self.conn.commit()

    def enqueue(
        self,
        requested_url: str,
        parent_url: Optional[str],
        anchor_text: str,
        depth: int,
        max_depth: int,
        source_role_hint: str,
        priority: int,
        relevance: int,
        discovery_reason: str,
    ) -> bool:
        normalized = normalize_url(requested_url, parent_url or BASE_URL)
        if not normalized:
            return False
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO frontier(
                normalized_url, requested_url, parent_url, anchor_text, depth,
                max_depth, source_role_hint, priority, relevance_score,
                discovery_reason, status, attempts, discovered_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?, 'PENDING', 0, ?)
            """,
            (
                normalized, requested_url, parent_url, collapse_ws(anchor_text),
                depth, max_depth, source_role_hint, priority, relevance,
                discovery_reason, utc_now(),
            ),
        )
        if cur.rowcount == 0:
            # Improve existing frontier metadata when a stronger path is found.
            self.conn.execute(
                """
                UPDATE frontier SET
                    priority = MAX(priority, ?),
                    relevance_score = MAX(relevance_score, ?),
                    max_depth = MAX(max_depth, ?),
                    source_role_hint = CASE
                        WHEN ? IN ('SCHEME_PROGRAMME_INDEX','PROGRAMME_CATEGORY',
                                   'CALL_INDEX_CURRENT','CALL_INDEX_ARCHIVE',
                                   'GUIDELINES_INDEX','SANCTIONED_PROJECTS_INDEX')
                        THEN ? ELSE source_role_hint END
                WHERE normalized_url=?
                """,
                (priority, relevance, max_depth, source_role_hint, source_role_hint, normalized),
            )
        return cur.rowcount > 0

    def next_frontier(self) -> Optional[sqlite3.Row]:
        row = self.conn.execute(
            """
            SELECT * FROM frontier
            WHERE status='PENDING'
            ORDER BY priority DESC, relevance_score DESC, depth ASC, discovered_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE frontier SET status='FETCHING', attempts=attempts+1,
                    last_attempt_at=? WHERE normalized_url=?
                """,
                (utc_now(), row["normalized_url"]),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM frontier WHERE normalized_url=?",
                (row["normalized_url"],),
            ).fetchone()
        return row

    def complete_frontier(self, normalized_url: str, status: str = "DONE", error: str = "") -> None:
        self.conn.execute(
            """
            UPDATE frontier SET status=?, completed_at=?, last_error=?
            WHERE normalized_url=?
            """,
            (status, utc_now(), error or None, normalized_url),
        )
        self.conn.commit()

    def record_page(self, record: Mapping[str, Any]) -> None:
        columns = list(record.keys())
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != "page_id")
        self.conn.execute(
            f"INSERT INTO pages({','.join(columns)}) VALUES({placeholders}) "
            f"ON CONFLICT(normalized_url) DO UPDATE SET {updates}",
            tuple(record[c] for c in columns),
        )
        self.conn.commit()

    def find_duplicate_page(self, content_sha256: str, normalized_url: str) -> Optional[str]:
        if not content_sha256:
            return None
        row = self.conn.execute(
            """
            SELECT page_id FROM pages
            WHERE content_sha256=? AND normalized_url<>? AND http_status BETWEEN 200 AND 299
            ORDER BY fetched_at ASC LIMIT 1
            """,
            (content_sha256, normalized_url),
        ).fetchone()
        return str(row["page_id"]) if row else None

    def record_link(self, record: Mapping[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO links(
                from_url,to_url,normalized_to_url,anchor_text,rel,in_main_content,
                is_internal,is_document,authority_class,role_hint,relevance_score,
                enqueue_decision,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["from_url"], record["to_url"], record.get("normalized_to_url"),
                record.get("anchor_text", ""), record.get("rel", ""),
                int(bool(record.get("in_main_content"))), int(bool(record.get("is_internal"))),
                int(bool(record.get("is_document"))), record.get("authority_class"),
                record.get("role_hint"), int(record.get("relevance_score", 0)),
                record.get("enqueue_decision"), record.get("discovered_at", utc_now()),
            ),
        )

    def record_document(
        self,
        url: str,
        source_url: str,
        anchor_text: str,
        role_hint: str,
        authority_class: str,
    ) -> None:
        normalized = normalize_url(url, source_url)
        if not normalized:
            return
        filename = Path(urlsplit(normalized).path).name or "document"
        extension = Path(filename).suffix.lower()
        self.conn.execute(
            """
            INSERT INTO documents(
                document_id,url,source_url,anchor_text,role_hint,filename,extension,
                authority_class,status,discovered_at
            ) VALUES(?,?,?,?,?,?,?,?, 'DISCOVERED', ?)
            ON CONFLICT(url) DO UPDATE SET
                source_url=COALESCE(documents.source_url, excluded.source_url),
                anchor_text=CASE WHEN length(excluded.anchor_text)>length(documents.anchor_text)
                                 THEN excluded.anchor_text ELSE documents.anchor_text END,
                role_hint=excluded.role_hint
            """,
            (
                stable_id("dst_doc", normalized), normalized, source_url,
                collapse_ws(anchor_text), role_hint, filename, extension,
                authority_class, utc_now(),
            ),
        )

    def record_external(
        self,
        source_url: str,
        external_url: str,
        anchor_text: str,
        authority_class: str,
        role_hint: str,
    ) -> None:
        normalized = normalize_url(external_url, source_url)
        if not normalized:
            return
        external_id = stable_id("dst_ext", f"{source_url}|{normalized}|{anchor_text}")
        self.conn.execute(
            """
            INSERT OR IGNORE INTO external_links(
                external_id,source_url,external_url,anchor_text,authority_class,
                role_hint,discovered_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                external_id, source_url, normalized, collapse_ws(anchor_text),
                authority_class, role_hint, utc_now(),
            ),
        )

    def record_error(self, url: str, stage: str, exc: BaseException | str, attempt: int) -> None:
        message = collapse_ws(str(exc))[:2000]
        error_type = type(exc).__name__ if isinstance(exc, BaseException) else "CrawlerError"
        error_id = stable_id("dst_err", f"{url}|{stage}|{attempt}|{message}|{utc_now()}")
        self.conn.execute(
            """
            INSERT INTO errors(error_id,url,stage,error_type,message,attempt,occurred_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (error_id, url, stage, error_type, message, attempt, utc_now()),
        )
        self.conn.commit()

    def next_document(self) -> Optional[sqlite3.Row]:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE status='DISCOVERED' ORDER BY discovered_at LIMIT 1"
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE documents SET status='FETCHING' WHERE document_id=?",
                (row["document_id"],),
            )
            self.conn.commit()
        return row

    def update_document(self, document_id: str, values: Mapping[str, Any]) -> None:
        assignments = ",".join(f"{key}=?" for key in values)
        self.conn.execute(
            f"UPDATE documents SET {assignments} WHERE document_id=?",
            tuple(values.values()) + (document_id,),
        )
        self.conn.commit()

    def table_rows(self, table: str) -> list[dict[str, Any]]:
        allowed = {
            "source_registry", "frontier", "pages", "links", "documents",
            "external_links", "errors",
        }
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")
        rows = self.conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]

    def count(self, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
        allowed = {
            "source_registry", "frontier", "pages", "links", "documents",
            "external_links", "errors",
        }
        if table not in allowed:
            raise ValueError(table)
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += " WHERE " + where
        return int(self.conn.execute(sql, params).fetchone()[0])


class RobotsPolicy:
    def __init__(self, session: requests.Session, user_agent: str, mode: str, timeout: tuple[float, float]) -> None:
        self.session = session
        self.user_agent = user_agent
        self.mode = mode
        self.timeout = timeout
        self.parser = RobotFileParser()
        self.status = "NOT_LOADED"
        self.error = ""
        self._load()

    def _load(self) -> None:
        robots_url = urljoin(BASE_URL, "/robots.txt")
        self.parser.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.timeout, allow_redirects=True)
            if response.status_code == 200 and response.text.strip():
                self.parser.parse(response.text.splitlines())
                self.status = "LOADED"
            elif response.status_code in {401, 403}:
                self.status = "DENY_ALL_BY_STATUS"
            else:
                self.status = f"UNAVAILABLE_HTTP_{response.status_code}"
        except requests.RequestException as exc:
            self.status = "UNAVAILABLE_ERROR"
            self.error = str(exc)

    def can_fetch(self, url: str) -> tuple[bool, str]:
        if self.status == "LOADED":
            allowed = bool(self.parser.can_fetch(self.user_agent, url))
            return allowed, "ROBOTS_ALLOWED" if allowed else "ROBOTS_DENIED"
        if self.status == "DENY_ALL_BY_STATUS":
            return False, self.status
        if self.mode == "strict":
            return False, f"{self.status}_STRICT_DENY"
        return True, f"{self.status}_CONSERVATIVE_ALLOW"


class DSTCrawler:
    def __init__(self, config: CrawlerConfig, db: StateDB, seeds: list[dict[str, Any]]) -> None:
        self.config = config
        self.db = db
        self.seeds = seeds
        self.logger = logging.getLogger("ssip.dst.crawler")
        self.session = self._build_session()
        self.robots = RobotsPolicy(
            self.session,
            config.user_agent,
            config.robots_mode,
            (config.connect_timeout, config.read_timeout),
        )
        self.last_request_monotonic = 0.0
        self.pages_processed_this_run = 0
        self.documents_processed_this_run = 0

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.config.retries,
            connect=self.config.retries,
            read=self.config.retries,
            status=self.config.retries,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf,application/msword,"
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document;q=0.9,*/*;q=0.5",
                "Accept-Language": "en-IN,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )
        return session

    def seed_registry(self) -> None:
        for seed in self.seeds:
            self.db.upsert_seed(seed)

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self.last_request_monotonic
        remaining = self.config.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_monotonic = time.monotonic()

    def _read_limited_response(self, response: requests.Response, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"Response exceeded configured limit of {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def _snapshot_html(self, normalized_url: str, content: bytes) -> str:
        if not self.config.save_html_snapshots:
            return ""
        token = sha256_text(normalized_url)[:16]
        slug = ascii_slug(urlsplit(normalized_url).path.strip("/") or "home", 70)
        path = self.config.output_dir / "snapshots" / "html" / f"{slug}_{token}.html.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wb") as handle:
            handle.write(content)
        os.replace(tmp, path)
        return str(path.relative_to(self.config.output_dir))

    def parse_html(self, html_bytes: bytes, final_url: str, inherited_hint: str) -> ParsedPage:
        soup = BeautifulSoup(html_bytes, "html.parser")
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = collapse_ws(h1.get_text(" ", strip=True))
        if not title and soup.title:
            title = collapse_ws(soup.title.get_text(" ", strip=True))
        canonical = ""
        canonical_tag = soup.find("link", attrs={"rel": lambda v: v and "canonical" in v})
        if canonical_tag and canonical_tag.get("href"):
            canonical = normalize_url(str(canonical_tag.get("href")), final_url) or ""
        html_tag = soup.find("html")
        language = collapse_ws(str(html_tag.get("lang", ""))) if html_tag else ""

        # Extract main-content links first, before destructive text cleanup.
        main_root = None
        selectors = [
            "main", "#main-content", "#content", ".main-content", ".region-content",
            ".field-name-body", "article", ".content",
        ]
        for selector in selectors:
            main_root = soup.select_one(selector)
            if main_root:
                break
        if main_root is None:
            main_root = soup.body or soup

        links: list[dict[str, Any]] = []
        seen_link_keys: set[tuple[str, str]] = set()
        main_nodes = set(main_root.find_all("a", href=True))
        for anchor in soup.find_all("a", href=True):
            href_raw = str(anchor.get("href", "")).strip()
            normalized = normalize_url(href_raw, final_url)
            if not normalized:
                continue
            anchor_text = collapse_ws(anchor.get_text(" ", strip=True))
            rel_attr = anchor.get("rel") or []
            rel = " ".join(rel_attr) if isinstance(rel_attr, list) else str(rel_attr)
            key = (normalized, anchor_text)
            if key in seen_link_keys:
                continue
            seen_link_keys.add(key)
            links.append(
                {
                    "raw_url": href_raw,
                    "url": normalized,
                    "anchor_text": anchor_text,
                    "rel": rel,
                    "in_main_content": anchor in main_nodes,
                }
            )

        for tag in soup(["script", "style", "noscript", "template", "svg", "form"]):
            tag.decompose()
        for selector in ["nav", "header", "footer", ".breadcrumb", ".social-media", ".accessibility"]:
            for node in soup.select(selector):
                node.decompose()
        text_root = None
        for selector in selectors:
            text_root = soup.select_one(selector)
            if text_root:
                break
        if text_root is None:
            text_root = soup.body or soup
        text = collapse_ws(text_root.get_text(" ", strip=True))
        excerpt = text[:1500]
        word_count = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
        page_role_hint = infer_role_hint(final_url, title, inherited_hint)
        updated_match = re.search(
            r"(?:Last\s+Updated|Updated\s+on)\s*:?\s*([A-Za-z0-9,./\- ]{4,40})",
            collapse_ws(soup.get_text(" ", strip=True)),
            flags=re.IGNORECASE,
        )
        last_updated_text = collapse_ws(updated_match.group(1)) if updated_match else ""
        return ParsedPage(
            title=title,
            canonical_url=canonical,
            language=language,
            text_content=text,
            text_excerpt=excerpt,
            word_count=word_count,
            page_role_hint=page_role_hint,
            last_updated_text=last_updated_text,
            links=links,
        )

    def crawl(self) -> dict[str, Any]:
        self.seed_registry()
        self.db.recover_interrupted()
        started = utc_now()
        self.logger.info("DST crawl started | robots=%s", self.robots.status)

        while True:
            if self.config.max_pages and self.pages_processed_this_run >= self.config.max_pages:
                self.logger.info("Reached --max-pages=%s", self.config.max_pages)
                break
            item = self.db.next_frontier()
            if item is None:
                break
            self._crawl_one(item)

        if self.config.download_documents:
            self._download_documents()

        summary = self.export_outputs(started_at=started)
        self.logger.info(
            "DST crawl finished | pages=%s documents=%s pending=%s",
            summary["counts"]["pages"], summary["counts"]["documents"],
            summary["counts"]["frontier_pending"],
        )
        return summary

    def _crawl_one(self, item: sqlite3.Row) -> None:
        normalized_url = str(item["normalized_url"])
        attempt = int(item["attempts"])
        allowed, robots_decision = self.robots.can_fetch(normalized_url)
        if not allowed:
            self.db.complete_frontier(normalized_url, "ROBOTS_DENIED", robots_decision)
            self.logger.warning("Robots denied: %s", normalized_url)
            return

        self._rate_limit()
        started_monotonic = time.monotonic()
        try:
            response = self.session.get(
                normalized_url,
                timeout=(self.config.connect_timeout, self.config.read_timeout),
                allow_redirects=True,
                stream=True,
            )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            final_url = normalize_url(response.url, normalized_url) or normalized_url
            if is_document_url(final_url) or content_type in {
                "application/pdf", "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }:
                self.db.record_document(
                    final_url,
                    item["parent_url"] or normalized_url,
                    item["anchor_text"] or "",
                    "DOCUMENT",
                    "DST_OFFICIAL" if is_internal_dst_url(final_url) else classify_external_authority(final_url),
                )
                self.db.complete_frontier(normalized_url, "DONE")
                return

            content = self._read_limited_response(response, self.config.max_html_bytes)
            received_hash = sha256_bytes(content) if content else ""
            parsed: Optional[ParsedPage] = None
            snapshot_path = ""
            text_hash = ""
            duplicate_of = None
            error_text = ""
            if content and ("html" in content_type or content.lstrip().startswith((b"<!DOCTYPE", b"<html", b"<"))):
                parsed = self.parse_html(content, final_url, str(item["source_role_hint"]))
                text_hash = sha256_text(parsed.text_content)
                duplicate_of = self.db.find_duplicate_page(received_hash, normalized_url)
                snapshot_path = self._snapshot_html(normalized_url, content)
            elif response.status_code < 400:
                error_text = f"Unsupported content type for page crawl: {content_type or 'unknown'}"

            duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            page_id = stable_id("dst_page", normalized_url)
            self.db.record_page(
                {
                    "page_id": page_id,
                    "requested_url": str(item["requested_url"]),
                    "normalized_url": normalized_url,
                    "final_url": final_url,
                    "canonical_url": parsed.canonical_url if parsed else "",
                    "parent_url": item["parent_url"],
                    "depth": int(item["depth"]),
                    "source_role_hint": str(item["source_role_hint"]),
                    "page_role_hint": parsed.page_role_hint if parsed else "UNSUPPORTED_CONTENT",
                    "http_status": int(response.status_code),
                    "content_type": content_type,
                    "charset": response.encoding or "",
                    "title": parsed.title if parsed else "",
                    "language": parsed.language if parsed else "",
                    "fetched_at": utc_now(),
                    "last_modified_header": response.headers.get("Last-Modified", ""),
                    "etag": response.headers.get("ETag", ""),
                    "last_updated_text": parsed.last_updated_text if parsed else "",
                    "content_length_header": _safe_int(response.headers.get("Content-Length")),
                    "bytes_received": len(content),
                    "content_sha256": received_hash,
                    "text_sha256": text_hash,
                    "word_count": parsed.word_count if parsed else 0,
                    "link_count": len(parsed.links) if parsed else 0,
                    "text_excerpt": parsed.text_excerpt if parsed else "",
                    "snapshot_path": snapshot_path,
                    "duplicate_of_page_id": duplicate_of,
                    "robots_decision": robots_decision,
                    "fetch_duration_ms": duration_ms,
                    "error": error_text,
                }
            )

            if parsed and response.status_code < 400:
                self._process_links(item, final_url, parsed.links)

            status = "DONE" if response.status_code < 400 else "FAILED"
            error = "" if status == "DONE" else f"HTTP {response.status_code}"
            self.db.complete_frontier(normalized_url, status, error)
            self.pages_processed_this_run += 1
            self.logger.info(
                "[%s] depth=%s links=%s %s",
                response.status_code, item["depth"], len(parsed.links) if parsed else 0,
                normalized_url,
            )
        except Exception as exc:  # noqa: BLE001 - crawler must persist all failures
            self.db.record_error(normalized_url, "FETCH_OR_PARSE", exc, attempt)
            self.db.complete_frontier(normalized_url, "FAILED", str(exc)[:1000])
            self.pages_processed_this_run += 1
            self.logger.error("Failed %s: %s", normalized_url, exc)

    def _process_links(self, item: sqlite3.Row, source_url: str, links: list[dict[str, Any]]) -> None:
        inherited_hint = str(item["source_role_hint"])
        parent_priority = int(item["priority"])
        parent_max_depth = min(int(item["max_depth"]), self.config.max_depth)
        next_depth = int(item["depth"]) + 1

        for link in links:
            target = str(link["url"])
            anchor_text = str(link["anchor_text"])
            internal = is_internal_dst_url(target)
            document = is_document_url(target)
            authority = "DST_OFFICIAL" if internal else classify_external_authority(target)
            role_hint = infer_role_hint(target, anchor_text, inherited_hint)
            enqueue_decision = "NOT_APPLICABLE"
            score = relevance_score(target, anchor_text, inherited_hint, bool(link["in_main_content"]))

            if document:
                self.db.record_document(
                    target, source_url, anchor_text, role_hint, authority,
                )
                enqueue_decision = "DOCUMENT_RECORDED"
            elif not internal:
                self.db.record_external(
                    source_url, target, anchor_text, authority, role_hint,
                )
                enqueue_decision = "EXTERNAL_RECORDED"
            else:
                should_enqueue, reason, score = should_enqueue_internal(
                    target,
                    anchor_text,
                    inherited_hint,
                    next_depth,
                    parent_max_depth,
                    self.config.include_hindi,
                    bool(link["in_main_content"]),
                )
                enqueue_decision = reason
                if should_enqueue:
                    child_priority = max(10, parent_priority - next_depth * 3 + min(score, 80) // 10)
                    self.db.enqueue(
                        requested_url=target,
                        parent_url=source_url,
                        anchor_text=anchor_text,
                        depth=next_depth,
                        max_depth=parent_max_depth,
                        source_role_hint=role_hint,
                        priority=child_priority,
                        relevance=score,
                        discovery_reason="HTML_LINK",
                    )

            self.db.record_link(
                {
                    "from_url": source_url,
                    "to_url": target,
                    "normalized_to_url": target,
                    "anchor_text": anchor_text,
                    "rel": link.get("rel", ""),
                    "in_main_content": link.get("in_main_content", False),
                    "is_internal": internal,
                    "is_document": document,
                    "authority_class": authority,
                    "role_hint": role_hint,
                    "relevance_score": score,
                    "enqueue_decision": enqueue_decision,
                    "discovered_at": utc_now(),
                }
            )
        self.db.conn.commit()

    def _download_documents(self) -> None:
        self.logger.info("Document download pass started")
        while True:
            if self.config.max_documents and self.documents_processed_this_run >= self.config.max_documents:
                break
            row = self.db.next_document()
            if row is None:
                break
            url = str(row["url"])
            allowed, robots_decision = self.robots.can_fetch(url) if is_internal_dst_url(url) else (True, "EXTERNAL_DOCUMENT_METADATA")
            if not allowed:
                self.db.update_document(
                    str(row["document_id"]),
                    {"status": "ROBOTS_DENIED", "error": robots_decision},
                )
                continue
            self._rate_limit()
            try:
                response = self.session.get(
                    url,
                    timeout=(self.config.connect_timeout, self.config.read_timeout),
                    allow_redirects=True,
                    stream=True,
                )
                content = self._read_limited_response(response, self.config.max_document_bytes)
                final_url = normalize_url(response.url, url) or url
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                extension = str(row["extension"] or Path(urlsplit(final_url).path).suffix.lower())
                if not extension:
                    extension = mimetypes.guess_extension(content_type) or ".bin"
                token = sha256_text(url)[:16]
                filename = ascii_slug(Path(urlsplit(final_url).path).stem or row["filename"] or "document", 70)
                target = self.config.output_dir / "snapshots" / "documents" / f"{filename}_{token}{extension}"
                atomic_write_bytes(target, content)
                self.db.update_document(
                    str(row["document_id"]),
                    {
                        "final_url": final_url,
                        "status": "DOWNLOADED" if response.status_code < 400 else "FAILED",
                        "http_status": int(response.status_code),
                        "content_type": content_type,
                        "content_length_header": _safe_int(response.headers.get("Content-Length")),
                        "bytes_received": len(content),
                        "content_sha256": sha256_bytes(content),
                        "snapshot_path": str(target.relative_to(self.config.output_dir)),
                        "fetched_at": utc_now(),
                        "error": "" if response.status_code < 400 else f"HTTP {response.status_code}",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self.db.update_document(
                    str(row["document_id"]),
                    {"status": "FAILED", "fetched_at": utc_now(), "error": str(exc)[:1000]},
                )
                self.db.record_error(url, "DOCUMENT_DOWNLOAD", exc, 1)
            self.documents_processed_this_run += 1

    def export_outputs(self, started_at: str) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        export_map = {
            "source_registry": "dst_source_registry_v3_4_0_1.csv",
            "pages": "dst_crawled_pages_v3_4_0_1.csv",
            "documents": "dst_discovered_documents_v3_4_0_1.csv",
            "external_links": "dst_external_official_links_v3_4_0_1.csv",
            "links": "dst_link_graph_v3_4_0_1.csv",
            "errors": "dst_crawl_errors_v3_4_0_1.csv",
            "frontier": "dst_crawl_frontier_v3_4_0_1.csv",
        }
        for table, filename in export_map.items():
            rows = self.db.table_rows(table)
            write_csv(self.config.output_dir / filename, rows)

        pages = self.db.table_rows("pages")
        role_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for row in pages:
            role = str(row.get("page_role_hint") or "UNKNOWN")
            role_counts[role] = role_counts.get(role, 0) + 1
            status = str(row.get("http_status") or "NO_STATUS")
            status_counts[status] = status_counts.get(status, 0) + 1

        summary = {
            "service_version": VERSION,
            "department_code": DEPARTMENT_CODE,
            "department_name": DEPARTMENT_NAME,
            "started_at": started_at,
            "completed_at": utc_now(),
            "run_configuration": {
                "output_dir": str(self.config.output_dir),
                "state_db": str(self.config.state_db),
                "max_pages": self.config.max_pages,
                "max_depth": self.config.max_depth,
                "delay_seconds": self.config.delay_seconds,
                "download_documents": self.config.download_documents,
                "include_hindi": self.config.include_hindi,
                "robots_mode": self.config.robots_mode,
                "save_html_snapshots": self.config.save_html_snapshots,
            },
            "robots": {
                "status": self.robots.status,
                "error": self.robots.error,
            },
            "identity_safeguard": {
                "canonical_scheme_identity_created": False,
                "call_titles_promoted_to_scheme_names": False,
                "description": (
                    "This phase stores source-page titles and role hints only. "
                    "Canonical scheme identity is reserved for v3.4.0.3/v3.4.0.4."
                ),
            },
            "counts": {
                "registry_seeds": self.db.count("source_registry"),
                "pages": self.db.count("pages"),
                "pages_success": self.db.count("pages", "http_status BETWEEN 200 AND 299"),
                "pages_failed": self.db.count("frontier", "status='FAILED'"),
                "frontier_pending": self.db.count("frontier", "status='PENDING'"),
                "frontier_done": self.db.count("frontier", "status='DONE'"),
                "robots_denied": self.db.count("frontier", "status='ROBOTS_DENIED'"),
                "links": self.db.count("links"),
                "documents": self.db.count("documents"),
                "documents_downloaded": self.db.count("documents", "status='DOWNLOADED'"),
                "external_links": self.db.count("external_links"),
                "errors": self.db.count("errors"),
                "duplicate_pages": self.db.count("pages", "duplicate_of_page_id IS NOT NULL"),
                "pages_processed_this_run": self.pages_processed_this_run,
                "documents_processed_this_run": self.documents_processed_this_run,
            },
            "page_role_hint_counts": dict(sorted(role_counts.items())),
            "http_status_counts": dict(sorted(status_counts.items())),
            "outputs": {key: filename for key, filename in export_map.items()},
        }
        atomic_write_text(
            self.config.output_dir / "dst_crawl_summary_v3_4_0_1.json",
            json.dumps(summary, indent=2, ensure_ascii=False),
        )
        return summary


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        atomic_write_text(path, "")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def load_seed_config(config_path: Optional[Path]) -> list[dict[str, Any]]:
    if config_path is None:
        return [dict(seed) for seed in DEFAULT_SEEDS]
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    seeds = payload.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError(f"Config {config_path} must contain a non-empty 'seeds' list")
    required = {
        "seed_id", "source_group", "source_role_hint", "url", "priority",
        "crawl_depth", "rationale",
    }
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict):
            raise ValueError(f"Seed #{index} must be an object")
        missing = sorted(required - set(seed))
        if missing:
            raise ValueError(f"Seed #{index} missing fields: {', '.join(missing)}")
        normalized = normalize_url(str(seed["url"]))
        if not normalized or not is_internal_dst_url(normalized):
            raise ValueError(f"Seed #{index} is not an official dst.gov.in URL: {seed['url']}")
        if seed["seed_id"] in seen_ids:
            raise ValueError(f"Duplicate seed_id: {seed['seed_id']}")
        if normalized in seen_urls:
            raise ValueError(f"Duplicate normalized seed URL: {normalized}")
        seen_ids.add(str(seed["seed_id"]))
        seen_urls.add(normalized)
        validated.append(dict(seed))
    return validated


def write_registry_only(config: CrawlerConfig, seeds: list[dict[str, Any]], db: StateDB) -> dict[str, Any]:
    for seed in seeds:
        db.upsert_seed(seed)
    rows = db.table_rows("source_registry")
    write_csv(config.output_dir / "dst_source_registry_v3_4_0_1.csv", rows)
    summary = {
        "service_version": VERSION,
        "department": DEPARTMENT_CODE,
        "mode": "REGISTRY_ONLY",
        "seed_count": len(rows),
        "output": str(config.output_dir / "dst_source_registry_v3_4_0_1.csv"),
        "identity_safeguard": "No scheme identity or scheme name is created in this phase.",
    }
    atomic_write_text(
        config.output_dir / "dst_registry_summary_v3_4_0_1.json",
        json.dumps(summary, indent=2, ensure_ascii=False),
    )
    return summary


def run_self_test() -> dict[str, Any]:
    tests: dict[str, bool] = {}
    details: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="ssip_dst_v3401_") as temp:
        root = Path(temp)
        output = root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
        db = StateDB(output / "dst_crawl_state_v3_4_0_1.db")
        try:
            normalized = normalize_url(
                "http://www.dst.gov.in/archive-call-for-proposals/?utm_source=x&page=17#top"
            )
            tests["url_normalization"] = normalized == "https://dst.gov.in/archive-call-for-proposals?page=17"
            tests["pagination_preserved"] = bool(normalized and "page=17" in normalized)
            tests["tracking_parameters_removed"] = bool(normalized and "utm_" not in normalized)
            tests["document_detection"] = is_document_url(
                "https://dst.gov.in/sites/default/files/guidelines.PDF"
            )
            tests["hindi_exclusion"] = not should_enqueue_internal(
                "https://dst.gov.in/hi/schemes", "Schemes", "SCHEME_PROGRAMME_INDEX",
                1, 3, False, True,
            )[0]
            tests["main_content_unknown_slug_allowed"] = should_enqueue_internal(
                "https://dst.gov.in/purse", "PURSE", "PROGRAMME_CATEGORY",
                1, 4, False, True,
            )[0]
            tests["static_asset_excluded"] = not should_enqueue_internal(
                "https://dst.gov.in/logo.png", "Logo", "DEPARTMENT_HOME",
                1, 2, False, True,
            )[0]

            for seed in DEFAULT_SEEDS[:3]:
                db.upsert_seed(seed)
            tests["registry_persistence"] = db.count("source_registry") == 3
            tests["frontier_seeded"] = db.count("frontier") == 3

            sample_html = b"""
            <!doctype html><html lang='en'><head>
            <title>Call for Project Proposals under Technology Development Programme (TDP)</title>
            <link rel='canonical' href='/callforproposals/tdp-2026'>
            </head><body><header><a href='/recruitment'>Recruitment</a></header>
            <main id='main-content'><h1>Call for Project Proposals under Technology Development Programme (TDP)</h1>
            <p>Applications are invited under the standard Technology Development Programme.</p>
            <a href='/technology-development-and-transfer'>Technology Development Programme</a>
            <a href='/sites/default/files/tdp-guidelines.pdf'>Guidelines PDF</a>
            <a href='https://onlinedst.gov.in/'>Apply online</a>
            </main><footer>Last Updated: 10 July 2026</footer></body></html>
            """
            dummy_config = CrawlerConfig(root, output, output / "state.db")
            crawler = object.__new__(DSTCrawler)
            crawler.config = dummy_config
            parsed = DSTCrawler.parse_html(crawler, sample_html, "https://dst.gov.in/callforproposals/tdp-2026", "CALL_INDEX_CURRENT")
            tests["html_title_extraction"] = parsed.title.startswith("Call for Project Proposals")
            tests["call_role_hint_preserved"] = parsed.page_role_hint == "CALL_CANDIDATE"
            tests["links_extracted"] = len(parsed.links) == 4
            tests["canonical_url_extracted"] = parsed.canonical_url == "https://dst.gov.in/callforproposals/tdp-2026"
            tests["external_authority_classification"] = (
                classify_external_authority("https://onlinedst.gov.in/") == "DST_APPLICATION_PORTAL"
            )

            # The critical identity guarantee: this schema has no canonical scheme
            # name column and therefore cannot mutate or promote call titles.
            page_columns = {
                row[1] for row in db.conn.execute("PRAGMA table_info(pages)").fetchall()
            }
            tests["call_not_promoted_to_scheme_identity"] = "canonical_scheme_name" not in page_columns
            tests["scheme_identity_not_created_in_crawler"] = "scheme_master" not in {
                row[0] for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            # Duplicate-content test.
            common = {
                "page_id": "dst_page_a",
                "requested_url": "https://dst.gov.in/a",
                "normalized_url": "https://dst.gov.in/a",
                "final_url": "https://dst.gov.in/a",
                "canonical_url": "",
                "parent_url": None,
                "depth": 1,
                "source_role_hint": "PROGRAMME_CATEGORY",
                "page_role_hint": "SCHEME_PROGRAMME_CANDIDATE",
                "http_status": 200,
                "content_type": "text/html",
                "charset": "utf-8",
                "title": "A",
                "language": "en",
                "fetched_at": utc_now(),
                "last_modified_header": "",
                "etag": "",
                "last_updated_text": "",
                "content_length_header": 10,
                "bytes_received": 10,
                "content_sha256": "abc123",
                "text_sha256": "def456",
                "word_count": 1,
                "link_count": 0,
                "text_excerpt": "A",
                "snapshot_path": "",
                "duplicate_of_page_id": None,
                "robots_decision": "ROBOTS_ALLOWED",
                "fetch_duration_ms": 1,
                "error": "",
            }
            db.record_page(common)
            tests["duplicate_detection"] = db.find_duplicate_page(
                "abc123", "https://dst.gov.in/b"
            ) == "dst_page_a"

            details["normalized_example"] = normalized
            details["parsed_role_hint"] = parsed.page_role_hint
            details["parsed_link_count"] = len(parsed.links)
        finally:
            db.close()

    passed = all(tests.values())
    return {
        "service_version": VERSION,
        "department": DEPARTMENT_CODE,
        "self_test_passed": passed,
        "tests": tests,
        "details": details,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SSIP v3.4.0.1 — DST Source Registry and Department Crawler"
    )
    parser.add_argument("--project-root", default=".", help="SSIP project root directory")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--config", help="JSON file containing curated DST seeds")
    parser.add_argument("--self-test", action="store_true", help="Run offline self-tests and exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate and display the plan; no files or network")
    parser.add_argument("--registry-only", action="store_true", help="Write registry and state, but do not crawl")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum pages this run; 0 means until frontier exhausted")
    parser.add_argument("--max-depth", type=int, default=5, help="Global crawl-depth ceiling")
    parser.add_argument("--delay", type=float, default=0.75, help="Minimum delay between requests in seconds")
    parser.add_argument("--connect-timeout", type=float, default=12.0)
    parser.add_argument("--read-timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--download-documents", action="store_true", help="Download discovered documents after page crawl")
    parser.add_argument("--max-documents", type=int, default=0, help="Maximum documents this run; 0 means all discovered")
    parser.add_argument("--include-hindi", action="store_true", help="Also crawl /hi/ pages")
    parser.add_argument("--no-html-snapshots", action="store_true", help="Do not save compressed HTML snapshots")
    parser.add_argument("--robots-mode", choices=("respect", "strict"), default="respect")
    parser.add_argument("--refresh", action="store_true", help="Requeue completed/failed URLs for a fresh recrawl")
    parser.add_argument("--reset-state", action="store_true", help="Delete existing crawl state before starting")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.max_pages < 0:
        raise SystemExit("--max-pages cannot be negative")
    if args.max_documents < 0:
        raise SystemExit("--max-documents cannot be negative")
    if args.max_depth < 0:
        raise SystemExit("--max-depth cannot be negative")
    if args.delay < 0:
        raise SystemExit("--delay cannot be negative")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise SystemExit("Timeout values must be greater than zero")
    if args.retries < 0:
        raise SystemExit("--retries cannot be negative")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(args)

    if args.self_test:
        result = run_self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["self_test_passed"] else 1

    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else project_root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    )
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    seeds = load_seed_config(config_path)

    if args.dry_run:
        plan = {
            "service_version": VERSION,
            "department": DEPARTMENT_CODE,
            "mode": "DRY_RUN",
            "project_root": str(project_root),
            "output_dir": str(output_dir),
            "seed_count": len(seeds),
            "max_pages": args.max_pages,
            "max_depth": args.max_depth,
            "download_documents": bool(args.download_documents),
            "robots_mode": args.robots_mode,
            "identity_safeguard": (
                "Source-page titles are collected only; call titles cannot rename schemes."
            ),
            "seeds": seeds,
        }
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    state_db = output_dir / "dst_crawl_state_v3_4_0_1.db"
    if args.reset_state and state_db.exists():
        state_db.unlink()
        for suffix in ("-wal", "-shm"):
            extra = Path(str(state_db) + suffix)
            if extra.exists():
                extra.unlink()

    config = CrawlerConfig(
        project_root=project_root,
        output_dir=output_dir,
        state_db=state_db,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        delay_seconds=args.delay,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        retries=args.retries,
        save_html_snapshots=not args.no_html_snapshots,
        download_documents=args.download_documents,
        max_documents=args.max_documents,
        include_hindi=args.include_hindi,
        robots_mode=args.robots_mode,
        config_path=config_path,
    )

    db = StateDB(state_db)
    try:
        if args.refresh:
            db.refresh_pages()
        if args.registry_only:
            summary = write_registry_only(config, seeds, db)
        else:
            crawler = DSTCrawler(config, db, seeds)
            summary = crawler.crawl()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
