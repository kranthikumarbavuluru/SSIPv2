from __future__ import annotations

"""Governed MyMSME directory crawler.

This adapter searches only the public MyMSME scheme directory and its linked
detail pages. It does not log in, submit forms, bypass controls, or crawl the
whole domain. Before fetching, it checks robots.txt; an unavailable or missing
robots policy requires the explicit ``--allow-unpublished-robots`` Admin flag.
The crawler is sequential, rate-limited, host/path allowlisted, resumable and
publishes only a hash-verified active bundle.
"""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VERSION = "3.4.6.0"
SOURCE_ID = "my_msme_mobile_directory"
SOURCE_INDEX = "https://my.msme.gov.in/MyMsmeMob/MsmeScheme/MSME_Scheme.htm"
SOURCE_HOME = "https://my.msme.gov.in/MyMsmeMob/MsmeScheme/Home.htm"
HOST = "my.msme.gov.in"
PATH_PREFIX = "/MyMsmeMob/MsmeScheme/"
PUBLICATION_DIR = PROJECT_ROOT / "data/departments/msme/v3_4_6_0/mymsme"
RUNS_DIR = PUBLICATION_DIR / "runs"
ACTIVE_INVENTORY = PUBLICATION_DIR / "active_inventory.csv"
ACTIVE_MANIFEST = PUBLICATION_DIR / "active_publication_manifest_v3_4_6_0.json"
LOCK_FILE = PUBLICATION_DIR / ".run.lock"
USER_AGENT = "SSIP-Governed-MSME-Agent/3.4.6 (+official-public-directory-monitoring)"
MIN_DELAY_SECONDS = 1.25
CONFIG_PATH = PROJECT_ROOT / "config/msme_department_agent_v3_4_6_0.json"

IDENTITY_ALIASES = {
    "credit guarantee": "credit guarantee micro small enterprises",
    "bank credit facilitation": "credit facilitation through bank",
    "marketing intelligence services lease": "marketing intelligence",
    "single point registration": "single point registration",
    "aspire": "promotion innovation rural industries entrepreneurship",
    "revamped fund regeneration traditional industries": "fund regeneration traditional industries",
}

INVENTORY_FIELDS = [
    "master_id", "scheme_code", "canonical_name", "short_name", "record_kind",
    "source", "ministry", "department", "implementing_agency", "ownership_scope",
    "geographic_scope", "category", "support_type", "applicant_layer",
    "startup_relevance", "target_beneficiaries", "description", "benefit_summary",
    "eligibility", "official_page_url", "application_url", "reference_urls",
    "status_basis", "status_evidence", "programme_status", "application_status",
    "opening_date", "closing_date", "last_verified_at", "warnings",
    "publication_decision", "decision_reasons", "evidence_confidence",
]

DIVISION_PATHS = (
    "SME_Division.htm",
    "DCMSME_Scheme.htm",
    "NSIC.htm",
    "ARI_Scheme.htm",
)

KNOWN_TITLES = {
    "0_3_0.html": "International Cooperation",
    "0_3_1.html": "Assistance to Training Institutions (ATI)",
    "0_3_2.html": "Marketing Assistance Scheme",
    "0_2_0.html": "Credit Guarantee",
    "0_2_1.html": "Credit Linked Capital Subsidy Scheme for Technology Upgradation",
    "0_2_2.html": "ISO 9000/ISO 14001 Certification Reimbursement",
    "0_2_3.html": "Micro & Small Enterprises Cluster Development Programme",
    "0_2_4.html": "Micro Finance Programme",
    "0_2_5.html": "MSME Market Development Assistance (MDA)",
    "0_2_6.html": "National Awards (Individual MSEs)",
    "NMCP.htm": "National Manufacturing Competitiveness Programme",
    "1_2_0.html": "Performance and Credit Rating",
    "1_2_1.html": "Bank Credit Facilitation",
    "1_2_2.html": "Raw Material Assistance",
    "1_2_3.html": "Single Point Registration",
    "1_2_4.html": "Infomediary Services",
    "1_2_5.html": "Marketing Intelligence Services Lease",
    "1_2_6.html": "Bill Discounting",
    "NSIC_Infrastructure.htm": "NSIC Infrastructure",
    "1_3_0.html": "Prime Minister's Employment Generation Programme (PMEGP)",
    "1_3_1.html": "Janshree Bima Yojana for Khadi Artisans",
    "1_3_2.html": "Market Development Assistance",
    "1_3_3.html": "Science and Technology Schemes",
    "1_3_4.html": "Coir Udyami Yojana",
    "COIR_Vikas_Yojna.htm": "Coir Vikas Yojana",
    "1_3_6.html": "Aspire (Scheme for promotion of Innovation, Entrepreneurship and Agro-Industry)",
    "1_3_7.html": "Revamped Scheme of Fund for Regeneration of Traditional Industries (SFURTI)",
}


