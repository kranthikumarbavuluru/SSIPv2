from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Run:\n"
        "  python -m pip install requests beautifulsoup4\n"
        f"Import error: {exc}"
    )

VERSION = "3.4.3.1"
PHASE = "MeitY Discovery Expansion Hotfix"
USER_AGENT = "SSIP-Governed-Discovery/3.4.3.1 (+official-source research)"

DEFAULT_SEEDS = [
    "https://www.meity.gov.in/offerings/schemes-and-services",
    "https://www.meity.gov.in/offerings?page=0",
    "https://www.meity.gov.in/archives?page=schemes_and_services",
    "https://www.meity.gov.in/sitemap.xml",
    "https://msh.meity.gov.in/",
    "https://msh.meity.gov.in/whatsnew",
    "https://msh.meity.gov.in/sitemap.xml",
    "https://msh.meity.gov.in/schemes/samridh",
    "https://msh.meity.gov.in/schemes/tide",
    "https://msh.meity.gov.in/schemes/sasact",
    "https://msh.meity.gov.in/schemes/genesis",
]

ALLOWED_HOST_SUFFIXES = ("meity.gov.in",)
ALLOWED_QUERY_KEYS = {
    "page",
    "persona",
    "category",
    "type",
    "scheme",
    "id",
    "nid",
    "field",
    "search",
    "sort",
    "order",
    "lang",
}

DISCOVERY_INDEX_PATH_SIGNALS = (
    "/offerings/schemes-and-services",
    "/offerings",
    "/archives",
    "/whatsnew",
    "/what-s-new",
    "/schemes",
    "/programmes",
    "/programs",
)

SCHEME_PATH_SIGNALS = (
    "/schemes/",
    "/scheme/",
    "/offerings/schemes-and-services/details/",
)

PROGRAMME_PATH_SIGNALS = (
    "/programmes/",
    "/programme/",
    "/programs/",
    "/program/",
)

CALL_PATH_SIGNALS = (
    "/challenges/",
    "/challenge/",
    "/announcement/",
    "/announcements/",
    "/call/",
    "/cohort/",
    "/eoi/",
    "/rfp/",
    "/tender/",
)

EVIDENCE_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
)

STATIC_ASSET_EXTENSIONS = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
    ".mp4",
    ".webm",
    ".zip",
)

CALL_SIGNALS = (
    "applications invited",
    "application invited",
    "applications open",
    "apply now",
    "call for proposals",
    "call for applications",
    "expression of interest",
    "request for proposal",
    "request for applications",
    "eoi",
    "rfp",
    "cohort",
    "round",
    "challenge",
    "deadline",
    "last date",
    "registration open",
    "startup selection",
    "winners",
    "results announced",
)

PERMANENT_SIGNALS = (
    "scheme",
    "programme",
    "program",
    "initiative",
    "mission",
    "fund",
    "incentive",
    "incubation",
    "accelerator",
)

EVIDENCE_SIGNALS = (
    "guideline",
    "guidelines",
    "administrative approval",
    "gazette",
    "notification",
    "manual",
    "brochure",
    "handbook",
    "report",
    "annual report",
    "office memorandum",
    "sanction order",
    "list of incubators",
    "list of accelerators",
)

NON_CATALOGUE_SIGNALS = (
    "contact us",
    "about us",
    "privacy policy",
    "terms and conditions",
    "sitemap",
    "login",
    "sign in",
    "gallery",
    "media gallery",
    "team",
    "dashboard",
    "apply for the logo",
)

INVALID_LOGO_PATH = "/about/applyforthelogo"

API_PATH_HINTS = (
    "/api/",
    "/api",
    "/graphql",
    "/jsonapi/",
    "/views/ajax",
    "/ajax",
    "/rest/",
    "/wp-json/",
)

DETAIL_KEYS = {
    "url",
    "href",
    "link",
    "path",
    "slug",
    "detailurl",
    "detailsurl",
    "schemeurl",
    "programurl",
    "programmeurl",
}

TITLE_KEYS = {
    "title",
    "name",
    "heading",
    "label",
    "schemename",
    "programname",
    "programmename",
}

DATE_PATTERN = re.compile(
    r"\b(?:0?[1-9]|[12][0-9]|3[01])[\s./-]"
    r"(?:0?[1-9]|1[0-2]|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
    r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)[\s./-](?:20\d{2})\b",
    re.IGNORECASE,
)

MONEY_PATTERN = re.compile(
    r"(?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:crore|cr|lakh|lakhs|million|billion)?",
    re.IGNORECASE,
)

URL_IN_TEXT_PATTERN = re.compile(
    r"""(?P<quote>["'])(?P<url>(?:https?:)?//[^"'\\\s]+|/[^"'\\\s]{3,})(?P=quote)"""
)


@dataclass
class Page:
    url: str
    canonical_url: str
    discovered_from: str
    discovery_method: str
    depth: int
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    heading: str = ""
    description: str = ""
    text_excerpt: str = ""
    published_date_signal: str = ""
    money_signals: str = ""
    static_link_count: int = 0
    rendered_link_count: int = 0
    api_link_count: int = 0
    script_endpoint_count: int = 0
    fetched_at: str = ""
    error: str = ""
    classification: str = ""
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    status_hint: str = ""
    parent_hint: str = ""
    existing_master_id: str = ""
    candidate_id: str = ""
    llm_used: bool = False
    llm_classification: str = ""
    llm_confidence: float = 0.0
    llm_reason: str = ""
    is_discovery_index: bool = False
    rendered_used: bool = False
    api_endpoints: list[str] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_title(value: Any) -> str:
    text = normalize_space(value)
    suffixes = (
        " | Ministry of Electronics and Information Technology",
        " - Ministry of Electronics and Information Technology",
        " - MeitY Startup Hub",
        " | MeitY Startup Hub",
        " - MeityStartupHub",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def normalize_name(value: Any) -> str:
    text = normalize_space(value).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    ignored = {
        "scheme",
        "schemes",
        "programme",
        "program",
        "programmes",
        "the",
        "of",
        "for",
        "and",
        "ministry",
        "meity",
        "official",
    }
    return " ".join(token for token in text.split() if token not in ignored)


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = "https"
    host = (parsed.hostname or "").casefold()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() in ALLOWED_QUERY_KEYS
    ]
    query = urlencode(sorted(query_pairs))
    return urlunparse((scheme, host, path, "", query, ""))


def allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    return any(host == suffix or host.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def is_static_asset(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return any(path.endswith(ext) for ext in STATIC_ASSET_EXTENSIONS)


def is_evidence_document(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return any(path.endswith(ext) for ext in EVIDENCE_EXTENSIONS)


def priority_for(url: str, depth: int, method: str) -> int:
    text = url.casefold()
    score = depth * 100
    if any(signal in text for signal in SCHEME_PATH_SIGNALS):
        score -= 80
    if any(signal in text for signal in PROGRAMME_PATH_SIGNALS):
        score -= 70
    if any(signal in text for signal in CALL_PATH_SIGNALS):
        score -= 60
    if any(signal in text for signal in DISCOVERY_INDEX_PATH_SIGNALS):
        score -= 50
    if method in {"rendered_dom", "network_json", "sitemap"}:
        score -= 20
    if is_evidence_document(text):
        score += 25
    return score


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.9",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


class RobotsCache:
    def __init__(self, session: requests.Session, timeout: int):
        self.session = session
        self.timeout = timeout
        self.cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            parser = RobotFileParser()
            parser.set_url(origin + "/robots.txt")
            try:
                response = self.session.get(origin + "/robots.txt", timeout=self.timeout)
                if response.ok:
                    parser.parse(response.text.splitlines())
                    self.cache[origin] = parser
                else:
                    self.cache[origin] = None
            except requests.RequestException:
                self.cache[origin] = None
        parser = self.cache[origin]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)


def html_metadata(html: str, base_url: str) -> tuple[dict[str, str], list[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    script_urls = [
        canonicalize_url(urljoin(base_url, tag.get("src", "")))
        for tag in soup.find_all("script", src=True)
        if allowed_url(urljoin(base_url, tag.get("src", "")))
    ]

    links: list[str] = []
    for tag in soup.find_all(["a", "link"], href=True):
        absolute = urljoin(base_url, normalize_space(tag.get("href", "")))
        if allowed_url(absolute) and not is_static_asset(absolute):
            links.append(canonicalize_url(absolute))

    title = clean_title(soup.title.get_text(" ", strip=True) if soup.title else "")
    heading_tag = soup.find(["h1", "h2"])
    heading = clean_title(heading_tag.get_text(" ", strip=True) if heading_tag else "")
    description = ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta and meta.get("content"):
        description = normalize_space(meta["content"])

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalize_space(main.get_text(" ", strip=True))
    date_match = DATE_PATTERN.search(text)
    money = MONEY_PATTERN.findall(text)

    return (
        {
            "title": title,
            "heading": heading,
            "description": description,
            "text_excerpt": text[:18000],
            "published_date_signal": date_match.group(0) if date_match else "",
            "money_signals": "; ".join(
                dict.fromkeys(normalize_space(item) for item in money[:12])
            ),
        },
        list(dict.fromkeys(links)),
        list(dict.fromkeys(script_urls)),
    )


def parse_sitemap_xml(text: str, base_url: str) -> list[str]:
    output: list[str] = []
    try:
        root = ElementTree.fromstring(text)
        for element in root.iter():
            if element.tag.casefold().endswith("loc") and element.text:
                value = normalize_space(element.text)
                if allowed_url(value):
                    output.append(canonicalize_url(value))
    except ElementTree.ParseError:
        for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S):
            value = normalize_space(match)
            if allowed_url(value):
                output.append(canonicalize_url(value))
    return list(dict.fromkeys(output))


def urls_from_json(value: Any, base_url: str) -> list[str]:
    found: list[str] = []

    def walk(item: Any, parent_key: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, str(key).casefold())
        elif isinstance(item, list):
            for child in item:
                walk(child, parent_key)
        elif isinstance(item, str):
            text = normalize_space(item)
            if not text:
                return

            candidates: list[str] = []
            if parent_key in DETAIL_KEYS:
                candidates.append(text)
            if text.startswith(("http://", "https://", "/")):
                candidates.append(text)

            for candidate in candidates:
                absolute = urljoin(base_url, candidate)
                if allowed_url(absolute) and not is_static_asset(absolute):
                    found.append(canonicalize_url(absolute))

    walk(value)
    return list(dict.fromkeys(found))


def endpoints_from_script_text(text: str, script_url: str) -> list[str]:
    endpoints: list[str] = []
    for match in URL_IN_TEXT_PATTERN.finditer(text):
        candidate = match.group("url")
        absolute = urljoin(script_url, candidate)
        if not allowed_url(absolute):
            continue
        canonical = canonicalize_url(absolute)
        lowered = canonical.casefold()
        if any(hint in lowered for hint in API_PATH_HINTS):
            endpoints.append(canonical)
        elif any(signal in lowered for signal in SCHEME_PATH_SIGNALS + CALL_PATH_SIGNALS):
            endpoints.append(canonical)
    return list(dict.fromkeys(endpoints))


class BrowserDiscovery:
    def __init__(self, enabled: bool, timeout_ms: int, headless: bool = True):
        self.enabled = enabled
        self.timeout_ms = timeout_ms
        self.headless = headless
        self._playwright = None
        self._browser = None
        self.available = False
        self.error = ""

        if not enabled:
            return

        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=headless)
            self.available = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def discover(self, url: str) -> tuple[dict[str, str], list[str], list[str]]:
        if not self.available or self._browser is None:
            return {}, [], []

        page = self._browser.new_page()
        network_json_urls: list[str] = []

        def on_response(response: Any) -> None:
            try:
                request_url = canonicalize_url(response.url)
                content_type = str(response.headers.get("content-type", "")).casefold()
                if allowed_url(request_url) and (
                    "json" in content_type
                    or any(hint in request_url.casefold() for hint in API_PATH_HINTS)
                ):
                    network_json_urls.append(request_url)
            except Exception:
                return

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 15000))
            except Exception:
                pass

            for _ in range(4):
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(350)

            title = clean_title(page.title())
            heading = clean_title(
                page.locator("h1, h2").first.inner_text(timeout=1500)
                if page.locator("h1, h2").count()
                else ""
            )
            body_text = normalize_space(page.locator("body").inner_text(timeout=4000))
            links = page.locator("a[href]").evaluate_all(
                """els => els.map(e => e.href).filter(Boolean)"""
            )
            rendered_links = [
                canonicalize_url(item)
                for item in links
                if allowed_url(item) and not is_static_asset(item)
            ]

            return (
                {
                    "title": title,
                    "heading": heading,
                    "text_excerpt": body_text[:18000],
                },
                list(dict.fromkeys(rendered_links)),
                list(dict.fromkeys(network_json_urls)),
            )
        finally:
            page.close()


