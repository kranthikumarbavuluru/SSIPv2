from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

VERSION = "3.4.3.7.5"
SOURCE = "MeitY Startup Hub"
MINISTRY = "Ministry of Electronics and Information Technology (MeitY)"
GENESIS_ID = "94f8ab0a070a6ff15fce"
SASACT_ID = "194b7ba77d6b53f30b91"
OFFICIAL_HOSTS = {
    "msh.meity.gov.in",
    "api.meity.gov.in",
    "meity.gov.in",
    "www.meity.gov.in",
}
CALL_MARKERS = (
    "call",
    "challenge",
    "cohort",
    "applications invited",
    "application window",
    "expression of interest",
    " eoi ",
    "request for proposal",
    " rfp ",
    "hackathon",
    "grand challenge",
    "startup applications",
    "invitation",
)
GENERIC_TITLES = {
    "",
    "meitystartuphub",
    "view challenge aspx",
    "register challenge aspx",
    "innovation challenge html",
    "sitemap xml",
    "whatsnew",
    "schemes",
    "program",
    "programme",
    "home",
    "state",
}
QUEUE_FIELDS = (
    "master_id",
    "canonical_name",
    "source",
    "ministry",
    "department",
    "implementing_agency",
    "record_kind",
    "permanent_scheme_or_call",
    "parent_master_id",
    "parent_scheme_name",
    "parent_resolution",
    "official_source_url",
    "application_url",
    "opening_date",
    "deadline",
    "application_status",
    "status_basis",
    "status_evidence",
    "eligible_applicants",
    "applicant_layer",
    "startup_relevance",
    "sector_scope",
    "confidence",
    "network_verified",
    "verified_current",
    "evidence_title",
    "evidence_excerpt",
    "discovered_from",
    "discovery_method",
    "quality_flags",
    "evidence_hash",
)
TITLE_KEYS = (
    "title",
    "name",
    "heading",
    "subject",
    "challenge_name",
    "challengeName",
    "call_name",
    "callName",
)
TEXT_KEYS = (
    "description",
    "details",
    "body",
    "content",
    "summary",
    "objective",
    "eligibility",
    "status",
)
OPEN_KEYS = (
    "opening_date",
    "open_date",
    "start_date",
    "startDate",
    "from_date",
    "application_start_date",
)
CLOSE_KEYS = (
    "closing_date",
    "close_date",
    "end_date",
    "endDate",
    "deadline",
    "last_date",
    "application_end_date",
)
URL_KEYS = (
    "url",
    "link",
    "detail_url",
    "detailUrl",
    "official_url",
    "officialUrl",
    "file_path",
    "selectedfile_path",
)
APPLICATION_KEYS = (
    "application_url",
    "applicationUrl",
    "apply_url",
    "applyUrl",
    "registration_url",
    "registrationUrl",
    "register_url",
    "registerUrl",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace(chr(0), " ").split()).strip()


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).casefold()).strip()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_url(value: Any, base_url: str = "") -> str:
    text = clean(value)
    if not text:
        return ""
    absolute = urllib.parse.urljoin(base_url, html.unescape(text))
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    path = re.sub(r"/+", "/", parsed.path or "/")
    return urllib.parse.urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def official_url(value: Any, base_url: str = "") -> str:
    url = canonical_url(value, base_url)
    if not url:
        return ""
    host = urllib.parse.urlparse(url).netloc.casefold().split(":", 1)[0]
    return url if host in OFFICIAL_HOSTS else ""


def has_call_marker(value: Any) -> bool:
    text = f" {normalized(value)} "
    return any(marker in text for marker in CALL_MARKERS)


def usable_title(value: Any) -> bool:
    text = normalized(value)
    return len(text) >= 5 and text not in GENERIC_TITLES


def title_from_url(url: str) -> str:
    leaf = urllib.parse.unquote(
        urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    )
    leaf = re.sub(r"\.(pdf|html?|aspx?|json)$", "", leaf, flags=re.I)
    leaf = re.sub(r"[_+%\-]+", " ", leaf)
    leaf = re.sub(
        r"\b(final|latest|document|details|om)\b",
        " ",
        leaf,
        flags=re.I,
    )
    return clean(leaf).title()


