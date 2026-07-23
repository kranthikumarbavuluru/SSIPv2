from __future__ import annotations

"""Governed Department of Telecommunications (DoT) public publication bundle.

The dashboard consumes a hash-verified, manually curated snapshot.  It does not
crawl DoT, TTDF or DCIS at render time, and it never infers an open call from a
permanent programme page.
"""

import csv
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from .catalogue import CatalogueRecord


PUBLICATION_DIR = Path("data/departments/dot/v3_4_8_0")
MANIFEST_NAME = "active_publication_manifest_v3_4_8_0.json"
OFFICIAL_HOSTS = ("dot.gov.in", "ttdf.usof.gov.in", "dcis.dot.gov.in", "usof.gov.in")
CALL_KINDS = {"APPLICATION_CALL", "CHALLENGE", "COMPETITION"}
CURRENT_STATUSES = {"OPEN", "UPCOMING"}
HISTORICAL_STATUSES = {"CLOSED", "CLOSED_OR_HISTORICAL", "ARCHIVED", "HISTORICAL"}


class DOTSupplementError(RuntimeError):
    """Raised when the active DoT publication gate fails."""


@dataclass(frozen=True)
class DOTSupplement:
    records: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class DOTPublicBundle:
    permanent_records: tuple[CatalogueRecord, ...]
    current_calls: tuple[CatalogueRecord, ...]
    historical_records: tuple[CatalogueRecord, ...]
    documents: tuple[dict[str, str], ...]
    excluded_count: int
    latest_verification_date: str

    @property
    def public_records(self) -> tuple[CatalogueRecord, ...]:
        return (*self.permanent_records, *self.current_calls, *self.historical_records)


