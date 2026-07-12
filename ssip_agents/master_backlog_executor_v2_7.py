"""
SSIP Multi-Source Master Backlog Executor v2.7.0

Purpose
-------
Process unresolved rows from data/audit/master_pipeline_backlog_v2_6.csv
without modifying the SSIP database. The runner:

1. Selects only unresolved, actionable master records.
2. Skips master_ids already present in protected database tables.
3. Fetches the best available official page.
4. Discovers a more specific internal page when the starting URL is a listing/call page.
5. Preserves raw HTML and normalized evidence.
6. Uses LM Studio's OpenAI-compatible endpoint when available.
7. Falls back to deterministic extraction when local AI is unavailable.
8. Produces extraction, review, audit and summary artifacts.
9. Supports resume-safe reruns.

No database writes are performed by this version. Existing validation and staging
agents should consume READY_FOR_VALIDATION records after the pilot succeeds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse, urldefrag

try:
    import requests
except ImportError as exc:
    raise SystemExit("Missing dependency: requests. Install with: pip install requests") from exc

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: beautifulsoup4. Install with: pip install beautifulsoup4"
    ) from exc


VERSION = "2.7.0"
DEFAULT_INPUT = Path("data/audit/master_pipeline_backlog_v2_6.csv")
DEFAULT_OUTPUT = Path("data/incremental/v2_7")
DEFAULT_DB = Path("database/ssip_staging_v1.db")
DEFAULT_LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

ACTIONABLE_EXTRACTION_STATUSES = {
    "",
    "NOT_EXTRACTED",
    "EXTRACTION_PENDING",
    "RETRY_REQUIRED",
    "PARTIAL",
    "FAILED",
}
NON_ACTIONABLE_VALIDATION_DECISIONS = {
    "APPROVED_FOR_DATABASE",
    "APPROVED",
    "REJECTED",
}
NON_ACTIONABLE_DATABASE_STATUSES = {
    "PRESENT",
    "STAGED",
    "APPROVED",
    "REJECTED",
    "LOADED",
}
SKIP_RECOMMENDATION_MARKERS = {
    "NO ACTION",
    "DO NOT EXTRACT",
    "ALREADY COMPLETE",
    "MANUAL ONLY",
}
LISTING_URL_HINTS = (
    "government-schemes",
    "/schemes",
    "/programmes",
    "/programs",
    "/funding",
    "/calls",
    "/cfp",
    "cfp_view",
    "archive",
    "opportunities",
)
BLOCK_MARKERS = (
    "access denied",
    "captcha",
    "verify you are human",
    "cloudflare",
    "forbidden",
    "login required",
    "sign in to continue",
    "javascript is required",
)
ERROR_PAGE_MARKERS = (
    "404 not found",
    "page not found",
    "the requested url was not found",
    "service unavailable",
    "internal server error",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0 Safari/537.36 SSIP/2.7"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
}

SECTION_ALIASES = {
    "eligibility": (
        "eligibility", "eligible", "who can apply", "applicant eligibility",
        "target beneficiaries", "target group",
    ),
    "benefits": (
        "benefits", "support offered", "financial assistance", "funding support",
        "grant support", "incentives", "assistance",
    ),
    "documents_required": (
        "documents required", "required documents", "documents", "documentation",
        "attachments", "enclosures",
    ),
    "application_process": (
        "application process", "how to apply", "apply now", "submission process",
        "procedure for application", "application procedure",
    ),
    "deadline": (
        "deadline", "last date", "closing date", "application closes",
        "submission date", "important dates",
    ),
    "funding": (
        "funding", "grant", "financial support", "amount", "award",
        "assistance", "budget",
    ),
    "contact": (
        "contact", "contact us", "helpdesk", "programme contact",
        "program contact", "email",
    ),
}

LLM_SCHEMA_FIELDS = (
    "scheme_name", "ministry", "department", "programme_status", "eligibility",
    "benefits", "funding_text", "funding_min", "funding_max", "deadline",
    "documents_required", "application_process", "application_url",
    "contact_details", "evidence_notes",
)


@dataclass
class BacklogRow:
    master_id: str
    source: str
    canonical_name: str
    master_type: str
    current_status: str
    readiness: str
    best_available_url: str
    member_url_count: str = ""
    extraction_status: str = ""
    validation_decision: str = ""
    database_status: str = ""
    final_category: str = ""
    recommended_action: str = ""
    original: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchResult:
    requested_url: str
    final_url: str = ""
    status_code: int = 0
    content_type: str = ""
    html: str = ""
    elapsed_ms: int = 0
    error: str = ""
    blocked: bool = False
    error_page: bool = False


@dataclass
class ExtractionRecord:
    run_id: str
    extractor_version: str
    master_id: str
    source: str
    canonical_name: str
    master_type: str
    input_url: str
    selected_url: str
    final_url: str
    http_status: int
    page_title: str
    fetched_at_utc: str
    extraction_method: str
    scheme_name: str = ""
    ministry: str = ""
    department: str = ""
    programme_status: str = ""
    eligibility: str = ""
    benefits: str = ""
    funding_text: str = ""
    funding_min: Optional[float] = None
    funding_max: Optional[float] = None
    deadline: str = ""
    documents_required: str = ""
    application_process: str = ""
    application_url: str = ""
    contact_details: str = ""
    evidence_notes: str = ""
    confidence: float = 0.0
    quality_flags: list[str] = field(default_factory=list)
    next_decision: str = "NEEDS_MORE_EVIDENCE"
    raw_text_sha256: str = ""
    raw_html_path: str = ""
    fetch_error: str = ""
    discovered_candidate_count: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def slug(value: str, max_len: int = 80) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", clean(value)).strip("_").lower()
    return (s[:max_len] or "record")


def first_present(row: dict[str, str], *names: str) -> str:
    normalized = {norm_key(k): clean(v) for k, v in row.items()}
    for name in names:
        v = normalized.get(norm_key(name), "")
        if v:
            return v
    return ""


def read_backlog(path: Path) -> list[BacklogRow]:
    if not path.exists():
        raise FileNotFoundError(f"Backlog file not found: {path}")
    rows: list[BacklogRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows.append(
                BacklogRow(
                    master_id=first_present(raw, "master_id"),
                    source=first_present(raw, "source"),
                    canonical_name=first_present(raw, "canonical_name"),
                    master_type=first_present(raw, "master_type"),
                    current_status=first_present(raw, "current_status"),
                    readiness=first_present(raw, "readiness"),
                    best_available_url=first_present(raw, "best_available_url", "url"),
                    member_url_count=first_present(raw, "member_url_count"),
                    extraction_status=first_present(raw, "extraction_status"),
                    validation_decision=first_present(raw, "validation_decision"),
                    database_status=first_present(raw, "database_status"),
                    final_category=first_present(raw, "final_category", "final_categ"),
                    recommended_action=first_present(raw, "recommended_action"),
                    original={clean(k): clean(v) for k, v in raw.items()},
                )
            )
    return rows


def is_http_url(url: str) -> bool:
    try:
        return urlparse(url).scheme in {"http", "https"} and bool(urlparse(url).netloc)
    except Exception:
        return False


def is_actionable(row: BacklogRow) -> tuple[bool, str]:
    if not row.master_id:
        return False, "MISSING_MASTER_ID"
    if not row.best_available_url or not is_http_url(row.best_available_url):
        return False, "MISSING_OR_INVALID_URL"

    extraction_status = row.extraction_status.upper()
    validation = row.validation_decision.upper()
    database = row.database_status.upper()
    recommendation = row.recommended_action.upper()

    if extraction_status not in ACTIONABLE_EXTRACTION_STATUSES:
        return False, f"EXTRACTION_STATUS_{extraction_status}"
    if validation in NON_ACTIONABLE_VALIDATION_DECISIONS:
        return False, f"VALIDATION_{validation}"
    if database in NON_ACTIONABLE_DATABASE_STATUSES:
        return False, f"DATABASE_{database}"
    if any(marker in recommendation for marker in SKIP_RECOMMENDATION_MARKERS):
        return False, "RECOMMENDATION_SKIP"
    return True, "ACTIONABLE"


def inspect_db_master_ids(db_path: Path) -> set[str]:
    """Read-only protection: collect master_ids from known tables if present."""
    if not db_path.exists():
        return set()

    protected: set[str] = set()
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        table_rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row[0] for row in table_rows}
        preferred = {
            "scheme_staging", "admin_review_queue", "admin_review_actions",
            "schemes", "scheme_master", "scheme_records",
        }
        for table in sorted(tables & preferred):
            columns = {
                row[1] for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            if "master_id" not in columns:
                continue

            where = ""
            params: tuple[Any, ...] = ()
            if table == "admin_review_queue" and "review_status" in columns:
                where = (
                    " WHERE UPPER(COALESCE(review_status,'')) "
                    "IN ('APPROVED','REJECTED','COMPLETED')"
                )
            query = f'SELECT DISTINCT master_id FROM "{table}"{where}'
            for (master_id,) in con.execute(query, params).fetchall():
                if master_id:
                    protected.add(clean(master_id))
    finally:
        con.close()
    return protected


def backup_inputs(input_path: Path, db_path: Path, output_dir: Path, run_id: str) -> None:
    backup_dir = output_dir / "backups" / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, backup_dir / input_path.name)
    if db_path.exists():
        shutil.copy2(db_path, backup_dir / db_path.name)


class Fetcher:
    def __init__(self, timeout: int = 30, retries: int = 2, delay: float = 1.0):
        self.timeout = timeout
        self.retries = retries
        self.delay = max(delay, 0.0)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> FetchResult:
        last_error = ""
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                content_type = response.headers.get("content-type", "")
                html = response.text if "html" in content_type.lower() or response.text else ""
                lower = html.lower()
                blocked = any(marker in lower for marker in BLOCK_MARKERS)
                error_page = (
                    response.status_code >= 400
                    or any(marker in lower for marker in ERROR_PAGE_MARKERS)
                )
                return FetchResult(
                    requested_url=url,
                    final_url=response.url,
                    status_code=response.status_code,
                    content_type=content_type,
                    html=html,
                    elapsed_ms=elapsed_ms,
                    blocked=blocked,
                    error_page=error_page,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    time.sleep(self.delay * (attempt + 1))
        return FetchResult(requested_url=url, error=last_error)


def same_site(a: str, b: str) -> bool:
    try:
        ha = urlparse(a).hostname or ""
        hb = urlparse(b).hostname or ""
        return ha.lower().removeprefix("www.") == hb.lower().removeprefix("www.")
    except Exception:
        return False


def canonicalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    return url.strip()


def token_set(value: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "scheme", "programme", "program",
        "initiative", "challenge", "grant", "support", "startup", "startups",
    }
    return {
        t for t in re.findall(r"[a-z0-9]+", value.lower())
        if len(t) >= 3 and t not in stop
    }


def page_title_and_text(html: str) -> tuple[str, str, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "canvas", "template"]):
        node.decompose()
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    text = clean(unescape(soup.get_text(" ", strip=True)))
    return title, text, soup


def is_likely_listing(url: str, page_title: str, row: BacklogRow) -> bool:
    u = url.lower()
    title = page_title.lower()
    if any(hint in u for hint in LISTING_URL_HINTS):
        return True
    generic_titles = ("government schemes", "funding opportunities", "calls for proposal")
    return any(x in title for x in generic_titles) and (
        norm_key(row.canonical_name) not in norm_key(page_title)
    )


def score_link(row: BacklogRow, link_text: str, href: str, starting_url: str) -> float:
    if not same_site(starting_url, href):
        return -100.0
    if not href.startswith(("http://", "https://")):
        return -100.0

    name_tokens = token_set(row.canonical_name)
    haystack = f"{link_text} {href}".lower()
    hay_tokens = token_set(haystack)
    overlap = len(name_tokens & hay_tokens)
    score = overlap * 6.0

    name_norm = norm_key(row.canonical_name)
    if name_norm and name_norm in norm_key(haystack):
        score += 20.0

    positive = ("scheme", "programme", "program", "grant", "challenge", "fund", "support")
    negative = (
        "login", "register", "privacy", "terms", "contact", "about", "news",
        "facebook", "twitter", "linkedin", "youtube", "javascript:", "mailto:",
    )
    score += sum(1.5 for x in positive if x in haystack)
    score -= sum(8.0 for x in negative if x in haystack)

    path = urlparse(href).path
    if path in {"", "/"}:
        score -= 5.0
    if href.rstrip("/") == starting_url.rstrip("/"):
        score -= 10.0
    return score


def discover_candidate_urls(
    row: BacklogRow,
    base_url: str,
    soup: BeautifulSoup,
    max_candidates: int = 5,
) -> list[tuple[float, str, str]]:
    seen: set[str] = set()
    scored: list[tuple[float, str, str]] = []
    for a in soup.find_all("a", href=True):
        href = canonicalize_url(urljoin(base_url, clean(a.get("href"))))
        label = clean(a.get_text(" ", strip=True))
        if not href or href in seen:
            continue
        seen.add(href)
        score = score_link(row, label, href, base_url)
        if score > 0:
            scored.append((score, href, label))
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return scored[:max_candidates]


def select_best_page(
    row: BacklogRow,
    first: FetchResult,
    fetcher: Fetcher,
    max_candidates: int,
) -> tuple[FetchResult, int]:
    if first.error or not first.html:
        return first, 0

    title, text, soup = page_title_and_text(first.html)
    candidates = discover_candidate_urls(
        row, first.final_url or row.best_available_url, soup, max_candidates
    )
    if not candidates:
        return first, 0

    should_probe = is_likely_listing(first.final_url or row.best_available_url, title, row)
    title_match = len(token_set(row.canonical_name) & token_set(f"{title} {text[:1500]}"))
    if not should_probe and title_match >= max(1, min(2, len(token_set(row.canonical_name)))):
        return first, len(candidates)

    best_result = first
    best_score = 0.0
    for link_score, candidate_url, _label in candidates:
        result = fetcher.fetch(candidate_url)
        if result.error or result.status_code >= 400 or not result.html:
            continue
        c_title, c_text, _ = page_title_and_text(result.html)
        content_overlap = len(
            token_set(row.canonical_name) & token_set(f"{c_title} {c_text[:4000]}")
        )
        combined = link_score + content_overlap * 8.0
        if result.blocked or result.error_page:
            combined -= 30.0
        if combined > best_score:
            best_result = result
            best_score = combined
        time.sleep(fetcher.delay)

    return best_result, len(candidates)


def find_section(soup: BeautifulSoup, aliases: Iterable[str], max_chars: int = 4000) -> str:
    aliases_norm = tuple(norm_key(a) for a in aliases)

    # Prefer semantic heading boundaries.
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        heading_text = clean(heading.get_text(" ", strip=True))
        hnorm = norm_key(heading_text)
        if not any(alias in hnorm or hnorm in alias for alias in aliases_norm):
            continue

        chunks: list[str] = []
        for sibling in heading.next_siblings:
            name = getattr(sibling, "name", None)
            if name and re.fullmatch(r"h[1-6]", name):
                break
            if hasattr(sibling, "get_text"):
                txt = clean(sibling.get_text(" ", strip=True))
            else:
                txt = clean(str(sibling))
            if txt:
                chunks.append(txt)
            if sum(len(x) for x in chunks) >= max_chars:
                break
        if chunks:
            return clean(" ".join(chunks))[:max_chars]

    # Fallback: locate text node and use parent block.
    for text_node in soup.find_all(string=True):
        value = clean(text_node)
        vnorm = norm_key(value)
        if not vnorm or len(value) > 150:
            continue
        if any(alias in vnorm or vnorm in alias for alias in aliases_norm):
            parent = text_node.parent
            if parent:
                block = clean(parent.get_text(" ", strip=True))
                if len(block) >= 20:
                    return block[:max_chars]
    return ""


def find_application_url(soup: BeautifulSoup, base_url: str) -> str:
    best = ""
    best_score = -1
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" ", strip=True)).lower()
        href = canonicalize_url(urljoin(base_url, clean(a.get("href"))))
        hay = f"{text} {href.lower()}"
        score = 0
        if "apply now" in hay:
            score += 10
        if "apply" in hay or "application" in hay:
            score += 5
        if "register" in hay:
            score += 2
        if href.startswith(("http://", "https://")) and score > best_score:
            best, best_score = href, score
    return best if best_score > 0 else ""


def regex_first(patterns: Iterable[str], text: str, flags: int = re.I) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return clean(match.group(1))
    return ""


def parse_money_values(text: str) -> tuple[Optional[float], Optional[float]]:
    multipliers = {
        "thousand": 1_000,
        "lakh": 100_000,
        "lakhs": 100_000,
        "crore": 10_000_000,
        "crores": 10_000_000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
    }
    values: list[float] = []
    pattern = re.compile(
        r"(?:₹|rs\.?|inr)?\s*"
        r"(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*"
        r"(thousand|lakhs?|crores?|million|billion)?",
        re.I,
    )
    for match in pattern.finditer(text):
        raw = match.group(1).replace(",", "")
        unit = (match.group(2) or "").lower()
        try:
            value = float(raw) * multipliers.get(unit, 1)
        except ValueError:
            continue
        # Avoid treating years, dates and tiny integers as funding.
        if value >= 1_000 or unit:
            values.append(value)
    if not values:
        return None, None
    return min(values), max(values)


def deterministic_extract(
    row: BacklogRow,
    fetch: FetchResult,
) -> tuple[dict[str, Any], str, str, BeautifulSoup]:
    title, text, soup = page_title_and_text(fetch.html)
    base_url = fetch.final_url or row.best_available_url

    h1 = soup.find("h1")
    scheme_name = clean(h1.get_text(" ", strip=True) if h1 else "") or title
    if not scheme_name:
        scheme_name = row.canonical_name

    sections = {
        field: find_section(soup, aliases)
        for field, aliases in SECTION_ALIASES.items()
    }
    funding_text = sections["funding"]
    funding_min, funding_max = parse_money_values(funding_text or text[:12000])

    extracted = {
        "scheme_name": scheme_name,
        "ministry": regex_first(
            (
                r"(?:ministry|ministries)\s*(?:of|:|-)\s*([A-Za-z0-9 &(),./'-]{3,120})",
            ),
            text,
        ),
        "department": regex_first(
            (
                r"(?:department|dept\.?)\s*(?:of|:|-)\s*([A-Za-z0-9 &(),./'-]{3,120})",
            ),
            text,
        ),
        "programme_status": regex_first(
            (
                r"\b(status)\s*[:\-]\s*([A-Za-z ]{3,50})",
            ),
            text,
        ),
        "eligibility": sections["eligibility"],
        "benefits": sections["benefits"],
        "funding_text": funding_text,
        "funding_min": funding_min,
        "funding_max": funding_max,
        "deadline": sections["deadline"],
        "documents_required": sections["documents_required"],
        "application_process": sections["application_process"],
        "application_url": find_application_url(soup, base_url),
        "contact_details": sections["contact"],
        "evidence_notes": (
            "Deterministic HTML extraction; fields are evidence snippets and "
            "must pass the existing validation agent."
        ),
    }
    # Fix the status regex if it captured only the literal word "status".
    status_match = re.search(r"\bstatus\s*[:\-]\s*([A-Za-z ]{3,50})", text, re.I)
    extracted["programme_status"] = clean(status_match.group(1)) if status_match else ""
    return extracted, title, text, soup


class LocalAIExtractor:
    def __init__(self, endpoint: str, model: str, timeout: int = 90):
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            root = self.endpoint.split("/v1/")[0].rstrip("/")
            response = requests.get(f"{root}/v1/models", timeout=3)
            return response.ok
        except requests.RequestException:
            return False

    def extract(
        self,
        row: BacklogRow,
        url: str,
        page_title: str,
        page_text: str,
    ) -> Optional[dict[str, Any]]:
        schema = {field: "" for field in LLM_SCHEMA_FIELDS}
        schema["funding_min"] = None
        schema["funding_max"] = None
        prompt = f"""