def parse_date(value: Any) -> date | None:
    text = clean(value)
    if not text:
        return None
    text = re.sub(r"(?i)(st|nd|rd|th)", "", text)
    text = text.replace("/", "-").replace(".", "-")
    for candidate in (text, text[:10], text[:19]):
        for fmt in (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d-%m-%y",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    return None


def iso_date(value: Any) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


@dataclass
class RawCandidate:
    title: str
    evidence_url: str
    application_url: str = ""
    opening_date: str = ""
    closing_date: str = ""
    description: str = ""
    status_text: str = ""
    discovered_from: str = ""
    discovery_method: str = ""
    network_verified: bool = False


@dataclass(frozen=True)
class RecoveryPaths:
    project_root: Path
    config_path: Path
    output_dir: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "RecoveryPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            config_path=(
                root / "config/meity_calls_official_seeds_v3_4_3_7_5.json"
            ),
            output_dir=root / "data/departments/meity/v3_4_3_7_5",
            database_path=root / "database/ssip_staging_v1.db",
        )


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        lowered = tag.casefold()
        if lowered == "a" and values.get("href"):
            self.links.append(values["href"])
        if lowered == "script":
            self._skip += 1
            if values.get("src"):
                self.scripts.append(values["src"])
        elif lowered == "style":
            self._skip += 1
        elif lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style"} and self._skip:
            self._skip -= 1
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = clean(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if not self._skip:
            self.text_parts.append(text)


def fetch_url(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
) -> tuple[int, str, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "SSIP-MeitY-Calls-Recovery/3.4.3.7.5 "
                "(official-evidence verification)"
            ),
            "Accept": (
                "text/html,application/json,application/javascript,"
                "text/javascript,application/pdf,*/*;q=0.5"
            ),
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            return (
                int(response.status),
                clean(response.headers.get("Content-Type")).casefold(),
                response.read(max_bytes),
                "",
            )
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
    ) as exc:
        return (
            int(getattr(exc, "code", 0) or 0),
            "",
            b"",
            f"{type(exc).__name__}: {exc}",
        )


ABSOLUTE_URL_RE = re.compile(
    r"https?://(?:msh|api|www)?\.?meity\.gov\.in"
    r"[A-Za-z0-9_~:/?#\[\]@!$&()*+,;=%.'\-]*",
    re.I,
)
RELATIVE_URL_RE = re.compile(
    r"[\"'](/[^\"'\s]*(?:challenge|cohort|call|application|"
    r"whatsnew|scheme|program|eoi|rfp)[^\"'\s]*)[\"']",
    re.I,
)


def discover_urls(text: str, base_url: str) -> set[str]:
    output: set[str] = set()
    for raw in ABSOLUTE_URL_RE.findall(text):
        url = official_url(raw.rstrip("),.;"), base_url)
        if url:
            output.add(url)
    for raw in RELATIVE_URL_RE.findall(text):
        url = official_url(raw, base_url)
        if url:
            output.add(url)
    return output


def json_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_objects(child)


