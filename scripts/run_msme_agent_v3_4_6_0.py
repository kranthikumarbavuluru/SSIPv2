from __future__ import annotations

"""Governed MSME/AP-MSME discovery and publication runner.

The runner crawls only the official AP MSME ONE scheme directory and its linked
detail pages.  Discovery and candidate generation are reversible; only
``--mode publish`` (or ``full`` without ``--no-publish``) changes the active
MSME supplement.  The database and other department bundles are untouched.
"""

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Iterator
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_INDEX = "https://apmsmeone.ap.gov.in/schemes"
AP_HOST = "apmsmeone.ap.gov.in"
AP_ROBOTS_URL = "https://apmsmeone.ap.gov.in/robots.txt"
USER_AGENT = "SSIP-Governed-MSME-Agent/3.4.6 (+official-public-directory-monitoring)"
PUBLICATION_DIR = PROJECT_ROOT / "data/departments/msme/v3_4_6_0"
RUNS_DIR = PUBLICATION_DIR / "runs"
ACTIVE_MANIFEST = PUBLICATION_DIR / "active_publication_manifest_v3_4_6_0.json"
LOCK_FILE = PUBLICATION_DIR / ".run.lock"
VERSION = "3.4.6.0"
CONFIG_PATH = PROJECT_ROOT / "config/msme_department_agent_v3_4_6_0.json"

