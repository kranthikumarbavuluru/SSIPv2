from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator


VERSION = "3.4.3.8.0"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 SSIP-MeitY-Intelligence/3.4.3.8.0"
)

CALL_TYPES = {
    "APPLICATION_CALL",
    "CHALLENGE_CALL",
    "GRAND_CHALLENGE",
    "HACKATHON",
    "ACCELERATOR_COHORT",
    "EOI",
    "RFP",
    "IMPLEMENTATION_PARTNER_CALL",
}
EVENT_TYPES = {
    "RESULT_ANNOUNCEMENT",
    "EXTENSION_NOTICE",
    "CORRIGENDUM",
    "WINNER_NOTICE",
    "SELECTED_COHORT",
}
PERMANENT_TYPES = {
    "PERMANENT_SCHEME",
    "PERMANENT_PROGRAMME",
    "ACCELERATOR_PROGRAMME",
    "GRANT_PROGRAMME",
    "INCUBATION_PROGRAMME",
    "ECOSYSTEM_PROGRAMME",
    "IMPLEMENTATION_PROGRAMME",
}
EXCLUDED_TYPES = {
    "DIRECTORY_OR_LISTING",
    "EVENT_OR_CONFERENCE",
    "PRESS_RELEASE_OR_NEWS",
    "ORGANISATION_PROFILE",
    "NAVIGATION_PAGE",
    "UNRESOLVED_NON_CALL",
}

OPEN_MARKERS = (
    "applications are invited",
    "application is invited",
    "apply now",
    "register now",
    "applications open",
    "application open",
    "submit your application",
    "last date to apply",
    "deadline for application",
    "open for applications",
)
CLOSED_MARKERS = (
    "applications closed",
    "application closed",
    "deadline has passed",
    "closed for applications",
    "call closed",
)
RESULT_MARKERS = (
    "winner",
    "runner-up",
    "runner up",
    "results of",
    "result announcement",
    "selected startups",
    "selected start-ups",
    "awardees",
    "final results",
    "declared the result",
)
CALL_MARKERS = (
    "applications invited",
    "call for applications",
    "call for proposal",
    "call for proposals",
    "challenge",
    "hackathon",
    "cohort",
    "expression of interest",
    "request for proposal",
    "apply now",
    "application window",
)
PROGRAMME_MARKERS = (
    "scheme",
    "programme",
    "program",
    "accelerator",
    "incubation",
    "grant support",
    "startup support",
    "start-up support",
    "funding support",
)
EVENT_MARKERS = (
    "conference",
    "summit",
    "delegation",
    "expo",
    "exhibition",
    "event partner",
    "vivatech",
)
GENERIC_TITLE_WORDS = {
    "home", "schemes", "scheme", "challenges", "challenge",
    "whatsnew", "what s new", "what's new", "press release all",
    "event partner", "organisationprofile", "organisation profile",
    "meity startup hub", "msh",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def slug_tokens(value: str) -> list[str]:
    value = re.sub(r"(?i)\b(meity|startup hub|official|government)\b", " ", value)
    return [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()
        if len(token) > 1 and token not in {
            "the", "and", "for", "of", "to", "in", "on", "with",
            "scheme", "programme", "program", "call", "application",
        }
    ]


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_url(url: str, base: str = "") -> str:
    url = clean(url)
    if not url:
        return ""
    absolute = urllib.parse.urljoin(base, html.unescape(url))
    parsed = urllib.parse.urlsplit(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.netloc.casefold()
    path = re.sub(r"/+", "/", parsed.path or "/")
    query_pairs = [
        pair
        for pair in urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
        if pair[0].casefold()
        not in {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "gclid",
        }
    ]
    query = urllib.parse.urlencode(query_pairs)
    return urllib.parse.urlunsplit(
        (parsed.scheme.casefold(), host, path, query, "")
    )


def official_domain(url: str, domains: Iterable[str]) -> bool:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    host = host.casefold()
    return any(
        host == domain.casefold()
        or host.endswith("." + domain.casefold())
        for domain in domains
    )


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
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: row.get(field, "") for field in fields}
            )


class DiscoveryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.forms: list[str] = []
        self.headings: list[str] = []
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._skip = 0
        self._heading_depth = 0
        self._in_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr = {
            key.casefold(): (value or "")
            for key, value in attrs
        }
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "a" and attr.get("href"):
            self.links.append(attr["href"])
        if tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])
        if tag == "form" and attr.get("action"):
            self.forms.append(attr["action"])
        if tag in {"h1", "h2", "h3"}:
            self._heading_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = clean(
                attr.get("property")
                or attr.get("name")
                or attr.get("itemprop")
                or ""
            ).casefold()
            value = attr.get("content", "")
            if key and value:
                self.meta[key] = value

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if (
            tag in {"script", "style", "noscript", "svg"}
            and self._skip
        ):
            self._skip -= 1
        if (
            tag in {"h1", "h2", "h3"}
            and self._heading_depth
        ):
            self._heading_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = clean(data)
        if not value:
            return
        if self._in_title:
            self.title_parts.append(value)
        if self._heading_depth:
            self.headings.append(value)
        if not self._skip:
            self.text_parts.append(value)

    @property
    def title(self) -> str:
        return clean(" ".join(self.title_parts))

    @property
    def visible_text(self) -> str:
        return clean(" ".join(self.text_parts))


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    data: bytes
    method: str
    error: str = ""
    elapsed_seconds: float = 0.0

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.data)

    @property
    def text(self) -> str:
        content_type = self.content_type.casefold()
        if (
            "text/" in content_type
            or "json" in content_type
            or "javascript" in content_type
            or self.final_url.casefold().endswith(
                (".js", ".json", ".html", "/")
            )
        ):
            for encoding in (
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "latin-1",
            ):
                try:
                    return self.data.decode(encoding)
                except UnicodeDecodeError:
                    continue
        return ""


class HttpFetcher:
    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.context = ssl.create_default_context()

    def fetch(self, url: str) -> FetchResult:
        started = time.monotonic()
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/json,application/pdf,"
                    "text/javascript,*/*;q=0.8"
                ),
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self.context,
            ) as response:
                data = response.read()
                return FetchResult(
                    requested_url=url,
                    final_url=response.geturl(),
                    status_code=int(
                        getattr(response, "status", 200) or 200
                    ),
                    content_type=response.headers.get(
                        "Content-Type",
                        "",
                    ),
                    data=data,
                    method="HTTP",
                    elapsed_seconds=time.monotonic() - started,
                )
        except Exception as exc:
            return FetchResult(
                requested_url=url,
                final_url=url,
                status_code=0,
                content_type="",
                data=b"",
                method="HTTP",
                error=f"{type(exc).__name__}: {exc}",
                elapsed_seconds=time.monotonic() - started,
            )