def first_value(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and clean(mapping.get(key)):
            return mapping.get(key)
    return ""


def candidates_from_json(
    payload: Any,
    *,
    document_url: str,
) -> list[RawCandidate]:
    output: list[RawCandidate] = []
    for item in json_objects(payload):
        title = clean(first_value(item, TITLE_KEYS))
        description = clean(
            " ".join(
                clean(item.get(key))
                for key in TEXT_KEYS
                if clean(item.get(key))
            )
        )
        evidence = (
            official_url(first_value(item, URL_KEYS), document_url)
            or document_url
        )
        application = official_url(
            first_value(item, APPLICATION_KEYS),
            document_url,
        )
        if not has_call_marker(
            " ".join((title, description, evidence, application))
        ):
            continue
        if not usable_title(title):
            title = title_from_url(evidence)
        if not usable_title(title):
            continue
        output.append(
            RawCandidate(
                title=title,
                evidence_url=evidence,
                application_url=application,
                opening_date=clean(first_value(item, OPEN_KEYS)),
                closing_date=clean(first_value(item, CLOSE_KEYS)),
                description=description,
                status_text=clean(item.get("status")),
                discovered_from=document_url,
                discovery_method="network_json",
                network_verified=True,
            )
        )
    return output


def crawl_official(
    config: dict[str, Any],
) -> tuple[list[RawCandidate], list[dict[str, Any]]]:
    timeout = int(config.get("timeout_seconds", 10))
    maximum = int(config.get("max_network_documents", 30))
    max_bytes = int(config.get("max_document_bytes", 2_500_000))
    pending = [
        official_url(url)
        for url in config.get("entry_urls", [])
        if official_url(url)
    ]
    seen: set[str] = set()
    candidates: list[RawCandidate] = []
    fetch_log: list[dict[str, Any]] = []

    while pending and len(seen) < maximum:
        url = pending.pop(0)
        if not url or url in seen:
            continue
        seen.add(url)
        status, content_type, body, error = fetch_url(
            url,
            timeout=timeout,
            max_bytes=max_bytes,
        )
        fetch_log.append(
            {
                "url": url,
                "status_code": status,
                "content_type": content_type,
                "bytes": len(body),
                "error": error,
                "fetched_at": utc_now(),
            }
        )
        if status != 200 or not body:
            continue

        text = body.decode("utf-8", errors="replace")
        discovered: set[str] = set()

        if "json" in content_type or text.lstrip().startswith(("{", "[")):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                candidates.extend(
                    candidates_from_json(
                        payload,
                        document_url=url,
                    )
                )
                for item in json_objects(payload):
                    for key in (*URL_KEYS, *APPLICATION_KEYS):
                        child = official_url(item.get(key), url)
                        if child:
                            discovered.add(child)

        elif (
            "javascript" in content_type
            or url.casefold().split("?", 1)[0].endswith(".js")
        ):
            discovered.update(discover_urls(text, url))

        elif "html" in content_type or "<html" in text[:1000].casefold():
            parser = PageParser()
            try:
                parser.feed(text)
            except Exception:
                pass
            title = clean(" ".join(parser.title_parts))
            page_text = clean(" ".join(parser.text_parts))
            for raw in (*parser.links, *parser.scripts):
                child = official_url(raw, url)
                if child:
                    discovered.add(child)
            discovered.update(discover_urls(text, url))
            if has_call_marker(" ".join((title, page_text, url))):
                rendered = title if usable_title(title) else title_from_url(url)
                if usable_title(rendered):
                    candidates.append(
                        RawCandidate(
                            title=rendered,
                            evidence_url=url,
                            description=page_text[:10_000],
                            discovered_from="official_crawl",
                            discovery_method="network_html",
                            network_verified=True,
                        )
                    )

        for child in sorted(discovered):
            if child not in seen and child not in pending:
                pending.append(child)

    return candidates, fetch_log


def read_local_candidates(
    project_root: Path,
) -> tuple[list[RawCandidate], list[dict[str, Any]]]:
    output: list[RawCandidate] = []
    rejected: list[dict[str, Any]] = []
    meity_root = project_root / "data/departments/meity"
    if not meity_root.exists():
        return output, rejected

    for path in sorted(meity_root.rglob("*.csv")):
        if "v3_4_3_7_5" in path.as_posix():
            continue
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            continue

        for index, row in enumerate(rows, start=2):
            title = clean(
                row.get("title")
                or row.get("heading")
                or row.get("canonical_name")
                or row.get("display_name")
                or row.get("scheme_name")
            )
            evidence = ""
            for key in (
                "canonical_url",
                "url",
                "official_source_url",
                "detail_url",
                "final_url",
                "source_url",
            ):
                evidence = official_url(row.get(key))
                if evidence:
                    break

            discovered_from = official_url(row.get("discovered_from"))
            all_values = " ".join(clean(value) for value in row.values())
            if not has_call_marker(
                " ".join((title, evidence, discovered_from, all_values))
            ):
                continue

            if not evidence:
                rejected.append(
                    {
                        "source_file": str(path.relative_to(project_root)),
                        "locator": f"csv_row:{index}",
                        "title": title,
                        "reason": "NO_OFFICIAL_MEITY_EVIDENCE_URL",
                    }
                )
                continue

            rendered = title if usable_title(title) else title_from_url(evidence)
            if not usable_title(rendered):
                rejected.append(
                    {
                        "source_file": str(path.relative_to(project_root)),
                        "locator": f"csv_row:{index}",
                        "title": title,
                        "url": evidence,
                        "reason": "GENERIC_OR_MISSING_CALL_TITLE",
                    }
                )
                continue

            output.append(
                RawCandidate(
                    title=rendered,
                    evidence_url=evidence,
                    application_url=official_url(row.get("application_url")),
                    opening_date=clean(row.get("opening_date")),
                    closing_date=clean(
                        row.get("closing_date") or row.get("deadline")
                    ),
                    description=clean(
                        row.get("description")
                        or row.get("text_excerpt")
                        or row.get("objective_summary")
                    ),
                    status_text=clean(
                        row.get("status_hint")
                        or row.get("application_status")
                        or row.get("status")
                    ),
                    discovered_from=(
                        discovered_from
                        or str(path.relative_to(project_root))
                    ),
                    discovery_method="local_governed_evidence",
                    network_verified=clean(row.get("status_code")) == "200",
                )
            )

    for path in sorted(meity_root.rglob("*.json")):
        if "v3_4_3_7_5" in path.as_posix():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue

        for item in json_objects(payload):
            title = clean(first_value(item, TITLE_KEYS))
            evidence = ""
            for key in (*URL_KEYS, "official_source_url"):
                evidence = official_url(item.get(key))
                if evidence:
                    break
            if not evidence:
                continue
            combined = clean(" ".join(str(value) for value in item.values()))
            if not has_call_marker(" ".join((title, evidence, combined))):
                continue
            rendered = title if usable_title(title) else title_from_url(evidence)
            if not usable_title(rendered):
                continue
            output.append(
                RawCandidate(
                    title=rendered,
                    evidence_url=evidence,
                    application_url=official_url(
                        first_value(item, APPLICATION_KEYS)
                    ),
                    opening_date=clean(first_value(item, OPEN_KEYS)),
                    closing_date=clean(first_value(item, CLOSE_KEYS)),
                    description=clean(first_value(item, TEXT_KEYS)),
                    status_text=clean(item.get("status")),
                    discovered_from=str(path.relative_to(project_root)),
                    discovery_method="local_governed_evidence",
                    network_verified=False,
                )
            )

    return output, rejected


def load_parents(
    database_path: Path,
) -> dict[str, tuple[str, str]]:
    output: dict[str, tuple[str, str]] = {
        "genesis": (GENESIS_ID, "GENESIS"),
        "sasact": (SASACT_ID, "SASACT"),
    }
    if not database_path.exists():
        return output

    try:
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        for table in ("scheme_staging", "admin_review_queue"):
            try:
                rows = connection.execute(
                    f"SELECT master_id,scheme_name FROM {table}"
                ).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                name = clean(row["scheme_name"])
                key = normalized(name)
                for token in (
                    "samridh",
                    "tide 2 0",
                    "tide",
                    "genesis",
                    "sasact",
                ):
                    if token in key:
                        output.setdefault(
                            token,
                            (str(row["master_id"]), name),
                        )
        connection.close()
    except sqlite3.Error:
        pass

    return output


def resolve_parent(
    candidate: RawCandidate,
    parents: dict[str, tuple[str, str]],
) -> tuple[str, str, str]:
    text = normalized(
        " ".join(
            (
                candidate.title,
                candidate.description,
                candidate.evidence_url,
                candidate.discovered_from,
            )
        )
    )
    for token in (
        "genesis",
        "sasact",
        "samridh",
        "tide 2 0",
        "tide",
    ):
        if token in text and token in parents:
            master_id, name = parents[token]
            return master_id, name, "CURATED_OFFICIAL_RELATIONSHIP"

    if has_call_marker(candidate.title):
        return "", "", "STANDALONE_OFFICIAL_CALL"

    return "", "", "UNRESOLVED"


def status_decision(
    candidate: RawCandidate,
    *,
    today: date,
) -> tuple[str, bool, str, str, str]:
    opening = parse_date(candidate.opening_date)
    closing = parse_date(candidate.closing_date)
    status_text = normalized(candidate.status_text)
    explicit_open = any(
        marker in status_text
        for marker in (
            "open",
            "active",
            "applications invited",
            "ongoing",
        )
    )
    explicit_closed = any(
        marker in status_text
        for marker in (
            "closed",
            "expired",
            "completed",
            "deadline passed",
        )
    )
    application = official_url(candidate.application_url)

    if closing and closing < today:
        return (
            "CLOSED_OR_DEADLINE_PASSED",
            False,
            "",
            "CLOSING_DATE",
            f"Official evidence closing date {closing.isoformat()} has passed.",
        )

    if explicit_closed:
        return (
            "CLOSED_OR_DEADLINE_PASSED",
            False,
            "",
            "EXPLICIT_OFFICIAL_STATUS",
            clean(candidate.status_text),
        )

    if closing and closing >= today:
        if opening and opening > today:
            return (
                "UPCOMING_WINDOW",
                False,
                "",
                "DATED_WINDOW",
                (
                    f"Opening date {opening.isoformat()} and closing date "
                    f"{closing.isoformat()} require curator confirmation."
                ),
            )

        if application and explicit_open and candidate.network_verified:
            return (
                "OPEN_VERIFIED",
                True,
                application,
                "DATED_OFFICIAL_STATUS_AND_ROUTE",
                (
                    f"Official source states {candidate.status_text!r}; "
                    f"closing date {closing.isoformat()}; "
                    "official application route verified."
                ),
            )

        return (
            "CURRENT_WINDOW_REQUIRES_ROUTE_VERIFICATION",
            False,
            "",
            "FUTURE_CLOSING_DATE",
            (
                f"Closing date {closing.isoformat()} is current or future, "
                "but explicit live status and application route were not "
                "both verified."
            ),
        )

    if explicit_open:
        return (
            "STATUS_REQUIRES_DEADLINE_VERIFICATION",
            False,
            "",
            "EXPLICIT_STATUS_WITHOUT_VERIFIED_DEADLINE",
            clean(candidate.status_text),
        )

    return (
        "VERIFICATION_REQUIRED",
        False,
        "",
        "INSUFFICIENT_CURRENT_STATUS_EVIDENCE",
        (
            "No verified current deadline and official application "
            "route were established."
        ),
    )


def score(candidate: RawCandidate) -> float:
    value = 0.35
    if has_call_marker(candidate.title):
        value += 0.25
    if candidate.network_verified:
        value += 0.15
    if parse_date(candidate.closing_date):
        value += 0.10
    if candidate.description:
        value += 0.05
    if candidate.application_url:
        value += 0.05
    if candidate.discovery_method == "local_governed_evidence":
        value += 0.05
    return min(round(value, 3), 0.99)


def merge_candidates(
    candidates: Iterable[RawCandidate],
) -> list[RawCandidate]:
    merged: dict[str, RawCandidate] = {}

    for candidate in candidates:
        key = (
            f"{normalized(candidate.title)}|"
            f"{canonical_url(candidate.evidence_url)}"
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue

        if candidate.network_verified and not existing.network_verified:
            merged[key] = candidate
            existing = candidate

        existing.application_url = (
            existing.application_url or candidate.application_url
        )
        existing.opening_date = (
            existing.opening_date or candidate.opening_date
        )
        existing.closing_date = (
            existing.closing_date or candidate.closing_date
        )
        existing.description = (
            existing.description or candidate.description
        )
        existing.status_text = (
            existing.status_text or candidate.status_text
        )

    return sorted(
        merged.values(),
        key=lambda item: (
            normalized(item.title),
            item.evidence_url,
        ),
    )


def to_queue_row(
    candidate: RawCandidate,
    *,
    parents: dict[str, tuple[str, str]],
    today: date,
) -> dict[str, Any] | None:
    evidence = official_url(candidate.evidence_url)
    if not evidence or not usable_title(candidate.title):
        return None

    if not has_call_marker(
        " ".join(
            (
                candidate.title,
                candidate.description,
                evidence,
                candidate.discovered_from,
            )
        )
    ):
        return None

    confidence = score(candidate)
    if confidence < 0.55:
        return None

    parent_id, parent_name, parent_resolution = resolve_parent(
        candidate,
        parents,
    )
    status, verified, application, basis, status_evidence = (
        status_decision(candidate, today=today)
    )

    identity = (
        f"{normalized(candidate.title)}|"
        f"{canonical_url(evidence)}"
    )
    master_id = (
        "meitycall_"
        + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    )

    excerpt = clean(candidate.description)[:1200]
    flags: list[str] = []

    if parent_resolution == "UNRESOLVED":
        flags.append("PARENT_RELATIONSHIP_REQUIRES_VERIFICATION")
    if not parse_date(candidate.closing_date):
        flags.append("DEADLINE_REQUIRES_VERIFICATION")
    if not verified:
        flags.append("NO_PUBLIC_APPLY_ROUTE")
    if not candidate.network_verified:
        flags.append("REVERIFY_OFFICIAL_SOURCE_LIVE")

    evidence_hash = hashlib.sha256(
        stable_json(
            {
                "title": candidate.title,
                "evidence_url": evidence,
                "application_url": application,
                "opening_date": iso_date(candidate.opening_date),
                "closing_date": iso_date(candidate.closing_date),
                "status": status,
                "excerpt": excerpt,
            }
        ).encode("utf-8")
    ).hexdigest()

    return {
        "master_id": master_id,
        "canonical_name": clean(candidate.title),
        "source": SOURCE,
        "ministry": MINISTRY,
        "department": "",
        "implementing_agency": SOURCE,
        "record_kind": "APPLICATION_CALL",
        "permanent_scheme_or_call": "CALL_INSTANCE",
        "parent_master_id": parent_id,
        "parent_scheme_name": parent_name,
        "parent_resolution": parent_resolution,
        "official_source_url": evidence,
        "application_url": application,
        "opening_date": iso_date(candidate.opening_date),
        "deadline": iso_date(candidate.closing_date),
        "application_status": status,
        "status_basis": basis,
        "status_evidence": status_evidence,
        "eligible_applicants": "",
        "applicant_layer": "REQUIRES_ADMIN_VERIFICATION",
        "startup_relevance": "DIRECT_OR_REVIEW_REQUIRED",
        "sector_scope": "UNKNOWN",
        "confidence": f"{confidence:.3f}",
        "network_verified": str(candidate.network_verified),
        "verified_current": str(verified),
        "evidence_title": clean(candidate.title),
        "evidence_excerpt": excerpt,
        "discovered_from": clean(candidate.discovered_from),
        "discovery_method": clean(candidate.discovery_method),
        "quality_flags": ";".join(flags),
        "evidence_hash": evidence_hash,
    }


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: row.get(field, "") for field in fields}
            )