def fetch_api_json(
    session: requests.Session,
    robots: RobotsCache,
    url: str,
    timeout: int,
) -> tuple[list[str], str]:
    if not robots.allowed(url):
        return [], "ROBOTS_DISALLOWED"

    try:
        response = session.get(url, timeout=timeout)
        if response.status_code >= 400:
            return [], f"HTTP_{response.status_code}"
        content_type = response.headers.get("content-type", "").casefold()
        if "json" not in content_type and not response.text.lstrip().startswith(("{", "[")):
            return [], "NOT_JSON"
        payload = response.json()
        return urls_from_json(payload, response.url), ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def classify(page: Page) -> None:
    url_text = page.canonical_url.casefold()
    title = clean_title(page.heading or page.title)
    combined = " ".join(
        [title, page.description, page.text_excerpt[:9000], url_text]
    ).casefold()
    path = urlparse(page.canonical_url).path.casefold()

    if INVALID_LOGO_PATH in path or "apply for the logo" in combined:
        page.classification = "NON_CATALOGUE"
        page.confidence = 1.0
        page.reasons = ["UNRELATED_MSH_LOGO_APPLICATION"]
        return

    if page.error:
        page.classification = "MANUAL_REVIEW"
        page.confidence = 0.1
        page.reasons = ["FETCH_ERROR"]
        return

    if any(signal in path for signal in DISCOVERY_INDEX_PATH_SIGNALS) and not any(
        signal in path for signal in SCHEME_PATH_SIGNALS + PROGRAMME_PATH_SIGNALS + CALL_PATH_SIGNALS
    ):
        page.classification = "DISCOVERY_INDEX"
        page.confidence = 0.99
        page.reasons = ["LISTING_OR_INDEX_PAGE"]
        page.is_discovery_index = True
        return

    if page.content_type in {"application/xml", "text/xml"} or path.endswith(".xml"):
        page.classification = "DISCOVERY_INDEX"
        page.confidence = 0.99
        page.reasons = ["SITEMAP_OR_XML_INDEX"]
        page.is_discovery_index = True
        return

    if is_evidence_document(page.canonical_url):
        page.classification = "EVIDENCE_ONLY"
        page.confidence = 0.98
        page.reasons = ["OFFICIAL_DOCUMENT_NOT_MASTER_IDENTITY"]
        return

    call_path = any(signal in path for signal in CALL_PATH_SIGNALS)
    scheme_path = any(signal in path for signal in SCHEME_PATH_SIGNALS)
    programme_path = any(signal in path for signal in PROGRAMME_PATH_SIGNALS)
    call_signal = any(signal in combined for signal in CALL_SIGNALS)
    permanent_signal = any(signal in f"{title} {page.description}".casefold() for signal in PERMANENT_SIGNALS)
    evidence_signal = any(signal in combined for signal in EVIDENCE_SIGNALS)
    non_catalogue_signal = any(signal in combined for signal in NON_CATALOGUE_SIGNALS)

    if call_path or (call_signal and not scheme_path and not programme_path):
        page.classification = "CALL_INSTANCE_CANDIDATE"
        page.confidence = 0.90 if call_path else 0.78
        page.reasons = ["CALL_COHORT_CHALLENGE_SIGNAL"]
    elif scheme_path:
        page.classification = "SCHEME_MASTER_CANDIDATE"
        page.confidence = 0.96
        page.reasons = ["OFFICIAL_SCHEME_PATH"]
    elif programme_path:
        page.classification = "PROGRAMME_MASTER_CANDIDATE"
        page.confidence = 0.90
        page.reasons = ["OFFICIAL_PROGRAMME_PATH"]
    elif evidence_signal:
        page.classification = "EVIDENCE_ONLY"
        page.confidence = 0.78
        page.reasons = ["GUIDANCE_NOTIFICATION_OR_REPORT_SIGNAL"]
    elif non_catalogue_signal:
        page.classification = "NON_CATALOGUE"
        page.confidence = 0.85
        page.reasons = ["GENERIC_OR_NAVIGATION_PAGE"]
    elif permanent_signal:
        page.classification = "MANUAL_REVIEW"
        page.confidence = 0.62
        page.reasons = ["POSSIBLE_PERMANENT_SUPPORT_PAGE"]
    else:
        page.classification = "NON_CATALOGUE"
        page.confidence = 0.70
        page.reasons = ["NO_SCHEME_OR_CALL_SIGNAL"]

    if page.classification == "CALL_INSTANCE_CANDIDATE":
        page.status_hint = "CALL_STATUS_REQUIRES_DATE_VALIDATION"
    elif any(token in combined for token in ("historical", "completed", "closed")):
        page.status_hint = "HISTORICAL_SIGNAL_REQUIRES_VALIDATION"
    else:
        page.status_hint = "STATUS_REQUIRES_VALIDATION"


