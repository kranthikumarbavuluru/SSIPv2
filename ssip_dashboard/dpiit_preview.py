from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DPIITPreviewRecord:
    record_id: str
    canonical_name: str
    record_type: str
    parent_record_id: str
    direct_applicant_layer: str
    startup_relevance: str
    sector: str
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
class DPIITPreviewBundle:
    records: tuple[DPIITPreviewRecord, ...]
    documents: tuple[dict[str, str], ...]
    review_items: tuple[dict[str, str], ...]
    manifest: dict[str, Any]


def default_dpiit_preview_dir(project_root: Path) -> Path:
    return project_root / "data/departments/dpiit/v3_4_4_0"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_dpiit_preview(project_root: Path) -> DPIITPreviewBundle:
    directory = default_dpiit_preview_dir(project_root)
    rows = _read_csv(directory / "dpiit_dashboard_preview_catalogue_v3_4_4_0.csv")
    public_rows = [
        row for row in rows
        if row.get("publication_status") == "PUBLIC_DEPARTMENT_PAGE"
        and row.get("record_type") != "REVIEW_REQUIRED"
    ]
    records = tuple(
        DPIITPreviewRecord(
            record_id=row.get("record_id", ""),
            canonical_name=row.get("canonical_name", ""),
            record_type=row.get("record_type", "REVIEW_REQUIRED"),
            parent_record_id=row.get("parent_record_id", ""),
            direct_applicant_layer=row.get("direct_applicant_layer", "unverified"),
            startup_relevance=row.get("startup_relevance", "REVIEW_REQUIRED"),
            sector=row.get("sector", "Not verified"),
            application_status=row.get("application_status", "STATUS_UNVERIFIED"),
            opening_date=row.get("opening_date", ""),
            closing_date=row.get("closing_date", ""),
            application_url=row.get("application_url", ""),
            official_url=row.get("official_url", ""),
            guideline_url=row.get("guideline_url", ""),
            last_verified_date=row.get("last_verified_date", ""),
            publication_status=row.get("publication_status", "REVIEW_ONLY_HIDDEN"),
            review_required=row.get("review_required", "1") == "1",
            summary=row.get("summary", ""),
        )
        for row in public_rows
    )
    documents = tuple(_read_csv(directory / "dpiit_supporting_document_index_v3_4_4_0.csv"))
    review_items = tuple(_read_csv(directory / "dpiit_unresolved_review_queue_v3_4_4_0.csv"))
    manifest = json.loads(
        (directory / "dpiit_signed_dry_run_manifest_v3_4_4_0.json").read_text(encoding="utf-8")
    )
    return DPIITPreviewBundle(records, documents, review_items, manifest)


def filter_dpiit_preview(
    records: tuple[DPIITPreviewRecord, ...],
    *,
    keyword: str = "",
    record_type: str = "All",
    status: str = "All",
    applicant_layer: str = "All",
) -> list[DPIITPreviewRecord]:
    needle = keyword.strip().casefold()
    result = []
    for record in records:
        searchable = " ".join((record.canonical_name, record.summary, record.sector, record.direct_applicant_layer)).casefold()
        if needle and needle not in searchable:
            continue
        if record_type != "All" and record.record_type != record_type:
            continue
        if status != "All" and record.application_status != status:
            continue
        if applicant_layer != "All" and applicant_layer not in record.direct_applicant_layer.split(";"):
            continue
        result.append(record)
    return result