class MeitYCallsRecovery:
    def __init__(self, paths: RecoveryPaths) -> None:
        self.paths = paths

    def run(
        self,
        *,
        network: bool = True,
        today: date | None = None,
    ) -> dict[str, Any]:
        config = json.loads(
            self.paths.config_path.read_text(encoding="utf-8")
        )
        effective_today = today or datetime.now(timezone.utc).date()

        local, rejected = read_local_candidates(
            self.paths.project_root
        )
        network_rows: list[RawCandidate] = []
        fetch_log: list[dict[str, Any]] = []

        if network:
            network_rows, fetch_log = crawl_official(config)

        merged = merge_candidates([*local, *network_rows])
        parents = load_parents(self.paths.database_path)

        rows: list[dict[str, Any]] = []
        for candidate in merged:
            row = to_queue_row(
                candidate,
                parents=parents,
                today=effective_today,
            )
            if row is None:
                rejected.append(
                    {
                        "title": candidate.title,
                        "url": candidate.evidence_url,
                        "reason": (
                            "NOT_QUEUE_ELIGIBLE_AFTER_GOVERNED_CLASSIFICATION"
                        ),
                    }
                )
            else:
                rows.append(row)

        rows = sorted(
            {row["master_id"]: row for row in rows}.values(),
            key=lambda row: (
                normalized(row["canonical_name"]),
                row["master_id"],
            ),
        )

        output = self.paths.output_dir
        queue_path = output / "meity_admin_review_queue_v3_4_3_7_5.csv"
        candidate_path = output / "meity_call_candidates_v3_4_3_7_5.csv"
        fetch_path = output / "meity_fetch_log_v3_4_3_7_5.csv"
        rejected_path = output / "meity_rejected_noise_v3_4_3_7_5.csv"
        report_path = output / "meity_calls_recovery_report_v3_4_3_7_5.json"

        write_csv(queue_path, rows, QUEUE_FIELDS)
        write_csv(candidate_path, rows, QUEUE_FIELDS)
        write_csv(
            fetch_path,
            fetch_log,
            (
                "url",
                "status_code",
                "content_type",
                "bytes",
                "error",
                "fetched_at",
            ),
        )

        rejection_fields = sorted(
            {key for row in rejected for key in row}
            or {"reason"}
        )
        write_csv(rejected_path, rejected, rejection_fields)

        verified = [
            row
            for row in rows
            if row["verified_current"] == "True"
        ]
        historical = [
            row
            for row in rows
            if row["application_status"]
            == "CLOSED_OR_DEADLINE_PASSED"
        ]
        unresolved = [
            row
            for row in rows
            if row["parent_resolution"] == "UNRESOLVED"
        ]

        report: dict[str, Any] = {
            "version": VERSION,
            "phase": (
                "MeitY Calls, Challenges and Application "
                "Windows Recovery"
            ),
            "generated_at": utc_now(),
            "effective_date": effective_today.isoformat(),
            "network_requested": network,
            "network_documents_attempted": len(fetch_log),
            "network_documents_successful": sum(
                row["status_code"] == 200 for row in fetch_log
            ),
            "local_raw_candidates": len(local),
            "network_raw_candidates": len(network_rows),
            "merged_raw_candidates": len(merged),
            "admin_queue_count": len(rows),
            "verified_current_call_count": len(verified),
            "historical_or_closed_call_count": len(historical),
            "unresolved_parent_count": len(unresolved),
            "public_application_route_count": sum(
                bool(row["application_url"]) for row in rows
            ),
            "off_domain_sources_accepted": 0,
            "permanent_scheme_records_modified": 0,
            "database_modified": False,
            "publication_performed": False,
            "output_files": {
                "admin_queue": str(queue_path),
                "candidates": str(candidate_path),
                "fetch_log": str(fetch_path),
                "rejected_noise": str(rejected_path),
            },
        }

        report["recovery_signature"] = hashlib.sha256(
            stable_json(
                {
                    "effective_date": report["effective_date"],
                    "queue": rows,
                }
            ).encode("utf-8")
        ).hexdigest()

        output.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return report