class BrowserRenderer:
    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.executable = self._find_browser()

    @staticmethod
    def _find_browser() -> str:
        candidates = [
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("google-chrome"),
            shutil.which("chromium"),
        ]
        for variable in (
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "LOCALAPPDATA",
        ):
            base = os.environ.get(variable, "")
            if not base:
                continue
            candidates.extend(
                [
                    str(
                        Path(base)
                        / "Microsoft/Edge/Application/msedge.exe"
                    ),
                    str(
                        Path(base)
                        / "Google/Chrome/Application/chrome.exe"
                    ),
                    str(
                        Path(base)
                        / "Chromium/Application/chrome.exe"
                    ),
                ]
            )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(Path(candidate))
        return ""

    def render(self, url: str) -> FetchResult:
        if not self.executable:
            return FetchResult(
                requested_url=url,
                final_url=url,
                status_code=0,
                content_type="text/html",
                data=b"",
                method="BROWSER",
                error=(
                    "No Chrome or Edge headless executable "
                    "was found."
                ),
            )
        started = time.monotonic()
        commands = [
            [
                self.executable,
                "--headless=new",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--virtual-time-budget=12000",
                "--dump-dom",
                url,
            ],
            [
                self.executable,
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--disable-extensions",
                "--virtual-time-budget=12000",
                "--dump-dom",
                url,
            ],
        ]
        errors: list[str] = []
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=self.timeout,
                    check=False,
                )
                if (
                    result.returncode == 0
                    and len(result.stdout) > 200
                ):
                    return FetchResult(
                        requested_url=url,
                        final_url=url,
                        status_code=200,
                        content_type=(
                            "text/html; rendered=browser"
                        ),
                        data=result.stdout,
                        method="BROWSER",
                        elapsed_seconds=(
                            time.monotonic() - started
                        ),
                    )
                errors.append(
                    f"exit={result.returncode}: "
                    + clean(
                        result.stderr.decode(
                            "utf-8",
                            errors="replace",
                        )
                    )[:500]
                )
            except Exception as exc:
                errors.append(
                    f"{type(exc).__name__}: {exc}"
                )
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=0,
            content_type="text/html",
            data=b"",
            method="BROWSER",
            error=" | ".join(errors),
            elapsed_seconds=time.monotonic() - started,
        )


def looks_like_app_shell(
    parser: DiscoveryHTMLParser,
    html_text: str,
) -> bool:
    text = parser.visible_text.casefold()
    if len(text) < 400:
        return True
    if clean(text) in {
        "meitystartuphub",
        "meity startup hub",
        "loading",
        "please wait",
    }:
        return True
    if (
        len(parser.links) < 4
        and len(parser.scripts) > 0
        and re.search(
            r'<div[^>]+id=["\'](?:root|app)["\']',
            html_text,
            re.I,
        )
    ):
        return True
    return False


ABSOLUTE_URL_RE = re.compile(
    r"""
    https?://[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+
    """,
    re.I | re.X,
)
RELATIVE_ENDPOINT_RE = re.compile(
    r"""
    ["'](
        /(?:
            api|backend|services?|schemes?|programmes?|
            programs?|challenges?|whatsnew|announcements?|
            results?|documents?|uploads?|media|downloads?|
            assets?
        )
        /?[a-z0-9._~:/?#\[\]@!$&()*+,;=%-]*
    )["']
    """,
    re.I | re.X,
)


def extract_js_urls(
    text: str,
    base_url: str,
) -> set[str]:
    urls: set[str] = set()
    for match in ABSOLUTE_URL_RE.findall(text):
        value = canonical_url(
            match.rstrip("\\'\""),
            base_url,
        )
        if value:
            urls.add(value)
    for match in RELATIVE_ENDPOINT_RE.findall(text):
        value = canonical_url(match, base_url)
        if value:
            urls.add(value)
    for encoded in re.findall(
        r"(?i)(?:https?:)?\\?/\\?/"
        r"[a-z0-9._~:/?&=%-]+",
        text,
    ):
        value = canonical_url(
            encoded.replace("\\/", "/"),
            base_url,
        )
        if value:
            urls.add(value)
    return urls