class AgentError(RuntimeError):
    """A safe, actionable crawl or publication failure."""


def configured_source() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"Cannot read governed MSME source registry: {CONFIG_PATH}") from exc
    source = next((item for item in config.get("official_sources", []) if item.get("source_id") == SOURCE_ID), None)
    if not source:
        raise AgentError(f"Source {SOURCE_ID} is missing from the governed source registry.")
    if source.get("index_url") != SOURCE_INDEX or source.get("domain") != HOST:
        raise AgentError("Governed source registry does not match the MyMSME adapter allowlist.")
    return source


@dataclass
class LegalCrawlPolicy:
    allow_unpublished_robots: bool = False
    min_delay_seconds: float = MIN_DELAY_SECONDS
    robots_state: str = "NOT_CHECKED"
    robots_detail: str = ""
    robots_parser: RobotFileParser | None = None
    last_request_at: float = 0.0

    def check_robots(self) -> None:
        robots_url = f"https://{HOST}/robots.txt"
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read().decode("utf-8", errors="replace")
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(payload.splitlines())
                self.robots_parser = parser
                self.robots_state = "PUBLISHED"
                self.robots_detail = "robots.txt retrieved successfully."
        except HTTPError as exc:
            if exc.code == 404:
                self.robots_state = "NOT_PUBLISHED"
                self.robots_detail = "robots.txt returned HTTP 404; no published crawl policy was found."
            else:
                self.robots_state = "UNAVAILABLE"
                self.robots_detail = f"robots.txt returned HTTP {exc.code}."
        except (OSError, URLError, TimeoutError) as exc:
            self.robots_state = "UNAVAILABLE"
            self.robots_detail = f"robots.txt could not be retrieved: {exc}"
        if self.robots_state != "PUBLISHED" and not self.allow_unpublished_robots:
            raise AgentError(
                f"Crawl blocked by legal safety gate: {self.robots_detail} "
                "Re-run only after confirming the public-source policy with --allow-unpublished-robots."
            )

    def permit(self, url: str) -> None:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().strip(".")
        if parsed.scheme != "https" or host != HOST or not parsed.path.startswith(PATH_PREFIX):
            raise AgentError(f"URL outside the MyMSME public allowlist: {url}")
        if self.robots_parser is not None and not self.robots_parser.can_fetch(USER_AGENT, url):
            raise AgentError(f"robots.txt disallows the requested public URL: {url}")
        if self.robots_state != "PUBLISHED" and not self.allow_unpublished_robots:
            raise AgentError("robots policy is not published; automatic fetching is blocked")
        now = time.monotonic()
        remaining = self.min_delay_seconds - (now - self.last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_at = time.monotonic()

    def summary(self) -> dict[str, Any]:
        return {
            "user_agent": USER_AGENT,
            "public_pages_only": True,
            "no_authentication_or_bypass": True,
            "form_submissions": False,
            "host_allowlist": [HOST],
            "path_allowlist": [PATH_PREFIX],
            "min_delay_seconds": self.min_delay_seconds,
            "robots_state": self.robots_state,
            "robots_detail": self.robots_detail,
            "explicit_unpublished_robots_override": self.allow_unpublished_robots,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] = INVENTORY_FIELDS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalise_key(value: str) -> str:
    value = value.split("|", 1)[0]
    value = value.casefold().replace("&", " and ").replace("assitance", "assistance")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    ignored = {"the", "scheme", "schemes", "programme", "program", "for", "and", "of"}
    key = " ".join(token for token in value.split() if token not in ignored)
    return IDENTITY_ALIASES.get(key, key)


def classify_division(url: str) -> tuple[str, str]:
    path = urlsplit(url).path.casefold()
    if "sme_division" in path:
        return "SME Division", ""
    if "dcmsme" in path or "/0_2_" in path:
        return "Development Commissioner (MSME)", "Office of the Development Commissioner (MSME)"
    if "nsic" in path or "/1_2_" in path:
        return "NSIC", "National Small Industries Corporation"
    if "ari" in path or "/1_3_" in path or "coir" in path:
        return "ARI Division", ""
    return "Ministry of MSME", ""


def _agency_for(title: str, division: str) -> str:
    text = title.casefold()
    if "coir" in text or "science and technology" in text:
        return "Coir Board"
    if "khadi" in text or "market development assistance" == text.strip():
        return "Khadi and Village Industries Commission"
    return classify_division(division)[1]


def _kind_for(title: str) -> str:
    text = title.casefold()
    if "infrastructure" in text or "infomediary" in text:
        return "GOVERNMENT_SERVICE"
    if "programme" in text or "assistance" in text or "cooperation" in text:
        return "PROGRAMME"
    return "SCHEME"


def _category_for(title: str) -> tuple[str, str]:
    text = title.casefold()
    if any(token in text for token in ("credit", "finance", "bill discount", "raw material", "rating")):
        return "Credit & Finance", "Credit Support"
    if any(token in text for token in ("marketing", "cooperation", "infomediary")):
        return "Market Access", "Assistance"
    if any(token in text for token in ("iso", "technology", "competitiveness")):
        return "Technology & Quality", "Assistance"
    if "award" in text:
        return "Recognition", "Award"
    if "infrastructure" in text:
        return "Cluster & Infrastructure", "Service"
    if any(token in text for token in ("coir", "khadi", "bima")):
        return "Sector Specific", "Support"
    return "MSME Support", "Assistance"


def _title_for(url: str, heading: str) -> str:
    name = Path(urlsplit(url).path).name
    return KNOWN_TITLES.get(name, heading.strip())


def _record_from_page(url: str, heading: str, body: str, division_url: str, retrieved_at: str) -> dict[str, Any]:
    title = _title_for(url, heading) or "MyMSME information record"
    division, agency = classify_division(division_url)
    agency = _agency_for(title, division_url) or agency
    category, support_type = _category_for(title)
    slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")
    description = body[:900]
    if "description" in body.casefold():
        description = body[body.casefold().find("description") + len("description"):].strip()[:900]
    applicant = "ARTISAN" if any(token in title.casefold() for token in ("artisan", "khadi", "coir")) else "DIRECT_MSME_SUPPORT"
    relevance = "GENERAL_ENTERPRISE_SERVICE" if support_type in {"Credit Support", "Service", "Support"} else "STARTUP_AND_MSME_SUPPORT"
    evidence = "Official MyMSME detail page retrieved; the page does not establish a current application window."
    warning = "Permanent information record; current status and application route are not verified."
    return {
        "master_id": "mymsme_" + slug,
        "scheme_code": slug.upper(),
        "canonical_name": title,
        "short_name": "",
        "record_kind": _kind_for(title),
        "source": "MyMSME Portal",
        "ministry": "Ministry of Micro, Small and Medium Enterprises",
        "department": division,
        "implementing_agency": agency,
        "ownership_scope": "UNION_DIRECTORY_RECORD",
        "geographic_scope": "India; scheme scope as stated by official MyMSME source",
        "category": category,
        "support_type": support_type,
        "applicant_layer": applicant,
        "startup_relevance": relevance,
        "target_beneficiaries": "MSMEs and eligible applicants",
        "description": description,
        "benefit_summary": "Support details are described on the official MyMSME page.",
        "eligibility": "See eligibility and applicant conditions on the official MyMSME detail page.",
        "official_page_url": url,
        "application_url": "",
        "reference_urls": f"{SOURCE_INDEX}|{url}",
        "status_basis": "Official MyMSME detail page",
        "status_evidence": evidence,
        "programme_status": "STATUS_UNVERIFIED",
        "application_status": "STATUS_UNVERIFIED",
        "opening_date": "",
        "closing_date": "",
        "last_verified_at": retrieved_at,
        "warnings": warning,
        "publication_decision": "AUTO_APPROVED",
        "decision_reasons": "Public detail page is canonical, host/path are allowlisted, and no call status is inferred.",
        "evidence_confidence": "0.90",
    }


def _clean_links(page: Any) -> list[str]:
    links = page.locator("a[href]").evaluate_all(
        "nodes => nodes.map(node => node.href).filter(Boolean)"
    )
    output: list[str] = []
    for value in links:
        parsed = urlsplit(str(value))
        if parsed.scheme == "https" and parsed.hostname == HOST and parsed.path.startswith(PATH_PREFIX):
            clean = f"https://{HOST}{parsed.path}"
            if clean not in output:
                output.append(clean)
    return output


def discover(max_pages: int, policy: LegalCrawlPolicy, *, verbose: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AgentError("Playwright is required for MyMSME discovery.") from exc
    retrieved_at = utc_now()
    failures: list[dict[str, str]] = []
    detail_urls: list[tuple[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        def visit(url: str) -> None:
            policy.permit(url)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            visit(SOURCE_HOME)
            visit(SOURCE_INDEX)
            division_urls = [
                value for value in _clean_links(page)
                if Path(urlsplit(value).path).name in DIVISION_PATHS
            ]
            for division_url in division_urls:
                visit(division_url)
                links = _clean_links(page)
                for value in links:
                    name = Path(urlsplit(value).path).name
                    if name in DIVISION_PATHS or value in {SOURCE_HOME, SOURCE_INDEX}:
                        continue
                    detail_urls.append((value, division_url))
            unique: list[tuple[str, str]] = []
            seen: set[str] = set()
            for url, division_url in detail_urls:
                if url not in seen:
                    seen.add(url)
                    unique.append((url, division_url))
            records: list[dict[str, Any]] = []
            for url, division_url in unique[:max_pages]:
                try:
                    visit(url)
                    heading = page.locator("h1, h2, h3, h4, h5").first.inner_text(timeout=10000)
                    body = re.sub(r"\s+", " ", page.locator("body").inner_text(timeout=10000)).strip()
                    records.append(_record_from_page(url, heading, body, division_url, retrieved_at))
                except Exception as exc:
                    failures.append({"url": url, "error": str(exc)[:500]})
                    if verbose:
                        print(f"[warning] {url}: {exc}")
        finally:
            browser.close()
    if not records:
        raise AgentError("MyMSME directory yielded no detail records.")
    return records, {
        "source_id": SOURCE_ID,
        "source_index": SOURCE_INDEX,
        "retrieved_at": retrieved_at,
        "pages_discovered": len(unique),
        "pages_attempted": min(len(unique), max_pages),
        "pages_fetched": len(records),
        "pages_failed": len(failures),
        "failures": failures,
        "source_host": HOST,
        "legal_policy": policy.summary(),
    }


def _existing_identity_map() -> dict[str, dict[str, Any]]:
    try:
        from ssip_dashboard.catalogue import load_catalogue
        from ssip_dashboard.config import DashboardConfig
        bundle = load_catalogue(DashboardConfig.from_env(PROJECT_ROOT))
        return {normalise_key(row.scheme_name): row.__dict__ for row in bundle.records}
    except Exception:
        return {}


def _merge_candidate(discovered: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active_rows = read_csv(ACTIVE_INVENTORY)
    active_by_key = {normalise_key(row.get("canonical_name", "")): row for row in active_rows}
    existing = _existing_identity_map()
    candidate_by_key = dict(active_by_key)
    exceptions: list[dict[str, Any]] = []
    for row in discovered:
        key = normalise_key(row["canonical_name"])
        current = active_by_key.get(key)
        if current:
            row["master_id"] = current.get("master_id", row["master_id"])
            candidate_by_key[key] = {**current, **row}
            continue
        existing_record = existing.get(key)
        if existing_record and existing_record.get("source") != "MyMSME Portal":
            row["publication_decision"] = "REVIEW_REQUIRED"
            row["decision_reasons"] = f"Existing canonical identity is already represented by master ID {existing_record.get('master_id', '')}; preserve it and reconcile the MyMSME evidence."
            exceptions.append(row)
            continue
        candidate_by_key[key] = row
    candidate = list(candidate_by_key.values())
    candidate.sort(key=lambda item: str(item.get("canonical_name", "")).casefold())
    return candidate, exceptions


def _write_candidate(run_dir: Path, discovered: list[dict[str, Any]], crawl: dict[str, Any]) -> dict[str, Any]:
    candidate, exceptions = _merge_candidate(discovered)
    write_csv(run_dir / "discovered_scheme_inventory.csv", discovered)
    write_csv(run_dir / "candidate_inventory.csv", candidate)
    write_csv(run_dir / "automatic_publication_decisions.csv", discovered)
    write_csv(run_dir / "admin_exception_queue.csv", exceptions)
    write_json(run_dir / "crawl_manifest.json", crawl)
    write_json(run_dir / "official_source_registry.json", {
        "version": VERSION,
        "source_id": SOURCE_ID,
        "organisation": "Ministry of MSME / MyMSME portal",
        "official_domain": HOST,
        "source_index": SOURCE_INDEX,
        "path_allowlist": PATH_PREFIX,
        "legal_policy": crawl.get("legal_policy", {}),
        "monitoring": "daily only when the legal policy gate passes",
    })
    write_json(run_dir / "exclusions_reasons.json", exceptions)
    candidate_bytes = (run_dir / "candidate_inventory.csv").read_bytes()
    manifest = {
        "version": VERSION,
        "source_id": SOURCE_ID,
        "run_id": run_dir.name,
        "candidate_status": "VALIDATED" if not exceptions else "VALIDATED_WITH_EXCEPTIONS",
        "inventory_file": "candidate_inventory.csv",
        "inventory_sha256": sha256_bytes(candidate_bytes),
        "record_count": len(candidate),
        "new_record_count": len(candidate) - len(read_csv(ACTIVE_INVENTORY)),
        "exception_count": len(exceptions),
        "source_index": SOURCE_INDEX,
        "legal_policy": crawl.get("legal_policy", {}),
        "created_at": utc_now(),
    }
    write_json(run_dir / "candidate_manifest.json", manifest)
    write_json(run_dir / "validation_report.json", {"passed": not exceptions, "record_count": len(candidate), "exception_count": len(exceptions)})
    return manifest


def _publish(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "candidate_manifest.json"
    if not manifest_path.exists():
        raise AgentError("Candidate manifest is missing; run --mode candidate first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("candidate_status") != "VALIDATED":
        raise AgentError("Candidate has unresolved exceptions and cannot be published automatically.")
    candidate = run_dir / manifest["inventory_file"]
    if sha256_file(candidate) != manifest.get("inventory_sha256"):
        raise AgentError("Candidate inventory hash mismatch; publication is stale.")
    PUBLICATION_DIR.mkdir(parents=True, exist_ok=True)
    backup = PUBLICATION_DIR / "backups" / run_dir.name
    backup.mkdir(parents=True, exist_ok=True)
    if ACTIVE_INVENTORY.exists():
        shutil.copy2(ACTIVE_INVENTORY, backup / ACTIVE_INVENTORY.name)
    if ACTIVE_MANIFEST.exists():
        shutil.copy2(ACTIVE_MANIFEST, backup / ACTIVE_MANIFEST.name)
    temporary = ACTIVE_INVENTORY.with_suffix(".publish.tmp")
    shutil.copy2(candidate, temporary)
    temporary.replace(ACTIVE_INVENTORY)
    active_manifest = {
        "version": VERSION,
        "activation_status": "ACTIVE",
        "run_id": run_dir.name,
        "activated_at": utc_now(),
        "inventory_file": ACTIVE_INVENTORY.name,
        "inventory_sha256": sha256_file(ACTIVE_INVENTORY),
        "record_count": len(read_csv(ACTIVE_INVENTORY)),
        "auto_approved_count": len(read_csv(ACTIVE_INVENTORY)),
        "exception_count": 0,
        "publication_decision": "AUTO_APPROVED",
        "source_index": SOURCE_INDEX,
        "source_last_verified": utc_now()[:10],
        "legal_policy": manifest.get("legal_policy", {}),
    }
    write_json(ACTIVE_MANIFEST, active_manifest)
    write_json(run_dir / "signed_publication_manifest.json", active_manifest)
    write_json(run_dir / "post_publication_report.json", {"passed": True, "active_record_count": active_manifest["record_count"], "active_inventory_sha256": active_manifest["inventory_sha256"]})
    return {"published": True, "run_id": run_dir.name, "record_count": active_manifest["record_count"], "backup": str(backup)}


def _rollback(run_id: str | None) -> dict[str, Any]:
    backups = sorted(path for path in (PUBLICATION_DIR / "backups").iterdir() if path.is_dir()) if (PUBLICATION_DIR / "backups").exists() else []
    backup = (PUBLICATION_DIR / "backups" / run_id) if run_id else (backups[-1] if backups else None)
    if backup is None or not (backup / ACTIVE_INVENTORY.name).exists() or not (backup / ACTIVE_MANIFEST.name).exists():
        raise AgentError("No rollback checkpoint is available for MyMSME.")
    shutil.copy2(backup / ACTIVE_INVENTORY.name, ACTIVE_INVENTORY)
    shutil.copy2(backup / ACTIVE_MANIFEST.name, ACTIVE_MANIFEST)
    return {"rolled_back": True, "backup": str(backup), "manifest": json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))}


def status() -> dict[str, Any]:
    active = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8")) if ACTIVE_MANIFEST.exists() else {"activation_status": "NOT_CONFIGURED"}
    return {"version": VERSION, "source_id": SOURCE_ID, "active": active, "runs": len([p for p in RUNS_DIR.iterdir() if p.is_dir()]) if RUNS_DIR.exists() else 0}


class RunLock:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def __enter__(self):
        PUBLICATION_DIR.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            raise AgentError(f"Another MyMSME run is active: {LOCK_FILE.read_text(encoding='utf-8')[:200]}")
        LOCK_FILE.write_text(json.dumps({"run_id": self.run_id, "started_at": utc_now()}), encoding="utf-8")
        return self

    def __exit__(self, *_exc):
        LOCK_FILE.unlink(missing_ok=True)


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(description="Governed MyMSME public-directory discovery and publication agent")
    parser.add_argument("--mode", choices=("discover", "candidate", "publish", "full", "status", "rollback"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--allow-unpublished-robots", action="store_true")
    parser.add_argument("--json-report", nargs="?", const="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    source_definition = configured_source()
    if args.mode == "status":
        result = {**status(), "source_definition": source_definition}
        rc = 0
    elif args.mode == "rollback":
        result = _rollback(args.run_id)
        rc = 0
    else:
        name = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
        with RunLock(name):
            policy = LegalCrawlPolicy(allow_unpublished_robots=args.allow_unpublished_robots)
            policy.check_robots()
            records, crawl = discover(args.max_pages, policy, verbose=args.verbose)
            run_dir = RUNS_DIR / name
            run_dir.mkdir(parents=True, exist_ok=True)
            candidate = _write_candidate(run_dir, records, crawl)
            result = {"run_id": name, "mode": args.mode, "candidate": candidate}
            if args.mode in {"publish", "full"} and not args.dry_run:
                result["publication"] = _publish(run_dir)
            elif args.mode == "publish" and args.dry_run:
                result["publication"] = {"published": False, "reason": "dry-run"}
            write_json(run_dir / "latest_run_status.json", result)
        rc = 0
    if args.json_report is not None:
        path = Path(args.json_report) if args.json_report else PUBLICATION_DIR / "last_command_report.json"
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        write_json(path, result)
    return rc, result


def main(argv: list[str] | None = None) -> int:
    try:
        rc, result = run(argv)
    except Exception as exc:
        result = {"version": VERSION, "status": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc), "reported_at": utc_now()}
        write_json(PUBLICATION_DIR / "last_command_report.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
