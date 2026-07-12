from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CONTROLLED_STATUSES = ("OPEN", "UPCOMING", "CLOSED", "STATUS_UNVERIFIED")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(_text(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def safe_http_url(value: Any) -> str:
    text = _text(value)
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else ""


@dataclass(frozen=True)
class DSTProgramme:
    master_id: str
    code: str
    canonical_name: str
    entity_type: str
    parent_master_id: str
    parent_name: str
    public_classification: str
    sector_scope: str
    primary_sector: str
    secondary_sectors: str
    official_master_url: str
    evidence_text: str
    review_status: str


@dataclass(frozen=True)
class DSTCall:
    call_id: str
    call_title: str
    call_type: str
    parent_master_id: str
    parent_name: str
    parent_code: str
    parent_resolution: str
    implementing_entity: str
    implementation_role: str
    applicant_layer: str
    applicant_layer_reason: str
    opening_date: str
    closing_date: str
    application_status: str
    status_basis: str
    status_evidence: str
    last_verified_at: str
    startup_relevance: str
    startup_relevance_reason: str
    sector_scope: str
    primary_sector: str
    secondary_sectors: str
    sector_reason: str
    eligible_applicants: str
    funding_summary: str
    funding_maximum: str
    startup_stage: str
    application_url: str
    detail_url: str
    attachment_url: str
    guideline_url: str
    evidence_note: str
    source_container_role: str = ""
    source_row_number: str = ""
    source_fetched_at: str = ""

    @property
    def is_direct_or_review(self) -> bool:
        return self.startup_relevance in {"STARTUP_RELEVANT", "REVIEW_REQUIRED"}

    @property
    def is_ecosystem(self) -> bool:
        return self.startup_relevance == "STARTUP_ECOSYSTEM_CALL" or self.applicant_layer == "INTERMEDIARY_IMPLEMENTER"


@dataclass(frozen=True)
class DSTPilotBundle:
    programmes: list[DSTProgramme]
    calls: list[DSTCall]
    database_path: Path

    @property
    def direct_calls(self) -> list[DSTCall]:
        return [item for item in self.calls if item.is_direct_or_review and not item.is_ecosystem]

    @property
    def ecosystem_calls(self) -> list[DSTCall]:
        return [item for item in self.calls if item.is_ecosystem]


def default_dst_pilot_path(project_root: Path) -> Path:
    return project_root / "data/departments/dst/pilot_v1/dst_evidence_pilot_v1.db"


def load_dst_pilot(path: Path) -> DSTPilotBundle:
    database = path.resolve()
    if not database.exists():
        return DSTPilotBundle([], [], database)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        programme_rows = connection.execute("SELECT * FROM programme_master ORDER BY canonical_name COLLATE NOCASE").fetchall()
        names = {row["master_id"]: row["canonical_name"] for row in programme_rows}
        codes = {row["master_id"]: row["code"] for row in programme_rows}
        programmes = [
            DSTProgramme(
                master_id=_text(row["master_id"]), code=_text(row["code"]),
                canonical_name=_text(row["canonical_name"]), entity_type=_text(row["entity_type"]),
                parent_master_id=_text(row["parent_master_id"]), parent_name=_text(names.get(row["parent_master_id"])),
                public_classification=_text(row["public_classification"]), sector_scope=_text(row["sector_scope"]),
                primary_sector=_text(row["primary_sector"]), secondary_sectors=_text(row["secondary_sectors"]),
                official_master_url=safe_http_url(row["official_master_url"]), evidence_text=_text(row["evidence_text"]),
                review_status=_text(row["review_status"]),
            )
            for row in programme_rows
        ]
        call_rows = connection.execute("SELECT * FROM call_instance ORDER BY closing_date DESC, call_title COLLATE NOCASE").fetchall()
        calls: list[DSTCall] = []
        for row in call_rows:
            raw = _json(row["raw_json"])
            parent_id = _text(row["parent_master_id"])
            calls.append(DSTCall(
                call_id=_text(row["call_id"]), call_title=_text(row["call_title"]),
                call_type=_text(row["call_type"]), parent_master_id=parent_id,
                parent_name=_text(names.get(parent_id)), parent_code=_text(codes.get(parent_id)),
                parent_resolution=_text(row["parent_resolution"]), implementing_entity=_text(row["implementing_entity"]),
                implementation_role=_text(row["implementation_role"]), applicant_layer=_text(row["applicant_layer"]),
                applicant_layer_reason=_text(row["applicant_layer_reason"]), opening_date=_text(row["opening_date"]),
                closing_date=_text(row["closing_date"]), application_status=_text(row["application_status"]),
                status_basis=_text(row["status_basis"]), status_evidence=_text(row["status_evidence"]),
                last_verified_at=_text(row["last_verified_at"]),
                startup_relevance=_text(row["startup_relevance"]), startup_relevance_reason=_text(raw.get("startup_relevance_reason")),
                sector_scope=_text(row["sector_scope"]), primary_sector=_text(row["primary_sector"]),
                secondary_sectors=_text(row["secondary_sectors"]), sector_reason=_text(raw.get("sector_reason")),
                eligible_applicants=_text(raw.get("eligible_applicants")), funding_summary=_text(raw.get("funding_summary")),
                funding_maximum=_text(raw.get("funding_maximum")), startup_stage=_text(row["startup_stage"]),
                application_url=safe_http_url(raw.get("application_url")),
                detail_url=safe_http_url(row["detail_url"]), attachment_url=safe_http_url(row["attachment_url"]),
                guideline_url=safe_http_url(row["guideline_url"]),
                evidence_note=_text(raw.get("evidence_note")),
                source_container_role=_text(raw.get("source_container_role")),
                source_row_number=_text(raw.get("source_row_number")),
                source_fetched_at=_text(raw.get("source_fetched_at")),
            ))
    finally:
        connection.close()
    return DSTPilotBundle(programmes, calls, database)


def filter_dst_programmes(
    programmes: list[DSTProgramme], *, keyword: str = "", entity_type: str = "", sector_scope: str = ""
) -> list[DSTProgramme]:
    key = keyword.casefold().strip()
    return [
        item for item in programmes
        if (not key or key in " ".join((item.canonical_name, item.code, item.public_classification, item.evidence_text)).casefold())
        and (not entity_type or item.entity_type == entity_type)
        and (not sector_scope or item.sector_scope == sector_scope)
    ]


def filter_dst_calls(
    calls: list[DSTCall], *, status: str = "", keyword: str = "", sector: str = "", parent_id: str = ""
) -> list[DSTCall]:
    key = keyword.casefold().strip()
    return [
        item for item in calls
        if (not status or item.application_status == status)
        and (not sector or item.primary_sector == sector or sector in item.secondary_sectors.split("; "))
        and (not parent_id or item.parent_master_id == parent_id)
        and (
            not key
            or key in " ".join((item.call_title, item.parent_name, item.primary_sector, item.secondary_sectors, item.eligible_applicants)).casefold()
        )
    ]
