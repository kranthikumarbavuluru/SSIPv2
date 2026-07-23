from __future__ import annotations

"""Governed Ministry of Education / AICTE public bundle.

This surface focuses on higher-education innovation, entrepreneurship and
research pathways.  It keeps permanent identities, dated calls and historical
cycles distinct and never treats an innovation programme page as an open call.
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


PUBLICATION_DIR = Path("data/departments/moe/v3_4_12_0")
MANIFEST_NAME = "active_publication_manifest_v3_4_12_0.json"
OFFICIAL_HOSTS = (
    "education.gov.in", "aicte-india.org", "mic.gov.in", "pmrc.education.gov.in",
    "bootcamp.mic.gov.in", "pib.gov.in",
)
CALL_KINDS = {"APPLICATION_CALL", "CHALLENGE", "COMPETITION"}
CURRENT_STATUSES = {"OPEN", "UPCOMING"}
HISTORICAL_STATUSES = {"CLOSED", "CLOSED_OR_HISTORICAL", "ARCHIVED", "HISTORICAL"}


class MOESupplementError(RuntimeError):
    """Raised when the active MoE publication gate fails."""


@dataclass(frozen=True)
class MOESupplement:
    records: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


@dataclass(frozen=True)
class MOEPublicBundle:
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


def is_official_moe_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme == "https" and any(
        host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_HOSTS
    )


def _verified_date(value: str) -> str:
    candidate = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return ""


def _record_from_row(row: dict[str, str]) -> dict[str, Any]:
    source_url = str(row.get("official_page_url") or "").strip()
    if not is_official_moe_url(source_url):
        raise MOESupplementError(f"Unsafe MoE source URL: {source_url}")
    application_url = str(row.get("application_url") or "").strip()
    if application_url and not is_official_moe_url(application_url):
        raise MOESupplementError(f"Unsafe MoE application URL: {application_url}")
    record_kind = row.get("record_kind", "SCHEME").strip() or "SCHEME"
    status = row.get("application_status", "STATUS_UNVERIFIED").strip() or "STATUS_UNVERIFIED"
    return {
        "master_id": row["master_id"].strip(),
        "scheme_name": row["canonical_name"].strip(),
        "source": row.get("source", "Ministry of Education / AICTE innovation ecosystem").strip(),
        "ministry": row.get("ministry", "Ministry of Education").strip(),
        "department": row.get("department", "Department of Higher Education, Ministry of Education").strip(),
        "implementing_agency": row.get("implementing_agency", "Ministry of Education / AICTE").strip(),
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
        "current_location": "MOE_ACTIVE_PUBLICATION",
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
                row.get("scheme_types", ""), row.get("target_beneficiaries", ""),
            )
            if value.strip()
        ).casefold(),
    }


def load_active_moe_supplement(project_root: Path) -> MOESupplement:
    directory = (project_root / PUBLICATION_DIR).resolve()
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        return MOESupplement(records=(), manifest={"status": "NOT_CONFIGURED"})
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MOESupplementError(f"Cannot read active MoE manifest: {manifest_path}") from exc
    if manifest.get("activation_status") != "ACTIVE":
        return MOESupplement(records=(), manifest=manifest)
    inventory_path = (directory / str(manifest.get("inventory_file", "")).strip()).resolve()
    if directory not in inventory_path.parents:
        raise MOESupplementError("Active MoE inventory path escapes the governed directory.")
    try:
        payload = inventory_path.read_bytes()
    except OSError as exc:
        raise MOESupplementError(f"Cannot read active MoE inventory: {inventory_path}") from exc
    if sha256(payload).hexdigest() != manifest.get("inventory_sha256"):
        raise MOESupplementError("Active MoE inventory hash does not match its manifest.")
    rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
    records = tuple(_record_from_row(row) for row in rows)
    ids = [record["master_id"] for record in records]
    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise MOESupplementError("Duplicate or blank master IDs in active MoE inventory.")
    if len(records) != int(manifest.get("record_count", -1)):
        raise MOESupplementError("Active MoE record count does not match its manifest.")
    return MOESupplement(records=records, manifest=manifest)


def build_moe_public_bundle(records: Iterable[CatalogueRecord]) -> MOEPublicBundle:
    owned = [
        record for record in records
        if record.current_location == "MOE_ACTIVE_PUBLICATION"
        or "ministry of education" in " ".join((record.ministry, record.department, record.source)).casefold()
    ]
    permanent: list[CatalogueRecord] = []
    current: list[CatalogueRecord] = []
    historical: list[CatalogueRecord] = []
    documents: list[dict[str, str]] = []
    excluded = 0
    for record in owned:
        status = record.application_status.upper()
        kind = record.record_kind.upper()
        documents.extend(
            {"title": record.scheme_name, "document_type": "GUIDELINE", "official_url": url,
             "department_label": "Ministry of Education / AICTE"}
            for url in record.guideline_urls if is_official_moe_url(url)
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
    return MOEPublicBundle(
        permanent_records=tuple(permanent), current_calls=tuple(current), historical_records=tuple(historical),
        documents=tuple(documents), excluded_count=excluded,
        latest_verification_date=max((item for item in dates if item), default="Not recorded"),
    )


def filter_moe_records(records: Iterable[CatalogueRecord], *, keyword: str = "", record_type: str = "All", status: str = "All") -> list[CatalogueRecord]:
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