def self_test() -> dict[str, bool]:
    today = date(2026, 7, 14)

    strict = RawCandidate(
        title="GENESIS Startup Applications Cohort 3",
        evidence_url=(
            "https://msh.meity.gov.in/challenges/genesis-cohort-3"
        ),
        application_url=(
            "https://msh.meity.gov.in/register/genesis-cohort-3"
        ),
        closing_date="2026-08-31",
        status_text="Open",
        network_verified=True,
    )
    strict_status = status_decision(strict, today=today)

    no_route = RawCandidate(
        title="SASACT Applications Invited",
        evidence_url=(
            "https://msh.meity.gov.in/challenges/sasact-2026"
        ),
        closing_date="2026-08-31",
        status_text="Open",
        network_verified=True,
    )
    no_route_status = status_decision(no_route, today=today)

    closed = RawCandidate(
        title="SAMRIDH 2nd Cohort",
        evidence_url=(
            "https://msh.meity.gov.in/assets/samridh-cohort.pdf"
        ),
        closing_date="2025-12-31",
        network_verified=True,
    )
    closed_status = status_decision(closed, today=today)

    parent = resolve_parent(
        strict,
        {"genesis": (GENESIS_ID, "GENESIS")},
    )

    return {
        "off_domain_rejected": (
            official_url("https://example.com/challenge") == ""
        ),
        "generic_title_rejected": (
            not usable_title("View Challenge.Aspx")
        ),
        "strict_open_verified": (
            strict_status[0] == "OPEN_VERIFIED"
            and strict_status[1]
            and bool(strict_status[2])
        ),
        "open_without_route_suppressed": (
            no_route_status[0]
            == "CURRENT_WINDOW_REQUIRES_ROUTE_VERIFICATION"
            and not no_route_status[1]
            and no_route_status[2] == ""
        ),
        "past_deadline_closed": (
            closed_status[0] == "CLOSED_OR_DEADLINE_PASSED"
        ),
        "parent_identity_preserved": parent[0] == GENESIS_ID,
    }
