from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MeitYHistoricalRecord:
    historical_id: str
    source_master_id: str
    canonical_title: str
    official_page_url: str
    historical_status: str
    historical_year: str
    programme_type: str
    sector: str
    applicant_layer: str
    startup_relevance: str
    parent_resolution: str
    historical_basis: str
    evidence_excerpt: str
    date_confidence: str
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class MeitYHistoricalArchive:
    records: tuple[MeitYHistoricalRecord, ...]
    manifest: dict[str, Any]


def default_meity_history_dir(project_root: Path) -> Path:
    return (
        project_root
        / "data/departments/meity/v3_4_3_7_8"
    )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def load_meity_historical_archive(
    project_root: Path,
) -> MeitYHistoricalArchive:
    directory = default_meity_history_dir(project_root)
    archive_path = (
        directory
        / "meity_historical_archive_v3_4_3_7_8.csv"
    )
    manifest_path = (
        directory
        / "meity_historical_archive_manifest_v3_4_3_7_8.json"
    )

    if not archive_path.exists():
        raise FileNotFoundError(
            f"MeitY historical archive not found: {archive_path}"
        )
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"MeitY historical manifest not found: {manifest_path}"
        )

    with archive_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    records = tuple(
        MeitYHistoricalRecord(
            historical_id=_clean(row.get("historical_id")),
            source_master_id=_clean(row.get("source_master_id")),
            canonical_title=_clean(row.get("canonical_title")),
            official_page_url=_clean(row.get("official_page_url")),
            historical_status=_clean(row.get("historical_status")),
            historical_year=_clean(row.get("historical_year")),
            programme_type=_clean(row.get("programme_type")),
            sector=_clean(row.get("sector")),
            applicant_layer=_clean(row.get("applicant_layer")),
            startup_relevance=_clean(
                row.get("startup_relevance")
            ),
            parent_resolution=_clean(
                row.get("parent_resolution")
            ),
            historical_basis=_clean(
                row.get("historical_basis")
            ),
            evidence_excerpt=_clean(
                row.get("evidence_excerpt")
            ),
            date_confidence=_clean(row.get("date_confidence")),
            quality_flags=tuple(
                item
                for item in _clean(
                    row.get("quality_flags")
                ).split(";")
                if item
            ),
        )
        for row in rows
    )
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8-sig")
    )
    if int(
        manifest.get("qualified_historical_calls", -1)
    ) != len(records):
        raise ValueError(
            "MeitY historical archive count does not match manifest."
        )
    if int(manifest.get("apply_actions_allowed", -1)) != 0:
        raise ValueError(
            "MeitY historical archive must not expose Apply actions."
        )
    return MeitYHistoricalArchive(
        records=records,
        manifest=manifest,
    )
