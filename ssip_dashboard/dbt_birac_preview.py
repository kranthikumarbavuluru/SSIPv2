from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


OFFICIAL_HOSTS = {"birac.nic.in", "dbtindia.gov.in", "pgt.dbtindia.gov.in", "birac.eoffice.gov.in"}


@dataclass(frozen=True)
class DBTBIRACPreviewRecord:
    record_id: str
    canonical_name: str
    record_type: str
    parent_record_id: str
    implementing_agency: str
    direct_applicant_layer: str
    startup_relevance: str
    sector: str
    support_type: str
    application_status: str
    opening_date: str
    closing_date: str
    application_url: str
    official_url: str
    guideline_url: str
    last_verified_date: str
    publication_status: str
    review_required: bool
    summary: str


@dataclass(frozen=True)
class DBTBIRACPreviewBundle:
    records: tuple[DBTBIRACPreviewRecord, ...]
    documents: tuple[dict[str, str], ...]
    review_items: tuple[dict[str, str], ...]
    manifest: dict[str, Any]


def default_dbt_birac_preview_dir(project_root: Path) -> Path:
    return project_root / "data/departments/dbt_birac/v3_4_5_0"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_verified_official_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").casefold().strip(".")
    return parts.scheme == "https" and any(host == allowed or host.endswith("." + allowed) for allowed in OFFICIAL_HOSTS)


def load_dbt_birac_preview(project_root: Path) -> DBTBIRACPreviewBundle:
    directory = default_dbt_birac_preview_dir(project_root)
    rows = _read_csv(directory / "dbt_birac_dashboard_preview_projection_v3_4_5_0.csv")
    records = tuple(
        DBTBIRACPreviewRecord(
            record_id=row.get("record_id", ""), canonical_name=row.get("canonical_name", ""),
            record_type=row.get("record_type", "REVIEW_REQUIRED"), parent_record_id=row.get("parent_record_id", ""),
            implementing_agency=row.get("implementing_agency", ""), direct_applicant_layer=row.get("direct_applicant_layer", "unverified"),
            startup_relevance=row.get("startup_relevance", "REVIEW_REQUIRED"), sector=row.get("sector", "Not verified"),
            support_type=row.get("support_type", "Not verified"), application_status=row.get("application_status", "STATUS_UNVERIFIED"),
            opening_date=row.get("opening_date", ""), closing_date=row.get("closing_date", ""),
            application_url="",  # Preview records never expose Apply actions.
            official_url=row.get("official_url", "") if is_verified_official_url(row.get("official_url", "")) else "",
            guideline_url=row.get("guideline_url", "") if is_verified_official_url(row.get("guideline_url", "")) else "",
            last_verified_date=row.get("last_verified_date", ""), publication_status=row.get("publication_status", "PREVIEW_NOT_PUBLISHED"),
            review_required=row.get("review_required", "1") == "1", summary=row.get("summary", ""),
        )
        for row in rows
    )
    documents = tuple(row for row in _read_csv(directory / "dbt_birac_supporting_document_index_v3_4_5_0.csv") if is_verified_official_url(row.get("official_url", "")))
    review_items = tuple(_read_csv(directory / "dbt_birac_unresolved_admin_review_queue_v3_4_5_0.csv"))
    manifest = json.loads((directory / "dbt_birac_signed_dry_run_manifest_v3_4_5_0.json").read_text(encoding="utf-8"))
    return DBTBIRACPreviewBundle(records, documents, review_items, manifest)


def filter_dbt_birac_preview(
    records: tuple[DBTBIRACPreviewRecord, ...], *, keyword: str = "", record_type: str = "All",
    status: str = "All", applicant_layer: str = "All", sector: str = "All",
) -> list[DBTBIRACPreviewRecord]:
    needle = keyword.strip().casefold()
    visible = []
    for record in records:
        searchable = " ".join((record.canonical_name, record.summary, record.sector, record.support_type, record.direct_applicant_layer)).casefold()
        if needle and needle not in searchable:
            continue
        if record_type != "All" and record.record_type != record_type:
            continue
        if status != "All" and record.application_status != status:
            continue
        if applicant_layer != "All" and applicant_layer not in record.direct_applicant_layer.split(";"):
            continue
        if sector != "All" and sector not in record.sector.split(";"):
            continue
        visible.append(record)
    return visible


def public_apply_url(record: DBTBIRACPreviewRecord) -> str:
    """Apply is deliberately suppressed for every unpublished preview record."""
    return ""