def load_existing_identity_index(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    url_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}

    candidates = [
        root / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv",
        root / "data" / "catalogue_preview" / "v3_4_2_0_2" / "catalogue_preview_v3_4_2_0_2.csv",
        root / "data" / "departments" / "meity" / "v3_4_2_0_1" / "meity_existing_identity_lookup_v3_4_2_0_1.csv",
        root / "data" / "departments" / "meity" / "v3_4_2_0_1" / "meity_scheme_master_registry_v3_4_2_0_1.csv",
    ]

    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    master_id = normalize_space(
                        row.get("master_id") or row.get("scheme_master_id") or ""
                    )
                    if not master_id:
                        continue

                    source_text = " ".join(
                        normalize_space(row.get(key, ""))
                        for key in (
                            "source",
                            "ministry",
                            "department",
                            "implementing_agency",
                        )
                    ).casefold()

                    if path.name.startswith("catalogue") and "meity" not in source_text:
                        continue

                    for key in (
                        "official_page_url",
                        "core_scheme_url",
                        "best_available_url",
                        "final_url",
                        "source_url",
                    ):
                        value = normalize_space(row.get(key, ""))
                        if value and allowed_url(value):
                            url_to_id[canonicalize_url(value)] = master_id

                    for key in (
                        "canonical_name",
                        "scheme_name",
                        "candidate_name",
                        "title",
                    ):
                        value = normalize_name(row.get(key, ""))
                        if value:
                            name_to_id[value] = master_id
        except (OSError, csv.Error):
            continue

    return url_to_id, name_to_id


def assign_identity(
    page: Page,
    url_to_id: dict[str, str],
    name_to_id: dict[str, str],
) -> None:
    title = clean_title(page.heading or page.title)
    existing = (
        url_to_id.get(page.canonical_url)
        or name_to_id.get(normalize_name(title))
    )
    if existing:
        page.existing_master_id = existing
        page.candidate_id = existing
    else:
        digest = hashlib.sha256(page.canonical_url.encode("utf-8")).hexdigest()[:20]
        page.candidate_id = f"meity_{digest}"


def link_parents(pages: list[Page]) -> None:
    masters = [
        page
        for page in pages
        if page.classification
        in {"SCHEME_MASTER_CANDIDATE", "PROGRAMME_MASTER_CANDIDATE"}
    ]
    master_tokens = [
        (page, set(normalize_name(page.heading or page.title).split()))
        for page in masters
    ]

    by_url = {page.canonical_url: page for page in pages}

    for page in pages:
        if page.classification not in {
            "CALL_INSTANCE_CANDIDATE",
            "EVIDENCE_ONLY",
        }:
            continue

        referrer = by_url.get(page.discovered_from)
        if referrer and referrer.classification in {
            "SCHEME_MASTER_CANDIDATE",
            "PROGRAMME_MASTER_CANDIDATE",
        }:
            page.parent_hint = referrer.candidate_id
            continue

        page_tokens = set(normalize_name(page.heading or page.title).split())
        best: tuple[int, Page] | None = None
        for master, tokens in master_tokens:
            overlap = len(page_tokens & tokens)
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, master)
        if best:
            page.parent_hint = best[1].candidate_id


class LocalLLM:
    def __init__(self, session: requests.Session, endpoint: str, timeout: int):
        self.session = session
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.model = ""

    def available(self) -> bool:
        try:
            response = self.session.get(
                self.endpoint + "/models",
                timeout=min(self.timeout, 8),
            )
            response.raise_for_status()
            models = response.json().get("data", [])
            if models:
                self.model = normalize_space(models[0].get("id", ""))
            return bool(self.model)
        except Exception:
            return False

    def classify(self, page: Page) -> dict[str, Any] | None:
        allowed = [
            "SCHEME_MASTER_CANDIDATE",
            "PROGRAMME_MASTER_CANDIDATE",
            "CALL_INSTANCE_CANDIDATE",
            "EVIDENCE_ONLY",
            "NON_CATALOGUE",
            "MANUAL_REVIEW",
        ]
        prompt = {
            "task": "Conservatively classify an official MeitY detail page for SSIP.",
            "rules": [
                "A permanent scheme/programme is separate from calls, cohorts, rounds, challenges and application windows.",
                "Listing pages, sitemaps, reports, approvals, guidelines, contact pages and logo pages are not permanent scheme masters.",
                "Do not infer that applications are open merely because a scheme page exists.",
            ],
            "allowed_classifications": allowed,
            "page": {
                "url": page.canonical_url,
                "title": page.title,
                "heading": page.heading,
                "description": page.description,
                "text_excerpt": page.text_excerpt[:3500],
            },
            "response_format": {
                "classification": "one allowed value",
                "confidence": "0 to 1",
                "reason": "brief",
            },
        }

        try:
            response = self.session.post(
                self.endpoint + "/chat/completions",
                json={
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": 240,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return only valid JSON. Be conservative.",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(prompt, ensure_ascii=False),
                        },
                    ],
                },
                timeout=max(self.timeout, 60),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return None
            result = json.loads(match.group(0))
            if result.get("classification") not in allowed:
                return None
            return result
        except Exception:
            return None


def fetch_static(
    session: requests.Session,
    robots: RobotsCache,
    url: str,
    discovered_from: str,
    discovery_method: str,
    depth: int,
    timeout: int,
) -> tuple[Page, list[str], list[str]]:
    page = Page(
        url=url,
        canonical_url=canonicalize_url(url),
        discovered_from=discovered_from,
        discovery_method=discovery_method,
        depth=depth,
        fetched_at=now_iso(),
    )

    if not robots.allowed(page.canonical_url):
        page.error = "ROBOTS_DISALLOWED"
        return page, [], []

    try:
        response = session.get(
            page.canonical_url,
            timeout=timeout,
            allow_redirects=True,
        )
        page.status_code = response.status_code
        page.content_type = (
            response.headers.get("Content-Type", "").split(";")[0].strip().casefold()
        )
        page.canonical_url = canonicalize_url(response.url)

        if response.status_code >= 400:
            page.error = f"HTTP_{response.status_code}"
            return page, [], []

        path = urlparse(page.canonical_url).path.casefold()

        if (
            page.content_type in {"application/xml", "text/xml"}
            or path.endswith(".xml")
        ):
            links = parse_sitemap_xml(response.text, page.canonical_url)
            page.title = "Official sitemap"
            page.heading = page.title
            page.static_link_count = len(links)
            return page, links, []

        if (
            page.content_type == "application/pdf"
            or is_evidence_document(page.canonical_url)
        ):
            page.title = clean_title(Path(path).name)
            page.heading = page.title
            return page, [], []

        if "json" in page.content_type or response.text.lstrip().startswith(("{", "[")):
            try:
                links = urls_from_json(response.json(), response.url)
            except Exception:
                links = []
            page.title = "Official JSON endpoint"
            page.heading = page.title
            page.api_link_count = len(links)
            return page, links, []

        if "html" not in page.content_type and page.content_type:
            page.title = clean_title(Path(path).name)
            page.heading = page.title
            return page, [], []

        metadata, links, scripts = html_metadata(response.text, page.canonical_url)
        for key, value in metadata.items():
            setattr(page, key, value)
        page.static_link_count = len(links)
        return page, links, scripts

    except requests.RequestException as exc:
        page.error = f"{type(exc).__name__}: {exc}"
        return page, [], []


