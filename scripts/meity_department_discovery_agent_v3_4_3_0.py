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
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Run: python -m pip install requests beautifulsoup4\n"
        f"Import error: {exc}"
    )

VERSION = "3.4.3.0"
PHASE = "MeitY Department-Wide Automated Discovery and Classification"
USER_AGENT = "SSIP-Governed-Discovery/3.4.3.0 (+official-source research)"
INVALID_LOGO_PATH = "/about/applyforthelogo"

DEFAULT_SEEDS = [
    "https://www.meity.gov.in/offerings/schemes-and-services",
    "https://www.meity.gov.in/offerings?page=0",
    "https://www.meity.gov.in/archives?page=schemes_and_services",
    "https://msh.meity.gov.in/",
    "https://msh.meity.gov.in/whatsnew",
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
}

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

CALL_SIGNALS = (
    "applications invited",
    "application invited",
    "applications open",
    "apply now",
    "call for proposals",
    "call for application",
    "expression of interest",
    "request for proposal",
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

SCHEME_PATH_SIGNALS = (
    "/schemes/",
    "/offerings/schemes-and-services/details/",
)

CALL_PATH_SIGNALS = (
    "/challenges/",
    "/whatsnew",
    "/announcement",
    "/announcements",
    "/call",
    "/cohort",
    "/eoi",
    "/rfp",
)

EVIDENCE_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
)

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


@dataclass
class Page:
    url: str
    canonical_url: str
    discovered_from: str
    depth: int
    status_code: int = 0
    content_type: str = ""
    title: str = ""
    heading: str = ""
    description: str = ""
    text_excerpt: str = ""
    published_date_signal: str = ""
    money_signals: str = ""
    link_count: int = 0
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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_name(value: str) -> str:
    text = normalize_space(value).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    ignored = {
        "scheme", "schemes", "programme", "program", "programmes",
        "the", "of", "for", "and", "ministry", "meity", "official",
    }
    tokens = [token for token in text.split() if token not in ignored]
    return " ".join(tokens)