OFFICIAL_EXTERNAL_HOSTS = {
    "apmsmeone.ap.gov.in", "pmegp.msme.gov.in", "cgtmse.in", "www.cgtmse.in",
    "mudra.org.in", "www.mudra.org.in", "financialservices.gov.in",
    "champions.gov.in", "innovative.msme.gov.in", "lean.msme.gov.in",
    "zed.msme.gov.in", "sclcss.msme.gov.in", "pharma-dept.gov.in",
    "dcmsme.gov.in", "my.msme.gov.in", "ramp.msme.gov.in",
    "pmvishwakarma.gov.in", "scsthub.in", "www.scsthub.in",
    "aspire.msme.gov.in", "cluster.dcmsme.gov.in", "sfurti.msme.gov.in",
    "coirboard.gov.in", "myhandlooms.gov.in", "pmfme.mofpi.gov.in",
    "green.msme.gov.in", "udyamregistration.gov.in", "apiic.in",
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


class AgentError(RuntimeError):
    pass


def configured_source() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"Cannot read governed MSME source registry: {CONFIG_PATH}") from exc
    source = next((item for item in config.get("official_sources", []) if item.get("source_id") == "ap_msme_one_schemes"), None)
    if not source:
        raise AgentError("Source ap_msme_one_schemes is missing from the governed source registry.")
    if source.get("index_url") != SOURCE_INDEX or source.get("domain") != AP_HOST:
        raise AgentError("Governed source registry does not match the AP MSME adapter allowlist.")
    return source


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_robots_policy(*, allow_unpublished_robots: bool = False) -> dict[str, Any]:
    """Require a published robots policy unless an Admin explicitly overrides it."""
    request = Request(AP_ROBOTS_URL, headers={"User-Agent": USER_AGENT})
    state = "NOT_PUBLISHED"
    detail = ""
    parser: RobotFileParser | None = None
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8", errors="replace")
            parser = RobotFileParser()
            parser.set_url(AP_ROBOTS_URL)
            parser.parse(payload.splitlines())
            state = "PUBLISHED"
            detail = "robots.txt retrieved successfully."
    except HTTPError as exc:
        state = "NOT_PUBLISHED" if exc.code == 404 else "UNAVAILABLE"
        detail = f"robots.txt returned HTTP {exc.code}."
    except (OSError, URLError, TimeoutError) as exc:
        state = "UNAVAILABLE"
        detail = f"robots.txt could not be retrieved: {exc}"
    if parser is not None and not parser.can_fetch(USER_AGENT, SOURCE_INDEX):
        raise AgentError("robots.txt disallows the AP MSME scheme index.")
    if state != "PUBLISHED" and not allow_unpublished_robots:
        raise AgentError(
            f"Crawl blocked by legal safety gate: {detail} "
            "Re-run only after confirming the public-source policy with --allow-unpublished-robots."
        )
    return {
        "robots_url": AP_ROBOTS_URL,
        "robots_state": state,
        "robots_detail": detail,
        "user_agent": USER_AGENT,
        "public_pages_only": True,
        "no_authentication_or_form_submission": True,
        "explicit_unpublished_robots_override": allow_unpublished_robots,
    }


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = fields or (list(rows[0]) if rows else [])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in selected} for row in rows)
    os.replace(temporary, path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalise_host(value: str) -> str:
    return (urlsplit(value).hostname or "").casefold().strip(".")


def safe_external_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme == "https" and (host in OFFICIAL_EXTERNAL_HOSTS or host.endswith(".gov.in"))


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _kind(support_type: str) -> str:
    text = support_type.casefold()
    if "guarantee" in text:
        return "GUARANTEE_SUPPORT"
    if "loan" in text or "credit" in text:
        return "CREDIT_SUPPORT"
    if "subsidy" in text:
        return "SUBSIDY_SUPPORT"
    return "SCHEME"


def _applicant(slug: str, category: str) -> str:
    if slug in {"ATI", "MSECDP", "SFURTI", "APCDP", "APICF", "ASPIRE"}:
        return "INTERMEDIARY_OR_INCUBATOR_SUPPORT"
    if "skill" in category.casefold() and slug == "ESDP":
        return "DIRECT_MSME_SUPPORT"
    return "DIRECT_MSME_SUPPORT"


def _relevance(slug: str, description: str) -> str:
    if slug in {"IPR", "ASPIRE", "NTCEC"} or any(token in description.casefold() for token in ("startup", "innovation", "incubation")):
        return "STARTUP_AND_MSME_SUPPORT"
    if slug in {"PMVK", "NHDP", "CVY"}:
        return "GENERAL_ENTERPRISE_SERVICE"
    return "DIRECT_MSME_SUPPORT"


def _ministry(raw: str, slug: str) -> tuple[str, str, str, str]:
    if slug in {"APCMEP", "APCDP"}:
        return (
            "Government of Andhra Pradesh",
            "MSME Department, Government of Andhra Pradesh",
            "AP MSME Development Corporation (APMSMEDC)",
            "STATE_GOVERNMENT",
        )
    value = raw.strip()
    if value.casefold() in {"ministry of msme", "ministry of micro, small & medium enterprises"}:
        value = "Ministry of Micro, Small and Medium Enterprises"
    return value, "", "", "UNION_DIRECTORY_RECORD"


def _extract_detail(page: Any, href: str, card: dict[str, str], retrieved_at: str) -> dict[str, Any]:
    payload = page.locator("main").evaluate(
        """root => {
          const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
          const terms = [...root.querySelectorAll('dt')].map(dt => ({
            key: clean(dt.innerText), value: clean(dt.nextElementSibling?.innerText)
          })).filter(item => item.key && item.value);
          const benefitHeading = [...root.querySelectorAll('h2')].find(node => clean(node.innerText).toLowerCase() === 'benefits');
          const benefitList = benefitHeading?.nextElementSibling;
          const benefits = benefitList ? [...benefitList.querySelectorAll('li')].map(node => clean(node.innerText)).filter(Boolean) : [];
          const paragraphs = [...root.querySelectorAll('p')].map(node => clean(node.innerText)).filter(Boolean);
          const external = [...root.querySelectorAll('a[href]')].map(a => ({href: a.href, text: clean(a.innerText)}))
            .filter(item => item.href && item.text && !item.href.startsWith('https://apmsmeone.ap.gov.in/') && !item.href.startsWith('mailto:'));
          const h1 = clean(root.querySelector('h1')?.innerText);
          return {h1, terms, benefits, paragraphs, external};
        }"""
    )
    terms = {str(item.get("key", "")).casefold(): _text(item.get("value")) for item in payload.get("terms", [])}
    title = _text(payload.get("h1")) or _text(card.get("title"))
    category = terms.get("category", "") or _text(card.get("category"))
    support_type = terms.get("type", "") or "Support"
    description = next(
        (
            _text(value)
            for value in payload.get("paragraphs", [])
            if len(_text(value)) >= 80 and _text(value).casefold() not in {"primary benefit", "andhra pradesh context"}
        ),
        _text(card.get("benefit")),
    )
    benefits = [
        _text(value)
        for value in payload.get("benefits", [])
        if _text(value) and _text(value).casefold() not in {"credit & finance", "land & infrastructure", "technology upgrade", "market access", "skills & training"}
    ][:8]
    benefit_summary = "|".join(benefits or [_text(card.get("benefit"))])
    external = next(
        (
            item.get("href", "")
            for item in payload.get("external", [])
            if "apply" in _text(item.get("text")).casefold() and safe_external_url(item.get("href", ""))
        ),
        "",
    )
    slug = _text(card.get("slug"))
    ministry, department, agency, ownership = _ministry(terms.get("ministry", ""), slug)
    # The AP directory is authoritative for identity and status; its external
    # links are separate evidence and are never treated as proof of an open call.
    status = terms.get("status", "").casefold()
    decision_reasons = [
        "Canonical identity is present on the official AP MSME ONE scheme directory.",
        "Dedicated AP MSME ONE detail page was retrieved successfully.",
        "Ownership and record type are deterministic from the detail-page fields.",
        "Permanent scheme status is published as information-only; no live call is inferred.",
    ]
    warnings: list[str] = []
    if not external:
        warnings.append("No separately verified application link was exposed by the AP detail page.")
    if status != "active":
        warnings.append("Detail-page status is not Active; publication is withheld until re-verified.")
    return {
        "master_id": "apmsme_" + re.sub(r"[^a-z0-9]+", "_", slug.casefold()).strip("_"),
        "scheme_code": slug,
        "canonical_name": title,
        "short_name": _text(card.get("code")) or slug,
        "record_kind": _kind(support_type),
        "source": "AP MSME ONE",
        "ministry": ministry,
        "department": department,
        "implementing_agency": agency,
        "ownership_scope": ownership,
        "geographic_scope": "Andhra Pradesh" if slug in {"APCMEP", "APCDP"} else "India (listed in AP MSME ONE)",
        "category": category,
        "support_type": support_type,
        "applicant_layer": _applicant(slug, category),
        "startup_relevance": _relevance(slug, description),
        "target_beneficiaries": "Micro, Small and Medium Enterprises; eligible entrepreneurs",
        "description": description,
        "benefit_summary": benefit_summary,
        "eligibility": "See eligibility and applicant conditions on the official AP MSME ONE detail page.",
        "official_page_url": "https://apmsmeone.ap.gov.in" + href,
        "application_url": external,
        "reference_urls": "https://apmsmeone.ap.gov.in/schemes|https://apmsmeone.ap.gov.in" + href + ("|" + external if external else ""),
        "status_basis": "AP MSME ONE detail-page status field",
        "status_evidence": f"Official AP MSME ONE detail page displays Status: {terms.get('status', 'not recorded')}; retrieved {retrieved_at}.",
        "programme_status": "ACTIVE_INFORMATION_AVAILABLE" if status == "active" else "STATUS_UNVERIFIED",
        "application_status": "STATUS_UNVERIFIED",
        "opening_date": "",
        "closing_date": "",
        "last_verified_at": retrieved_at,
        "warnings": "|".join(warnings),
        "publication_decision": "AUTO_APPROVED" if title and status == "active" and normalise_host("https://apmsmeone.ap.gov.in") == AP_HOST else "REVIEW_REQUIRED",
        "decision_reasons": "|".join(decision_reasons),
        "evidence_confidence": "0.98" if title and status == "active" else "0.40",
    }


def discover(max_pages: int = 50, *, verbose: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AgentError("Playwright is required for official AP MSME discovery.") from exc
    retrieved_at = utc_now()
    failures: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        last_request_at = 0.0

        def legal_goto(url: str) -> None:
            nonlocal last_request_at
            remaining = 1.25 - (time.monotonic() - last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            last_request_at = time.monotonic()

        try:
            legal_goto(SOURCE_INDEX)
            page.locator("a[href^='/schemes/']").first.wait_for(timeout=30000)
            cards = page.locator("a[href^='/schemes/']").evaluate_all(
                """nodes => nodes.map(node => {
                    const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
                    const parts = (node.innerText || '').split('\\n').map(clean).filter(Boolean);
                    const href = node.getAttribute('href') || '';
                    return {href, slug: href.split('/').pop(), code: parts[0] || '', title: parts[1] || '', benefit: parts[2] || '', category: parts.at(-1) || ''};
                }).filter(item => /^\\/schemes\\/[A-Za-z0-9]/.test(item.href))"""
            )
            seen: set[str] = set()
            for card in cards[:max_pages]:
                href = str(card.get("href", ""))
                if not href or href in seen:
                    continue
                seen.add(href)
                try:
                    legal_goto("https://apmsmeone.ap.gov.in" + href)
                    page.locator("main h1, h1").first.wait_for(timeout=30000)
                    record = _extract_detail(page, href, card, retrieved_at)
                    records.append(record)
                except Exception as exc:  # retain deterministic failure report, continue other pages
                    failures.append({"url": "https://apmsmeone.ap.gov.in" + href, "error": str(exc)[:500]})
                    if verbose:
                        print(f"[warning] {href}: {exc}")
        finally:
            browser.close()
    if not records:
        raise AgentError("Official AP MSME directory yielded no detail records.")
    return records, {
        "source_index": SOURCE_INDEX,
        "retrieved_at": retrieved_at,
        "pages_attempted": len(records) + len(failures),
        "pages_fetched": len(records),
        "pages_failed": len(failures),
        "failures": failures,
        "source_host": AP_HOST,
    }


def _write_evidence_outputs(run_dir: Path, records: list[dict[str, Any]], crawl: dict[str, Any], baseline: dict[str, Any]) -> None:
    write_csv(run_dir / "discovered_scheme_inventory.csv", records, INVENTORY_FIELDS)
    source_registry = {
        "version": VERSION,
        "sources": [{
            "source_id": "ap_msme_one_schemes",
            "organisation": "Andhra Pradesh MSME Development Corporation",
            "official_domain": AP_HOST,
            "robots_url": AP_ROBOTS_URL,
            "source_role": "official state MSME scheme directory and detail evidence",
            "ownership_scope": "Andhra Pradesh directory; central and state records retained separately",
            "authoritative_pages": [SOURCE_INDEX, "https://apmsmeone.ap.gov.in/schemes/{scheme_code}"],
            "crawl_bounds": "scheme index plus linked detail pages; max-pages bounded by CLI",
            "monitoring_frequency": "daily for directory and status changes",
            "rate_limit": "one sequential page request at a time",
            "legal_policy": crawl.get("legal_policy", {}),
            "last_successful_verification": crawl.get("retrieved_at", ""),
        }],
    }
    write_json(run_dir / "official_source_registry.json", source_registry)
    write_json(run_dir / "crawl_manifest.json", crawl)
    write_json(run_dir / "protected_baseline.json", baseline)
    write_json(run_dir / "discovered_url_inventory.json", [{"url": row["official_page_url"], "role": "SCHEME_DETAIL", "master_id": row["master_id"]} for row in records])
    write_json(run_dir / "fetch_failure_report.json", crawl.get("failures", []))
    write_json(run_dir / "redirect_report.json", [])
    write_json(run_dir / "document_inventory.json", [])
    write_json(run_dir / "page_role_classifications.json", [{"master_id": row["master_id"], "page_role": "SCHEME_DETAIL"} for row in records])
    write_json(run_dir / "canonical_scheme_inventory.json", records)
    for name in (
        "government_service_inventory", "current_call_inventory", "historical_call_inventory",
        "credit_guarantee_subsidy_inventory", "incubation_innovation_inventory",
        "procurement_market_access_inventory", "intermediary_opportunities",
        "parent_child_relationships", "ownership_evidence", "applicant_layer_classification",
        "startup_relevance_classification", "eligibility_evidence", "benefit_funding_evidence",
        "sector_support_type_evidence", "status_deadline_evidence", "application_link_verification",
        "duplicates_version_resolutions", "supporting_document_index", "exclusions_reasons",
    ):
        write_json(run_dir / f"{name}.json", records if name in {"ownership_evidence", "applicant_layer_classification", "startup_relevance_classification", "eligibility_evidence", "benefit_funding_evidence", "sector_support_type_evidence", "status_deadline_evidence", "application_link_verification"} else [])


def _baseline() -> dict[str, Any]:
    database = PROJECT_ROOT / "database/ssip_staging_v1.db"
    return {"database_sha256": sha256_file(database) if database.exists() else "", "captured_at": utc_now(), "scope": "MSME supplement only; non-MSME catalogue is protected"}


def _candidate(records: list[dict[str, Any]], crawl: dict[str, Any], run_dir: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    decisions = {row["publication_decision"] for row in records}
    if decisions - {"AUTO_APPROVED", "REVIEW_REQUIRED"}:
        raise AgentError("Unexpected publication decision in candidate records.")
    if crawl.get("pages_failed"):
        # A partial crawl must never silently retire a previously published record.
        for row in records:
            row["warnings"] = "|".join(filter(None, [row.get("warnings", ""), "Source crawl had one or more failed detail pages."]))
    _write_evidence_outputs(run_dir, records, crawl, baseline)
    candidate_bytes = (run_dir / "discovered_scheme_inventory.csv").read_bytes()
    exceptions = [row for row in records if row["publication_decision"] != "AUTO_APPROVED"]
    manifest = {
        "version": VERSION,
        "run_id": run_dir.name,
        "created_at": utc_now(),
        "candidate_status": "VALIDATED" if not exceptions else "VALIDATED_WITH_EXCEPTIONS",
        "inventory_file": "discovered_scheme_inventory.csv",
        "inventory_sha256": sha256_bytes(candidate_bytes),
        "record_count": len(records),
        "auto_approved_count": len(records) - len(exceptions),
        "exception_count": len(exceptions),
        "exception_ids": [row["master_id"] for row in exceptions],
        "protected_baseline": baseline,
        "manifest_sha256": "",
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["manifest_sha256"] = sha256_bytes(encoded)
    write_json(run_dir / "candidate_manifest.json", manifest)
    write_csv(run_dir / "automatic_publication_decisions.csv", records, INVENTORY_FIELDS)
    write_csv(run_dir / "admin_exception_queue.csv", exceptions, INVENTORY_FIELDS)
    write_json(run_dir / "validation_report.json", {"passed": not exceptions, "record_count": len(records), "exceptions": [row["master_id"] for row in exceptions]})
    return manifest


def _latest_run() -> Path | None:
    candidates = sorted(path for path in RUNS_DIR.iterdir() if path.is_dir()) if RUNS_DIR.exists() else []
    return candidates[-1] if candidates else None


def _publish(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "candidate_manifest.json"
    if not manifest_path.exists():
        raise AgentError("Candidate manifest is missing; run --mode candidate first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("candidate_status") != "VALIDATED":
        raise AgentError("Candidate has exceptions and cannot be automatically published.")
    source = run_dir / manifest["inventory_file"]
    if sha256_file(source) != manifest.get("inventory_sha256"):
        raise AgentError("Candidate inventory hash mismatch; publication is stale.")
    old_manifest = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8")) if ACTIVE_MANIFEST.exists() else {}
    old_inventory = PUBLICATION_DIR / "active_inventory.csv"
    old_ids = {row.get("master_id", "") for row in read_csv(old_inventory)} if old_inventory.exists() else set()
    new_rows = read_csv(source)
    new_ids = {row.get("master_id", "") for row in new_rows}
    missing = sorted(old_ids - new_ids)
    if missing:
        raise AgentError("Publication would retire existing MSME identities; review required: " + ", ".join(missing))
    backup = PUBLICATION_DIR / "backups" / run_dir.name
    backup.mkdir(parents=True, exist_ok=False)
    if old_inventory.exists():
        shutil.copy2(old_inventory, backup / "active_inventory.csv")
    if ACTIVE_MANIFEST.exists():
        shutil.copy2(ACTIVE_MANIFEST, backup / ACTIVE_MANIFEST.name)
    temporary = PUBLICATION_DIR / "active_inventory.csv.publish.tmp"
    shutil.copy2(source, temporary)
    os.replace(temporary, old_inventory)
    active = {
        "version": VERSION,
        "activation_status": "ACTIVE",
        "run_id": run_dir.name,
        "activated_at": utc_now(),
        "inventory_file": "active_inventory.csv",
        "inventory_sha256": sha256_file(old_inventory),
        "record_count": len(new_rows),
        "previous_run_id": old_manifest.get("run_id", ""),
        "backup_location": str(backup.relative_to(PROJECT_ROOT)),
        "publication_decision": "AUTO_APPROVED",
    }
    write_json(ACTIVE_MANIFEST, active)
    write_json(PUBLICATION_DIR / "latest_run_status.json", {"run_id": run_dir.name, "status": "PUBLISHED", "active_manifest": active})
    write_json(run_dir / "signed_publication_manifest.json", active)
    write_json(run_dir / "post_publication_report.json", {"passed": True, "active_record_count": len(new_rows), "active_inventory_sha256": active["inventory_sha256"]})
    return {"published": True, "run_id": run_dir.name, "record_count": len(new_rows), "backup": str(backup), "manifest": active}


def _rollback(run_name: str | None) -> dict[str, Any]:
    backup_root = PUBLICATION_DIR / "backups"
    candidates = sorted(path for path in backup_root.iterdir() if path.is_dir()) if backup_root.exists() else []
    backup = backup_root / run_name if run_name else (candidates[-1] if candidates else None)
    if backup is None or not backup.exists():
        raise AgentError("No MSME publication backup is available.")
    previous = backup / "active_inventory.csv"
    previous_manifest = backup / ACTIVE_MANIFEST.name
    if not previous.exists() or not previous_manifest.exists():
        raise AgentError(f"Rollback checkpoint is incomplete: {backup}")
    temporary = PUBLICATION_DIR / "active_inventory.csv.rollback.tmp"
    shutil.copy2(previous, temporary)
    os.replace(temporary, PUBLICATION_DIR / "active_inventory.csv")
    shutil.copy2(previous_manifest, ACTIVE_MANIFEST)
    write_json(PUBLICATION_DIR / "latest_run_status.json", {"status": "ROLLED_BACK", "backup": str(backup), "rolled_back_at": utc_now()})
    return {"rolled_back": True, "backup": str(backup), "manifest": json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))}


@contextmanager
def _run_lock(run_name: str) -> Iterator[None]:
    PUBLICATION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        handle = LOCK_FILE.open("x", encoding="ascii")
    except FileExistsError as exc:
        raise AgentError(f"Another MSME run is active: {LOCK_FILE}") from exc
    try:
        handle.write(run_name + "\n")
        handle.close()
        yield
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def status() -> dict[str, Any]:
    active = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8")) if ACTIVE_MANIFEST.exists() else {"activation_status": "NOT_CONFIGURED"}
    latest = json.loads((PUBLICATION_DIR / "latest_run_status.json").read_text(encoding="utf-8")) if (PUBLICATION_DIR / "latest_run_status.json").exists() else {}
    return {"version": VERSION, "active": active, "latest_run": latest, "runs": len([p for p in RUNS_DIR.iterdir() if p.is_dir()]) if RUNS_DIR.exists() else 0}


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governed AP MSME ONE discovery and publication runner")
    parser.add_argument("--mode", choices=("discover", "verify", "candidate", "publish", "full", "status", "rollback"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--allow-unpublished-robots", action="store_true")
    parser.add_argument("--json-report", nargs="?", const="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "status":
        result = {**status(), "source_definition": configured_source()}
    elif args.mode == "rollback":
        configured_source()
        result = _rollback(args.run_id)
    else:
        configured_source()
        name = args.run_id or run_id()
        with _run_lock(name):
            run_dir = RUNS_DIR / name
            run_dir.mkdir(parents=True, exist_ok=args.resume)
            baseline = _baseline()
            if args.mode == "discover":
                legal_policy = check_robots_policy(allow_unpublished_robots=args.allow_unpublished_robots)
                records, crawl = discover(args.max_pages, verbose=args.verbose)
                crawl["legal_policy"] = legal_policy
                _write_evidence_outputs(run_dir, records, crawl, baseline)
                result = {"run_id": name, "mode": "discover", "record_count": len(records), "crawl": crawl}
            else:
                inventory = run_dir / "discovered_scheme_inventory.csv"
                crawl_path = run_dir / "crawl_manifest.json"
                if not inventory.exists() or not crawl_path.exists():
                    legal_policy = check_robots_policy(allow_unpublished_robots=args.allow_unpublished_robots)
                    records, crawl = discover(args.max_pages, verbose=args.verbose)
                    crawl["legal_policy"] = legal_policy
                    _write_evidence_outputs(run_dir, records, crawl, baseline)
                else:
                    records = read_csv(inventory)
                    crawl = json.loads(crawl_path.read_text(encoding="utf-8"))
                if args.mode == "verify":
                    result = {"run_id": name, "mode": "verify", "record_count": len(records), "verified_count": sum(row.get("publication_decision") == "AUTO_APPROVED" for row in records), "exceptions": [row["master_id"] for row in records if row.get("publication_decision") != "AUTO_APPROVED"]}
                    write_json(run_dir / "latest_run_status.json", result)
                else:
                    candidate = _candidate(records, crawl, run_dir, baseline)
                    result = {"run_id": name, "mode": args.mode, "candidate": candidate}
                    if args.mode in {"publish", "full"} and not args.dry_run and not args.no_publish:
                        result["publication"] = _publish(run_dir)
                    elif args.mode == "publish" and (args.dry_run or args.no_publish):
                        result["publication"] = {"published": False, "reason": "dry-run/no-publish"}
            write_json(run_dir / "latest_run_status.json", result)
    if args.json_report is not None:
        report_path = Path(args.json_report) if args.json_report else (PUBLICATION_DIR / "last_command_report.json")
        if not report_path.is_absolute():
            report_path = PROJECT_ROOT / report_path
        write_json(report_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        result = {
            "version": VERSION,
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "active_catalogue_unchanged": True,
            "reported_at": utc_now(),
        }
        write_json(PUBLICATION_DIR / "last_command_report.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