def walk_json(
    value: Any,
    path: str = "$",
) -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(
                child,
                f"{path}.{key}",
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(
                child,
                f"{path}[{index}]",
            )


def extract_json_urls(
    value: Any,
    base_url: str,
) -> set[str]:
    urls: set[str] = set()
    for _, child in walk_json(value):
        if not isinstance(child, str):
            continue
        if (
            child.startswith(
                ("http://", "https://", "/")
            )
            or ".pdf" in child.casefold()
        ):
            candidate = canonical_url(child, base_url)
            if candidate:
                urls.add(candidate)
    return urls


def dict_title(record: dict[str, Any]) -> str:
    for key in (
        "title",
        "name",
        "schemeName",
        "scheme_name",
        "programmeName",
        "programName",
        "challengeName",
        "heading",
        "subject",
        "label",
    ):
        value = clean(record.get(key))
        if value:
            return value
    return ""


def dict_url(
    record: dict[str, Any],
    base: str,
) -> str:
    for key in (
        "url",
        "link",
        "href",
        "pageUrl",
        "page_url",
        "officialUrl",
        "official_url",
        "documentUrl",
        "attachment",
        "file",
        "pdf",
    ):
        value = clean(record.get(key))
        if not value:
            continue
        result = canonical_url(value, base)
        if result:
            return result
    return base


def flatten_json_records(
    value: Any,
    base_url: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, child in walk_json(value):
        if not isinstance(child, dict):
            continue
        title = dict_title(child)
        if not title:
            continue
        payload = stable_json(child)
        key = hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        text_values = [
            clean(item)
            for _, item in walk_json(child)
            if isinstance(item, (str, int, float))
        ]
        records.append(
            {
                "title": title,
                "url": dict_url(child, base_url),
                "text": clean(
                    " ".join(text_values)
                )[:12000],
                "json_path": path,
                "raw_json": payload[:30000],
            }
        )
    return records


DATE_PATTERNS = (
    re.compile(
        r"\b([0-3]?\d)[./\-\s]+"
        r"([01]?\d)[./\-\s]+(20\d{2})\b"
    ),
    re.compile(
        r"\b([0-3]?\d)\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)"
        r"[\s,]+(20\d{2})\b",
        re.I,
    ),
    re.compile(
        r"\b"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+([0-3]?\d)[,\s]+(20\d{2})\b",
        re.I,
    ),
)
MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def extract_dates(text: str) -> list[date]:
    dates: set[date] = set()
    for index, pattern in enumerate(DATE_PATTERNS):
        for match in pattern.finditer(text):
            try:
                if index == 0:
                    day, month, year = map(
                        int,
                        match.groups(),
                    )
                elif index == 1:
                    day = int(match.group(1))
                    month = MONTHS[
                        match.group(2)[:3].casefold()
                    ]
                    year = int(match.group(3))
                else:
                    month = MONTHS[
                        match.group(1)[:3].casefold()
                    ]
                    day = int(match.group(2))
                    year = int(match.group(3))
                dates.add(date(year, month, day))
            except (ValueError, KeyError):
                continue
    return sorted(dates)


def find_context_date(
    text: str,
    markers: Iterable[str],
) -> str:
    lowered = text.casefold()
    found: list[date] = []
    for marker in markers:
        position = lowered.find(marker)
        if position < 0:
            continue
        segment = text[
            max(0, position - 120):
            position + 260
        ]
        found.extend(extract_dates(segment))
    return max(found).isoformat() if found else ""


def derive_open_close_dates(
    text: str,
) -> tuple[str, str]:
    opening = find_context_date(
        text,
        (
            "opening date",
            "applications open",
            "application starts",
            "start date",
            "commencement",
        ),
    )
    closing = find_context_date(
        text,
        (
            "closing date",
            "last date",
            "deadline",
            "apply by",
            "applications close",
            "submission date",
        ),
    )
    all_dates = extract_dates(text)
    if not closing and all_dates:
        closing = max(all_dates).isoformat()
    if not opening and len(all_dates) >= 2:
        opening = min(all_dates).isoformat()
    return opening, closing


def extract_application_url(
    urls: Iterable[str],
) -> str:
    priorities = (
        "apply",
        "application",
        "register",
        "registration",
        "submit",
        "portal",
        "login",
        "challenge.gov",
        "forms.",
    )
    candidates = [
        canonical_url(url)
        for url in urls
        if canonical_url(url)
    ]
    for priority in priorities:
        for url in candidates:
            if priority in url.casefold():
                return url
    return ""


def title_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    name = (
        Path(path).name
        or Path(path.rstrip("/")).name
    )
    name = urllib.parse.unquote(name)
    name = re.sub(
        r"\.(?:html?|php|aspx?|pdf|docx?|json)$",
        "",
        name,
        flags=re.I,
    )
    return clean(
        re.sub(r"[-_]+", " ", name)
    ).title()


def clean_title(value: str) -> str:
    value = clean(html.unescape(value))
    value = re.sub(
        r"(?i)\s*[-|:]\s*"
        r"(?:meity\s*startup\s*hub|msh|meity)\s*$",
        "",
        value,
    )
    value = re.sub(
        r"(?i)^details?\s*(?:of|for)?\s*",
        "",
        value,
    )
    return clean(value)


def choose_title(
    parser: DiscoveryHTMLParser | None,
    url: str,
    proposed: str = "",
) -> str:
    candidates = [proposed]
    if parser:
        candidates.extend(parser.headings[:5])
        candidates.extend(
            [
                parser.meta.get("og:title", ""),
                parser.meta.get("twitter:title", ""),
                parser.title,
            ]
        )
    candidates.append(title_from_url(url))
    for candidate in candidates:
        value = clean_title(candidate)
        normalized = " ".join(slug_tokens(value))
        if (
            value
            and normalized not in GENERIC_TITLE_WORDS
            and len(value) >= 3
        ):
            return value
    return (
        clean_title(title_from_url(url))
        or "Unresolved MeitY Record"
    )


def score_startup_relevance(
    text: str,
) -> tuple[str, float]:
    lowered = text.casefold()
    direct = sum(
        marker in lowered
        for marker in (
            "startup",
            "start-up",
            "innovator",
            "innovation challenge",
            "early-stage",
            "early stage",
            "dpiit recognised",
            "dpiit-recognised",
            "entrepreneur",
        )
    )
    intermediary = sum(
        marker in lowered
        for marker in (
            "incubator",
            "accelerator",
            "implementation partner",
            "ecosystem partner",
            "centre of excellence",
            "cohort manager",
        )
    )
    if direct >= 2:
        return (
            "STARTUP_DIRECT",
            min(0.98, 0.65 + direct * 0.07),
        )
    if direct == 1 and intermediary:
        return "STARTUP_AND_ECOSYSTEM", 0.78
    if intermediary >= 1:
        return (
            "ECOSYSTEM_INTERMEDIARY",
            min(0.9, 0.62 + intermediary * 0.08),
        )
    return "RELEVANCE_REVIEW", 0.42


def classify_entity(
    title: str,
    text: str,
    url: str,
    content_type: str,
) -> tuple[str, str, float]:
    combined = clean(
        f"{title} {url} {text}"
    ).casefold()
    title_key = clean(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            title.casefold(),
        )
    )
    path = urllib.parse.urlsplit(url).path.casefold()

    if (
        title_key in GENERIC_TITLE_WORDS
        or path.rstrip("/")
        in {
            "/schemes",
            "/challenges",
            "/whatsnew",
            "/press-release-all",
        }
    ):
        return (
            "DIRECTORY_OR_LISTING",
            "Generic directory/listing identity",
            0.99,
        )
    if any(
        marker in combined
        for marker in RESULT_MARKERS
    ):
        return (
            "RESULT_ANNOUNCEMENT",
            "Official result/winner markers",
            0.94,
        )
    if "corrigendum" in combined:
        return (
            "CORRIGENDUM",
            "Corrigendum marker",
            0.95,
        )
    if any(
        marker in combined
        for marker in (
            "extension of last date",
            "deadline extended",
            "date extension",
        )
    ):
        return (
            "EXTENSION_NOTICE",
            "Deadline-extension marker",
            0.94,
        )
    if (
        any(
            marker in combined
            for marker in EVENT_MARKERS
        )
        and not any(
            marker in combined
            for marker in CALL_MARKERS
        )
    ):
        return (
            "EVENT_OR_CONFERENCE",
            "Event/conference page without call markers",
            0.88,
        )
    if (
        "organisation profile" in combined
        or "organisationprofile" in combined
    ):
        return (
            "ORGANISATION_PROFILE",
            "Organisation profile page",
            0.99,
        )
    if (
        "press release" in title.casefold()
        and not any(
            marker in combined
            for marker in CALL_MARKERS
        )
    ):
        return (
            "PRESS_RELEASE_OR_NEWS",
            "News page without a call identity",
            0.82,
        )

    call_context = any(
        marker in combined
        for marker in CALL_MARKERS
    )
    if "grand challenge" in combined and call_context:
        return (
            "GRAND_CHALLENGE",
            "Grand challenge markers",
            0.91,
        )
    if "hackathon" in combined and call_context:
        return (
            "HACKATHON",
            "Hackathon markers",
            0.91,
        )
    if "challenge" in combined and call_context:
        return (
            "CHALLENGE_CALL",
            "Challenge and application markers",
            0.87,
        )
    if (
        "expression of interest" in combined
        or re.search(r"\beoi\b", combined)
    ):
        return (
            "EOI",
            "Expression of interest markers",
            0.9,
        )
    if (
        "request for proposal" in combined
        or re.search(r"\brfp\b", combined)
    ):
        return (
            "RFP",
            "Request for proposal markers",
            0.9,
        )
    if "cohort" in combined and call_context:
        return (
            "ACCELERATOR_COHORT",
            "Dated cohort/call markers",
            0.84,
        )
    if (
        call_context
        and any(
            marker in combined
            for marker in OPEN_MARKERS
        )
    ):
        return (
            "APPLICATION_CALL",
            "Application-call markers",
            0.86,
        )

    programme_context = any(
        marker in combined
        for marker in PROGRAMME_MARKERS
    )
    if programme_context:
        if "accelerator" in combined:
            return (
                "ACCELERATOR_PROGRAMME",
                "Permanent accelerator description",
                0.78,
            )
        if "incubat" in combined:
            return (
                "INCUBATION_PROGRAMME",
                "Permanent incubation description",
                0.78,
            )
        if (
            "grant" in combined
            or "funding" in combined
        ):
            return (
                "GRANT_PROGRAMME",
                "Permanent grant/funding description",
                0.76,
            )
        if (
            "/schemes/" in path
            or "/scheme/" in path
            or "scheme" in combined
        ):
            return (
                "PERMANENT_SCHEME",
                "Permanent scheme page markers",
                0.8,
            )
        return (
            "PERMANENT_PROGRAMME",
            "Permanent programme description",
            0.73,
        )

    if content_type.casefold().startswith(
        "application/pdf"
    ):
        return (
            "UNRESOLVED_NON_CALL",
            "Document requires identity review",
            0.45,
        )
    return (
        "UNRESOLVED_NON_CALL",
        "Insufficient scheme/call evidence",
        0.35,
    )


def determine_status(
    entity_type: str,
    text: str,
    application_url: str,
    opening_date: str,
    closing_date: str,
    today: date,
) -> tuple[str, str, list[str]]:
    lowered = text.casefold()
    flags: list[str] = []
    if entity_type in EVENT_TYPES:
        return (
            "HISTORICAL_CLOSED",
            "Result/notice role",
            flags,
        )
    if entity_type in PERMANENT_TYPES:
        return (
            "SCHEME_INFORMATION_AVAILABLE",
            "Permanent identity",
            flags,
        )
    if entity_type in EXCLUDED_TYPES:
        return (
            "NOT_APPLICABLE",
            "Excluded page role",
            flags,
        )
    close_value = None
    open_value = None
    try:
        close_value = (
            date.fromisoformat(closing_date)
            if closing_date
            else None
        )
    except ValueError:
        flags.append("INVALID_CLOSING_DATE")
    try:
        open_value = (
            date.fromisoformat(opening_date)
            if opening_date
            else None
        )
    except ValueError:
        flags.append("INVALID_OPENING_DATE")

    if any(
        marker in lowered
        for marker in RESULT_MARKERS + CLOSED_MARKERS
    ):
        return (
            "CLOSED",
            "Official closure/result evidence",
            flags,
        )
    if close_value and close_value < today:
        return (
            "CLOSED",
            "Official deadline is in the past",
            flags,
        )
    if open_value and open_value > today:
        if (
            close_value
            and close_value >= open_value
        ):
            return (
                "UPCOMING",
                "Verified future application window",
                flags,
            )
        flags.append(
            "UPCOMING_CLOSING_DATE_MISSING"
        )
        return (
            "VERIFICATION_REQUIRED",
            "Future opening without complete window",
            flags,
        )
    explicit_open = any(
        marker in lowered
        for marker in OPEN_MARKERS
    )
    if (
        explicit_open
        and close_value
        and close_value >= today
        and application_url
    ):
        return (
            "OPEN",
            (
                "Explicit open status, current deadline "
                "and application route"
            ),
            flags,
        )
    if explicit_open:
        if not close_value:
            flags.append(
                "OPEN_DEADLINE_NOT_VERIFIED"
            )
        if not application_url:
            flags.append(
                "OPEN_APPLICATION_ROUTE_NOT_VERIFIED"
            )
    return (
        "VERIFICATION_REQUIRED",
        "Current status requirements are incomplete",
        flags,
    )


def token_similarity(a: str, b: str) -> float:
    left = set(slug_tokens(a))
    right = set(slug_tokens(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def extract_pdf_text(
    data: bytes,
    max_pages: int,
    ocr_pages: int,
) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    text_parts: list[str] = []
    method = ""

    import io

    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(
                io.BytesIO(data)
            )
            text_parts = [
                clean(page.extract_text() or "")
                for page in reader.pages[:max_pages]
            ]
            method = module_name
            break
        except Exception as exc:
            flags.append(
                f"{module_name.upper()}_FAILED:"
                f"{type(exc).__name__}"
            )
            text_parts = []

    if not clean(" ".join(text_parts)):
        try:
            import fitz  # type: ignore

            document = fitz.open(
                stream=data,
                filetype="pdf",
            )
            text_parts = [
                clean(
                    document[index].get_text("text")
                )
                for index in range(
                    min(len(document), max_pages)
                )
            ]
            method = "PYMUPDF"
            if not clean(" ".join(text_parts)):
                try:
                    import pytesseract  # type: ignore
                    from PIL import Image  # type: ignore

                    ocr: list[str] = []
                    for index in range(
                        min(len(document), ocr_pages)
                    ):
                        pix = document[index].get_pixmap(
                            matrix=fitz.Matrix(2, 2),
                            alpha=False,
                        )
                        image = Image.frombytes(
                            "RGB",
                            [pix.width, pix.height],
                            pix.samples,
                        )
                        ocr.append(
                            clean(
                                pytesseract.image_to_string(
                                    image,
                                    lang="eng",
                                )
                            )
                        )
                    text_parts = ocr
                    method = "PYMUPDF_OCR"
                except Exception as exc:
                    flags.append(
                        "OCR_UNAVAILABLE:"
                        + type(exc).__name__
                    )
        except Exception as exc:
            flags.append(
                "PYMUPDF_UNAVAILABLE:"
                + type(exc).__name__
            )

    text = clean(" ".join(text_parts))
    if not text:
        flags.append(
            "IMAGE_ONLY_OR_UNREADABLE_PDF"
        )
        method = method or "NONE"
    return text, method, flags


@dataclass
class EvidenceItem:
    evidence_id: str
    url: str
    final_url: str
    content_type: str
    fetch_method: str
    status_code: int
    sha256: str
    title: str
    text: str
    links: list[str]
    source_kind: str
    json_path: str = ""
    extraction_method: str = ""
    quality_flags: list[str] = field(
        default_factory=list
    )
    error: str = ""


@dataclass
class Candidate:
    candidate_id: str
    canonical_name: str
    entity_type: str
    entity_reason: str
    entity_confidence: float
    record_kind: str
    programme_status: str
    status_basis: str
    application_status: str
    opening_date: str
    closing_date: str
    official_page_url: str
    application_url: str
    source: str
    ministry: str
    implementing_agency: str
    startup_relevance: str
    startup_relevance_confidence: float
    parent_candidate_id: str
    parent_master_id: str
    parent_scheme_name: str
    parent_resolution: str
    related_candidate_id: str
    existing_master_id: str
    existing_public_record: bool
    duplicate_key: str
    evidence_id: str
    evidence_excerpt: str
    status_evidence: str
    source_evidence_urls: list[str]
    quality_flags: list[str]
    admin_queue: str
    publication_eligible: bool
    apply_action_allowed: bool


@dataclass
class PipelinePaths:
    project_root: Path
    database_path: Path
    output_dir: Path
    runtime_dir: Path
    config_path: Path

    @classmethod
    def defaults(
        cls,
        project_root: Path,
    ) -> "PipelinePaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            database_path=(
                root
                / "database/ssip_staging_v1.db"
            ),
            output_dir=(
                root
                / "data/departments/meity/v3_4_3_8_0"
            ),
            runtime_dir=(
                root
                / "data/departments/meity/"
                "v3_4_3_8_0/runtime"
            ),
            config_path=(
                root
                / "config/"
                "meity_complete_intelligence_v3_4_3_8_0.json"
            ),
        )


class MeitYCompleteIntelligence:
    def __init__(
        self,
        paths: PipelinePaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config
        self.domains = tuple(
            config["official_domains"]
        )
        self.fetcher = HttpFetcher(
            int(
                config[
                    "request_timeout_seconds"
                ]
            )
        )
        self.browser = BrowserRenderer(
            int(
                config[
                    "browser_timeout_seconds"
                ]
            )
        )
        self.evidence: list[EvidenceItem] = []
        self.fetch_log: list[
            dict[str, Any]
        ] = []
        self.discovered_urls: set[str] = set()
        self.errors: list[str] = []
        self._evidence_keys: set[str] = set()

    def _add_evidence(
        self,
        result: FetchResult,
        *,
        title: str,
        text: str,
        links: Iterable[str],
        source_kind: str,
        json_path: str = "",
        extraction_method: str = "",
        quality_flags: Iterable[str] = (),
    ) -> EvidenceItem:
        text = clean(text)[
            : int(
                self.config[
                    "snapshot_text_limit"
                ]
            )
        ]
        final_url = canonical_url(
            result.final_url
            or result.requested_url
        )
        key_payload = {
            "url": final_url,
            "title": clean(title),
            "text_sha": hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest(),
            "json_path": json_path,
        }
        key = hashlib.sha256(
            stable_json(key_payload).encode(
                "utf-8"
            )
        ).hexdigest()
        evidence_id = (
            "meityev_" + key[:20]
        )
        item = EvidenceItem(
            evidence_id=evidence_id,
            url=canonical_url(
                result.requested_url
            ),
            final_url=final_url,
            content_type=result.content_type,
            fetch_method=result.method,
            status_code=result.status_code,
            sha256=result.sha256,
            title=clean(title),
            text=text,
            links=sorted(
                {
                    canonical_url(
                        link,
                        final_url,
                    )
                    for link in links
                    if canonical_url(
                        link,
                        final_url,
                    )
                }
            ),
            source_kind=source_kind,
            json_path=json_path,
            extraction_method=(
                extraction_method
            ),
            quality_flags=list(
                dict.fromkeys(
                    quality_flags
                )
            ),
            error=result.error,
        )
        if (
            evidence_id
            not in self._evidence_keys
        ):
            self.evidence.append(item)
            self._evidence_keys.add(
                evidence_id
            )
        return item

    def _parse_html(
        self,
        result: FetchResult,
        source_kind: str,
    ) -> tuple[
        EvidenceItem,
        DiscoveryHTMLParser,
    ]:
        parser = DiscoveryHTMLParser()
        try:
            parser.feed(result.text)
        except Exception as exc:
            self.errors.append(
                "HTML_PARSE:"
                + result.final_url
                + ":"
                + type(exc).__name__
            )
        links = [
            canonical_url(
                value,
                result.final_url,
            )
            for value in [
                *parser.links,
                *parser.forms,
            ]
        ]
        item = self._add_evidence(
            result,
            title=choose_title(
                parser,
                result.final_url,
            ),
            text=parser.visible_text,
            links=links,
            source_kind=source_kind,
        )
        return item, parser

    def _process_json(
        self,
        result: FetchResult,
    ) -> list[str]:
        try:
            payload = json.loads(
                result.text
            )
        except json.JSONDecodeError as exc:
            self.errors.append(
                f"JSON_PARSE:"
                f"{result.final_url}:"
                f"{exc}"
            )
            return []
        urls = extract_json_urls(
            payload,
            result.final_url,
        )
        for record in flatten_json_records(
            payload,
            result.final_url,
        ):
            synthetic = FetchResult(
                requested_url=(
                    result.requested_url
                ),
                final_url=record["url"],
                status_code=(
                    result.status_code
                ),
                content_type=(
                    "application/json; record"
                ),
                data=record[
                    "raw_json"
                ].encode("utf-8"),
                method=result.method,
            )
            self._add_evidence(
                synthetic,
                title=record["title"],
                text=record["text"],
                links=urls,
                source_kind="JSON_RECORD",
                json_path=(
                    record["json_path"]
                ),
                extraction_method=(
                    "JSON_FLATTEN"
                ),
            )
        self._add_evidence(
            result,
            title=title_from_url(
                result.final_url
            ),
            text=result.text[:12000],
            links=urls,
            source_kind="JSON_RESPONSE",
            extraction_method="JSON",
        )
        return sorted(urls)

    def _process_pdf(
        self,
        result: FetchResult,
    ) -> None:
        text, method, flags = (
            extract_pdf_text(
                result.data,
                int(
                    self.config[
                        "max_pdf_pages"
                    ]
                ),
                int(
                    self.config[
                        "ocr_page_limit"
                    ]
                ),
            )
        )
        self._add_evidence(
            result,
            title=choose_title(
                None,
                result.final_url,
            ),
            text=text,
            links=[],
            source_kind="PDF_DOCUMENT",
            extraction_method=method,
            quality_flags=flags,
        )

    def _relevant_url(
        self,
        url: str,
    ) -> bool:
        if not official_domain(
            url,
            self.domains,
        ):
            return False
        lowered = urllib.parse.unquote(
            url
        ).casefold()
        if lowered.endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".woff",
                ".woff2",
                ".css",
                ".ico",
                ".mp4",
            )
        ):
            return False
        path = urllib.parse.urlsplit(
            url
        ).path.casefold()
        if path in {"", "/"}:
            return True
        return (
            any(
                term in lowered
                for term in self.config[
                    "relevant_path_terms"
                ]
            )
            or lowered.endswith(
                (".pdf", ".json", ".js")
            )
        )

    def _seed_api_probes(
        self,
    ) -> list[str]:
        root = (
            "https://msh.meity.gov.in"
        )
        return [
            canonical_url(path, root)
            for path in self.config[
                "api_probe_paths"
            ]
        ]

    def crawl(self) -> None:
        queue: deque[
            tuple[str, int, str]
        ] = deque()
        for seed in [
            *self.config["seed_urls"],
            *self._seed_api_probes(),
        ]:
            value = canonical_url(seed)
            if value:
                queue.append(
                    (value, 0, "SEED")
                )

        visited: set[str] = set()
        javascript_seen = 0
        documents_seen = 0
        max_pages = int(
            self.config["max_pages"]
        )
        max_depth = int(
            self.config["max_depth"]
        )
        self.paths.runtime_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        while (
            queue
            and len(visited) < max_pages
        ):
            url, depth, source = (
                queue.popleft()
            )
            url = canonical_url(url)
            if not url or url in visited:
                continue
            if (
                depth > max_depth
                or not official_domain(
                    url,
                    self.domains,
                )
            ):
                continue

            visited.add(url)
            self.discovered_urls.add(url)
            result = self.fetcher.fetch(url)
            self.fetch_log.append(
                {
                    "url": url,
                    "final_url": (
                        result.final_url
                    ),
                    "status_code": (
                        result.status_code
                    ),
                    "content_type": (
                        result.content_type
                    ),
                    "method": result.method,
                    "bytes": len(
                        result.data
                    ),
                    "elapsed_seconds": round(
                        result.elapsed_seconds,
                        3,
                    ),
                    "source": source,
                    "error": result.error,
                }
            )
            if result.status_code == 0:
                continue

            content_type = (
                result.content_type.casefold()
            )
            lower_url = (
                result.final_url.casefold()
            )
            new_urls: set[str] = set()

            if (
                "pdf" in content_type
                or lower_url.endswith(".pdf")
            ):
                if (
                    documents_seen
                    < int(
                        self.config[
                            "max_documents"
                        ]
                    )
                ):
                    self._process_pdf(result)
                    documents_seen += 1
                continue

            if (
                "json" in content_type
                or lower_url.endswith(".json")
            ):
                new_urls.update(
                    self._process_json(result)
                )
            elif (
                "javascript" in content_type
                or lower_url.endswith(".js")
            ):
                if (
                    javascript_seen
                    < int(
                        self.config[
                            "max_javascript_files"
                        ]
                    )
                ):
                    new_urls.update(
                        extract_js_urls(
                            result.text,
                            result.final_url,
                        )
                    )
                    self._add_evidence(
                        result,
                        title=title_from_url(
                            result.final_url
                        ),
                        text=result.text[
                            :8000
                        ],
                        links=new_urls,
                        source_kind=(
                            "JAVASCRIPT_BUNDLE"
                        ),
                        extraction_method=(
                            "JS_URL_SCAN"
                        ),
                    )
                    javascript_seen += 1
            else:
                item, parser = (
                    self._parse_html(
                        result,
                        "HTML_STATIC",
                    )
                )
                new_urls.update(item.links)
                new_urls.update(
                    {
                        canonical_url(
                            script,
                            result.final_url,
                        )
                        for script in (
                            parser.scripts
                        )
                        if canonical_url(
                            script,
                            result.final_url,
                        )
                    }
                )

                if (
                    looks_like_app_shell(
                        parser,
                        result.text,
                    )
                    and depth <= 1
                ):
                    rendered = (
                        self.browser.render(
                            result.final_url
                        )
                    )
                    self.fetch_log.append(
                        {
                            "url": url,
                            "final_url": (
                                rendered.final_url
                            ),
                            "status_code": (
                                rendered.status_code
                            ),
                            "content_type": (
                                rendered.content_type
                            ),
                            "method": (
                                rendered.method
                            ),
                            "bytes": len(
                                rendered.data
                            ),
                            "elapsed_seconds": round(
                                rendered.elapsed_seconds,
                                3,
                            ),
                            "source": (
                                "BROWSER_FALLBACK"
                            ),
                            "error": (
                                rendered.error
                            ),
                        }
                    )
                    if (
                        rendered.status_code
                    ):
                        (
                            rendered_item,
                            rendered_parser,
                        ) = self._parse_html(
                            rendered,
                            (
                                "HTML_BROWSER_"
                                "RENDERED"
                            ),
                        )
                        new_urls.update(
                            rendered_item.links
                        )
                        new_urls.update(
                            {
                                canonical_url(
                                    script,
                                    rendered.final_url,
                                )
                                for script in (
                                    rendered_parser.scripts
                                )
                                if canonical_url(
                                    script,
                                    rendered.final_url,
                                )
                            }
                        )

            for candidate in sorted(
                new_urls
            ):
                candidate = canonical_url(
                    candidate
                )
                if (
                    not candidate
                    or candidate in visited
                ):
                    continue
                if not self._relevant_url(
                    candidate
                ):
                    continue
                next_source = "DISCOVERED"
                if candidate.casefold().endswith(
                    ".js"
                ):
                    next_source = "JAVASCRIPT"
                elif candidate.casefold().endswith(
                    ".pdf"
                ):
                    next_source = "DOCUMENT"
                elif (
                    "/api/"
                    in candidate.casefold()
                ):
                    next_source = "API"
                queue.append(
                    (
                        candidate,
                        depth + 1,
                        next_source,
                    )
                )

    def import_prior_evidence(
        self,
    ) -> None:
        meity_root = (
            self.paths.project_root
            / "data/departments/meity"
        )
        if not meity_root.exists():
            return

        for path in sorted(
            meity_root.rglob("*.csv")
        ):
            if (
                "v3_4_3_8_0"
                in path.as_posix()
            ):
                continue
            try:
                with path.open(
                    "r",
                    encoding="utf-8-sig",
                    newline="",
                ) as handle:
                    rows = list(
                        csv.DictReader(handle)
                    )
            except Exception:
                continue

            for index, row in enumerate(
                rows
            ):
                title = ""
                for field_name in (
                    "canonical_name",
                    "scheme_name",
                    "candidate_name",
                    "canonical_title",
                    "proposed_title",
                    "current_title",
                    "title",
                    "name",
                ):
                    title = clean(
                        row.get(field_name)
                    )
                    if title:
                        break

                url = ""
                for field_name in (
                    "official_source_url",
                    "official_page_url",
                    "final_url",
                    "source_url",
                    "url",
                ):
                    url = canonical_url(
                        row.get(
                            field_name,
                            "",
                        )
                    )
                    if url:
                        break

                if (
                    not title
                    or not url
                    or not official_domain(
                        url,
                        self.domains,
                    )
                ):
                    continue

                text = clean(
                    " ".join(
                        clean(value)
                        for value in row.values()
                    )
                )[:12000]
                result = FetchResult(
                    requested_url=url,
                    final_url=url,
                    status_code=200,
                    content_type=(
                        "text/csv; "
                        "prior-evidence"
                    ),
                    data=stable_json(
                        row
                    ).encode("utf-8"),
                    method=(
                        "PRIOR_REPOSITORY_"
                        "EVIDENCE"
                    ),
                )
                self._add_evidence(
                    result,
                    title=title,
                    text=text,
                    links=[url],
                    source_kind=(
                        "PRIOR_CSV_RECORD"
                    ),
                    json_path=(
                        f"{path.relative_to(self.paths.project_root)}"
                        f"#{index + 2}"
                    ),
                    extraction_method=(
                        "CSV_IMPORT"
                    ),
                )

    def load_existing_database(
        self,
    ) -> list[dict[str, Any]]:
        path = self.paths.database_path
        if not path.exists():
            return []

        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            columns = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info("
                    "scheme_staging)"
                ).fetchall()
            ]
            if not columns:
                return []
            selected = [
                name
                for name in (
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
                    "publication_status",
                    "is_public",
                    "official_page_url",
                    "application_url",
                    "raw_record_json",
                )
                if name in columns
            ]
            query = (
                "SELECT "
                + ",".join(
                    f'"{name}"'
                    for name in selected
                )
                + " FROM scheme_staging"
            )
            rows: list[
                dict[str, Any]
            ] = []
            for row in connection.execute(
                query
            ):
                item = dict(row)
                blob = " ".join(
                    clean(value)
                    for value in (
                        item.values()
                    )
                ).casefold()
                if (
                    "meity" in blob
                    or "ministry of electronics"
                    in blob
                ):
                    rows.append(item)
            return rows
        finally:
            connection.close()

    def build_candidates(
        self,
    ) -> list[Candidate]:
        existing_rows = (
            self.load_existing_database()
        )
        existing_by_name: dict[
            str,
            dict[str, Any],
        ] = {}
        existing_by_url: dict[
            str,
            dict[str, Any],
        ] = {}

        for row in existing_rows:
            name = clean(
                row.get("scheme_name")
                or row.get("short_name")
            )
            if name:
                existing_by_name[
                    " ".join(
                        slug_tokens(name)
                    )
                ] = row
            url = canonical_url(
                row.get(
                    "official_page_url",
                    "",
                )
            )
            if url:
                existing_by_url[url] = row

        prelim: list[Candidate] = []
        seen_keys: set[str] = set()
        today = date.today()
        source = clean(
            self.config["source"]
        )
        ministry = clean(
            self.config["ministry"]
        )

        for evidence in self.evidence:
            if evidence.source_kind in {
                "JAVASCRIPT_BUNDLE",
                "JSON_RESPONSE",
            }:
                continue

            title = choose_title(
                None,
                evidence.final_url,
                evidence.title,
            )
            text = clean(
                f"{title} {evidence.text}"
            )
            (
                entity_type,
                reason,
                confidence,
            ) = classify_entity(
                title,
                text,
                evidence.final_url,
                evidence.content_type,
            )
            if (
                entity_type
                == "UNRESOLVED_NON_CALL"
                and len(evidence.text) < 100
            ):
                continue

            (
                opening_date,
                closing_date,
            ) = derive_open_close_dates(
                text
            )
            application_url = (
                extract_application_url(
                    evidence.links
                )
            )
            (
                application_status,
                status_basis,
                status_flags,
            ) = determine_status(
                entity_type,
                text,
                application_url,
                opening_date,
                closing_date,
                today,
            )
            (
                startup_relevance,
                startup_confidence,
            ) = score_startup_relevance(
                text
            )
            normalized_name = " ".join(
                slug_tokens(title)
            )
            duplicate_key = hashlib.sha256(
                stable_json(
                    {
                        "name": (
                            normalized_name
                        ),
                        "type": entity_type,
                        "url": (
                            evidence.final_url
                        ),
                    }
                ).encode("utf-8")
            ).hexdigest()
            if duplicate_key in seen_keys:
                continue
            seen_keys.add(duplicate_key)

            existing = (
                existing_by_url.get(
                    evidence.final_url
                )
                or existing_by_name.get(
                    normalized_name
                )
                or {}
            )
            existing_master_id = clean(
                existing.get("master_id")
            )
            existing_public = (
                clean(
                    existing.get(
                        "publication_status"
                    )
                ).upper()
                == "PUBLISHED"
                and int(
                    existing.get(
                        "is_public"
                    )
                    or 0
                )
                == 1
            )
            quality_flags = (
                list(
                    evidence.quality_flags
                )
                + status_flags
            )

            if entity_type in EXCLUDED_TYPES:
                admin_queue = (
                    "EXCLUDED_EVIDENCE"
                )
            elif (
                entity_type
                in PERMANENT_TYPES
            ):
                admin_queue = (
                    "EXISTING_PROGRAMME_"
                    "RECONCILIATION"
                    if existing_master_id
                    else "NEW_PERMANENT_PROGRAMME"
                )
            elif entity_type in CALL_TYPES:
                admin_queue = (
                    "CURRENT_CALL_OR_CHALLENGE"
                    if application_status
                    in {"OPEN", "UPCOMING"}
                    else "CALL_OR_CHALLENGE_REVIEW"
                )
            elif entity_type in EVENT_TYPES:
                admin_queue = (
                    "HISTORICAL_RESULT_OR_NOTICE"
                )
            else:
                admin_queue = (
                    "IDENTITY_REVIEW"
                )

            apply_allowed = (
                application_status == "OPEN"
                and bool(application_url)
                and bool(closing_date)
            )
            if (
                application_status == "OPEN"
                and not apply_allowed
            ):
                quality_flags.append(
                    "PUBLIC_APPLY_BLOCKED"
                )

            if entity_type in PERMANENT_TYPES:
                record_kind = (
                    "SCHEME_PROGRAMME"
                )
            elif entity_type in CALL_TYPES:
                record_kind = (
                    "APPLICATION_CALL"
                )
            elif entity_type in EVENT_TYPES:
                record_kind = "CALL_EVENT"
            else:
                record_kind = "EVIDENCE_ONLY"

            candidate_id = (
                "meity380_"
                + hashlib.sha256(
                    stable_json(
                        {
                            "title": title,
                            "type": (
                                entity_type
                            ),
                            "url": (
                                evidence.final_url
                            ),
                            "evidence": (
                                evidence.evidence_id
                            ),
                        }
                    ).encode("utf-8")
                ).hexdigest()[:20]
            )

            prelim.append(
                Candidate(
                    candidate_id=(
                        candidate_id
                    ),
                    canonical_name=title,
                    entity_type=(
                        entity_type
                    ),
                    entity_reason=reason,
                    entity_confidence=round(
                        confidence,
                        3,
                    ),
                    record_kind=(
                        record_kind
                    ),
                    programme_status=(
                        application_status
                    ),
                    status_basis=(
                        status_basis
                    ),
                    application_status=(
                        application_status
                    ),
                    opening_date=(
                        opening_date
                    ),
                    closing_date=(
                        closing_date
                    ),
                    official_page_url=(
                        evidence.final_url
                    ),
                    application_url=(
                        application_url
                    ),
                    source=source,
                    ministry=ministry,
                    implementing_agency=(
                        source
                    ),
                    startup_relevance=(
                        startup_relevance
                    ),
                    startup_relevance_confidence=round(
                        startup_confidence,
                        3,
                    ),
                    parent_candidate_id="",
                    parent_master_id="",
                    parent_scheme_name="",
                    parent_resolution=(
                        "NOT_APPLICABLE"
                        if entity_type
                        in PERMANENT_TYPES
                        else "UNRESOLVED"
                    ),
                    related_candidate_id="",
                    existing_master_id=(
                        existing_master_id
                    ),
                    existing_public_record=(
                        existing_public
                    ),
                    duplicate_key=(
                        duplicate_key
                    ),
                    evidence_id=(
                        evidence.evidence_id
                    ),
                    evidence_excerpt=(
                        evidence.text[:900]
                    ),
                    status_evidence=(
                        evidence.text[:1200]
                    ),
                    source_evidence_urls=sorted(
                        {
                            evidence.url,
                            evidence.final_url,
                            *evidence.links,
                        }
                    )[:20],
                    quality_flags=list(
                        dict.fromkeys(
                            quality_flags
                        )
                    ),
                    admin_queue=(
                        admin_queue
                    ),
                    publication_eligible=False,
                    apply_action_allowed=(
                        apply_allowed
                    ),
                )
            )

        permanent = [
            item
            for item in prelim
            if item.entity_type
            in PERMANENT_TYPES
        ]
        calls = [
            item
            for item in prelim
            if item.entity_type in CALL_TYPES
        ]
        events = [
            item
            for item in prelim
            if item.entity_type in EVENT_TYPES
        ]

        aliases = self.config.get(
            "known_programme_aliases",
            {},
        )
        alias_map: dict[
            str,
            Candidate,
        ] = {}

        for programme in permanent:
            normalized = " ".join(
                slug_tokens(
                    programme.canonical_name
                )
            )
            alias_map[normalized] = programme
            for (
                canonical_name,
                values,
            ) in aliases.items():
                checks = [
                    canonical_name,
                    *values,
                ]
                if any(
                    token_similarity(
                        programme.canonical_name,
                        alias,
                    )
                    >= 0.65
                    or clean(alias).casefold()
                    in programme.evidence_excerpt.casefold()
                    for alias in checks
                ):
                    for alias in checks:
                        alias_map[
                            " ".join(
                                slug_tokens(
                                    alias
                                )
                            )
                        ] = programme

        for call in calls:
            best: Candidate | None = None
            best_score = 0.0
            call_blob = clean(
                f"{call.canonical_name} "
                f"{call.evidence_excerpt}"
            )
            for programme in permanent:
                score = max(
                    token_similarity(
                        call.canonical_name,
                        programme.canonical_name,
                    ),
                    token_similarity(
                        call_blob,
                        programme.canonical_name,
                    ),
                )
                if score > best_score:
                    best = programme
                    best_score = score

            call_tokens = " ".join(
                slug_tokens(call_blob)
            )
            for (
                alias_key,
                programme,
            ) in alias_map.items():
                if (
                    alias_key
                    and alias_key
                    in call_tokens
                    and 0.92 > best_score
                ):
                    best = programme
                    best_score = 0.92

            if (
                best
                and best_score >= 0.62
            ):
                call.parent_candidate_id = (
                    best.candidate_id
                )
                call.parent_master_id = (
                    best.existing_master_id
                )
                call.parent_scheme_name = (
                    best.canonical_name
                )
                call.parent_resolution = (
                    "MATCHED_EXISTING_PROGRAMME"
                    if best.existing_master_id
                    else (
                        "MATCHED_DISCOVERED_"
                        "PROGRAMME"
                    )
                )
            else:
                call.parent_resolution = (
                    "PARENT_REQUIRES_"
                    "ADMIN_VERIFICATION"
                )
                call.quality_flags.append(
                    "PARENT_UNRESOLVED"
                )

        for event in events:
            best_call: Candidate | None = None
            best_score = 0.0
            for call in calls:
                score = token_similarity(
                    event.canonical_name,
                    call.canonical_name,
                )
                if score > best_score:
                    best_call = call
                    best_score = score
            if (
                best_call
                and best_score >= 0.5
            ):
                event.related_candidate_id = (
                    best_call.candidate_id
                )
                event.parent_candidate_id = (
                    best_call.parent_candidate_id
                )
                event.parent_master_id = (
                    best_call.parent_master_id
                )
                event.parent_scheme_name = (
                    best_call.parent_scheme_name
                )
                event.parent_resolution = (
                    "LINKED_TO_CALL_CANDIDATE"
                )
            else:
                event.parent_resolution = (
                    "RELATED_CALL_REQUIRES_"
                    "ADMIN_VERIFICATION"
                )
                event.quality_flags.append(
                    "RELATED_CALL_UNRESOLVED"
                )

        return sorted(
            prelim,
            key=lambda item: (
                item.admin_queue,
                item.canonical_name.casefold(),
                item.official_page_url,
            ),
        )

    def write_outputs(
        self,
        candidates: list[Candidate],
    ) -> dict[str, Any]:
        self.paths.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        evidence_rows = [
            {
                **asdict(item),
                "links": ";".join(
                    item.links
                ),
                "quality_flags": ";".join(
                    item.quality_flags
                ),
                "text": item.text[:5000],
            }
            for item in self.evidence
        ]
        candidate_rows = [
            {
                **asdict(item),
                "source_evidence_urls": (
                    ";".join(
                        item.source_evidence_urls
                    )
                ),
                "quality_flags": ";".join(
                    item.quality_flags
                ),
            }
            for item in candidates
        ]

        programmes = [
            row
            for row in candidate_rows
            if row["entity_type"]
            in PERMANENT_TYPES
        ]
        current_calls = [
            row
            for row in candidate_rows
            if (
                row["entity_type"]
                in CALL_TYPES
                and row[
                    "application_status"
                ]
                in {
                    "OPEN",
                    "UPCOMING",
                    "VERIFICATION_REQUIRED",
                }
            )
        ]
        historical = [
            row
            for row in candidate_rows
            if (
                row["entity_type"]
                in EVENT_TYPES
                or (
                    row["entity_type"]
                    in CALL_TYPES
                    and row[
                        "application_status"
                    ]
                    == "CLOSED"
                )
            )
        ]
        relationships = [
            row
            for row in candidate_rows
            if row["parent_resolution"]
            in {
                "PARENT_REQUIRES_ADMIN_VERIFICATION",
                "RELATED_CALL_REQUIRES_ADMIN_VERIFICATION",
            }
        ]
        exclusions = [
            row
            for row in candidate_rows
            if row["entity_type"]
            in EXCLUDED_TYPES
        ]
        admin = [
            row
            for row in candidate_rows
            if row["admin_queue"]
            != "EXCLUDED_EVIDENCE"
        ]

        candidate_fields = [
            "candidate_id",
            "canonical_name",
            "entity_type",
            "entity_reason",
            "entity_confidence",
            "record_kind",
            "programme_status",
            "application_status",
            "status_basis",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "source",
            "ministry",
            "implementing_agency",
            "startup_relevance",
            "startup_relevance_confidence",
            "parent_candidate_id",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "related_candidate_id",
            "existing_master_id",
            "existing_public_record",
            "evidence_id",
            "evidence_excerpt",
            "status_evidence",
            "source_evidence_urls",
            "quality_flags",
            "admin_queue",
            "publication_eligible",
            "apply_action_allowed",
            "duplicate_key",
        ]
        evidence_fields = [
            "evidence_id",
            "url",
            "final_url",
            "content_type",
            "fetch_method",
            "status_code",
            "sha256",
            "title",
            "source_kind",
            "json_path",
            "extraction_method",
            "quality_flags",
            "error",
            "links",
            "text",
        ]

        outputs = {
            "programme_inventory": (
                self.paths.output_dir
                / "meity_programme_inventory_v3_4_3_8_0.csv"
            ),
            "current_calls_challenges": (
                self.paths.output_dir
                / "meity_current_calls_challenges_v3_4_3_8_0.csv"
            ),
            "historical_calls_results": (
                self.paths.output_dir
                / "meity_historical_calls_results_v3_4_3_8_0.csv"
            ),
            "relationship_review": (
                self.paths.output_dir
                / "meity_relationship_review_v3_4_3_8_0.csv"
            ),
            "exclusions": (
                self.paths.output_dir
                / "meity_exclusions_v3_4_3_8_0.csv"
            ),
            "evidence": (
                self.paths.output_dir
                / "meity_document_and_page_evidence_v3_4_3_8_0.csv"
            ),
            "admin_review": (
                self.paths.output_dir
                / "meity_admin_review_preview_v3_4_3_8_0.csv"
            ),
            "fetch_log": (
                self.paths.output_dir
                / "meity_fetch_log_v3_4_3_8_0.csv"
            ),
        }
        write_csv(
            outputs["programme_inventory"],
            programmes,
            candidate_fields,
        )
        write_csv(
            outputs[
                "current_calls_challenges"
            ],
            current_calls,
            candidate_fields,
        )
        write_csv(
            outputs[
                "historical_calls_results"
            ],
            historical,
            candidate_fields,
        )
        write_csv(
            outputs["relationship_review"],
            relationships,
            candidate_fields,
        )
        write_csv(
            outputs["exclusions"],
            exclusions,
            candidate_fields,
        )
        write_csv(
            outputs["evidence"],
            evidence_rows,
            evidence_fields,
        )
        write_csv(
            outputs["admin_review"],
            admin,
            candidate_fields,
        )
        write_csv(
            outputs["fetch_log"],
            self.fetch_log,
            (
                "url",
                "final_url",
                "status_code",
                "content_type",
                "method",
                "bytes",
                "elapsed_seconds",
                "source",
                "error",
            ),
        )

        admin_json_path = (
            self.paths.output_dir
            / "meity_admin_review_preview_v3_4_3_8_0.json"
        )
        admin_json_path.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "generated_at": utc_now(),
                    "database_write_performed": False,
                    "publication_performed": False,
                    "records": admin,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        queue_counts = Counter(
            item.admin_queue
            for item in candidates
        )
        type_counts = Counter(
            item.entity_type
            for item in candidates
        )
        status_counts = Counter(
            item.application_status
            for item in candidates
        )
        fetch_success = sum(
            item["status_code"] > 0
            for item in self.fetch_log
        )
        browser_success = sum(
            item["method"] == "BROWSER"
            and item["status_code"] > 0
            for item in self.fetch_log
        )
        apply_count = sum(
            item.apply_action_allowed
            for item in candidates
        )
        open_count = sum(
            item.application_status == "OPEN"
            for item in candidates
        )

        signature_payload = {
            "version": VERSION,
            "candidate_rows": (
                candidate_rows
            ),
            "evidence_hashes": sorted(
                item.sha256
                for item in self.evidence
            ),
            "queue_counts": dict(
                sorted(
                    queue_counts.items()
                )
            ),
        }
        signature = hashlib.sha256(
            stable_json(
                signature_payload
            ).encode("utf-8")
        ).hexdigest()

        manifest = {
            "version": VERSION,
            "phase": (
                "MeitY Complete Scheme, "
                "Programme, Challenge and "
                "Call Intelligence"
            ),
            "generated_at": utc_now(),
            "signature": signature,
            "seed_count": len(
                self.config["seed_urls"]
            ),
            "discovered_url_count": len(
                self.discovered_urls
            ),
            "fetch_attempt_count": len(
                self.fetch_log
            ),
            "fetch_success_count": (
                fetch_success
            ),
            "browser_available": bool(
                self.browser.executable
            ),
            "browser_executable": (
                self.browser.executable
            ),
            "browser_success_count": (
                browser_success
            ),
            "evidence_count": len(
                self.evidence
            ),
            "candidate_count": len(
                candidates
            ),
            "programme_candidate_count": len(
                programmes
            ),
            "current_call_challenge_candidate_count": len(
                current_calls
            ),
            "historical_call_result_count": len(
                historical
            ),
            "relationship_review_count": len(
                relationships
            ),
            "exclusion_count": len(
                exclusions
            ),
            "admin_review_count": len(
                admin
            ),
            "verified_open_count": (
                open_count
            ),
            "apply_action_allowed_count": (
                apply_count
            ),
            "queue_counts": dict(
                sorted(
                    queue_counts.items()
                )
            ),
            "entity_type_counts": dict(
                sorted(
                    type_counts.items()
                )
            ),
            "status_counts": dict(
                sorted(
                    status_counts.items()
                )
            ),
            "errors": self.errors,
            "database_write_performed": False,
            "publication_performed": False,
            "outputs": {
                key: str(
                    path.relative_to(
                        self.paths.project_root
                    )
                )
                for key, path in (
                    outputs.items()
                )
            },
            "admin_json": str(
                admin_json_path.relative_to(
                    self.paths.project_root
                )
            ),
        }
        manifest_path = (
            self.paths.output_dir
            / "meity_complete_intelligence_manifest_v3_4_3_8_0.json"
        )
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest["manifest_path"] = str(
            manifest_path.relative_to(
                self.paths.project_root
            )
        )
        return manifest

    def run(
        self,
        live_network: bool = True,
    ) -> dict[str, Any]:
        self.import_prior_evidence()
        if live_network:
            self.crawl()
        candidates = (
            self.build_candidates()
        )
        return self.write_outputs(
            candidates
        )


def load_config(
    path: Path,
) -> dict[str, Any]:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig"
        )
    )


def run_pipeline(
    project_root: Path,
    live_network: bool = True,
) -> dict[str, Any]:
    paths = PipelinePaths.defaults(
        project_root
    )
    config = load_config(
        paths.config_path
    )
    return MeitYCompleteIntelligence(
        paths,
        config,
    ).run(
        live_network=live_network
    )