def clean_title(value: str) -> str:
    text = normalize_space(value)
    for suffix in (
        " | Ministry of Electronics and Information Technology",
        " - MeitY Startup Hub",
        " | MeitY Startup Hub",
        " - MeityStartupHub",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


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


def priority_for(url: str, depth: int) -> int:
    text = url.casefold()
    score = depth * 100
    if any(signal in text for signal in SCHEME_PATH_SIGNALS):
        score -= 60
    if any(signal in text for signal in CALL_PATH_SIGNALS):
        score -= 40
    if "/offerings" in text:
        score -= 30
    if any(text.endswith(ext) for ext in EVIDENCE_EXTENSIONS):
        score += 20
    return score


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
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
            robots_url = origin + "/robots.txt"
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                response = self.session.get(robots_url, timeout=self.timeout)
                if response.ok:
                    parser.parse(response.text.splitlines())
                    self.cache[origin] = parser
                else:
                    self.cache[origin] = None
            except requests.RequestException:
                self.cache[origin] = None
        parser = self.cache[origin]
        return True if parser is None else parser.can_fetch(USER_AGENT, url)


def extract_html(response: requests.Response, url: str) -> tuple[dict[str, str], list[str]]:
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = clean_title(soup.title.get_text(" ", strip=True) if soup.title else "")
    heading_tag = soup.find(["h1", "h2"])
    heading = clean_title(heading_tag.get_text(" ", strip=True) if heading_tag else "")

    description = ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta and meta.get("content"):
        description = normalize_space(meta["content"])

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalize_space(main.get_text(" ", strip=True))
    excerpt = text[:18000]

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href", ""))
        if not href:
            continue
        absolute = urljoin(url, href)
        if allowed_url(absolute):
            links.append(canonicalize_url(absolute))

    date_match = DATE_PATTERN.search(text)
    money = MONEY_PATTERN.findall(text)
    return (
        {
            "title": title,
            "heading": heading,
            "description": description,
            "text_excerpt": excerpt,
            "published_date_signal": date_match.group(0) if date_match else "",
            "money_signals": "; ".join(dict.fromkeys(normalize_space(item) for item in money[:12])),
        },
        list(dict.fromkeys(links)),
    )


def classify(page: Page) -> None:
    url_text = page.canonical_url.casefold()
    title = clean_title(page.heading or page.title)
    combined = " ".join(
        [title, page.description, page.text_excerpt[:8000], url_text]
    ).casefold()

    reasons: list[str] = []

    if INVALID_LOGO_PATH in url_text or "apply for the logo" in combined:
        page.classification = "NON_CATALOGUE"
        page.confidence = 1.0
        page.reasons = ["UNRELATED_MSH_LOGO_APPLICATION"]
        return

    if page.error:
        page.classification = "MANUAL_REVIEW"
        page.confidence = 0.1
        page.reasons = ["FETCH_ERROR"]
        return

    path = urlparse(page.canonical_url).path.casefold()
    is_document = any(path.endswith(ext) for ext in EVIDENCE_EXTENSIONS)
    evidence_signal = any(signal in combined for signal in EVIDENCE_SIGNALS)
    non_catalogue = any(signal in combined for signal in NON_CATALOGUE_SIGNALS)
    call_signal = any(signal in combined for signal in CALL_SIGNALS)
    scheme_path = any(signal in path for signal in SCHEME_PATH_SIGNALS)
    call_path = any(signal in path for signal in CALL_PATH_SIGNALS)
    permanent_signal = any(signal in f"{title} {page.description}".casefold() for signal in PERMANENT_SIGNALS)

    if is_document:
        page.classification = "EVIDENCE_ONLY"
        page.confidence = 0.98
        reasons.append("OFFICIAL_DOCUMENT_NOT_MASTER_IDENTITY")
    elif non_catalogue and not scheme_path and not call_path:
        page.classification = "NON_CATALOGUE"
        page.confidence = 0.92
        reasons.append("GENERIC_OR_NAVIGATION_PAGE")
    elif call_path or (call_signal and not scheme_path):
        page.classification = "CALL_INSTANCE_CANDIDATE"
        page.confidence = 0.88 if call_path else 0.78
        reasons.append("CALL_COHORT_CHALLENGE_SIGNAL")
    elif scheme_path:
        page.classification = "SCHEME_MASTER_CANDIDATE"
        page.confidence = 0.96
        reasons.append("OFFICIAL_SCHEME_PATH")
    elif "/program/" in path or "/programs/" in path:
        page.classification = "PROGRAMME_MASTER_CANDIDATE"
        page.confidence = 0.86
        reasons.append("OFFICIAL_PROGRAMME_PATH")
    elif "/offerings" in path and permanent_signal:
        page.classification = "SCHEME_MASTER_CANDIDATE"
        page.confidence = 0.85
        reasons.append("MEITY_OFFERING_WITH_PERMANENT_SIGNAL")
    elif evidence_signal:
        page.classification = "EVIDENCE_ONLY"
        page.confidence = 0.78
        reasons.append("GUIDANCE_NOTIFICATION_OR_REPORT_SIGNAL")
    elif permanent_signal:
        page.classification = "MANUAL_REVIEW"
        page.confidence = 0.62
        reasons.append("POSSIBLE_PERMANENT_SUPPORT_PAGE")
    else:
        page.classification = "NON_CATALOGUE"
        page.confidence = 0.72
        reasons.append("NO_SCHEME_OR_CALL_SIGNAL")

    if call_signal:
        page.status_hint = "CALL_STATUS_REQUIRES_DATE_VALIDATION"
    elif "historical" in combined or "completed" in combined or "closed" in combined:
        page.status_hint = "HISTORICAL_SIGNAL_REQUIRES_VALIDATION"
    else:
        page.status_hint = "STATUS_REQUIRES_VALIDATION"

    page.reasons = reasons


def load_existing_identity_index(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    url_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}

    candidate_files = [
        root / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv",
        root / "data" / "departments" / "meity" / "v3_4_2_0_1" / "meity_existing_identity_lookup_v3_4_2_0_1.csv",
        root / "data" / "departments" / "meity" / "v3_4_2_0_1" / "meity_scheme_master_registry_v3_4_2_0_1.csv",
        root / "data" / "catalogue_preview" / "v3_4_2_0_2" / "catalogue_preview_v3_4_2_0_2.csv",
    ]

    for path in candidate_files:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    master_id = normalize_space(
                        row.get("master_id")
                        or row.get("scheme_master_id")
                        or ""
                    )
                    if not master_id:
                        continue
                    source_text = " ".join(
                        normalize_space(row.get(key, ""))
                        for key in ("source", "ministry", "department", "implementing_agency")
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

                    for key in ("canonical_name", "scheme_name", "candidate_name", "title"):
                        value = normalize_name(row.get(key, ""))
                        if value:
                            name_to_id[value] = master_id
        except (OSError, csv.Error):
            continue

    return url_to_id, name_to_id


def assign_identity(page: Page, url_to_id: dict[str, str], name_to_id: dict[str, str]) -> None:
    title = clean_title(page.heading or page.title)
    existing = url_to_id.get(page.canonical_url) or name_to_id.get(normalize_name(title))
    if existing:
        page.existing_master_id = existing
        page.candidate_id = existing
    else:
        digest = hashlib.sha256(page.canonical_url.encode("utf-8")).hexdigest()[:20]
        page.candidate_id = f"meity_{digest}"


def parent_link(pages: list[Page]) -> None:
    masters = [
        page
        for page in pages
        if page.classification in {"SCHEME_MASTER_CANDIDATE", "PROGRAMME_MASTER_CANDIDATE"}
    ]
    master_tokens = [
        (
            page,
            set(normalize_name(page.heading or page.title).split()),
        )
        for page in masters
    ]

    for page in pages:
        if page.classification not in {"CALL_INSTANCE_CANDIDATE", "EVIDENCE_ONLY"}:
            continue

        page_tokens = set(normalize_name(page.heading or page.title).split())
        best: tuple[int, Page] | None = None

        for master, tokens in master_tokens:
            overlap = len(page_tokens & tokens)
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, master)

        if best:
            page.parent_hint = best[1].candidate_id
        elif page.discovered_from:
            referrer = next(
                (
                    item
                    for item in masters
                    if item.canonical_url == page.discovered_from
                ),
                None,
            )
            if referrer:
                page.parent_hint = referrer.candidate_id


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
            data = response.json()
            models = data.get("data", [])
            if models:
                self.model = models[0].get("id", "")
            return bool(self.model)
        except Exception:
            return False

    def classify(self, page: Page) -> dict[str, Any] | None:
        prompt = {
            "task": "Classify an official MeitY webpage for the SSIP catalogue.",
            "rules": [
                "Permanent scheme/programme identities are separate from calls, cohorts, rounds and challenges.",
                "PDFs, guidelines, reports, approvals, contact pages, sitemaps and logo pages are evidence/non-catalogue, not scheme masters.",
                "Do not infer that applications are open merely because a scheme page exists.",
            ],
            "allowed_classifications": [
                "SCHEME_MASTER_CANDIDATE",
                "PROGRAMME_MASTER_CANDIDATE",
                "CALL_INSTANCE_CANDIDATE",
                "EVIDENCE_ONLY",
                "NON_CATALOGUE",
                "MANUAL_REVIEW",
            ],
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
                    "max_tokens": 220,
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
            if result.get("classification") not in prompt["allowed_classifications"]:
                return None
            return result
        except Exception:
            return None


def fetch_page(
    session: requests.Session,
    robots: RobotsCache,
    url: str,
    discovered_from: str,
    depth: int,
    timeout: int,
) -> tuple[Page, list[str]]:
    page = Page(
        url=url,
        canonical_url=canonicalize_url(url),
        discovered_from=discovered_from,
        depth=depth,
        fetched_at=now_iso(),
    )

    if not robots.allowed(page.canonical_url):
        page.error = "ROBOTS_DISALLOWED"
        return page, []

    try:
        response = session.get(page.canonical_url, timeout=timeout, allow_redirects=True)
        page.status_code = response.status_code
        page.content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        page.canonical_url = canonicalize_url(response.url)

        if response.status_code >= 400:
            page.error = f"HTTP_{response.status_code}"
            return page, []

        path = urlparse(page.canonical_url).path.casefold()
        if page.content_type == "application/pdf" or path.endswith(".pdf"):
            page.title = clean_title(Path(path).name)
            page.heading = page.title
            page.text_excerpt = ""
            return page, []

        if "html" not in page.content_type and page.content_type:
            page.title = clean_title(Path(path).name)
            page.heading = page.title
            return page, []

        extracted, links = extract_html(response, page.canonical_url)
        for key, value in extracted.items():
            setattr(page, key, value)
        page.link_count = len(links)
        return page, links

    except requests.RequestException as exc:
        page.error = f"{type(exc).__name__}: {exc}"
        return page, []


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {}
            for key in fieldnames:
                value = row.get(key, "")
                if isinstance(value, list):
                    value = "; ".join(str(item) for item in value)
                safe[key] = value
            writer.writerow(safe)


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
            url="https://msh.meity.gov.in/schemes/samridh",
            canonical_url="https://msh.meity.gov.in/schemes/samridh",
            discovered_from="",
            depth=0,
            title="MeitY | Samridh Scheme",
            heading="SAMRIDH",
            description="Scheme supporting accelerators and technology startups",
        ),
        Page(
            url="https://msh.meity.gov.in/challenges/home/demo",
            canonical_url="https://msh.meity.gov.in/challenges/home/demo",
            discovered_from="",
            depth=0,
            title="Face Liveness Detection Challenge",
            heading="Applications open for first cohort",
        ),
        Page(
            url="https://msh.meity.gov.in/about/applyforthelogo",
            canonical_url="https://msh.meity.gov.in/about/applyforthelogo",
            discovered_from="",
            depth=0,
            title="Apply for the logo",
        ),
        Page(
            url="https://msh.meity.gov.in/assets/Administrative%20Approval_TIDE%202.0.pdf",
            canonical_url="https://msh.meity.gov.in/assets/Administrative%20Approval_TIDE%202.0.pdf",
            discovered_from="",
            depth=0,
            title="Administrative Approval TIDE 2.0.pdf",
            content_type="application/pdf",
        ),
    ]
    for page in samples:
        classify(page)

    expected = [
        "SCHEME_MASTER_CANDIDATE",
        "CALL_INSTANCE_CANDIDATE",
        "NON_CATALOGUE",
        "EVIDENCE_ONLY",
    ]
    actual = [page.classification for page in samples]
    if actual != expected:
        raise AssertionError(f"Self-test failed: expected={expected}, actual={actual}")
    print("MeitY discovery agent self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview-only MeitY department-wide discovery and classification agent."
    )
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument(
        "--use-llm",
        choices=("auto", "yes", "no"),
        default="auto",
        help="Use LM Studio only for ambiguous pages.",
    )
    parser.add_argument("--llm-max", type=int, default=40)
    parser.add_argument(
        "--llm-endpoint",
        default=os.environ.get("SSIP_LM_STUDIO_ENDPOINT", "http://127.0.0.1:1234/v1"),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.max_pages < 1 or args.max_pages > 2000:
        raise SystemExit("--max-pages must be between 1 and 2000.")

    root = project_root()
    output_dir = root / "data" / "departments" / "meity" / "v3_4_3_0"
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

    prechange = {
        "version": VERSION,
        "phase": PHASE,
        "recorded_at": now_iso(),
        "execution_mode": "DISCOVERY_PREVIEW_ONLY",
        "frozen_files": {
            active_catalogue.relative_to(root).as_posix(): hash_file(active_catalogue),
            current_manifest.relative_to(root).as_posix(): hash_file(current_manifest),
            database.relative_to(root).as_posix(): hash_file(database),
            dashboard.relative_to(root).as_posix(): hash_file(dashboard),
        },
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }
    write_json(
        audit_dir / "meity_v3_4_3_0_discovery_prechange_sha256.json",
        prechange,
    )

    session = build_session()
    robots = RobotsCache(session, args.timeout)
    url_to_id, name_to_id = load_existing_identity_index(root)

    seeds = list(dict.fromkeys(canonicalize_url(url) for url in (args.seed or DEFAULT_SEEDS)))
    queue: list[tuple[int, int, str, str, int]] = []
    sequence = 0
    for seed in seeds:
        if allowed_url(seed):
            heapq.heappush(queue, (priority_for(seed, 0), sequence, seed, "", 0))
            sequence += 1

    visited: set[str] = set()
    pages: list[Page] = []

    while queue and len(pages) < args.max_pages:
        _, _, url, discovered_from, depth = heapq.heappop(queue)
        canonical = canonicalize_url(url)
        if canonical in visited:
            continue
        visited.add(canonical)

        page, links = fetch_page(
            session=session,
            robots=robots,
            url=canonical,
            discovered_from=discovered_from,
            depth=depth,
            timeout=args.timeout,
        )
        classify(page)
        assign_identity(page, url_to_id, name_to_id)
        pages.append(page)

        print(
            f"[{len(pages):03d}/{args.max_pages}] "
            f"{page.classification:28s} "
            f"{page.status_code:3d} {page.canonical_url}"
        )

        if depth < args.max_depth and not page.error:
            for link in links:
                if link in visited or not allowed_url(link):
                    continue
                heapq.heappush(
                    queue,
                    (
                        priority_for(link, depth + 1),
                        sequence,
                        link,
                        page.canonical_url,
                        depth + 1,
                    ),
                )
                sequence += 1

        if args.delay:
            time.sleep(args.delay)

    parent_link(pages)

    llm = LocalLLM(session, args.llm_endpoint, args.timeout)
    llm_available = args.use_llm != "no" and llm.available()
    if args.use_llm == "yes" and not llm_available:
        raise RuntimeError("LM Studio was required but is not available.")

    ambiguous = [
        page
        for page in pages
        if page.classification == "MANUAL_REVIEW"
        or (page.confidence < 0.80 and page.classification != "NON_CATALOGUE")
    ][: args.llm_max]

    if llm_available:
        print(f"LM Studio detected: {llm.model}. Reviewing {len(ambiguous)} ambiguous pages.")
        for index, page in enumerate(ambiguous, start=1):
            result = llm.classify(page)
            if not result:
                continue
            page.llm_used = True
            page.llm_classification = str(result.get("classification", ""))
            try:
                page.llm_confidence = float(result.get("confidence", 0))
            except (TypeError, ValueError):
                page.llm_confidence = 0.0
            page.llm_reason = normalize_space(result.get("reason", ""))

            if (
                page.llm_confidence >= 0.85
                and page.llm_classification != page.classification
                and INVALID_LOGO_PATH not in page.canonical_url.casefold()
            ):
                page.reasons.append(
                    f"LLM_SUGGESTS_{page.llm_classification}"
                )
                page.classification = "MANUAL_REVIEW"
                page.confidence = min(page.confidence, 0.69)

            print(f"  LLM {index}/{len(ambiguous)}: {page.canonical_url}")

    page_rows = [asdict(page) for page in sorted(pages, key=lambda item: item.canonical_url)]

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
        "parent_hint",
        "status_hint",
        "status_code",
        "content_type",
        "published_date_signal",
        "money_signals",
        "depth",
        "link_count",
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
        output_dir / "meity_discovered_pages_v3_4_3_0.csv",
        page_rows,
        page_fields,
    )

    groups = {
        "SCHEME_MASTER_CANDIDATE": "meity_scheme_master_candidates_v3_4_3_0.csv",
        "PROGRAMME_MASTER_CANDIDATE": "meity_programme_master_candidates_v3_4_3_0.csv",
        "CALL_INSTANCE_CANDIDATE": "meity_call_instances_v3_4_3_0.csv",
        "EVIDENCE_ONLY": "meity_evidence_only_pages_v3_4_3_0.csv",
    }

    compact_fields = [
        "candidate_id",
        "existing_master_id",
        "classification",
        "confidence",
        "title",
        "heading",
        "canonical_url",
        "discovered_from",
        "parent_hint",
        "status_hint",
        "published_date_signal",
        "money_signals",
        "reasons",
        "llm_classification",
        "llm_confidence",
        "llm_reason",
    ]

    for classification_name, filename in groups.items():
        rows = [
            asdict(page)
            for page in pages
            if page.classification == classification_name
        ]
        write_csv(output_dir / filename, rows, compact_fields)

    review_rows: list[dict[str, Any]] = []
    for page in pages:
        review_reasons = list(page.reasons)
        needs_review = (
            page.classification == "MANUAL_REVIEW"
            or (
                page.classification == "CALL_INSTANCE_CANDIDATE"
                and not page.parent_hint
            )
            or (
                page.classification
                in {"SCHEME_MASTER_CANDIDATE", "PROGRAMME_MASTER_CANDIDATE"}
                and page.confidence < 0.90
            )
            or page.llm_used
        )
        if needs_review:
            review_rows.append(
                {
                    "review_id": "meity_review_"
                    + hashlib.sha256(page.canonical_url.encode("utf-8")).hexdigest()[:16],
                    "candidate_id": page.candidate_id,
                    "existing_master_id": page.existing_master_id,
                    "title": page.heading or page.title,
                    "canonical_url": page.canonical_url,
                    "provisional_classification": page.classification,
                    "confidence": page.confidence,
                    "parent_hint": page.parent_hint,
                    "review_reasons": "; ".join(review_reasons),
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
        output_dir / "meity_manual_review_queue_v3_4_3_0.csv",
        review_rows,
        review_fields,
    )

    counts = Counter(page.classification for page in pages)
    existing_count = sum(bool(page.existing_master_id) for page in pages)
    errors = Counter(page.error for page in pages if page.error)

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "execution_mode": "DISCOVERY_PREVIEW_ONLY",
        "started_from_seeds": seeds,
        "completed_at": now_iso(),
        "settings": {
            "max_pages": args.max_pages,
            "max_depth": args.max_depth,
            "delay": args.delay,
            "timeout": args.timeout,
            "use_llm": args.use_llm,
            "llm_available": llm_available,
            "llm_model": llm.model if llm_available else "",
            "llm_max": args.llm_max,
        },
        "counts": {
            "pages_fetched_or_attempted": len(pages),
            "unique_urls_visited": len(visited),
            "queued_urls_remaining": len(queue),
            "existing_identity_matches": existing_count,
            "manual_review_rows": len(review_rows),
            **dict(sorted(counts.items())),
        },
        "fetch_errors": dict(sorted(errors.items())),
        "governance": {
            "calls_and_cohorts_separate_from_permanent_schemes": True,
            "official_domains_only": True,
            "application_status_not_inferred_from_scheme_page": True,
            "invalid_msh_logo_application_excluded": True,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
        "outputs": sorted(
            path.name for path in output_dir.iterdir() if path.is_file()
        ),
    }
    write_json(
        output_dir / "meity_discovery_summary_v3_4_3_0.json",
        summary,
    )

    manifest_files = sorted(path for path in output_dir.iterdir() if path.is_file())
    manifest = {
        "version": VERSION,
        "phase": PHASE,
        "generated_at": now_iso(),
        "outputs": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hash_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in manifest_files
        ],
        "publication_status": "NOT_PUBLISHED",
    }
    write_json(
        output_dir / "meity_discovery_manifest_v3_4_3_0.json",
        manifest,
    )

    postchange = {
        "version": VERSION,
        "phase": PHASE,
        "recorded_at": now_iso(),
        "frozen_file_results": {
            path.relative_to(root).as_posix(): {
                "before": prechange["frozen_files"][path.relative_to(root).as_posix()],
                "after": hash_file(path),
                "unchanged": (
                    prechange["frozen_files"][path.relative_to(root).as_posix()]
                    == hash_file(path)
                ),
            }
            for path in (active_catalogue, current_manifest, database, dashboard)
        },
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }
    write_json(
        audit_dir / "meity_v3_4_3_0_discovery_postchange_sha256.json",
        postchange,
    )

    changed = [
        name
        for name, result in postchange["frozen_file_results"].items()
        if not result["unchanged"]
    ]

    print()
    print("SSIP MeitY v3.4.3.0 department-wide discovery")
    print("--------------------------------------------------")
    print(f"Pages attempted:              {len(pages)}")
    print(f"Scheme master candidates:     {counts.get('SCHEME_MASTER_CANDIDATE', 0)}")
    print(f"Programme master candidates:  {counts.get('PROGRAMME_MASTER_CANDIDATE', 0)}")
    print(f"Call/cohort candidates:       {counts.get('CALL_INSTANCE_CANDIDATE', 0)}")
    print(f"Evidence-only pages:          {counts.get('EVIDENCE_ONLY', 0)}")
    print(f"Manual review rows:           {len(review_rows)}")
    print(f"Existing identity matches:    {existing_count}")
    print(f"LM Studio used:               {'Yes' if llm_available else 'No'}")
    print(f"Frozen files changed:         {len(changed)}")
    print("Publication performed:        No")
    print()
    print("Output directory:")
    print(output_dir)

    if changed:
        print()
        print("ERROR: Frozen files changed unexpectedly:")
        for name in changed:
            print(f"- {name}")
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDiscovery interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"DISCOVERY ERROR: {exc}", file=sys.stderr)
        raise
