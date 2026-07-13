from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import requests
    from bs4 import BeautifulSoup
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as exc:
    raise SystemExit(
        "Missing dependencies. Run the supplied dependency installer.\n"
        f"Import error: {exc}"
    )

VERSION = "3.4.3.3"
PHASE = "MeitY SASACT and GENESIS Identity, Evidence and Status Validation"
USER_AGENT = "SSIP-Governed-Evidence-Agent/3.4.3.3 (+official-source research)"

INVALID_APPLICATION_URLS = {
    "https://msh.meity.gov.in/about/applyforthelogo",
    "https://msh.meity.gov.in/registration",
    "https://msh.meity.gov.in/about/contactus",
}

SCHEME_CONFIG: dict[str, dict[str, Any]] = {
    "SASACT": {
        "candidate_id": "meity_1c5c50d5e86fc876d0b3",
        "identity_key": "MEITY_SCHEME_SASACT",
        "canonical_name": "SASACT",
        "official_full_name": (
            "Scheme for Accelerating Startups around "
            "Post-COVID Technology Opportunities (SASACT)"
        ),
        "official_page_url": "https://msh.meity.gov.in/schemes/sasact",
        "scheme_status": "HISTORICAL_INFORMATION_ONLY",
        "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
        "programme_status": "HISTORICAL_SCHEME_INFORMATION_AVAILABLE",
        "status_rationale": (
            "Official evidence confirms the SASACT scheme identity and historical "
            "implementation, but no current application window or current official "
            "application route is confirmed."
        ),
        "sources": [
            {
                "url": "https://msh.meity.gov.in/schemes/sasact",
                "role": "SCHEME_MASTER_PAGE",
                "authority": "MeitY Startup Hub",
            },
            {
                "url": "https://www.meity.gov.in/static/uploads/2024/02/32-1.pdf",
                "role": "OFFICIAL_ANNUAL_REPORT",
                "authority": "Ministry of Electronics and Information Technology",
            },
            {
                "url": "https://www.meity.gov.in/static/uploads/2024/02/35ab.pdf",
                "role": "OFFICIAL_GRANT_RELEASE_LEDGER",
                "authority": "Ministry of Electronics and Information Technology",
            },
        ],
        "identity_patterns": [
            r"\bsasact\b",
            r"accelerating\s+start[- ]?ups?\s+around\s+post[- ]?covid",
        ],
        "field_rules": [
            {
                "field_name": "official_full_name",
                "value": (
                    "Scheme for Accelerating Startups around "
                    "Post-COVID Technology Opportunities (SASACT)"
                ),
                "patterns": [
                    r"scheme\s+for\s+accelerating\s+start[- ]?ups?\s+around\s+post[- ]?covid",
                    r"sasact\s+scheme",
                ],
                "required": True,
            },
            {
                "field_name": "objective",
                "value": (
                    "Support electronics-hardware and ICT-based technology startups "
                    "developing or adapting solutions for post-COVID opportunities."
                ),
                "patterns": [
                    r"support\s+electronics\s+hardware",
                    r"post[- ]?covid\s+technology",
                    r"covid\s+based\s+innovative\s+solutions",
                ],
                "required": True,
            },
            {
                "field_name": "implementing_agency",
                "value": "MeitY Startup Hub through Software Technology Parks of India",
                "patterns": [
                    r"software\s+technology\s+parks\s+of\s+india",
                    r"meity\s+startup\s+hub",
                ],
                "required": False,
            },
            {
                "field_name": "historical_grant_evidence",
                "value": (
                    "Official grant-release evidence records implementation funding "
                    "for SASACT through STPI."
                ),
                "patterns": [
                    r"implementation\s+of\s+the\s+scheme\s+entitled\s+[\"“]?sasact",
                    r"grants[- ]?in[- ]?aid.*sasact",
                ],
                "required": True,
            },
        ],
    },
    "GENESIS": {
        "candidate_id": "meity_28ac6fb921386a6968c7",
        "identity_key": "MEITY_SCHEME_GENESIS",
        "canonical_name": "GENESIS",
        "official_full_name": "GEN-NEXT Support for Innovative Startups (GENESIS)",
        "official_page_url": "https://msh.meity.gov.in/schemes/genesis",
        "scheme_status": "CURRENT_SCHEME_INFORMATION_AVAILABLE",
        "application_status": "APPLICATION_STATUS_REQUIRES_VERIFICATION",
        "programme_status": "UMBRELLA_SCHEME_INFORMATION_AVAILABLE",
        "status_rationale": (
            "Official MeitY material confirms GENESIS as a five-year umbrella scheme. "
            "A historical/reference Implementing Agency application form exists, but "
            "no currently open application window is confirmed for public display."
        ),
        "sources": [
            {
                "url": "https://msh.meity.gov.in/schemes/genesis",
                "role": "SCHEME_MASTER_PAGE",
                "authority": "MeitY Startup Hub",
            },
            {
                "url": (
                    "https://www.meity.gov.in/offerings/schemes-and-services/details/"
                    "gen-next-support-for-innovative-startups-genesis-gN5AjNtQWa"
                ),
                "role": "MINISTRY_SCHEME_DETAIL_PAGE",
                "authority": "Ministry of Electronics and Information Technology",
            },
            {
                "url": "https://msh.meity.gov.in/assets/Brochure_GENESIS.pdf",
                "role": "OFFICIAL_SCHEME_BROCHURE",
                "authority": "MeitY Startup Hub",
            },
            {
                "url": "https://msh.meity.gov.in/assets/GENESIS_Admin%20Approval.pdf",
                "role": "ADMINISTRATIVE_APPROVAL",
                "authority": "Ministry of Electronics and Information Technology",
            },
            {
                "url": "https://www.meity.gov.in/static/uploads/2024/02/About-GENESIS_Scheme.pdf",
                "role": "OFFICIAL_SCHEME_BRIEF",
                "authority": "Ministry of Electronics and Information Technology",
            },
            {
                "url": "https://www.meity.gov.in/static/uploads/2024/02/Application-Form_GENESIS.pdf",
                "role": "REFERENCE_APPLICATION_FORM",
                "authority": "Ministry of Electronics and Information Technology",
            },
        ],
        "identity_patterns": [
            r"\bgenesis\b",
            r"gen[- ]?next\s+support\s+for\s+innovative\s+startups",
        ],
        "field_rules": [
            {
                "field_name": "official_full_name",
                "value": "GEN-NEXT Support for Innovative Startups (GENESIS)",
                "patterns": [
                    r"gen[- ]?next\s+support\s+for\s+innovative\s+startups",
                ],
                "required": True,
            },
            {
                "field_name": "scheme_type",
                "value": "Umbrella startup ecosystem scheme",
                "patterns": [
                    r"umbrella\s+scheme",
                    r"consolidation\s+and\s+strengthening",
                ],
                "required": True,
            },
            {
                "field_name": "objective",
                "value": (
                    "Discover, support, grow and accelerate technology startups, "
                    "particularly in Tier-II and Tier-III cities."
                ),
                "patterns": [
                    r"discover,\s*support,\s*grow\s+and\s+accelerate",
                    r"tier[- ]?ii\s+and\s+tier[- ]?iii",
                    r"nurture\s+and\s+support\s+startup\s+ecosystem",
                ],
                "required": True,
            },
            {
                "field_name": "total_budget",
                "value": "INR 490 crore",
                "patterns": [
                    r"(?:inr|rs\.?|₹)\s*490\s*(?:crore|cr)",
                    r"budget\s+of\s+490\s+crores",
                ],
                "required": True,
            },
            {
                "field_name": "duration",
                "value": "5 years",
                "patterns": [r"\b5\s+years\b", r"\bfive\s+years\b"],
                "required": True,
            },
            {
                "field_name": "implementing_agency",
                "value": "MeitY Startup Hub through approximately 50 Implementing Agencies",
                "patterns": [
                    r"meity\s+startup\s+hub.*implement.*approximately?\s*50",
                    r"msh.*implement.*50\s+implementing\s+agencies",
                ],
                "required": True,
            },
            {
                "field_name": "target_geography",
                "value": "Tier-II and Tier-III cities in India",
                "patterns": [
                    r"tier[- ]?ii\s+and\s+tier[- ]?iii\s+cities",
                    r"tier\s+ii\s+and\s+iii\s+geograph",
                ],
                "required": True,
            },
            {
                "field_name": "startup_eligibility",
                "value": (
                    "DPIIT-registered startup; at least 51% Indian promoter "
                    "shareholding at application; additional component-specific "
                    "selection requirements apply."
                ),
                "patterns": [
                    r"dpiit\s+registered\s+startup",
                    r"shareholding\s+by\s+indian\s+promoters.*51",
                ],
                "required": True,
            },
            {
                "field_name": "funding_support",
                "value": (
                    "Support may include early-stage funding up to INR 10 lakh, "
                    "pilot/investment support up to INR 50 lakh, and deep-tech "
                    "support up to INR 1 crore, subject to component rules."
                ),
                "patterns": [
                    r"early[- ]?stage.*10\s+lakhs?",
                    r"up\s+to\s+rs\.?\s*50\s+lakhs?",
                    r"upper\s+ceiling\s+of\s+rs\.?\s*1\s+cr",
                ],
                "required": True,
            },
        ],
    },
}


