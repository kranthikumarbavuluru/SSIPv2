from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


VALIDATOR_VERSION = "2.7.2"
DEFAULT_EXPECTED_COUNT = 18
DECISIONS = (
    "APPROVED_FOR_DATABASE",
    "NEEDS_ADMIN_REVIEW",
    "NEEDS_MORE_EVIDENCE",
    "REJECTED",
)

SOURCE_HOSTS: dict[str, tuple[str, ...]] = {
    "birac": ("birac.nic.in",),
    "dst": ("dst.gov.in",),
    "startup india": ("startupindia.gov.in", "www.startupindia.gov.in"),
    "meity startup hub": ("msh.meity.gov.in", "meity.gov.in"),
    "msme": ("msme.gov.in", "my.msme.gov.in"),
}

NEGATIVE_PAGE_PATTERNS: dict[str, tuple[str, ...]] = {
    "LOGIN_PAGE": (
        "login required",
        "sign in to continue",
        "please login",
        "user login",
        "member login",
        "authentication required",
    ),
    "NEWS_OR_PRESS_RELEASE": (
        "press release",
        "news and updates",
        "in the news",
        "media release",
    ),
    "EVENT_ANNOUNCEMENT": (
        "webinar",
        "conference",
        "workshop",
        "seminar",
        "event registration",
    ),
    "RESULT_PAGE": (
        "results announced",
        "selected candidates",
        "list of selected",
        "winners announced",
        "shortlisted applicants",
    ),
}

PROGRAMME_KEYWORDS = (
    "scheme",
    "programme",
    "program",
    "initiative",
    "mission",
    "grant",
    "funding",
    "financial assistance",
    "call for proposal",
    "call for proposals",
    "challenge",
    "fellowship",
    "incubator",
    "incubation",
    "startup support",
    "research support",
    "guideline",
    "guidelines",
)

APPLICATION_URL_PATTERNS = (
    "apply",
    "application",
    "register",
    "registration",
    "submit",
    "proposal",
    "portal",
    "login",
)

GENERIC_NAME_PATTERNS = (
    "home",
    "welcome",
    "government schemes",
    "schemes",
    "programmes",
    "programs",
    "department",
    "ministry",
    "call for proposals",
    "latest updates",
    "untitled",
)

SUPPORTED_INFORMATION_STATUSES = {
    "SCHEME_INFORMATION_AVAILABLE",
    "UMBRELLA_PROGRAMME_INFORMATION_AVAILABLE",
    "PROGRAMME_INFORMATION_AVAILABLE",
    "CALL_INFORMATION_AVAILABLE",
}

OPEN_STATUS_TOKENS = (
    "OPEN",
    "CURRENT",
    "ACTIVE",
    "ACCEPTING_APPLICATIONS",
)

CLOSED_STATUS_TOKENS = (
    "CLOSED",
    "DEADLINE_PASSED",
    "EXPIRED",
)

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}

HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class DatabaseMatch:
    exact_tables: tuple[str, ...]
    action_history: tuple[dict[str, str], ...]
    name_matches: tuple[dict[str, str], ...]
    url_matches: tuple[dict[str, str], ...]

    @property
    def already_staged(self) -> bool:
        return "scheme_staging" in self.exact_tables

    @property
    def already_queued(self) -> bool:
        return "admin_review_queue" in self.exact_tables

    @property
    def previous_rejection(self) -> bool:
        return any("REJECT" in clean(item.get("action")).upper() for item in self.action_history)

    @property
    def potential_duplicate(self) -> bool:
        return bool(self.name_matches or self.url_matches)

    @property
    def orphan_exact_tables(self) -> tuple[str, ...]:
        excluded = {"scheme_staging", "admin_review_queue", "admin_review_actions"}
        return tuple(table for table in self.exact_tables if table not in excluded)


@dataclass
class Evaluation:
    output: dict[str, str]
    audit: dict[str, str]
    handoff: dict[str, str] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip())


def key(value: Any) -> str:
    return clean(value).casefold()


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(clean(value))
    except (TypeError, ValueError):
        return default


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def parse_json_list(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [clean(item) for item in parsed if clean(item)]
    except json.JSONDecodeError:
        pass
    return [clean(item) for item in re.split(r"[|;,]", text) if clean(item)]


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: Any) -> str:
    text = html.unescape(clean(value)).casefold()
    text = text.replace("&", " and ")
    return SPACE_RE.sub(" ", NON_ALNUM_RE.sub(" ", text)).strip()


def meaningful_name(value: Any) -> bool:
    normalized = normalize_name(value)
    if len(normalized) < 4:
        return False
    if normalized in GENERIC_NAME_PATTERNS:
        return False
    words = normalized.split()
    return len(words) >= 1 and any(len(word) >= 4 for word in words)