def script_discovery(
    session: requests.Session,
    scripts: list[str],
    timeout: int,
    max_scripts: int,
) -> list[str]:
    endpoints: list[str] = []
    for script_url in scripts[:max_scripts]:
        try:
            response = session.get(script_url, timeout=timeout)
            if response.ok:
                endpoints.extend(endpoints_from_script_text(response.text, script_url))
        except requests.RequestException:
            continue
    return list(dict.fromkeys(endpoints))


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            output: dict[str, Any] = {}
            for key in fieldnames:
                value = row.get(key, "")
                if isinstance(value, list):
                    value = "; ".join(str(item) for item in value)
                output[key] = value
            writer.writerow(output)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_test() -> None:
    samples = [
        Page(
            url="https://www.meity.gov.in/offerings/schemes-and-services",
            canonical_url="https://www.meity.gov.in/offerings/schemes-and-services",
            discovered_from="",
            discovery_method="seed",
            depth=0,
            title="Schemes and Services",
        ),
        Page(
            url="https://msh.meity.gov.in/schemes/samridh",
            canonical_url="https://msh.meity.gov.in/schemes/samridh",
            discovered_from="",
            discovery_method="seed",
            depth=0,
            title="SAMRIDH",
            description="Scheme supporting accelerators and startups.",
        ),
        Page(
            url="https://msh.meity.gov.in/challenges/demo",
            canonical_url="https://msh.meity.gov.in/challenges/demo",
            discovered_from="",
            discovery_method="seed",
            depth=0,
            title="Startup Challenge",
        ),
        Page(
            url="https://msh.meity.gov.in/about/applyforthelogo",
            canonical_url="https://msh.meity.gov.in/about/applyforthelogo",
            discovered_from="",
            discovery_method="seed",
            depth=0,
            title="Apply for the logo",
        ),
        Page(
            url="https://msh.meity.gov.in/assets/example.pdf",
            canonical_url="https://msh.meity.gov.in/assets/example.pdf",
            discovered_from="",
            discovery_method="seed",
            depth=0,
            title="Administrative Approval.pdf",
            content_type="application/pdf",
        ),
    ]

    for page in samples:
        classify(page)

    expected = [
        "DISCOVERY_INDEX",
        "SCHEME_MASTER_CANDIDATE",
        "CALL_INSTANCE_CANDIDATE",
        "NON_CATALOGUE",
        "EVIDENCE_ONLY",
    ]
    actual = [page.classification for page in samples]
    if actual != expected:
        raise AssertionError(f"Expected {expected}, got {actual}")

    api_sample = {
        "data": [
            {"title": "Demo", "detailsUrl": "/schemes/demo"},
            {"href": "https://msh.meity.gov.in/challenges/test"},
        ]
    }
    discovered = urls_from_json(api_sample, "https://msh.meity.gov.in/")
    if len(discovered) != 2:
        raise AssertionError(f"JSON discovery failed: {discovered}")

    print("MeitY discovery expansion self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview-only MeitY discovery expansion agent with sitemap, "
            "browser-rendered DOM, script endpoint and network JSON discovery."
        )
    )
    parser.add_argument("--max-pages", type=int, default=400)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--browser-timeout-ms", type=int, default=30000)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument(
        "--browser",
        choices=("auto", "yes", "no"),
        default="auto",
    )
    parser.add_argument(
        "--use-llm",
        choices=("auto", "yes", "no"),
        default="auto",
    )
    parser.add_argument("--llm-max", type=int, default=60)
    parser.add_argument(
        "--llm-endpoint",
        default=os.environ.get(
            "SSIP_LM_STUDIO_ENDPOINT",
            "http://127.0.0.1:1234/v1",
        ),
    )
    parser.add_argument("--max-scripts-per-page", type=int, default=12)
    parser.add_argument("--max-api-endpoints", type=int, default=80)
    parser.add_argument("--min-pages", type=int, default=20)
    parser.add_argument("--min-detail-urls", type=int, default=8)
    parser.add_argument("--min-master-candidates", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = project_root()
    output_dir = root / "data" / "departments" / "meity" / "v3_4_3_1"
    audit_dir = root / "data" / "audit"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    active_catalogue = (
        root
        / "data"
        / "catalogue_preview"
        / "v3_3_2"
        / "catalogue_preview_v3_3_2.csv"
    )
    current_manifest = root / "data" / "publication" / "current_manifest.json"
    database = root / "database" / "ssip_staging_v1.db"
    dashboard = root / "apps" / "public_dashboard_app_v2_9.py"

    frozen_files = {
        active_catalogue.relative_to(root).as_posix(): hash_file(active_catalogue),
        current_manifest.relative_to(root).as_posix(): hash_file(current_manifest),
        database.relative_to(root).as_posix(): hash_file(database),
        dashboard.relative_to(root).as_posix(): hash_file(dashboard),
    }
    write_json(
        audit_dir / "meity_v3_4_3_1_discovery_prechange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "execution_mode": "DISCOVERY_PREVIEW_ONLY",
            "frozen_files": frozen_files,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    )

    session = build_session()
    robots = RobotsCache(session, args.timeout)
    browser_requested = args.browser != "no"
    browser = BrowserDiscovery(
        enabled=browser_requested,
        timeout_ms=args.browser_timeout_ms,
    )

    if args.browser == "yes" and not browser.available:
        raise RuntimeError(
            "Browser rendering was required but Playwright is unavailable. "
            "Run: python -m pip install playwright && python -m playwright install chromium"
        )

    url_to_id, name_to_id = load_existing_identity_index(root)
    seeds = list(
        dict.fromkeys(
            canonicalize_url(url)
            for url in (args.seed or DEFAULT_SEEDS)
            if allowed_url(url)
        )
    )
    seed_set = set(seeds)

    queue: list[tuple[int, int, str, str, str, int]] = []
    queued: set[str] = set()
    visited: set[str] = set()
    sequence = 0

    def enqueue(
        url: str,
        discovered_from: str,
        method: str,
        depth: int,
    ) -> None:
        nonlocal sequence
        if not allowed_url(url) or is_static_asset(url):
            return
        canonical = canonicalize_url(url)
        if canonical in visited or canonical in queued:
            return
        heapq.heappush(
            queue,
            (
                priority_for(canonical, depth, method),
                sequence,
                canonical,
                discovered_from,
                method,
                depth,
            ),
        )
        queued.add(canonical)
        sequence += 1

    for seed in seeds:
        enqueue(seed, "", "seed", 0)

    pages: list[Page] = []
    discovered_detail_urls: set[str] = set()
    discovery_index_count = 0
    rendered_index_count = 0
    api_endpoints_seen: set[str] = set()
    api_endpoints_attempted = 0

    try:
        while queue and len(pages) < args.max_pages:
            _, _, url, discovered_from, method, depth = heapq.heappop(queue)
            queued.discard(url)
            canonical = canonicalize_url(url)
            if canonical in visited:
                continue
            visited.add(canonical)

            page, static_links, scripts = fetch_static(
                session=session,
                robots=robots,
                url=canonical,
                discovered_from=discovered_from,
                discovery_method=method,
                depth=depth,
                timeout=args.timeout,
            )

            rendered_links: list[str] = []
            network_endpoints: list[str] = []
            should_render = (
                browser.available
                and not page.error
                and (
                    any(signal in page.canonical_url.casefold() for signal in DISCOVERY_INDEX_PATH_SIGNALS)
                    or len(page.text_excerpt) < 300
                    or len(static_links) < 3
                )
            )

            if should_render:
                rendered_meta, rendered_links, network_endpoints = browser.discover(
                    page.canonical_url
                )
                if rendered_meta:
                    page.rendered_used = True
                    for key in ("title", "heading", "text_excerpt"):
                        value = normalize_space(rendered_meta.get(key, ""))
                        if value and (
                            key != "text_excerpt"
                            or len(value) > len(page.text_excerpt)
                        ):
                            setattr(page, key, value)
                page.rendered_link_count = len(rendered_links)
                if any(
                    signal in page.canonical_url.casefold()
                    for signal in DISCOVERY_INDEX_PATH_SIGNALS
                ):
                    rendered_index_count += 1

            script_endpoints = script_discovery(
                session=session,
                scripts=scripts,
                timeout=args.timeout,
                max_scripts=args.max_scripts_per_page,
            )
            page.script_endpoint_count = len(script_endpoints)

            for endpoint in network_endpoints + script_endpoints:
                if len(api_endpoints_seen) >= args.max_api_endpoints:
                    break
                if endpoint in api_endpoints_seen:
                    continue
                api_endpoints_seen.add(endpoint)
                page.api_endpoints.append(endpoint)

            api_links: list[str] = []
            for endpoint in page.api_endpoints:
                if api_endpoints_attempted >= args.max_api_endpoints:
                    break
                api_endpoints_attempted += 1
                links, _ = fetch_api_json(
                    session=session,
                    robots=robots,
                    url=endpoint,
                    timeout=args.timeout,
                )
                api_links.extend(links)
            api_links = list(dict.fromkeys(api_links))
            page.api_link_count = len(api_links)

            classify(page)
            assign_identity(page, url_to_id, name_to_id)
            pages.append(page)

            if page.is_discovery_index:
                discovery_index_count += 1

            discovered_links = list(
                dict.fromkeys(static_links + rendered_links + api_links)
            )

            for link in discovered_links:
                lower = link.casefold()
                if (
                    any(signal in lower for signal in SCHEME_PATH_SIGNALS)
                    or any(signal in lower for signal in PROGRAMME_PATH_SIGNALS)
                    or any(signal in lower for signal in CALL_PATH_SIGNALS)
                    or is_evidence_document(link)
                ):
                    discovered_detail_urls.add(link)

                if depth < args.max_depth:
                    if link in rendered_links:
                        child_method = "rendered_dom"
                    elif link in api_links:
                        child_method = "network_json"
                    elif urlparse(link).path.casefold().endswith(".xml"):
                        child_method = "sitemap"
                    else:
                        child_method = "static_anchor"
                    enqueue(link, page.canonical_url, child_method, depth + 1)

            print(
                f"[{len(pages):03d}/{args.max_pages}] "
                f"{page.classification:28s} "
                f"{page.status_code:3d} "
                f"S{page.static_link_count:03d} "
                f"R{page.rendered_link_count:03d} "
                f"A{page.api_link_count:03d} "
                f"{page.canonical_url}"
            )

            if args.delay:
                time.sleep(args.delay)

    finally:
        browser.close()

    link_parents(pages)

    llm = LocalLLM(session, args.llm_endpoint, args.timeout)
    llm_available = args.use_llm != "no" and llm.available()
    if args.use_llm == "yes" and not llm_available:
        raise RuntimeError("LM Studio was required but is not available.")

    ambiguous = [
        page
        for page in pages
        if page.classification == "MANUAL_REVIEW"
        or (
            page.classification
            in {
                "SCHEME_MASTER_CANDIDATE",
                "PROGRAMME_MASTER_CANDIDATE",
                "CALL_INSTANCE_CANDIDATE",
                "EVIDENCE_ONLY",
            }
            and page.confidence < 0.85
        )
    ][: args.llm_max]

    if llm_available:
        print(
            f"LM Studio detected: {llm.model}. "
            f"Reviewing {len(ambiguous)} ambiguous detail pages."
        )
        for index, page in enumerate(ambiguous, start=1):
            result = llm.classify(page)
            if not result:
                continue
            page.llm_used = True
            page.llm_classification = normalize_space(
                result.get("classification", "")
            )
            try:
                page.llm_confidence = float(result.get("confidence", 0))
            except (TypeError, ValueError):
                page.llm_confidence = 0.0
            page.llm_reason = normalize_space(result.get("reason", ""))
            if page.llm_confidence >= 0.90:
                page.reasons.append(
                    f"LLM_REVIEW_{page.llm_classification}"
                )
            print(f"  LLM {index}/{len(ambiguous)}: {page.canonical_url}")

    counts = Counter(page.classification for page in pages)
    master_candidate_count = (
        counts.get("SCHEME_MASTER_CANDIDATE", 0)
        + counts.get("PROGRAMME_MASTER_CANDIDATE", 0)
    )
    new_urls_beyond_seeds = {
        page.canonical_url
        for page in pages
        if page.canonical_url not in seed_set
    }

    coverage_checks = [
        {
            "name": "minimum_pages_attempted",
            "passed": len(pages) >= args.min_pages,
            "details": f"actual={len(pages)} minimum={args.min_pages}",
        },
        {
            "name": "discovery_indexes_parsed",
            "passed": discovery_index_count >= 2,
            "details": f"actual={discovery_index_count} minimum=2",
        },
        {
            "name": "detail_urls_discovered",
            "passed": len(discovered_detail_urls) >= args.min_detail_urls,
            "details": (
                f"actual={len(discovered_detail_urls)} "
                f"minimum={args.min_detail_urls}"
            ),
        },
        {
            "name": "urls_discovered_beyond_seeds",
            "passed": len(new_urls_beyond_seeds) >= 5,
            "details": f"actual={len(new_urls_beyond_seeds)} minimum=5",
        },
        {
            "name": "minimum_master_candidates",
            "passed": master_candidate_count >= args.min_master_candidates,
            "details": (
                f"actual={master_candidate_count} "
                f"minimum={args.min_master_candidates}"
            ),
        },
        {
            "name": "rendered_or_api_discovery_operational",
            "passed": (
                rendered_index_count > 0
                or api_endpoints_attempted > 0
                or any(
                    page.discovery_method == "sitemap"
                    for page in pages
                )
            ),
            "details": (
                f"rendered_indexes={rendered_index_count} "
                f"api_endpoints_attempted={api_endpoints_attempted}"
            ),
        },
        {
            "name": "invalid_logo_page_not_master",
            "passed": not any(
                INVALID_LOGO_PATH in page.canonical_url.casefold()
                and page.classification
                in {
                    "SCHEME_MASTER_CANDIDATE",
                    "PROGRAMME_MASTER_CANDIDATE",
                    "CALL_INSTANCE_CANDIDATE",
                }
                for page in pages
            ),
            "details": "The MSH logo application page must never be a scheme or call.",
        },
    ]
    coverage_failed = [
        check for check in coverage_checks if not check["passed"]
    ]
    coverage_status = "PASS" if not coverage_failed else "FAIL"

    page_rows = [
        asdict(page)
        for page in sorted(pages, key=lambda item: item.canonical_url)
    ]
    page_fields = [
        "candidate_id",
        "existing_master_id",
        "classification",
        "confidence",
        "title",
        "heading",
        "canonical_url",
        "url",
        "discovered_from",
        "discovery_method",
        "parent_hint",
        "status_hint",
        "status_code",
        "content_type",
        "published_date_signal",
        "money_signals",
        "depth",
        "static_link_count",
        "rendered_link_count",
        "api_link_count",
        "script_endpoint_count",
        "rendered_used",
        "api_endpoints",
        "reasons",
        "llm_used",
        "llm_classification",
        "llm_confidence",
        "llm_reason",
        "fetched_at",
        "error",
        "description",
        "text_excerpt",
    ]
    write_csv(
        output_dir / "meity_discovered_pages_v3_4_3_1.csv",
        page_rows,
        page_fields,
    )

    compact_fields = [
        "candidate_id",
        "existing_master_id",
        "classification",
        "confidence",
        "title",
        "heading",
        "canonical_url",
        "discovered_from",
        "discovery_method",
        "parent_hint",
        "status_hint",
        "published_date_signal",
        "money_signals",
        "rendered_used",
        "reasons",
        "llm_classification",
        "llm_confidence",
        "llm_reason",
    ]
    group_files = {
        "DISCOVERY_INDEX": "meity_discovery_indexes_v3_4_3_1.csv",
        "SCHEME_MASTER_CANDIDATE": "meity_scheme_master_candidates_v3_4_3_1.csv",
        "PROGRAMME_MASTER_CANDIDATE": "meity_programme_master_candidates_v3_4_3_1.csv",
        "CALL_INSTANCE_CANDIDATE": "meity_call_instances_v3_4_3_1.csv",
        "EVIDENCE_ONLY": "meity_evidence_only_pages_v3_4_3_1.csv",
        "NON_CATALOGUE": "meity_non_catalogue_pages_v3_4_3_1.csv",
    }
    for classification_name, filename in group_files.items():
        rows = [
            asdict(page)
            for page in pages
            if page.classification == classification_name
        ]
        write_csv(output_dir / filename, rows, compact_fields)

    review_rows: list[dict[str, Any]] = []
    for page in pages:
        needs_review = (
            page.classification == "MANUAL_REVIEW"
            or (
                page.classification == "CALL_INSTANCE_CANDIDATE"
                and not page.parent_hint
            )
            or (
                page.classification
                in {
                    "SCHEME_MASTER_CANDIDATE",
                    "PROGRAMME_MASTER_CANDIDATE",
                }
                and page.confidence < 0.90
            )
            or (
                page.llm_used
                and page.llm_classification
                and page.llm_classification != page.classification
            )
        )
        if not needs_review:
            continue
        review_rows.append(
            {
                "review_id": (
                    "meity_review_"
                    + hashlib.sha256(
                        page.canonical_url.encode("utf-8")
                    ).hexdigest()[:16]
                ),
                "candidate_id": page.candidate_id,
                "existing_master_id": page.existing_master_id,
                "title": page.heading or page.title,
                "canonical_url": page.canonical_url,
                "provisional_classification": page.classification,
                "confidence": page.confidence,
                "parent_hint": page.parent_hint,
                "review_reasons": "; ".join(page.reasons),
                "llm_classification": page.llm_classification,
                "llm_confidence": page.llm_confidence,
                "llm_reason": page.llm_reason,
                "review_status": "OPEN",
                "publication_status": "NOT_PUBLISHED",
            }
        )
    review_fields = [
        "review_id",
        "candidate_id",
        "existing_master_id",
        "title",
        "canonical_url",
        "provisional_classification",
        "confidence",
        "parent_hint",
        "review_reasons",
        "llm_classification",
        "llm_confidence",
        "llm_reason",
        "review_status",
        "publication_status",
    ]
    write_csv(
        output_dir / "meity_manual_review_queue_v3_4_3_1.csv",
        review_rows,
        review_fields,
    )

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "execution_mode": "DISCOVERY_PREVIEW_ONLY",
        "coverage_status": coverage_status,
        "completed_at": now_iso(),
        "settings": {
            "max_pages": args.max_pages,
            "max_depth": args.max_depth,
            "delay": args.delay,
            "timeout": args.timeout,
            "browser_mode": args.browser,
            "browser_available": browser.available,
            "browser_error": browser.error,
            "use_llm": args.use_llm,
            "llm_available": llm_available,
            "llm_model": llm.model if llm_available else "",
            "llm_max": args.llm_max,
            "min_pages": args.min_pages,
            "min_detail_urls": args.min_detail_urls,
            "min_master_candidates": args.min_master_candidates,
        },
        "counts": {
            "pages_attempted": len(pages),
            "unique_urls_visited": len(visited),
            "queued_urls_remaining": len(queue),
            "new_urls_beyond_seeds": len(new_urls_beyond_seeds),
            "discovered_detail_urls": len(discovered_detail_urls),
            "discovery_indexes": discovery_index_count,
            "rendered_indexes": rendered_index_count,
            "api_endpoints_seen": len(api_endpoints_seen),
            "api_endpoints_attempted": api_endpoints_attempted,
            "existing_identity_matches": sum(
                bool(page.existing_master_id) for page in pages
            ),
            "manual_review_rows": len(review_rows),
            **dict(sorted(counts.items())),
        },
        "coverage_checks": coverage_checks,
        "failed_coverage_checks": [
            check["name"] for check in coverage_failed
        ],
        "governance": {
            "calls_and_cohorts_separate_from_permanent_schemes": True,
            "listing_pages_classified_as_discovery_indexes": True,
            "official_domains_only": True,
            "application_status_not_inferred_from_scheme_page": True,
            "invalid_msh_logo_application_excluded": True,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    }
    write_json(
        output_dir / "meity_discovery_summary_v3_4_3_1.json",
        summary,
    )

    manifest_files = sorted(
        path for path in output_dir.iterdir() if path.is_file()
    )
    write_json(
        output_dir / "meity_discovery_manifest_v3_4_3_1.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "generated_at": now_iso(),
            "coverage_status": coverage_status,
            "outputs": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hash_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in manifest_files
            ],
            "publication_status": "NOT_PUBLISHED",
        },
    )

    postchange_results = {
        path.relative_to(root).as_posix(): {
            "before": frozen_files[path.relative_to(root).as_posix()],
            "after": hash_file(path),
            "unchanged": (
                frozen_files[path.relative_to(root).as_posix()]
                == hash_file(path)
            ),
        }
        for path in (
            active_catalogue,
            current_manifest,
            database,
            dashboard,
        )
    }
    changed = [
        name
        for name, result in postchange_results.items()
        if not result["unchanged"]
    ]
    write_json(
        audit_dir / "meity_v3_4_3_1_discovery_postchange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "coverage_status": coverage_status,
            "frozen_file_results": postchange_results,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    )

    print()
    print("SSIP MeitY v3.4.3.1 discovery expansion")
    print("--------------------------------------------------")
    print(f"Coverage status:             {coverage_status}")
    print(f"Pages attempted:             {len(pages)}")
    print(f"Discovery indexes:           {discovery_index_count}")
    print(f"Rendered indexes:            {rendered_index_count}")
    print(f"API endpoints attempted:     {api_endpoints_attempted}")
    print(f"New URLs beyond seeds:       {len(new_urls_beyond_seeds)}")
    print(f"Detail URLs discovered:      {len(discovered_detail_urls)}")
    print(
        "Scheme master candidates:    "
        f"{counts.get('SCHEME_MASTER_CANDIDATE', 0)}"
    )
    print(
        "Programme master candidates: "
        f"{counts.get('PROGRAMME_MASTER_CANDIDATE', 0)}"
    )
    print(
        "Call/cohort candidates:      "
        f"{counts.get('CALL_INSTANCE_CANDIDATE', 0)}"
    )
    print(
        "Evidence-only pages:         "
        f"{counts.get('EVIDENCE_ONLY', 0)}"
    )
    print(f"Manual review rows:          {len(review_rows)}")
    print(f"LM Studio used:              {'Yes' if llm_available else 'No'}")
    print(f"Browser rendering available: {'Yes' if browser.available else 'No'}")
    print(f"Frozen files changed:        {len(changed)}")
    print("Publication performed:       No")
    print()
    print("Output directory:")
    print(output_dir)

    if coverage_failed:
        print()
        print("Coverage checks failed:")
        for check in coverage_failed:
            print(f"- {check['name']}: {check['details']}")

    if changed:
        print()
        print("Frozen files changed unexpectedly:")
        for name in changed:
            print(f"- {name}")

    return 0 if coverage_status == "PASS" and not changed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDiscovery interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"DISCOVERY ERROR: {exc}", file=sys.stderr)
        raise