@dataclass
class SourceSnapshot:
    scheme: str
    url: str
    role: str
    authority: str
    status_code: int
    content_type: str
    extraction_method: str
    text_length: int
    content_sha256: str
    fetched_at: str
    fetch_error: str
    text: str


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_for_search(value: str) -> str:
    value = value.replace("\u00ad", "")
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return normalize_space(value)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deterministic_master_id(identity_key: str) -> str:
    return hashlib.sha256(identity_key.encode("utf-8")).hexdigest()[:20]


def build_session() -> requests.Session:
    retries = Retry(
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
            "Accept": (
                "text/html,application/xhtml+xml,application/pdf,"
                "application/json;q=0.8,*/*;q=0.5"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session


class BrowserReader:
    def __init__(self, enabled: bool, timeout_ms: int):
        self.available = False
        self.error = ""
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None

        if not enabled:
            return

        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self.available = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def read(self, url: str) -> str:
        if not self.available or self._browser is None:
            return ""

        page = self._browser.new_page(accept_downloads=False)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(self.timeout_ms, 15000),
                )
            except Exception:
                pass

            for _ in range(3):
                page.mouse.wheel(0, 1800)
                page.wait_for_timeout(300)

            return normalize_for_search(
                page.locator("body").inner_text(timeout=5000)
            )
        finally:
            page.close()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()


def html_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return normalize_for_search(main.get_text(" ", strip=True))


def pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required. Run the supplied dependency installer."
        ) from exc

    reader = PdfReader(BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return normalize_for_search(" ".join(pages))


def fetch_source(
    *,
    session: requests.Session,
    browser: BrowserReader,
    scheme: str,
    source: dict[str, str],
    timeout: int,
) -> SourceSnapshot:
    url = source["url"]
    fetched_at = now_iso()

    print(
        f"[FETCH] {scheme:7s} | {source['role']:30s} | {url}",
        flush=True,
    )

    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
        status_code = response.status_code
        content_type = (
            response.headers.get("content-type", "")
            .split(";")[0]
            .strip()
            .casefold()
        )
        content = response.content

        if status_code >= 400:
            return SourceSnapshot(
                scheme=scheme,
                url=url,
                role=source["role"],
                authority=source["authority"],
                status_code=status_code,
                content_type=content_type,
                extraction_method="NONE",
                text_length=0,
                content_sha256=sha256_bytes(content),
                fetched_at=fetched_at,
                fetch_error=f"HTTP_{status_code}",
                text="",
            )

        path = url.casefold()
        if content_type == "application/pdf" or path.endswith(".pdf"):
            extracted = pdf_text(content)
            method = "PYPDF"
        else:
            extracted = html_text(content)
            method = "STATIC_HTML"

            generic_or_empty = (
                len(extracted) < 500
                or extracted.casefold() in {"meitystartuphub", "meity startup hub"}
            )
            if generic_or_empty and browser.available:
                try:
                    rendered = browser.read(url)
                    if len(rendered) > len(extracted):
                        extracted = rendered
                        method = "PLAYWRIGHT_RENDERED_HTML"
                except Exception as exc:
                    method += f"_BROWSER_SKIPPED_{type(exc).__name__.upper()}"

        return SourceSnapshot(
            scheme=scheme,
            url=url,
            role=source["role"],
            authority=source["authority"],
            status_code=status_code,
            content_type=content_type,
            extraction_method=method,
            text_length=len(extracted),
            content_sha256=sha256_bytes(content),
            fetched_at=fetched_at,
            fetch_error="",
            text=extracted,
        )

    except Exception as exc:
        return SourceSnapshot(
            scheme=scheme,
            url=url,
            role=source["role"],
            authority=source["authority"],
            status_code=0,
            content_type="",
            extraction_method="NONE",
            text_length=0,
            content_sha256="",
            fetched_at=fetched_at,
            fetch_error=f"{type(exc).__name__}: {exc}",
            text="",
        )


def find_snippet(
    snapshots: list[SourceSnapshot],
    patterns: list[str],
    *,
    max_chars: int = 520,
) -> tuple[SourceSnapshot | None, str, str]:
    for snapshot in snapshots:
        if not snapshot.text:
            continue
        for pattern in patterns:
            match = re.search(pattern, snapshot.text, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            start = max(0, match.start() - 180)
            end = min(len(snapshot.text), match.end() + 300)
            snippet = normalize_space(snapshot.text[start:end])
            if len(snippet) > max_chars:
                snippet = snippet[: max_chars - 3].rstrip() + "..."
            return snapshot, snippet, pattern
    return None, "", ""


def source_has_pattern(
    snapshots: list[SourceSnapshot],
    pattern: str,
) -> bool:
    return any(
        snapshot.text
        and re.search(pattern, snapshot.text, re.IGNORECASE | re.DOTALL)
        for snapshot in snapshots
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def self_test() -> None:
    sasact_id = deterministic_master_id("MEITY_SCHEME_SASACT")
    genesis_id = deterministic_master_id("MEITY_SCHEME_GENESIS")

    if len(sasact_id) != 20 or len(genesis_id) != 20:
        raise AssertionError("Permanent master ID generation failed.")
    if sasact_id == genesis_id:
        raise AssertionError("Permanent master IDs collided.")

    sample = normalize_for_search(
        "GEN-NEXT Support for Innovative Startups (GENESIS) "
        "has a budget of INR 490 Cr for 5 Years."
    )
    if not re.search(r"gen[- ]?next\s+support", sample, re.I):
        raise AssertionError("Identity rule failed.")
    if not re.search(r"(?:inr|rs\.?|₹)\s*490\s*(?:crore|cr)", sample, re.I):
        raise AssertionError("Budget rule failed.")

    print("MeitY v3.4.3.3 identity/evidence self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--browser-timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--browser",
        choices=("auto", "yes", "no"),
        default="auto",
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = root_dir()
    input_dir = root / "data" / "departments" / "meity" / "v3_4_3_2"
    output_dir = root / "data" / "departments" / "meity" / "v3_4_3_3"
    audit_dir = root / "data" / "audit"
    snapshots_dir = output_dir / "source_snapshots"

    identity_input = (
        input_dir / "meity_candidate_identity_register_v3_4_3_2.csv"
    )
    triage_validation = input_dir / "meity_triage_validation_v3_4_3_2.json"

    required_inputs = [identity_input, triage_validation]
    missing = [str(path) for path in required_inputs if not path.exists()]
    if missing:
        raise RuntimeError(
            "Required v3.4.3.2 inputs are missing:\n" + "\n".join(missing)
        )

    input_rows = read_csv(identity_input)
    target_rows = {
        normalize_space(row.get("canonical_name", "")).upper(): row
        for row in input_rows
        if normalize_space(row.get("canonical_name", "")).upper()
        in SCHEME_CONFIG
    }

    if set(target_rows) != set(SCHEME_CONFIG):
        raise RuntimeError(
            "Expected SASACT and GENESIS in the v3.4.3.2 identity register."
        )

    for scheme, row in target_rows.items():
        if normalize_space(row.get("requires_identity_validation", "")).casefold() != "true":
            raise RuntimeError(
                f"{scheme} is not marked as requiring identity validation."
            )
        if normalize_space(row.get("master_id", "")):
            raise RuntimeError(
                f"{scheme} already has a permanent master ID unexpectedly."
            )

    frozen_paths = [
        root
        / "data"
        / "catalogue_preview"
        / "v3_3_2"
        / "catalogue_preview_v3_3_2.csv",
        root / "data" / "publication" / "current_manifest.json",
        root / "database" / "ssip_staging_v1.db",
        root / "apps" / "public_dashboard_app_v2_9.py",
        identity_input,
        triage_validation,
    ]
    pre_hashes = {
        path.relative_to(root).as_posix(): hash_file(path)
        for path in frozen_paths
    }
    write_json(
        audit_dir / "meity_v3_4_3_3_prechange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "frozen_files": pre_hashes,
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    browser = BrowserReader(
        enabled=args.browser != "no",
        timeout_ms=args.browser_timeout_ms,
    )
    if args.browser == "yes" and not browser.available:
        raise RuntimeError(
            "Playwright browser rendering was required but unavailable: "
            + browser.error
        )

    snapshots: list[SourceSnapshot] = []
    try:
        for scheme, config in SCHEME_CONFIG.items():
            for source in config["sources"]:
                snapshot = fetch_source(
                    session=session,
                    browser=browser,
                    scheme=scheme,
                    source=source,
                    timeout=args.timeout,
                )
                snapshots.append(snapshot)

                snapshot_filename = (
                    f"{scheme.casefold()}_"
                    f"{source['role'].casefold()}_"
                    f"{hashlib.sha256(source['url'].encode('utf-8')).hexdigest()[:10]}.txt"
                )
                (snapshots_dir / snapshot_filename).write_text(
                    snapshot.text,
                    encoding="utf-8",
                    newline="\n",
                )
    finally:
        browser.close()

    identity_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    application_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []

    for snapshot in snapshots:
        source_rows.append(
            {
                key: value
                for key, value in asdict(snapshot).items()
                if key != "text"
            }
        )

    identity_pass_count = 0
    required_evidence_missing = 0

    for scheme, config in SCHEME_CONFIG.items():
        scheme_snapshots = [
            snapshot for snapshot in snapshots if snapshot.scheme == scheme
        ]
        successful = [
            snapshot
            for snapshot in scheme_snapshots
            if not snapshot.fetch_error and snapshot.text_length > 0
        ]

        identity_pattern_results = {
            pattern: source_has_pattern(scheme_snapshots, pattern)
            for pattern in config["identity_patterns"]
        }
        identity_confirmed = (
            all(identity_pattern_results.values())
            and len(successful) >= 2
        )

        master_id = (
            deterministic_master_id(config["identity_key"])
            if identity_confirmed
            else ""
        )
        if identity_confirmed:
            identity_pass_count += 1

        identity_evidence_urls: list[str] = []
        for pattern in config["identity_patterns"]:
            snapshot, snippet, matched_pattern = find_snippet(
                scheme_snapshots,
                [pattern],
            )
            if snapshot is None:
                continue
            identity_evidence_urls.append(snapshot.url)
            evidence_rows.append(
                {
                    "master_id": master_id,
                    "candidate_id": config["candidate_id"],
                    "canonical_name": config["canonical_name"],
                    "field_name": "identity",
                    "field_value": config["official_full_name"],
                    "evidence_url": snapshot.url,
                    "source_role": snapshot.role,
                    "authority": snapshot.authority,
                    "evidence_snippet": snippet,
                    "matched_pattern": matched_pattern,
                    "content_sha256": snapshot.content_sha256,
                    "extraction_method": snapshot.extraction_method,
                    "confidence": "0.98",
                    "evidence_status": "VERIFIED",
                }
            )

        field_verified = 0
        field_missing: list[str] = []
        for rule in config["field_rules"]:
            snapshot, snippet, matched_pattern = find_snippet(
                scheme_snapshots,
                rule["patterns"],
            )
            if snapshot is None:
                field_missing.append(rule["field_name"])
                if rule["required"]:
                    required_evidence_missing += 1
                review_rows.append(
                    {
                        "review_id": (
                            "meity_v3433_"
                            + hashlib.sha256(
                                f"{scheme}|{rule['field_name']}".encode("utf-8")
                            ).hexdigest()[:16]
                        ),
                        "master_id": master_id,
                        "candidate_id": config["candidate_id"],
                        "canonical_name": config["canonical_name"],
                        "review_type": "FIELD_EVIDENCE_GAP",
                        "field_name": rule["field_name"],
                        "review_reason": (
                            "Required official evidence pattern was not found."
                            if rule["required"]
                            else "Optional field evidence was not found."
                        ),
                        "recommended_action": "CURATED_OFFICIAL_SOURCE_REVIEW",
                        "review_status": "OPEN",
                        "publication_status": "NOT_PUBLISHED",
                    }
                )
                continue

            field_verified += 1
            evidence_rows.append(
                {
                    "master_id": master_id,
                    "candidate_id": config["candidate_id"],
                    "canonical_name": config["canonical_name"],
                    "field_name": rule["field_name"],
                    "field_value": rule["value"],
                    "evidence_url": snapshot.url,
                    "source_role": snapshot.role,
                    "authority": snapshot.authority,
                    "evidence_snippet": snippet,
                    "matched_pattern": matched_pattern,
                    "content_sha256": snapshot.content_sha256,
                    "extraction_method": snapshot.extraction_method,
                    "confidence": "0.95" if rule["required"] else "0.88",
                    "evidence_status": "VERIFIED",
                }
            )

        identity_rows.append(
            {
                "master_id": master_id,
                "candidate_id": config["candidate_id"],
                "canonical_name": config["canonical_name"],
                "official_full_name": config["official_full_name"],
                "official_page_url": config["official_page_url"],
                "identity_decision": (
                    "VERIFIED_PERMANENT_SCHEME_IDENTITY"
                    if identity_confirmed
                    else "IDENTITY_VALIDATION_FAILED"
                ),
                "identity_confirmed": str(identity_confirmed).casefold(),
                "deterministic_id_rule": config["identity_key"],
                "official_sources_successful": len(successful),
                "identity_evidence_urls": "; ".join(
                    dict.fromkeys(identity_evidence_urls)
                ),
                "programme_status": config["programme_status"],
                "scheme_status": config["scheme_status"],
                "verified_field_count": field_verified,
                "missing_field_names": "; ".join(field_missing),
                "publication_status": "NOT_PUBLISHED",
            }
        )

        reference_application_form = (
            "https://www.meity.gov.in/static/uploads/2024/02/Application-Form_GENESIS.pdf"
            if scheme == "GENESIS"
            else ""
        )
        application_rows.append(
            {
                "master_id": master_id,
                "candidate_id": config["candidate_id"],
                "canonical_name": config["canonical_name"],
                "scheme_status": config["scheme_status"],
                "application_status": config["application_status"],
                "application_url": "",
                "application_route_status": "NO_PUBLIC_APPLY_ACTION",
                "reference_application_form_url": reference_application_form,
                "reference_form_role": (
                    "HISTORICAL_OR_REFERENCE_IMPLEMENTING_AGENCY_FORM"
                    if reference_application_form
                    else ""
                ),
                "current_call_id": "",
                "deadline": "",
                "status_rationale": config["status_rationale"],
                "invalid_application_urls_rejected": "; ".join(
                    sorted(INVALID_APPLICATION_URLS)
                ),
                "as_of_date": date.today().isoformat(),
                "publication_status": "NOT_PUBLISHED",
            }
        )

        if scheme == "SASACT":
            review_rows.append(
                {
                    "review_id": "meity_v3433_sasact_current_status",
                    "master_id": master_id,
                    "candidate_id": config["candidate_id"],
                    "canonical_name": config["canonical_name"],
                    "review_type": "HISTORICAL_STATUS_CONFIRMATION",
                    "field_name": "scheme_status",
                    "review_reason": (
                        "Identity is confirmed, but a current official application "
                        "route and current operational window are not present in the "
                        "validated official evidence."
                    ),
                    "recommended_action": (
                        "RETAIN_AS_HISTORICAL_SCHEME_WITHOUT_APPLY_ACTION"
                    ),
                    "review_status": "GOVERNED_OMISSION",
                    "publication_status": "NOT_PUBLISHED",
                }
            )
        else:
            review_rows.append(
                {
                    "review_id": "meity_v3433_genesis_application_status",
                    "master_id": master_id,
                    "candidate_id": config["candidate_id"],
                    "canonical_name": config["canonical_name"],
                    "review_type": "CURRENT_APPLICATION_ROUTE",
                    "field_name": "application_url",
                    "review_reason": (
                        "The official reference application form does not prove that "
                        "an application window is currently open."
                    ),
                    "recommended_action": (
                        "PUBLISH_SCHEME_INFORMATION_WITHOUT_APPLY_ACTION"
                    ),
                    "review_status": "GOVERNED_OMISSION",
                    "publication_status": "NOT_PUBLISHED",
                }
            )
            review_rows.append(
                {
                    "review_id": "meity_v3433_genesis_exact_end_date",
                    "master_id": master_id,
                    "candidate_id": config["candidate_id"],
                    "canonical_name": config["canonical_name"],
                    "review_type": "SCHEME_DURATION_BOUNDARY",
                    "field_name": "scheme_end_date",
                    "review_reason": (
                        "Official material states a five-year duration, but this phase "
                        "does not infer an exact end date without a verified start-date "
                        "and administrative-approval date extraction."
                    ),
                    "recommended_action": "LEAVE_EXACT_END_DATE_BLANK",
                    "review_status": "GOVERNED_OMISSION",
                    "publication_status": "NOT_PUBLISHED",
                }
            )

    fields_identity = [
        "master_id",
        "candidate_id",
        "canonical_name",
        "official_full_name",
        "official_page_url",
        "identity_decision",
        "identity_confirmed",
        "deterministic_id_rule",
        "official_sources_successful",
        "identity_evidence_urls",
        "programme_status",
        "scheme_status",
        "verified_field_count",
        "missing_field_names",
        "publication_status",
    ]
    fields_evidence = [
        "master_id",
        "candidate_id",
        "canonical_name",
        "field_name",
        "field_value",
        "evidence_url",
        "source_role",
        "authority",
        "evidence_snippet",
        "matched_pattern",
        "content_sha256",
        "extraction_method",
        "confidence",
        "evidence_status",
    ]
    fields_application = [
        "master_id",
        "candidate_id",
        "canonical_name",
        "scheme_status",
        "application_status",
        "application_url",
        "application_route_status",
        "reference_application_form_url",
        "reference_form_role",
        "current_call_id",
        "deadline",
        "status_rationale",
        "invalid_application_urls_rejected",
        "as_of_date",
        "publication_status",
    ]
    fields_review = [
        "review_id",
        "master_id",
        "candidate_id",
        "canonical_name",
        "review_type",
        "field_name",
        "review_reason",
        "recommended_action",
        "review_status",
        "publication_status",
    ]
    fields_source = [
        "scheme",
        "url",
        "role",
        "authority",
        "status_code",
        "content_type",
        "extraction_method",
        "text_length",
        "content_sha256",
        "fetched_at",
        "fetch_error",
    ]

    write_csv(
        output_dir / "meity_new_scheme_identity_validation_v3_4_3_3.csv",
        identity_rows,
        fields_identity,
    )
    write_csv(
        output_dir / "meity_new_scheme_field_evidence_v3_4_3_3.csv",
        evidence_rows,
        fields_evidence,
    )
    write_csv(
        output_dir / "meity_new_scheme_application_status_v3_4_3_3.csv",
        application_rows,
        fields_application,
    )
    write_csv(
        output_dir / "meity_new_scheme_review_queue_v3_4_3_3.csv",
        review_rows,
        fields_review,
    )
    write_csv(
        output_dir / "meity_official_source_fetch_log_v3_4_3_3.csv",
        source_rows,
        fields_source,
    )

    permanent_ids = [
        row["master_id"] for row in identity_rows if row["master_id"]
    ]
    duplicate_ids = len(permanent_ids) != len(set(permanent_ids))
    application_urls_blank = all(
        not normalize_space(row["application_url"])
        for row in application_rows
    )
    invalid_exposed = any(
        normalize_space(row["application_url"]) in INVALID_APPLICATION_URLS
        for row in application_rows
    )

    post_hashes = {
        path.relative_to(root).as_posix(): hash_file(path)
        for path in frozen_paths
    }
    frozen_unchanged = {
        name: pre_hashes[name] == post_hashes[name]
        for name in pre_hashes
    }

    checks = [
        {
            "name": "two_target_candidates_loaded",
            "passed": len(target_rows) == 2,
            "details": f"actual={len(target_rows)}",
        },
        {
            "name": "two_identities_confirmed",
            "passed": identity_pass_count == 2,
            "details": f"actual={identity_pass_count}",
        },
        {
            "name": "two_deterministic_master_ids_assigned",
            "passed": len(permanent_ids) == 2 and not duplicate_ids,
            "details": f"ids={permanent_ids}",
        },
        {
            "name": "minimum_field_evidence",
            "passed": len(evidence_rows) >= 12,
            "details": f"actual={len(evidence_rows)} minimum=12",
        },
        {
            "name": "required_evidence_complete",
            "passed": required_evidence_missing == 0,
            "details": f"missing_required={required_evidence_missing}",
        },
        {
            "name": "no_public_application_urls",
            "passed": application_urls_blank,
            "details": "Both schemes must remain without an Apply action.",
        },
        {
            "name": "invalid_application_urls_rejected",
            "passed": not invalid_exposed,
            "details": "Logo, registration and contact pages must not be exposed.",
        },
        {
            "name": "frozen_files_unchanged",
            "passed": all(frozen_unchanged.values()),
            "details": json.dumps(frozen_unchanged, sort_keys=True),
        },
        {
            "name": "publication_not_performed",
            "passed": True,
            "details": "This phase is validation-only.",
        },
    ]

    failed = [check for check in checks if not check["passed"]]
    validation_status = "PASS" if not failed else "FAIL"

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "validation_status": validation_status,
        "completed_at": now_iso(),
        "as_of_date": date.today().isoformat(),
        "counts": {
            "target_candidates": len(target_rows),
            "identity_confirmed": identity_pass_count,
            "permanent_master_ids_assigned": len(permanent_ids),
            "official_sources_configured": sum(
                len(config["sources"]) for config in SCHEME_CONFIG.values()
            ),
            "official_sources_successful": sum(
                not snapshot.fetch_error and snapshot.text_length > 0
                for snapshot in snapshots
            ),
            "field_evidence_rows": len(evidence_rows),
            "review_queue_rows": len(review_rows),
            "required_evidence_missing": required_evidence_missing,
            "public_application_urls": sum(
                bool(normalize_space(row["application_url"]))
                for row in application_rows
            ),
        },
        "scheme_results": identity_rows,
        "application_results": application_rows,
        "checks": checks,
        "failed_checks": [check["name"] for check in failed],
        "browser_available": browser.available,
        "browser_error": browser.error,
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }
    write_json(
        output_dir / "meity_new_scheme_validation_summary_v3_4_3_3.json",
        summary,
    )
    write_json(
        output_dir / "meity_new_scheme_validation_v3_4_3_3.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "validation_status": validation_status,
            "checks": checks,
            "failed_checks": [check["name"] for check in failed],
            "pre_hashes": pre_hashes,
            "post_hashes": post_hashes,
            "frozen_unchanged": frozen_unchanged,
        },
    )

    generated = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
    )
    write_json(
        output_dir / "meity_new_scheme_manifest_v3_4_3_3.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "generated_at": now_iso(),
            "validation_status": validation_status,
            "outputs": [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hash_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in generated
            ],
            "publication_status": "NOT_PUBLISHED",
        },
    )
    write_json(
        audit_dir / "meity_v3_4_3_3_postchange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "validation_status": validation_status,
            "frozen_file_results": {
                name: {
                    "before": pre_hashes[name],
                    "after": post_hashes[name],
                    "unchanged": frozen_unchanged[name],
                }
                for name in pre_hashes
            },
            "publication_performed": False,
            "database_modified": False,
            "dashboard_modified": False,
        },
    )

    print()
    print("SSIP MeitY v3.4.3.3 identity and evidence validation")
    print("--------------------------------------------------------")
    print(f"Validation status:                {validation_status}")
    print(f"Target candidates:                {len(target_rows)}")
    print(f"Identities confirmed:             {identity_pass_count}")
    print(f"Permanent master IDs assigned:    {len(permanent_ids)}")
    print(f"Official sources successful:      {summary['counts']['official_sources_successful']}")
    print(f"Field evidence rows:              {len(evidence_rows)}")
    print(f"Required evidence missing:        {required_evidence_missing}")
    print(f"Review queue rows:                {len(review_rows)}")
    print("Public application URLs:          0")
    print(f"Frozen files changed:             {sum(not value for value in frozen_unchanged.values())}")
    print("Publication performed:            No")
    print()
    for row in identity_rows:
        print(
            f"{row['canonical_name']}: "
            f"{row['identity_decision']} | "
            f"master_id={row['master_id']} | "
            f"status={row['scheme_status']}"
        )
    print()
    print("Output directory:")
    print(output_dir)

    if failed:
        print()
        print("Failed checks:")
        for check in failed:
            print(f"- {check['name']}: {check['details']}")

    return 0 if validation_status == "PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nValidation interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        raise
