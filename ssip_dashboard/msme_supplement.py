from __future__ import annotations

"""Governed MSME/AP-MSME publication-bundle loader.

The public dashboard never crawls a remote site.  It reads only the active,
hash-verified bundle produced by ``run_msme_agent_v3_4_6_0.py``.  This keeps
dashboard rendering deterministic and makes a failed crawl unable to change
the public catalogue.
"""

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PUBLICATION_DIR = Path("data/departments/msme/v3_4_6_0")
MANIFEST_NAME = "active_publication_manifest_v3_4_6_0.json"
AP_HOST = "apmsmeone.ap.gov.in"
MYMSME_PUBLICATION_DIR = PUBLICATION_DIR / "mymsme"
MYMSME_MANIFEST_NAME = "active_publication_manifest_v3_4_6_0.json"
MYMSME_HOST = "my.msme.gov.in"


class MSMESupplementError(RuntimeError):
    """Raised when an active MSME bundle fails a publication gate."""


@dataclass(frozen=True)
class MSMESupplement:
    records: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def is_official_ap_url(value: str) -> bool:
    return _is_official_source_url(value, (AP_HOST,))


def is_official_mymsme_url(value: str) -> bool:
    return _is_official_source_url(value, (MYMSME_HOST,))


def _is_official_source_url(value: str, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme == "https" and any(
        host == allowed or host.endswith("." + allowed)
        for allowed in allowed_hosts
    )


def _official_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme == "https" and bool(host) and not host.endswith(".example.com")


def _split(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _record_from_row(
    row: dict[str, str],
    *,
    allowed_hosts: tuple[str, ...],
    default_source: str,
    default_geographic_scope: str,
) -> dict[str, Any]:
    source_url = row.get("official_page_url", "").strip()
    if not _is_official_source_url(source_url, allowed_hosts):
        raise MSMESupplementError(f"Unsafe MSME source URL: {source_url}")
    if row.get("publication_decision", "").strip() != "AUTO_APPROVED":
        raise MSMESupplementError(f"Non-approved record present in active bundle: {row.get('master_id', '')}")
    application_url = row.get("application_url", "").strip()
    if application_url and not _official_url(application_url):
        raise MSMESupplementError(f"Unsafe application URL: {application_url}")
    return {
        "master_id": row["master_id"].strip(),
        "scheme_name": row["canonical_name"].strip(),
        "source": row.get("source", default_source).strip(),
        "ministry": row.get("ministry", "").strip(),
        "department": row.get("department", "").strip(),
        "implementing_agency": row.get("implementing_agency", "").strip(),
        "parent_master_id": row.get("parent_master_id", "").strip(),
        "parent_scheme_name": row.get("parent_scheme_name", "").strip(),
        "applicant_layer": row.get("applicant_layer", "DIRECT_MSME_SUPPORT").strip(),
        "implementation_role": row.get("ownership_scope", "").strip(),
        "status_basis": row.get("status_basis", "").strip(),
        "status_evidence": row.get("status_evidence", "").strip(),
        "last_verified_at": row.get("last_verified_at", "").strip(),
        "record_kind": row.get("record_kind", "SCHEME").strip(),
        "programme_status": row.get("programme_status", "ACTIVE_INFORMATION_AVAILABLE").strip(),
        "application_status": "STATUS_UNVERIFIED",
        "geographic_scope": row.get("geographic_scope", default_geographic_scope).strip(),
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "SCHEMES_AND_PROGRAMMES",
        "publication_status": "PUBLISHED",
        "is_public": 1,
        "current_location": "MSME_ACTIVE_PUBLICATION",
        "current_review_status": "AUTOMATED_GATES_PASSED",
        "current_decision": "AUTO_APPROVED",
        "official_page_url": source_url,
        "application_url": application_url,
        "objectives": _split(row.get("description", "")),
        "eligibility": _split(row.get("eligibility", "")),
        "benefits": _split(row.get("benefit_summary", "")),
        "sectors": _split(row.get("sector", "")),
        "scheme_types": _split("|".join(filter(None, (row.get("category", ""), row.get("support_type", ""))))),
        "target_beneficiaries": _split(row.get("target_beneficiaries", "")),
        "guideline_urls": _split(row.get("guideline_urls", "")),
        "reference_urls": _split(row.get("reference_urls", "")),
        "warnings": _split(row.get("warnings", "")),
        "last_updated": row.get("last_verified_at", "").strip(),
        "search_blob": " ".join(
            value.strip()
            for value in (
                row.get("scheme_code", ""),
                row.get("canonical_name", ""),
                row.get("description", ""),
                row.get("benefit_summary", ""),
                row.get("category", ""),
                row.get("sector", ""),
                row.get("target_beneficiaries", ""),
            )
            if value.strip()
        ).casefold(),
    }


def _load_active_bundle(
    project_root: Path,
    relative_directory: Path,
    manifest_name: str,
    *,
    allowed_hosts: tuple[str, ...],
    default_source: str,
    default_geographic_scope: str,
) -> MSMESupplement:
    directory = (project_root / relative_directory).resolve()
    manifest_path = directory / manifest_name
    if not manifest_path.exists():
        return MSMESupplement(records=(), manifest={"status": "NOT_CONFIGURED"})

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MSMESupplementError(f"Cannot read active MSME manifest: {manifest_path}") from exc
    if manifest.get("activation_status") != "ACTIVE":
        return MSMESupplement(records=(), manifest=manifest)

    relative_inventory = str(manifest.get("inventory_file", "")).strip()
    inventory_path = (directory / relative_inventory).resolve()
    if directory not in inventory_path.parents:
        raise MSMESupplementError("Active inventory path escapes the governed directory.")
    try:
        payload = inventory_path.read_bytes()
    except OSError as exc:
        raise MSMESupplementError(f"Cannot read active MSME inventory: {inventory_path}") from exc
    actual_hash = sha256(payload).hexdigest()
    if actual_hash != manifest.get("inventory_sha256"):
        raise MSMESupplementError("Active MSME inventory hash does not match its manifest.")

    rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
    records = tuple(
        _record_from_row(
            row,
            allowed_hosts=allowed_hosts,
            default_source=default_source,
            default_geographic_scope=default_geographic_scope,
        )
        for row in rows
    )
    master_ids = [record["master_id"] for record in records]
    urls = [record["official_page_url"].casefold().rstrip("/") for record in records]
    if not master_ids or not all(master_ids) or len(master_ids) != len(set(master_ids)):
        raise MSMESupplementError("Duplicate or blank master IDs in active MSME inventory.")
    if len(urls) != len(set(urls)):
        raise MSMESupplementError("Duplicate canonical URLs in active MSME inventory.")
    if len(records) != int(manifest.get("record_count", -1)):
        raise MSMESupplementError("Active MSME record count does not match its manifest.")
    return MSMESupplement(records=records, manifest=manifest)


def load_active_msme_supplement(project_root: Path) -> MSMESupplement:
    return _load_active_bundle(
        project_root,
        PUBLICATION_DIR,
        MANIFEST_NAME,
        allowed_hosts=(AP_HOST,),
        default_source="AP MSME ONE",
        default_geographic_scope="Andhra Pradesh directory; scheme scope as stated by official source",
    )


def load_active_mymsme_supplement(project_root: Path) -> MSMESupplement:
    return _load_active_bundle(
        project_root,
        MYMSME_PUBLICATION_DIR,
        MYMSME_MANIFEST_NAME,
        allowed_hosts=(MYMSME_HOST,),
        default_source="MyMSME Portal",
        default_geographic_scope="India; scheme scope as stated by official MyMSME source",
    )