def _split(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _int_value(value: str) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def is_official_dot_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme == "https" and any(host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_HOSTS)


def _verified_date(value: str) -> str:
    candidate = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return ""


def _record_from_row(row: dict[str, str]) -> dict[str, Any]:
    source_url = row.get("official_page_url", "").strip()
    if not is_official_dot_url(source_url):
        raise DOTSupplementError(f"Unsafe DoT source URL: {source_url}")
    application_url = row.get("application_url", "").strip()
    if application_url and not is_official_dot_url(application_url):
        raise DOTSupplementError(f"Unsafe DoT application URL: {application_url}")
    status = row.get("application_status", "STATUS_UNVERIFIED").strip() or "STATUS_UNVERIFIED"
    record_kind = row.get("record_kind", "SCHEME").strip() or "SCHEME"
    return {
        "master_id": row["master_id"].strip(),
        "scheme_name": row["canonical_name"].strip(),
        "source": row.get("source", "Department of Telecommunications").strip(),
        "ministry": row.get("ministry", "Ministry of Communications").strip(),
        "department": row.get("department", "Department of Telecommunications (DoT)").strip(),
        "implementing_agency": row.get("implementing_agency", "").strip(),
        "parent_master_id": row.get("parent_master_id", "").strip(),
        "parent_scheme_name": row.get("parent_scheme_name", "").strip(),
        "applicant_layer": row.get("applicant_layer", "DIRECT_SUPPORT").strip(),
        "implementation_role": row.get("implementation_role", "").strip(),
        "status_basis": row.get("status_basis", "").strip(),
        "status_evidence": row.get("status_evidence", "").strip(),
        "last_verified_at": row.get("last_verified_at", "").strip(),
        "record_kind": record_kind,
        "programme_status": row.get("programme_status", "INFORMATION_AVAILABLE").strip(),
        "application_status": status,
        "geographic_scope": row.get("geographic_scope", "India").strip(),
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "APPLICATION_CALLS" if record_kind.upper() in CALL_KINDS else "SCHEMES_AND_PROGRAMMES",
        "publication_status": "PUBLISHED",
        "is_public": 1,
        "current_location": "DOT_ACTIVE_PUBLICATION",
        "current_review_status": "AUTOMATED_GATES_PASSED",
        "current_decision": "AUTO_APPROVED",
        "official_page_url": source_url,
        "application_url": application_url,
        "opening_date": row.get("opening_date", "").strip(),
        "closing_date": row.get("closing_date", "").strip(),
        "currency": "INR",
        "funding_minimum": _int_value(row.get("funding_minimum", "")),
        "funding_maximum": _int_value(row.get("funding_maximum", "")),
        "funding_amount_status": row.get("funding_amount_status", "NOT_STATED").strip() or "NOT_STATED",
        "funding_amount_optional": row.get("funding_amount_optional", "1").strip() != "0",
        "funding_evidence": row.get("funding_evidence", "").strip() or None,
        "scheme_corpus": _int_value(row.get("scheme_corpus", "")),
        "objectives": _split(row.get("objectives", "")),
        "eligibility": _split(row.get("eligibility", "")),
        "benefits": _split(row.get("benefits", "")),
        "application_process": _split(row.get("application_process", "")),
        "required_documents": _split(row.get("required_documents", "")),
        "sectors": _split(row.get("sectors", "")),
        "scheme_types": _split(row.get("scheme_types", "")),
        "target_beneficiaries": _split(row.get("target_beneficiaries", "")),
        "startup_stage": _split(row.get("startup_stage", "")),
        "guideline_urls": _split(row.get("guideline_urls", "")),
        "reference_urls": _split(row.get("reference_urls", "")),
        "warnings": _split(row.get("warnings", "")),
        "recommended_actions": _split(row.get("recommended_actions", "")),
        "last_updated": row.get("last_verified_at", "").strip(),
        "search_blob": " ".join(
            value.strip()
            for value in (
                row.get("scheme_code", ""), row.get("canonical_name", ""),
                row.get("objectives", ""), row.get("benefits", ""),
                row.get("eligibility", ""), row.get("sectors", ""),
                row.get("target_beneficiaries", ""),
            )
            if value.strip()
        ).casefold(),
    }


def load_active_dot_supplement(project_root: Path) -> DOTSupplement:
    directory = (project_root / PUBLICATION_DIR).resolve()
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        return DOTSupplement(records=(), manifest={"status": "NOT_CONFIGURED"})
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DOTSupplementError(f"Cannot read active DoT manifest: {manifest_path}") from exc
    if manifest.get("activation_status") != "ACTIVE":
        return DOTSupplement(records=(), manifest=manifest)
    relative_inventory = str(manifest.get("inventory_file", "")).strip()
    inventory_path = (directory / relative_inventory).resolve()
    if directory not in inventory_path.parents:
        raise DOTSupplementError("Active DoT inventory path escapes the governed directory.")
    try:
        payload = inventory_path.read_bytes()
    except OSError as exc:
        raise DOTSupplementError(f"Cannot read active DoT inventory: {inventory_path}") from exc
    if sha256(payload).hexdigest() != manifest.get("inventory_sha256"):
        raise DOTSupplementError("Active DoT inventory hash does not match its manifest.")
    rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
    records = tuple(_record_from_row(row) for row in rows)
    ids = [record["master_id"] for record in records]
    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise DOTSupplementError("Duplicate or blank master IDs in active DoT inventory.")
    if len(records) != int(manifest.get("record_count", -1)):
        raise DOTSupplementError("Active DoT record count does not match its manifest.")
    return DOTSupplement(records=records, manifest=manifest)


def build_dot_public_bundle(records: Iterable[CatalogueRecord]) -> DOTPublicBundle:
    owned = [
        record for record in records
        if record.current_location == "DOT_ACTIVE_PUBLICATION"
        or "department of telecommunications" in " ".join((record.department, record.source)).casefold()
    ]
    permanent: list[CatalogueRecord] = []
    current: list[CatalogueRecord] = []
    historical: list[CatalogueRecord] = []
    documents: list[dict[str, str]] = []
    excluded = 0
    for record in owned:
        status = record.application_status.upper()
        kind = record.record_kind.upper()
        if record.guideline_urls:
            documents.extend(
                {"title": record.scheme_name, "document_type": "GUIDELINE", "official_url": url,
                 "department_label": "Department of Telecommunications (DoT)"}
                for url in record.guideline_urls if is_official_dot_url(url)
            )
        if status in HISTORICAL_STATUSES:
            historical.append(record)
        elif kind in CALL_KINDS and status not in CURRENT_STATUSES:
            excluded += 1
        elif kind in CALL_KINDS:
            current.append(record)
        else:
            permanent.append(record)
    key = lambda item: item.scheme_name.casefold()
    permanent.sort(key=key)
    current.sort(key=key)
    historical.sort(key=key)
    documents.sort(key=lambda item: item["title"].casefold())
    dates = [_verified_date(record.last_verified_at or record.last_updated) for record in (*permanent, *current, *historical)]
    return DOTPublicBundle(
        permanent_records=tuple(permanent), current_calls=tuple(current), historical_records=tuple(historical),
        documents=tuple(documents), excluded_count=excluded,
        latest_verification_date=max((item for item in dates if item), default="Not recorded"),
    )


def filter_dot_records(records: Iterable[CatalogueRecord], *, keyword: str = "", record_type: str = "All", status: str = "All") -> list[CatalogueRecord]:
    needle = keyword.strip().casefold()
    visible: list[CatalogueRecord] = []
    for record in records:
        searchable = " ".join((record.scheme_name, record.department, record.implementing_agency, record.search_blob, *record.sectors, *record.scheme_types)).casefold()
        if needle and needle not in searchable:
            continue
        if record_type != "All" and record.record_kind != record_type:
            continue
        if status != "All" and record.application_status != status:
            continue
        visible.append(record)
    return visible