def normalize_url(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    host = parts.hostname.casefold() if parts.hostname else ""
    port = parts.port
    netloc = host
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def host_for_url(value: Any) -> str:
    normalized = normalize_url(value)
    if not normalized:
        return ""
    return (urlsplit(normalized).hostname or "").casefold()


def official_url_for_source(source: str, url: str) -> bool:
    host = host_for_url(url)
    if not host:
        return False
    source_key = key(source)
    expected = SOURCE_HOSTS.get(source_key, ())
    if expected and any(host == item or host.endswith("." + item) for item in expected):
        return True
    return host.endswith(".gov.in") or host.endswith(".nic.in") or host in {"gov.in", "nic.in"}


def flatten_json(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from flatten_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_json(child)
    elif value is not None:
        text = clean(value)
        if text:
            yield text


def read_evidence_file(path: Path, maximum_bytes: int = 2_000_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    raw = path.read_bytes()[:maximum_bytes]
    text = raw.decode("utf-8", errors="replace")
    if path.suffix.casefold() == ".json":
        try:
            return "\n".join(flatten_json(json.loads(text)))
        except json.JSONDecodeError:
            return text
    if path.suffix.casefold() in {".html", ".htm"}:
        text = HTML_TAG_RE.sub(" ", text)
        text = html.unescape(text)
    return clean(text)


def resolve_evidence_path(project_root: Path, value: Any) -> Path | None:
    text = clean(value)
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        return candidate.resolve()
    except OSError:
        return candidate


def build_evidence(row: dict[str, str], project_root: Path) -> tuple[str, list[str]]:
    parts: list[str] = []
    sources: list[str] = []
    for column in (
        "page_title",
        "canonical_name",
        "scheme_name",
        "programme_status",
        "eligibility",
        "benefits",
        "funding_text",
        "deadline",
        "documents_required",
        "application_process",
        "contact_details",
        "evidence_notes",
    ):
        value = clean(row.get(column))
        if value:
            parts.append(value)
            sources.append(f"FIELD:{column}")
    for column in ("raw_evidence_path", "raw_html_path"):
        path = resolve_evidence_path(project_root, row.get(column))
        if path is None:
            continue
        text = read_evidence_file(path)
        if text:
            parts.append(text)
            sources.append(str(path))
    combined = clean("\n".join(parts))
    return combined, sources


def normalized_search_text(value: str) -> str:
    return SPACE_RE.sub(" ", re.sub(r"[^a-z0-9₹$€£.%/-]+", " ", value.casefold())).strip()


def text_contains_value(value: Any, evidence_text: str) -> bool:
    target = normalized_search_text(clean(value))
    evidence = normalized_search_text(evidence_text)
    if not target:
        return True
    if target in evidence:
        return True
    compact_target = re.sub(r"[^a-z0-9]", "", target)
    compact_evidence = re.sub(r"[^a-z0-9]", "", evidence)
    return bool(compact_target and compact_target in compact_evidence)


def date_variants(value: str) -> set[str]:
    text = clean(value)
    variants = {text}
    parsed: date | None = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%B %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed:
        variants.update(
            {
                parsed.isoformat(),
                parsed.strftime("%d-%m-%Y"),
                parsed.strftime("%d/%m/%Y"),
                parsed.strftime("%d.%m.%Y"),
                parsed.strftime("%d %B %Y"),
                parsed.strftime("%B %d, %Y"),
                parsed.strftime("%d %b %Y"),
            }
        )
    return {clean(item) for item in variants if clean(item)}


def deadline_supported(value: Any, evidence_text: str) -> bool:
    text = clean(value)
    if not text:
        return True
    return any(text_contains_value(variant, evidence_text) for variant in date_variants(text))


def parse_date(value: Any) -> date | None:
    text = clean(value)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%B %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def numeric_supported(value: Any, evidence_text: str) -> bool:
    text = clean(value)
    if not text:
        return True
    digits = re.sub(r"\D", "", text)
    if not digits:
        return text_contains_value(text, evidence_text)
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return False
    variants = {
        text,
        f"{number:g}",
        f"{number:,.0f}",
        str(int(number)) if number.is_integer() else f"{number:g}",
    }
    if any(text_contains_value(item, evidence_text) for item in variants):
        return True
    numeric_fragments = re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?(?!\w)", evidence_text)
    return any(re.sub(r"\D", "", fragment) == digits for fragment in numeric_fragments)


def status_supported(status: str, evidence_text: str, deadline: str, as_of: date) -> bool:
    normalized = clean(status).upper()
    evidence_lower = evidence_text.casefold()
    if not normalized:
        return False
    if normalized in SUPPORTED_INFORMATION_STATUSES:
        return any(keyword in evidence_lower for keyword in PROGRAMME_KEYWORDS)
    parsed_deadline = parse_date(deadline)
    if any(token in normalized for token in OPEN_STATUS_TOKENS):
        if parsed_deadline and parsed_deadline >= as_of:
            return True
        return any(
            phrase in evidence_lower
            for phrase in (
                "applications are open",
                "open for applications",
                "accepting applications",
                "call is open",
                "submit your application",
            )
        )
    if any(token in normalized for token in CLOSED_STATUS_TOKENS):
        if parsed_deadline and parsed_deadline < as_of:
            return True
        return any(
            phrase in evidence_lower
            for phrase in (
                "applications are closed",
                "call closed",
                "deadline has passed",
                "closed for applications",
            )
        )
    return text_contains_value(status.replace("_", " "), evidence_text)


def classify_negative_page(row: dict[str, str], evidence_text: str) -> list[str]:
    text = " ".join(
        [
            clean(row.get("page_title")),
            clean(row.get("document_type")),
            normalize_url(row.get("final_url")),
            evidence_text[:2000],
        ]
    ).casefold()
    hits: list[str] = []
    for code, phrases in NEGATIVE_PAGE_PATTERNS.items():
        if any(phrase in text for phrase in phrases):
            hits.append(code)
    return hits


def programme_identity_strength(row: dict[str, str], evidence_text: str) -> float:
    score = clamp(parse_float(row.get("page_identity_score"), 0.0))
    text = evidence_text.casefold()
    name = clean(row.get("scheme_name") or row.get("canonical_name"))
    if meaningful_name(name):
        score += 0.15
    if normalize_name(name) and normalize_name(name) in normalize_name(evidence_text):
        score += 0.20
    keyword_count = sum(1 for keyword in PROGRAMME_KEYWORDS if keyword in text)
    score += min(0.25, keyword_count * 0.04)
    if clean(row.get("eligibility")):
        score += 0.08
    if clean(row.get("benefits")):
        score += 0.08
    return clamp(score)


def application_url_is_plausible(application_url: str, final_url: str) -> bool:
    normalized = normalize_url(application_url)
    if not normalized:
        return True
    if normalized == normalize_url(final_url):
        return any(token in normalized.casefold() for token in APPLICATION_URL_PATTERNS)
    return any(token in normalized.casefold() for token in APPLICATION_URL_PATTERNS)


def evidence_excerpt(evidence_text: str, name: str, maximum: int = 600) -> str:
    if not evidence_text:
        return ""
    normalized_name = clean(name)
    location = evidence_text.casefold().find(normalized_name.casefold()) if normalized_name else -1
    if location < 0:
        return evidence_text[:maximum]
    start = max(0, location - maximum // 3)
    return evidence_text[start : start + maximum]


class ReadOnlyDatabaseInspector:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Database not found: {path}")
        uri = path.resolve().as_uri() + "?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.path = path
        self.tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        self.columns = {
            table: {
                row["name"]
                for row in self.connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            for table in self.tables
        }

    def close(self) -> None:
        self.connection.close()

    def snapshot_counts(self) -> dict[str, int]:
        return {
            table: int(self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in sorted(self.tables)
        }

    def _exact_in_table(self, table: str, master_id: str) -> bool:
        if table not in self.tables or "master_id" not in self.columns.get(table, set()):
            return False
        return self.connection.execute(
            f'SELECT 1 FROM "{table}" WHERE master_id = ? LIMIT 1',
            (master_id,),
        ).fetchone() is not None

    def _action_history(self, master_id: str) -> tuple[dict[str, str], ...]:
        table = "admin_review_actions"
        if table not in self.tables or "master_id" not in self.columns.get(table, set()):
            return ()
        selected = [name for name in ("action", "reviewer", "notes", "created_at") if name in self.columns[table]]
        if not selected:
            return ()
        rows = self.connection.execute(
            f'SELECT {", ".join(selected)} FROM "{table}" WHERE master_id = ? ORDER BY created_at',
            (master_id,),
        ).fetchall()
        return tuple({name: clean(row[name]) for name in selected} for row in rows)

    def _name_matches(self, normalized_name: str, master_id: str) -> tuple[dict[str, str], ...]:
        if not normalized_name:
            return ()
        matches: list[dict[str, str]] = []
        for table, column in (("scheme_staging", "scheme_name"), ("admin_review_queue", "scheme_name")):
            if table not in self.tables or not {"master_id", column}.issubset(self.columns.get(table, set())):
                continue
            rows = self.connection.execute(
                f'SELECT master_id, "{column}" AS matched_value FROM "{table}" WHERE master_id <> ?',
                (master_id,),
            ).fetchall()
            for row in rows:
                if normalize_name(row["matched_value"]) == normalized_name:
                    matches.append(
                        {
                            "table": table,
                            "master_id": clean(row["master_id"]),
                            "matched_value": clean(row["matched_value"]),
                        }
                    )
        return tuple(matches)

    def _url_matches(self, urls: set[str], master_id: str) -> tuple[dict[str, str], ...]:
        urls = {normalize_url(item) for item in urls if normalize_url(item)}
        if not urls:
            return ()
        matches: list[dict[str, str]] = []
        specifications = (
            ("scheme_staging", ("official_page_url", "application_url")),
            ("admin_review_queue", ("official_page_url", "application_url")),
            ("scheme_sources", ("source_url",)),
        )
        for table, columns in specifications:
            available = [column for column in columns if column in self.columns.get(table, set())]
            if table not in self.tables or "master_id" not in self.columns.get(table, set()) or not available:
                continue
            selected = ", ".join(["master_id"] + [f'"{column}"' for column in available])
            rows = self.connection.execute(
                f'SELECT {selected} FROM "{table}" WHERE master_id <> ?',
                (master_id,),
            ).fetchall()
            for row in rows:
                for column in available:
                    candidate = normalize_url(row[column])
                    if candidate and candidate in urls:
                        matches.append(
                            {
                                "table": table,
                                "column": column,
                                "master_id": clean(row["master_id"]),
                                "matched_value": clean(row[column]),
                            }
                        )
        unique = {json_compact(item): item for item in matches}
        return tuple(unique[item] for item in sorted(unique))

    def inspect(self, row: dict[str, str]) -> DatabaseMatch:
        master_id = clean(row.get("master_id"))
        exact_tables = tuple(
            table
            for table in (
                "scheme_staging",
                "admin_review_queue",
                "admin_review_actions",
                "scheme_sources",
                "scheme_attributes",
                "scheme_contacts",
            )
            if self._exact_in_table(table, master_id)
        )
        name = normalize_name(row.get("scheme_name") or row.get("canonical_name"))
        urls = {clean(row.get("final_url")), clean(row.get("application_url")), clean(row.get("selected_url"))}
        return DatabaseMatch(
            exact_tables=exact_tables,
            action_history=self._action_history(master_id),
            name_matches=self._name_matches(name, master_id),
            url_matches=self._url_matches(urls, master_id),
        )


def record_hash(record: dict[str, Any]) -> str:
    stable = {
        key_name: record.get(key_name, "")
        for key_name in sorted(record)
        if key_name not in {"validated_at_utc", "validation_timestamp"}
    }
    return sha256_text(json_compact(stable))


def append_unique(target: list[str], *values: str) -> None:
    for value in values:
        cleaned = clean(value)
        if cleaned and cleaned not in target:
            target.append(cleaned)


def evaluate_record(
    row: dict[str, str],
    project_root: Path,
    db_match: DatabaseMatch,
    as_of: date,
    validated_at: str,
) -> Evaluation:
    reasons: list[str] = []
    warnings: list[str] = []
    critical: list[str] = []
    actions: list[str] = []
    changed_fields: list[str] = []

    master_id = clean(row.get("master_id"))
    source = clean(row.get("source"))
    canonical_name = clean(row.get("canonical_name"))
    scheme_name = clean(row.get("scheme_name")) or canonical_name
    final_url = normalize_url(row.get("final_url"))
    application_url = normalize_url(row.get("application_url"))
    programme_status = clean(row.get("programme_status")).upper()
    deadline = clean(row.get("deadline"))
    funding_min = clean(row.get("funding_min"))
    funding_max = clean(row.get("funding_max"))
    confidence_before = clamp(parse_float(row.get("confidence"), 0.0))
    quality_flags = parse_json_list(row.get("quality_flags"))
    llm_status = clean(row.get("llm_status")).upper()
    http_status = clean(row.get("http_status"))

    evidence_text, evidence_sources = build_evidence(row, project_root)
    evidence_lower = evidence_text.casefold()
    identity_strength = programme_identity_strength(row, evidence_text)
    official = official_url_for_source(source, final_url)
    negative_hits = classify_negative_page(row, evidence_text)
    deadline_ok = deadline_supported(deadline, evidence_text)
    funding_min_ok = numeric_supported(funding_min, evidence_text)
    funding_max_ok = numeric_supported(funding_max, evidence_text)
    status_ok = status_supported(programme_status, evidence_text, deadline, as_of)
    application_ok = application_url_is_plausible(application_url, final_url)
    application_official = (
        not application_url or official_url_for_source(source, application_url)
    )
    programme_keywords_found = [keyword for keyword in PROGRAMME_KEYWORDS if keyword in evidence_lower]

    normalized_deadline = deadline if deadline_ok else ""
    normalized_funding_min = funding_min if funding_min_ok else ""
    normalized_funding_max = funding_max if funding_max_ok else ""
    normalized_application_url = application_url if application_ok else ""

    if clean(row.get("final_url")) != final_url:
        changed_fields.append("final_url")
    if clean(row.get("application_url")) != normalized_application_url:
        changed_fields.append("application_url")
    if deadline != normalized_deadline:
        changed_fields.append("deadline")
    if funding_min != normalized_funding_min:
        changed_fields.append("funding_min")
    if funding_max != normalized_funding_max:
        changed_fields.append("funding_max")

    if not master_id:
        append_unique(critical, "MASTER_ID_MISSING")
    if not source:
        append_unique(critical, "SOURCE_MISSING")
    if not meaningful_name(scheme_name):
        append_unique(critical, "MEANINGFUL_SCHEME_NAME_MISSING")
    if not final_url:
        append_unique(critical, "FINAL_URL_INVALID_OR_MISSING")
    if final_url and not official:
        append_unique(warnings, "FINAL_URL_NOT_CONFIRMED_OFFICIAL")
        append_unique(actions, "Locate and verify an official government or implementing-agency page.")
    if http_status and http_status not in {"200", "200.0"}:
        append_unique(critical, "HTTP_STATUS_NOT_SUCCESSFUL")
    if clean(row.get("fetch_error")):
        append_unique(critical, "FETCH_ERROR_PRESENT")
    if clean(row.get("parse_error")):
        append_unique(warnings, "PARSE_ERROR_PRESENT")
    if llm_status and llm_status != "SUCCESS":
        append_unique(critical, "LLM_EXTRACTION_NOT_SUCCESSFUL")
    if len(evidence_text) < 120:
        append_unique(critical, "INSUFFICIENT_EVIDENCE_TEXT")
    if identity_strength < 0.45:
        append_unique(critical, "PROGRAMME_IDENTITY_WEAK")
    elif identity_strength < 0.68:
        append_unique(warnings, "PROGRAMME_IDENTITY_REQUIRES_REVIEW")
    if not programme_keywords_found:
        append_unique(critical, "PROGRAMME_OR_SCHEME_EVIDENCE_NOT_FOUND")
    if programme_status and not status_ok:
        append_unique(warnings, "PROGRAMME_STATUS_NOT_SUPPORTED_BY_EVIDENCE")
        append_unique(actions, "Verify programme status from current official evidence.")
    if not programme_status:
        append_unique(warnings, "PROGRAMME_STATUS_MISSING")
        append_unique(actions, "Determine programme-level status without inferring an active call.")
    if deadline and not deadline_ok:
        append_unique(warnings, "DEADLINE_NOT_SUPPORTED_BY_EVIDENCE")
        append_unique(actions, "Verify or remove the deadline before database loading.")
    if funding_min and not funding_min_ok:
        append_unique(warnings, "FUNDING_MINIMUM_NOT_SUPPORTED_BY_EVIDENCE")
        append_unique(actions, "Verify or remove the minimum funding value.")
    if funding_max and not funding_max_ok:
        append_unique(warnings, "FUNDING_MAXIMUM_NOT_SUPPORTED_BY_EVIDENCE")
        append_unique(actions, "Verify or remove the maximum funding value.")
    if application_url and not application_ok:
        append_unique(warnings, "APPLICATION_URL_NOT_DISTINGUISHED_FROM_INFORMATION_URL")
        append_unique(actions, "Confirm a dedicated application or submission URL.")
    if application_url and not application_official:
        append_unique(warnings, "APPLICATION_URL_NOT_CONFIRMED_AUTHORITATIVE")
        append_unique(actions, "Verify that the application portal is linked by the official programme page.")
    for hit in negative_hits:
        append_unique(warnings, hit)
    for flag in quality_flags:
        if flag in {
            "CANONICAL_NAME_EVIDENCE_WEAK",
            "LLM_PROGRAMME_STATUS_UNSUPPORTED",
            "ELIGIBILITY_NOT_FOUND",
            "BENEFITS_NOT_FOUND",
            "APPLICATION_PROCESS_NOT_FOUND",
            "REQUIRED_DOCUMENTS_NOT_FOUND",
            "ACTIVE_CALL_DEADLINE_NOT_VERIFIED",
            "EXPLICIT_FUNDING_AMOUNT_NOT_FOUND",
        }:
            append_unique(warnings, flag)

    if db_match.already_staged:
        append_unique(critical, "DUPLICATE_MASTER_ID_ALREADY_IN_SCHEME_STAGING")
    if db_match.already_queued:
        append_unique(warnings, "MASTER_ID_ALREADY_IN_ADMIN_REVIEW_QUEUE")
    if db_match.previous_rejection:
        append_unique(critical, "MASTER_ID_HAS_PREVIOUS_REJECTION_ACTION")
    if db_match.name_matches:
        append_unique(warnings, "POTENTIAL_DUPLICATE_NORMALIZED_NAME")
    if db_match.url_matches:
        append_unique(warnings, "POTENTIAL_DUPLICATE_NORMALIZED_URL")
    if db_match.orphan_exact_tables:
        append_unique(warnings, "MASTER_ID_PRESENT_IN_RELATED_DATABASE_TABLES_ONLY")
        append_unique(actions, "Inspect orphaned related-table rows before any new insert.")

    score = confidence_before
    score += 0.12 if official else -0.10
    score += 0.14 if meaningful_name(scheme_name) else -0.20
    score += (identity_strength - 0.5) * 0.30
    score += 0.08 if len(evidence_text) >= 500 else -0.05
    score += 0.06 if clean(row.get("eligibility")) else -0.03
    score += 0.06 if clean(row.get("benefits")) else -0.03
    score += 0.04 if clean(row.get("application_process")) else -0.02
    score += 0.03 if clean(row.get("documents_required")) else -0.01
    score += 0.08 if status_ok else -0.08
    score += 0.03 if deadline_ok else -0.06
    score += 0.03 if funding_min_ok and funding_max_ok else -0.06
    score -= min(0.24, len(critical) * 0.08)
    score -= min(0.16, len(warnings) * 0.015)
    confidence_after = clamp(score)

    obvious_non_scheme = bool(negative_hits) and identity_strength < 0.55 and not clean(row.get("eligibility")) and not clean(row.get("benefits"))
    structural_invalid = any(
        item in critical
        for item in (
            "MASTER_ID_MISSING",
            "SOURCE_MISSING",
            "MEANINGFUL_SCHEME_NAME_MISSING",
            "FINAL_URL_INVALID_OR_MISSING",
        )
    )
    unsupported_important_values = any(
        item in warnings
        for item in (
            "DEADLINE_NOT_SUPPORTED_BY_EVIDENCE",
            "FUNDING_MINIMUM_NOT_SUPPORTED_BY_EVIDENCE",
            "FUNDING_MAXIMUM_NOT_SUPPORTED_BY_EVIDENCE",
        )
    )
    evidence_missing = any(
        item in critical
        for item in (
            "INSUFFICIENT_EVIDENCE_TEXT",
            "PROGRAMME_IDENTITY_WEAK",
            "PROGRAMME_OR_SCHEME_EVIDENCE_NOT_FOUND",
            "FETCH_ERROR_PRESENT",
            "HTTP_STATUS_NOT_SUCCESSFUL",
        )
    )

    if db_match.already_staged:
        decision = "REJECTED"
        append_unique(reasons, "DUPLICATE_EXISTING_STAGED_RECORD")
        append_unique(actions, "Do not insert or overwrite the existing staged record.")
    elif db_match.previous_rejection:
        decision = "REJECTED"
        append_unique(reasons, "PREVIOUSLY_REJECTED_RECORD")
        append_unique(actions, "Do not reintroduce without an explicit admin reversal.")
    elif structural_invalid or obvious_non_scheme:
        decision = "REJECTED"
        append_unique(reasons, "INVALID_OR_NON_PROGRAMME_RECORD")
    elif db_match.already_queued:
        decision = "NEEDS_ADMIN_REVIEW"
        append_unique(reasons, "ALREADY_PRESENT_IN_ADMIN_REVIEW_QUEUE")
        append_unique(actions, "Update through the existing review item; do not create a second queue row.")
    elif db_match.potential_duplicate:
        decision = "NEEDS_ADMIN_REVIEW"
        append_unique(reasons, "POTENTIAL_DATABASE_DUPLICATE")
        append_unique(actions, "Compare the candidate with the matched database records.")
    elif db_match.orphan_exact_tables or db_match.action_history:
        decision = "NEEDS_ADMIN_REVIEW"
        append_unique(reasons, "EXISTING_DATABASE_HISTORY_REQUIRES_RECONCILIATION")
        append_unique(actions, "Reconcile related rows or review history before handoff.")
    elif official and application_official and identity_strength >= 0.68 and status_ok and not unsupported_important_values and not evidence_missing and not negative_hits and confidence_after >= 0.72:
        decision = "APPROVED_FOR_DATABASE"
        append_unique(reasons, "STRICT_VALIDATION_REQUIREMENTS_SATISFIED")
        if not application_url:
            append_unique(warnings, "APPLICATION_URL_NOT_AVAILABLE")
    elif identity_strength >= 0.60 and official and not evidence_missing and (
        confidence_after >= 0.56
        or clean(row.get("next_decision")).upper() == "NEEDS_ADMIN_REVIEW"
    ):
        decision = "NEEDS_ADMIN_REVIEW"
        append_unique(reasons, "GENUINE_PROGRAMME_WITH_AMBIGUOUS_OR_CONFLICTING_FIELDS")
    else:
        decision = "NEEDS_MORE_EVIDENCE"
        append_unique(reasons, "INSUFFICIENT_VERIFIABLE_EVIDENCE_FOR_APPROVAL")

    if decision == "APPROVED_FOR_DATABASE":
        handoff_action = "INSERT_CANDIDATE_DRY_RUN"
        handoff_reason = "APPROVED_AND_NOT_FOUND_IN_EXISTING_DATABASE"
    elif decision == "NEEDS_ADMIN_REVIEW" and db_match.already_queued:
        handoff_action = "SKIP_ALREADY_QUEUED"
        handoff_reason = "EXISTING_ADMIN_REVIEW_ITEM_MUST_BE_USED"
    elif decision == "NEEDS_ADMIN_REVIEW":
        handoff_action = "QUEUE_CANDIDATE_DRY_RUN"
        handoff_reason = "ADMIN_REVIEW_REQUIRED_BEFORE_DATABASE_LOADING"
    else:
        handoff_action = "NO_DATABASE_HANDOFF"
        handoff_reason = decision

    db_status = "NO_MATCH"
    if db_match.already_staged:
        db_status = "EXACT_STAGING_MATCH"
    elif db_match.already_queued:
        db_status = "EXACT_ADMIN_QUEUE_MATCH"
    elif db_match.potential_duplicate:
        db_status = "POTENTIAL_NAME_OR_URL_MATCH"
    elif db_match.action_history:
        db_status = "ACTION_HISTORY_ONLY"

    normalized_record = {
        "master_id": master_id,
        "scheme_name": scheme_name,
        "canonical_name": canonical_name,
        "source": source,
        "programme_status": programme_status,
        "deadline": normalized_deadline,
        "funding_min": normalized_funding_min,
        "funding_max": normalized_funding_max,
        "final_url": final_url,
        "application_url": normalized_application_url,
    }

    output = dict(row)
    output.update(
        {
            "normalized_canonical_name": normalize_name(canonical_name),
            "normalized_scheme_name": scheme_name,
            "normalized_programme_status": programme_status,
            "normalized_deadline": normalized_deadline,
            "normalized_funding_min": normalized_funding_min,
            "normalized_funding_max": normalized_funding_max,
            "normalized_final_url": final_url,
            "normalized_application_url": normalized_application_url,
            "validation_decision": decision,
            "validation_score": f"{confidence_after:.3f}",
            "confidence_before_validation": f"{confidence_before:.3f}",
            "confidence_after_validation": f"{confidence_after:.3f}",
            "programme_identity_strength": f"{identity_strength:.3f}",
            "official_url_verified": "YES" if official else "NO",
            "programme_status_supported": "YES" if status_ok else "NO",
            "deadline_supported": "YES" if deadline_ok else "NO",
            "funding_min_supported": "YES" if funding_min_ok else "NO",
            "funding_max_supported": "YES" if funding_max_ok else "NO",
            "application_url_plausible": "YES" if application_ok else "NO",
            "application_url_authoritative": "YES" if application_official else "NO",
            "decision_reason_codes": json_compact(reasons),
            "validation_warnings": json_compact(warnings),
            "critical_flags": json_compact(critical),
            "recommended_actions": json_compact(actions),
            "evidence_url": final_url,
            "evidence_sources_json": json_compact(evidence_sources),
            "evidence_excerpt": evidence_excerpt(evidence_text, scheme_name),
            "changed_fields": json_compact(sorted(set(changed_fields))),
            "db_exact_master_id_match": "YES" if db_match.exact_tables else "NO",
            "db_master_id_tables": json_compact(db_match.exact_tables),
            "db_action_history_json": json_compact(db_match.action_history),
            "db_name_matches_json": json_compact(db_match.name_matches),
            "db_url_matches_json": json_compact(db_match.url_matches),
            "db_match_status": db_status,
            "database_handoff_action": handoff_action,
            "database_handoff_reason": handoff_reason,
            "dry_run": "YES",
            "llm_used_for_validation": "NO",
            "validator_version": VALIDATOR_VERSION,
            "validation_timestamp": validated_at,
        }
    )
    output["validation_record_hash"] = record_hash(output)

    audit = dict(output)
    audit.update(
        {
            "original_record_json": json_compact(row),
            "normalized_record_json": json_compact(normalized_record),
        }
    )

    handoff: dict[str, str] | None = None
    if decision == "APPROVED_FOR_DATABASE":
        handoff = {
            "master_id": master_id,
            "scheme_name": scheme_name,
            "short_name": "",
            "source": source,
            "ministry": clean(row.get("ministry")),
            "department": clean(row.get("department")),
            "implementing_agency": "",
            "record_kind": clean(row.get("master_type")) or "SCHEME_OR_PROGRAMME",
            "programme_status": programme_status,
            "application_status": "",
            "scheme_status": programme_status,
            "geographic_scope": "India",
            "official_page_url": final_url,
            "application_url": normalized_application_url,
            "opening_date": "",
            "closing_date": normalized_deadline,
            "validation_score": f"{confidence_after:.3f}",
            "validation_decision": decision,
            "publication_status": "DRAFT",
            "funding_minimum": normalized_funding_min,
            "funding_maximum": normalized_funding_max,
            "currency": "INR" if normalized_funding_min or normalized_funding_max else "",
            "record_hash": output["validation_record_hash"],
            "raw_record_json": json_compact(output),
            "handoff_action": handoff_action,
            "handoff_reason": handoff_reason,
            "dry_run": "YES",
            "validator_version": VALIDATOR_VERSION,
            "validated_at_utc": validated_at,
        }

    return Evaluation(output=output, audit=audit, handoff=handoff)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        rows = [
            {str(column): "" if value is None else str(value) for column, value in row.items()}
            for row in reader
        ]
        return list(reader.fieldnames), rows


def ordered_fieldnames(rows: list[dict[str, str]], preferred: list[str] | None = None) -> list[str]:
    result: list[str] = []
    for column in preferred or []:
        if column not in result:
            result.append(column)
    for row in rows:
        for column in row:
            if column not in result:
                result.append(column)
    return result


def write_csv_atomic(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fieldnames or ordered_fieldnames(rows)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    temporary.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def distributions(rows: list[dict[str, str]], column: str) -> dict[str, int]:
    counter = Counter(clean(row.get(column)) or "<blank>" for row in rows)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def validate_unique_master_ids(rows: list[dict[str, str]]) -> None:
    values = [clean(row.get("master_id")) for row in rows]
    blanks = [index + 2 for index, value in enumerate(values) if not value]
    if blanks:
        raise ValueError(f"Blank master_id at CSV lines: {blanks}")
    duplicates = {value: count for value, count in Counter(values).items() if count > 1}
    if duplicates:
        raise ValueError(f"Duplicate master_id values: {duplicates}")


def run_validation(
    project_root: Path,
    input_path: Path,
    database_path: Path,
    output_directory: Path,
    as_of: date,
    expected_count: int = DEFAULT_EXPECTED_COUNT,
) -> dict[str, Any]:
    input_columns, rows = read_csv(input_path)
    validate_unique_master_ids(rows)
    if expected_count and len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} records but found {len(rows)} in {input_path}")

    inspector = ReadOnlyDatabaseInspector(database_path)
    validated_at = utc_now()
    try:
        database_counts_before = inspector.snapshot_counts()
        evaluations = [
            evaluate_record(row, project_root, inspector.inspect(row), as_of, validated_at)
            for row in rows
        ]
        database_counts_after = inspector.snapshot_counts()
    finally:
        inspector.close()

    if database_counts_before != database_counts_after:
        raise RuntimeError("Database counts changed during a read-only strict-validation run")

    validated_rows = [item.output for item in evaluations]
    audit_rows = [item.audit for item in evaluations]
    handoff_rows = [item.handoff for item in evaluations if item.handoff is not None]
    subsets = {
        "approved_for_database_v2_7_2.csv": [row for row in validated_rows if row["validation_decision"] == "APPROVED_FOR_DATABASE"],
        "admin_review_queue_v2_7_2.csv": [row for row in validated_rows if row["validation_decision"] == "NEEDS_ADMIN_REVIEW"],
        "needs_more_evidence_v2_7_2.csv": [row for row in validated_rows if row["validation_decision"] == "NEEDS_MORE_EVIDENCE"],
        "rejected_records_v2_7_2.csv": [row for row in validated_rows if row["validation_decision"] == "REJECTED"],
    }

    validated_fields = ordered_fieldnames(validated_rows, input_columns)
    audit_fields = ordered_fieldnames(audit_rows, validated_fields)
    handoff_fields = [
        "master_id",
        "scheme_name",
        "short_name",
        "source",
        "ministry",
        "department",
        "implementing_agency",
        "record_kind",
        "programme_status",
        "application_status",
        "scheme_status",
        "geographic_scope",
        "official_page_url",
        "application_url",
        "opening_date",
        "closing_date",
        "validation_score",
        "validation_decision",
        "publication_status",
        "funding_minimum",
        "funding_maximum",
        "currency",
        "record_hash",
        "raw_record_json",
        "handoff_action",
        "handoff_reason",
        "dry_run",
        "validator_version",
        "validated_at_utc",
    ]

    output_directory.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "validated": output_directory / "validated_records_v2_7_2.csv",
        "audit": output_directory / "validation_audit_v2_7_2.csv",
        "handoff": output_directory / "database_handoff_v2_7_2.csv",
    }
    write_csv_atomic(output_paths["validated"], validated_rows, validated_fields)
    write_csv_atomic(output_paths["audit"], audit_rows, audit_fields)
    write_csv_atomic(output_paths["handoff"], handoff_rows, handoff_fields)
    for filename, subset_rows in subsets.items():
        path = output_directory / filename
        write_csv_atomic(path, subset_rows, validated_fields)
        output_paths[filename] = path

    reason_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    for row in validated_rows:
        reason_counter.update(parse_json_list(row["decision_reason_codes"]))
        warning_counter.update(parse_json_list(row["validation_warnings"]))

    summary: dict[str, Any] = {
        "validator_version": VALIDATOR_VERSION,
        "generated_at_utc": validated_at,
        "as_of_date": as_of.isoformat(),
        "dry_run": True,
        "database_modified": False,
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "database_path": str(database_path),
        "database_sha256_after_read_only_run": sha256_file(database_path),
        "input_record_count": len(rows),
        "expected_record_count": expected_count,
        "output_record_count": len(validated_rows),
        "handoff_candidate_count": len(handoff_rows),
        "records_by_decision": distributions(validated_rows, "validation_decision"),
        "records_by_source": distributions(validated_rows, "source"),
        "database_match_status": distributions(validated_rows, "db_match_status"),
        "database_handoff_actions": distributions(validated_rows, "database_handoff_action"),
        "reason_code_counts": dict(sorted(reason_counter.items())),
        "warning_code_counts": dict(sorted(warning_counter.items())),
        "database_table_counts_before": database_counts_before,
        "database_table_counts_after": database_counts_after,
        "database_counts_unchanged": database_counts_before == database_counts_after,
        "llm_validation_calls": 0,
        "output_files": {},
    }

    summary_path = output_directory / "validation_summary_v2_7_2.json"
    output_paths["summary"] = summary_path
    for name, path in output_paths.items():
        if name == "summary":
            continue
        if path.exists():
            summary["output_files"][name] = {
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
    summary["output_files"]["summary"] = {
        "path": str(summary_path),
        "sha256": None,
        "size_bytes": None,
        "note": "Self-hash intentionally omitted to avoid recursive summary mutation.",
    }
    write_json_atomic(summary_path, summary)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("=" * 78)
    print("SSIP v2.7.2 STRICT VALIDATION AND DATABASE HANDOFF — DRY RUN")
    print("=" * 78)
    print(f"Input records              : {summary['input_record_count']}")
    print(f"Validated records          : {summary['output_record_count']}")
    print(f"Database handoff candidates: {summary['handoff_candidate_count']}")
    print(f"Database modified          : {summary['database_modified']}")
    print(f"Database counts unchanged  : {summary['database_counts_unchanged']}")
    print("\nDecisions:")
    for decision in DECISIONS:
        print(f"  {decision:<28} {summary['records_by_decision'].get(decision, 0):>3}")
    print("\nDatabase handoff actions:")
    for action, count in summary["database_handoff_actions"].items():
        print(f"  {action:<34} {count:>3}")
    print("=" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description="SSIP v2.7.2 deterministic strict validation dry run")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--input", default="data/incremental/v2_7_2_strict_validation/validation_input_manifest_v2_7_2.csv")
    parser.add_argument("--database", default="database/ssip_staging_v1.db")
    parser.add_argument("--output-directory", default="data/incremental/v2_7_2_strict_validation")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_path = (project_root / args.input).resolve()
    database_path = (project_root / args.database).resolve()
    output_directory = (project_root / args.output_directory).resolve()
    try:
        as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
        summary = run_validation(
            project_root=project_root,
            input_path=input_path,
            database_path=database_path,
            output_directory=output_directory,
            as_of=as_of,
            expected_count=args.expected_count,
        )
        print_summary(summary)
        print(f"\nSummary written to:\n{output_directory / 'validation_summary_v2_7_2.json'}")
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