You are the SSIP evidence extraction engine.

Extract only facts explicitly supported by the official webpage text.
Do not infer missing eligibility, benefits, dates, funding or status.
Return one valid JSON object only. Do not use markdown.
Use empty strings for absent text fields and null for absent numeric fields.
Funding numeric fields must be rupee values, not strings.
Keep evidence snippets concise but sufficiently complete.

Expected keys:
{json.dumps(schema, ensure_ascii=False)}

Backlog identity:
master_id: {row.master_id}
source: {row.source}
canonical_name: {row.canonical_name}
master_type: {row.master_type}
current_status: {row.current_status}
URL: {url}
page_title: {page_title}

Official webpage text:
{page_text[:24000]}
""".strip()

        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return strict JSON only. Never invent information not present "
                        "in the supplied webpage evidence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return None
            return {key: parsed.get(key, schema[key]) for key in schema}
        except (requests.RequestException, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None


def merge_extractions(
    deterministic: dict[str, Any],
    llm: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    if not llm:
        return deterministic, "DETERMINISTIC"

    merged = dict(deterministic)
    for key in LLM_SCHEMA_FIELDS:
        value = llm.get(key)
        if value not in ("", None, [], {}):
            merged[key] = value

    # Keep deterministic official application URL when LLM omits it.
    return merged, "LOCAL_AI_PLUS_DETERMINISTIC"


def name_similarity(expected: str, observed: str) -> float:
    a, b = token_set(expected), token_set(observed)
    if not a:
        return 1.0
    return len(a & b) / len(a)


def evaluate_record(
    row: BacklogRow,
    fetch: FetchResult,
    extracted: dict[str, Any],
    text: str,
) -> tuple[float, list[str], str]:
    flags: list[str] = []

    if fetch.error:
        flags.append("FETCH_FAILED")
    if fetch.status_code >= 400:
        flags.append(f"HTTP_{fetch.status_code}")
    if fetch.blocked:
        flags.append("PAGE_BLOCKED_OR_LOGIN")
    if fetch.error_page:
        flags.append("ERROR_PAGE_DETECTED")
    if len(text) < 300:
        flags.append("INSUFFICIENT_PAGE_TEXT")

    expected = row.canonical_name
    observed = clean(extracted.get("scheme_name"))
    similarity = name_similarity(expected, f"{observed} {text[:2500]}")
    if similarity < 0.34:
        flags.append("CANONICAL_NAME_EVIDENCE_WEAK")

    required_checks = {
        "ELIGIBILITY_NOT_FOUND": extracted.get("eligibility"),
        "BENEFITS_NOT_FOUND": extracted.get("benefits"),
        "APPLICATION_PROCESS_NOT_FOUND": extracted.get("application_process"),
        "REQUIRED_DOCUMENTS_NOT_FOUND": extracted.get("documents_required"),
        "EXPLICIT_FUNDING_AMOUNT_NOT_FOUND": (
            extracted.get("funding_min") or extracted.get("funding_max")
            or extracted.get("funding_text")
        ),
    }
    for flag, value in required_checks.items():
        if not clean(value):
            flags.append(flag)

    evidence_fields = (
        "scheme_name", "eligibility", "benefits", "funding_text", "deadline",
        "application_process", "application_url", "documents_required",
    )
    present = sum(bool(clean(extracted.get(field))) for field in evidence_fields)
    confidence = 0.20 + (present / len(evidence_fields)) * 0.55
    confidence += min(similarity, 1.0) * 0.20
    if fetch.status_code == 200 and not fetch.blocked and not fetch.error_page:
        confidence += 0.05
    confidence -= 0.10 if "INSUFFICIENT_PAGE_TEXT" in flags else 0.0
    confidence -= 0.20 if "CANONICAL_NAME_EVIDENCE_WEAK" in flags else 0.0
    confidence -= 0.30 if "FETCH_FAILED" in flags else 0.0
    confidence = round(max(0.0, min(confidence, 1.0)), 3)

    fatal = {
        "FETCH_FAILED", "PAGE_BLOCKED_OR_LOGIN", "ERROR_PAGE_DETECTED",
        "INSUFFICIENT_PAGE_TEXT", "CANONICAL_NAME_EVIDENCE_WEAK",
    }
    if any(flag in fatal or flag.startswith("HTTP_") for flag in flags):
        decision = "NEEDS_MORE_EVIDENCE"
    elif confidence >= 0.72:
        decision = "READY_FOR_VALIDATION"
    else:
        decision = "NEEDS_ADMIN_REVIEW"
    return confidence, flags, decision


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            for key, value in normalized.items():
                if isinstance(value, (list, dict)):
                    normalized[key] = json.dumps(value, ensure_ascii=False)
            writer.writerow(normalized)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def load_completed_master_ids(ledger_path: Path) -> set[str]:
    if not ledger_path.exists():
        return set()
    completed = set()
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if clean(row.get("result")) == "COMPLETED":
                completed.add(clean(row.get("master_id")))
    return completed


def append_ledger(path: Path, row: dict[str, Any]) -> None:
    fieldnames = [
        "run_id", "timestamp_utc", "master_id", "source", "canonical_name",
        "input_url", "selected_url", "http_status", "result", "next_decision",
        "confidence", "quality_flags", "error",
    ]
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        normalized = dict(row)
        if isinstance(normalized.get("quality_flags"), list):
            normalized["quality_flags"] = "|".join(normalized["quality_flags"])
        writer.writerow(normalized)


def selection_report(
    all_rows: list[BacklogRow],
    protected_ids: set[str],
    completed_ids: set[str],
    force: bool,
) -> tuple[list[BacklogRow], list[dict[str, str]]]:
    selected: list[BacklogRow] = []
    audit: list[dict[str, str]] = []

    for row in all_rows:
        actionable, reason = is_actionable(row)
        if actionable and row.master_id in protected_ids:
            actionable, reason = False, "PROTECTED_BY_EXISTING_DATABASE_RECORD"
        if actionable and not force and row.master_id in completed_ids:
            actionable, reason = False, "ALREADY_COMPLETED_IN_V2_7_LEDGER"

        audit.append(
            {
                "master_id": row.master_id,
                "source": row.source,
                "canonical_name": row.canonical_name,
                "selected": "YES" if actionable else "NO",
                "selection_reason": reason,
                "best_available_url": row.best_available_url,
                "extraction_status": row.extraction_status,
                "validation_decision": row.validation_decision,
                "database_status": row.database_status,
                "recommended_action": row.recommended_action,
            }
        )
        if actionable:
            selected.append(row)
    return selected, audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SSIP v2.7 multi-source incremental backlog executor"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=0, help="0 means all selected rows")
    parser.add_argument("--source", action="append", default=[], help="Repeatable source filter")
    parser.add_argument("--master-id", action="append", default=[], help="Repeatable master filter")
    parser.add_argument("--execute", action="store_true", help="Perform network extraction")
    parser.add_argument("--force", action="store_true", help="Reprocess completed v2.7 records")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument(
        "--disable-local-ai",
        action="store_true",
        help="Use deterministic extraction only",
    )
    parser.add_argument(
        "--lm-studio-url",
        default=os.getenv("SSIP_LM_STUDIO_URL", DEFAULT_LM_STUDIO_URL),
    )
    parser.add_argument(
        "--lm-studio-model",
        default=os.getenv("SSIP_LOCAL_MODEL", "qwen2.5-7b-instruct"),
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )
    log = logging.getLogger("ssip.v2_7")

    run_id = datetime.now().strftime("v2_7_%Y%m%d_%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.output_dir / "execution_ledger_v2_7.csv"
    records_path = args.output_dir / "extracted_records_v2_7.jsonl"

    rows = read_backlog(args.input)
    protected_ids = inspect_db_master_ids(args.db)
    completed_ids = load_completed_master_ids(ledger_path)
    selected, selection_audit = selection_report(
        rows, protected_ids, completed_ids, args.force
    )

    if args.source:
        wanted = {norm_key(x) for x in args.source}
        selected = [row for row in selected if norm_key(row.source) in wanted]
    if args.master_id:
        wanted_ids = {clean(x) for x in args.master_id}
        selected = [row for row in selected if row.master_id in wanted_ids]

    selected.sort(key=lambda r: (r.source.lower(), r.canonical_name.lower(), r.master_id))
    if args.limit > 0:
        selected = selected[: args.limit]

    write_csv(
        args.output_dir / "selection_audit_v2_7.csv",
        selection_audit,
        [
            "master_id", "source", "canonical_name", "selected", "selection_reason",
            "best_available_url", "extraction_status", "validation_decision",
            "database_status", "recommended_action",
        ],
    )
    write_csv(
        args.output_dir / "selected_backlog_v2_7.csv",
        [
            {
                "master_id": r.master_id,
                "source": r.source,
                "canonical_name": r.canonical_name,
                "master_type": r.master_type,
                "current_status": r.current_status,
                "readiness": r.readiness,
                "best_available_url": r.best_available_url,
                "extraction_status": r.extraction_status,
                "validation_decision": r.validation_decision,
                "database_status": r.database_status,
                "recommended_action": r.recommended_action,
            }
            for r in selected
        ],
        [
            "master_id", "source", "canonical_name", "master_type",
            "current_status", "readiness", "best_available_url",
            "extraction_status", "validation_decision", "database_status",
            "recommended_action",
        ],
    )

    log.info("=" * 72)
    log.info("SSIP Multi-Source Backlog Executor v%s", VERSION)
    log.info("Run ID: %s", run_id)
    log.info("Backlog rows: %d", len(rows))
    log.info("Database-protected master_ids: %d", len(protected_ids))
    log.info("Selected rows after filters/limit: %d", len(selected))
    log.info("Mode: %s", "EXECUTE" if args.execute else "DRY RUN")
    log.info("=" * 72)

    if not args.execute:
        by_source: dict[str, int] = {}
        for row in selected:
            by_source[row.source] = by_source.get(row.source, 0) + 1
        summary = {
            "run_id": run_id,
            "version": VERSION,
            "mode": "DRY_RUN",
            "input_backlog": str(args.input),
            "input_row_count": len(rows),
            "protected_master_id_count": len(protected_ids),
            "selected_count": len(selected),
            "selected_by_source": by_source,
            "selected_file": str(args.output_dir / "selected_backlog_v2_7.csv"),
            "selection_audit_file": str(args.output_dir / "selection_audit_v2_7.csv"),
        }
        (args.output_dir / "preflight_summary_v2_7.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    backup_inputs(args.input, args.db, args.output_dir, run_id)

    fetcher = Fetcher(timeout=args.timeout, retries=args.retries, delay=args.delay)
    local_ai: Optional[LocalAIExtractor] = None
    if not args.disable_local_ai:
        candidate_ai = LocalAIExtractor(
            args.lm_studio_url,
            args.lm_studio_model,
        )
        if candidate_ai.available():
            local_ai = candidate_ai
            log.info("Local AI available: %s", args.lm_studio_model)
        else:
            log.warning("Local AI unavailable; deterministic fallback will be used.")

    raw_dir = args.output_dir / "raw_html" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    decision_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    failure_count = 0

    for index, row in enumerate(selected, start=1):
        log.info(
            "[%d/%d] %s | %s",
            index, len(selected), row.source, row.canonical_name
        )
        first = fetcher.fetch(row.best_available_url)
        selected_fetch, discovered_count = select_best_page(
            row, first, fetcher, args.max_candidates
        )

        html_path = ""
        page_title = ""
        page_text = ""
        extracted: dict[str, Any] = {
            key: (None if key in {"funding_min", "funding_max"} else "")
            for key in LLM_SCHEMA_FIELDS
        }
        method = "NONE"

        if selected_fetch.html:
            page_title, page_text, _soup = page_title_and_text(selected_fetch.html)
            filename = f"{slug(row.source, 30)}__{row.master_id}__{slug(row.canonical_name, 50)}.html"
            raw_path = raw_dir / filename
            raw_path.write_text(selected_fetch.html, encoding="utf-8", errors="replace")
            html_path = str(raw_path)

            deterministic, page_title, page_text, _soup = deterministic_extract(
                row, selected_fetch
            )
            llm_result = None
            if local_ai:
                llm_result = local_ai.extract(
                    row,
                    selected_fetch.final_url or row.best_available_url,
                    page_title,
                    page_text,
                )
            extracted, method = merge_extractions(deterministic, llm_result)

        confidence, flags, decision = evaluate_record(
            row, selected_fetch, extracted, page_text
        )
        if selected_fetch.error:
            failure_count += 1

        record = ExtractionRecord(
            run_id=run_id,
            extractor_version=VERSION,
            master_id=row.master_id,
            source=row.source,
            canonical_name=row.canonical_name,
            master_type=row.master_type,
            input_url=row.best_available_url,
            selected_url=selected_fetch.requested_url,
            final_url=selected_fetch.final_url,
            http_status=selected_fetch.status_code,
            page_title=page_title,
            fetched_at_utc=utc_now(),
            extraction_method=method,
            scheme_name=clean(extracted.get("scheme_name")),
            ministry=clean(extracted.get("ministry")),
            department=clean(extracted.get("department")),
            programme_status=clean(extracted.get("programme_status")),
            eligibility=clean(extracted.get("eligibility")),
            benefits=clean(extracted.get("benefits")),
            funding_text=clean(extracted.get("funding_text")),
            funding_min=extracted.get("funding_min"),
            funding_max=extracted.get("funding_max"),
            deadline=clean(extracted.get("deadline")),
            documents_required=clean(extracted.get("documents_required")),
            application_process=clean(extracted.get("application_process")),
            application_url=clean(extracted.get("application_url")),
            contact_details=clean(extracted.get("contact_details")),
            evidence_notes=clean(extracted.get("evidence_notes")),
            confidence=confidence,
            quality_flags=flags,
            next_decision=decision,
            raw_text_sha256=hashlib.sha256(
                page_text.encode("utf-8", errors="ignore")
            ).hexdigest() if page_text else "",
            raw_html_path=html_path,
            fetch_error=selected_fetch.error,
            discovered_candidate_count=discovered_count,
        )
        record_dict = asdict(record)
        append_jsonl(records_path, record_dict)
        records.append(record_dict)

        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        source_counts[row.source] = source_counts.get(row.source, 0) + 1

        append_ledger(
            ledger_path,
            {
                "run_id": run_id,
                "timestamp_utc": utc_now(),
                "master_id": row.master_id,
                "source": row.source,
                "canonical_name": row.canonical_name,
                "input_url": row.best_available_url,
                "selected_url": selected_fetch.final_url or selected_fetch.requested_url,
                "http_status": selected_fetch.status_code,
                "result": "COMPLETED",
                "next_decision": decision,
                "confidence": confidence,
                "quality_flags": flags,
                "error": selected_fetch.error,
            },
        )
        time.sleep(args.delay)

    csv_fields = [
        "run_id", "extractor_version", "master_id", "source", "canonical_name",
        "master_type", "input_url", "selected_url", "final_url", "http_status",
        "page_title", "fetched_at_utc", "extraction_method", "scheme_name",
        "ministry", "department", "programme_status", "eligibility", "benefits",
        "funding_text", "funding_min", "funding_max", "deadline",
        "documents_required", "application_process", "application_url",
        "contact_details", "evidence_notes", "confidence", "quality_flags",
        "next_decision", "raw_text_sha256", "raw_html_path", "fetch_error",
        "discovered_candidate_count",
    ]
    write_csv(args.output_dir / "extracted_records_v2_7.csv", records, csv_fields)
    write_csv(
        args.output_dir / "ready_for_validation_v2_7.csv",
        [r for r in records if r["next_decision"] == "READY_FOR_VALIDATION"],
        csv_fields,
    )
    write_csv(
        args.output_dir / "incremental_review_queue_v2_7.csv",
        [r for r in records if r["next_decision"] != "READY_FOR_VALIDATION"],
        csv_fields,
    )

    summary = {
        "run_id": run_id,
        "version": VERSION,
        "mode": "EXECUTE",
        "as_of_utc": utc_now(),
        "input_backlog": str(args.input),
        "selected_count": len(selected),
        "processed_count": len(records),
        "network_failure_count": failure_count,
        "records_by_source": source_counts,
        "records_by_next_decision": decision_counts,
        "local_ai_used": bool(local_ai),
        "database_write_performed": False,
        "outputs": {
            "records_jsonl": str(records_path),
            "records_csv": str(args.output_dir / "extracted_records_v2_7.csv"),
            "ready_for_validation": str(
                args.output_dir / "ready_for_validation_v2_7.csv"
            ),
            "review_queue": str(
                args.output_dir / "incremental_review_queue_v2_7.csv"
            ),
            "ledger": str(ledger_path),
            "raw_html_dir": str(raw_dir),
        },
    }
    (args.output_dir / "execution_summary_v2_7.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
