from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "3.4.3.8.2"
EDIT_TABLE = "admin_quick_edit_requests_v3_4_3_8_1"
AUDIT_TABLE = "admin_quick_edit_audit_v3_4_3_8_1"
READINESS_STATUSES = (
    "COMPLETE",
    "PARTIALLY_COMPLETE",
    "NEEDS_OFFICIAL_EVIDENCE",
    "NEEDS_PARENT_PROGRAMME",
    "NEEDS_FUNDING_REVIEW",
    "READY_FOR_PUBLICATION_REVIEW",
)
CSV_EDITABLE_FIELDS = {
    "category",
    "status",
    "applicant_types",
    "startup_stages",
    "funding_minimum",
    "funding_maximum",
    "admin_note",
}
CSV_IDENTITY_FIELDS = {
    "master_id",
    "scheme_name",
    "official_source",
    "department",
    "publication_status",
    "application_url",
}


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return copy.deepcopy(default)
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return copy.deepcopy(default)


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name=?
            """,
            (name,),
        ).fetchone()
        is not None
    )


def column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(connection, table):
        return set()
    return {
        str(row[1])
        for row in connection.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
    }


def normalized_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, tuple):
        raw = list(value)
    elif value in (None, ""):
        raw = []
    else:
        text = clean(value)
        if text.startswith("["):
            raw = loads(text, [])
        else:
            raw = [item for item in re.split(r"[;,|]", text)]
    output: list[str] = []
    for item in raw:
        token = clean(item).upper().replace(" ", "_")
        if token and token not in output:
            output.append(token)
    return output


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).upper() in {"1", "TRUE", "YES", "APPROVED", "VERIFIED"}


def record_value(record: dict[str, Any], *keys: str) -> Any:
    raw = record.get("raw_record") or {}
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def completeness(record: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed metadata and publication-readiness assessment."""
    category = clean(record_value(record, "admin_category", "record_kind")).upper()
    status = clean(
        record_value(
            record,
            "scheme_status",
            "application_status",
            "programme_status",
        )
    ).upper()
    applicant_types = normalized_list(record_value(record, "applicant_types"))
    startup_stages = normalized_list(record_value(record, "startup_stages"))
    minimum = record_value(record, "funding_minimum")
    maximum = record_value(record, "funding_maximum")
    funding_reviewed = truthy(record_value(record, "funding_reviewed")) or (
        minimum not in (None, "") or maximum not in (None, "")
    )
    official_source = clean(
        record_value(
            record,
            "official_page_url",
            "official_source_url",
            "official_source",
            "source_url",
        )
    )
    review_status = clean(record_value(record, "review_status")).upper()
    admin_approved = truthy(record_value(record, "admin_approval_complete")) or review_status in {
        "APPROVED",
        "VERIFIED",
        "APPROVED_FOR_DATABASE",
    }
    critical_flags = normalized_list(
        record_value(record, "critical_flags", "unresolved_critical_flags")
    )
    is_call = category in {"APPLICATION_CALL", "CALL", "CHALLENGE", "COHORT"}
    parent = clean(record_value(record, "parent_master_id", "parent_programme_id"))
    deadline_verified = truthy(record_value(record, "deadline_verified")) or (
        status in {"CLOSED", "VERIFICATION_REQUIRED"}
    )
    application_url = clean(record_value(record, "application_url"))
    blockers: list[str] = []
    if not category:
        blockers.append("CATEGORY_MISSING")
    if not status:
        blockers.append("STATUS_MISSING")
    if not applicant_types:
        blockers.append("TYPE_MISSING")
    if not startup_stages:
        blockers.append("STAGE_MISSING")
    if not funding_reviewed:
        blockers.append("FUNDING_REVIEW_REQUIRED")
    if not official_source:
        blockers.append("OFFICIAL_SOURCE_MISSING")
    if not admin_approved:
        blockers.append("ADMIN_APPROVAL_REQUIRED")
    if critical_flags:
        blockers.append("CRITICAL_FLAGS_UNRESOLVED")
    if is_call:
        if not parent:
            blockers.append("PARENT_PROGRAMME_MISSING")
        if not deadline_verified:
            blockers.append("DEADLINE_STATUS_UNVERIFIED")
        if status == "OPEN" and not application_url:
            blockers.append("OPEN_APPLICATION_ROUTE_MISSING")
    if not blockers:
        readiness = "READY_FOR_PUBLICATION_REVIEW"
    elif "OFFICIAL_SOURCE_MISSING" in blockers:
        readiness = "NEEDS_OFFICIAL_EVIDENCE"
    elif "PARENT_PROGRAMME_MISSING" in blockers:
        readiness = "NEEDS_PARENT_PROGRAMME"
    elif "FUNDING_REVIEW_REQUIRED" in blockers:
        readiness = "NEEDS_FUNDING_REVIEW"
    elif len(blockers) == 1 and blockers[0] == "ADMIN_APPROVAL_REQUIRED":
        readiness = "COMPLETE"
    else:
        readiness = "PARTIALLY_COMPLETE"
    return {
        "readiness_status": readiness,
        "blockers": blockers,
        "category_missing": not bool(category),
        "status_missing": not bool(status),
        "type_missing": not bool(applicant_types),
        "stage_missing": not bool(startup_stages),
        "funding_missing": not funding_reviewed,
        "official_source_missing": not bool(official_source),
        "parent_programme_missing": is_call and not bool(parent),
        "ready_for_publication_review": not blockers,
    }


def ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column not in column_names(connection, table):
        connection.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}'
        )


def create_consistent_backup(
    database_path: Path,
    backup_root: Path,
) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / database_path.name
    source = sqlite3.connect(database_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return backup_path


@dataclass(frozen=True)
class QuickEditorPaths:
    project_root: Path
    database_path: Path
    config_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "QuickEditorPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            database_path=root / "database/ssip_staging_v1.db",
            config_path=root / "config/admin_quick_editor_v3_4_3_8_1.json",
        )


class AdminQuickEditorService:
    def __init__(
        self,
        paths: QuickEditorPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config
        if not self.paths.database_path.exists():
            raise FileNotFoundError(self.paths.database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.paths.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EDIT_TABLE} (
                edit_id TEXT PRIMARY KEY,
                master_id TEXT NOT NULL,
                scheme_name TEXT NOT NULL,
                source_table TEXT NOT NULL,
                category TEXT NOT NULL,
                record_kind TEXT NOT NULL,
                status_value TEXT NOT NULL,
                funding_minimum REAL,
                funding_maximum REAL,
                currency TEXT,
                editor TEXT NOT NULL,
                note TEXT,
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                write_result TEXT NOT NULL CHECK (
                    write_result IN (
                        'REVIEW_QUEUE_UPDATED',
                        'STAGING_UPDATED',
                        'PENDING_PUBLICATION_REVIEW'
                    )
                ),
                created_at TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                publication_action TEXT NOT NULL CHECK (
                    publication_action='NONE'
                )
            )
            """
        )
        ensure_column(
            connection,
            EDIT_TABLE,
            "applicant_types_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        ensure_column(
            connection,
            EDIT_TABLE,
            "startup_stages_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
                audit_id TEXT PRIMARY KEY,
                edit_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK (
                    event='QUICK_EDIT_SAVED'
                ),
                editor TEXT NOT NULL,
                event_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )

    def _queue_rows(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        if not table_exists(connection, "admin_review_queue"):
            return []
        rows = connection.execute(
            """
            SELECT master_id,scheme_name,source,record_kind,
                   programme_status,application_status,review_status,
                   validated_record_json,updated_at
            FROM admin_review_queue
            ORDER BY scheme_name
            """
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            record = loads(item.pop("validated_record_json", None), {})
            item.update(
                {
                    "source_table": "admin_review_queue",
                    "ministry": clean(record.get("ministry")),
                    "department": clean(record.get("department")),
                    "implementing_agency": clean(
                        record.get("implementing_agency")
                        or record.get("implementing_entity")
                    ),
                    "scheme_status": clean(record.get("scheme_status")),
                    "funding_minimum": (
                        (record.get("funding_amount") or {}).get("minimum")
                    ),
                    "funding_maximum": (
                        (record.get("funding_amount") or {}).get("maximum")
                    ),
                    "currency": (
                        (record.get("funding_amount") or {}).get("currency")
                        or "INR"
                    ),
                    "applicant_types": normalized_list(
                        record.get("applicant_types")
                        or record.get("applicant_type")
                        or record.get("beneficiary_types")
                    ),
                    "startup_stages": normalized_list(
                        record.get("startup_stages")
                        or record.get("startup_stage")
                        or record.get("stages")
                    ),
                    "raw_record": record,
                }
            )
            output.append(item)
        return output

    def _staging_rows(
        self,
        connection: sqlite3.Connection,
        excluded_ids: set[str],
    ) -> list[dict[str, Any]]:
        if not table_exists(connection, "scheme_staging"):
            return []
        columns = column_names(connection, "scheme_staging")
        optional = {
            "is_public": "is_public" if "is_public" in columns else "0 AS is_public",
            "publication_status": (
                "publication_status"
                if "publication_status" in columns
                else "'' AS publication_status"
            ),
            "raw_record_json": (
                "raw_record_json"
                if "raw_record_json" in columns
                else "NULL AS raw_record_json"
            ),
        }
        rows = connection.execute(
            f"""
            SELECT master_id,scheme_name,source,record_kind,
                   programme_status,application_status,scheme_status,
                   ministry,department,implementing_agency,
                   funding_minimum,funding_maximum,currency,
                   {optional['publication_status']},
                   {optional['is_public']},
                   {optional['raw_record_json']}
            FROM scheme_staging
            ORDER BY scheme_name
            """
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            master_id = clean(item.get("master_id"))
            if master_id in excluded_ids:
                continue
            record = loads(item.pop("raw_record_json", None), {})
            output.append(
                {
                    **item,
                    "source_table": "scheme_staging",
                    "review_status": "",
                    "applicant_types": normalized_list(
                        record.get("applicant_types")
                        or record.get("applicant_type")
                        or record.get("beneficiary_types")
                    ),
                    "startup_stages": normalized_list(
                        record.get("startup_stages")
                        or record.get("startup_stage")
                        or record.get("stages")
                    ),
                    "raw_record": record,
                }
            )
        return output

    def list_records(
        self,
        *,
        ministry: str = "",
        department: str = "",
        keyword: str = "",
        completeness_filter: str = "ALL",
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            queue = self._queue_rows(connection)
            queue_ids = {clean(row.get("master_id")) for row in queue}
            staging = self._staging_rows(connection, queue_ids)
        finally:
            connection.close()

        rows = [*queue, *staging]
        ministry_key = clean(ministry).casefold()
        department_key = clean(department).casefold()
        keyword_key = clean(keyword).casefold()

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if ministry_key and clean(row.get("ministry")).casefold() != ministry_key:
                continue
            if (
                department_key
                and clean(row.get("department")).casefold()
                != department_key
            ):
                continue
            haystack = " ".join(
                [
                    clean(row.get("scheme_name")),
                    clean(row.get("source")),
                    clean(row.get("ministry")),
                    clean(row.get("department")),
                    clean(row.get("record_kind")),
                    " ".join(row.get("applicant_types") or []),
                    " ".join(row.get("startup_stages") or []),
                ]
            ).casefold()
            if keyword_key and keyword_key not in haystack:
                continue
            assessment = completeness(row)
            row = {**row, **assessment}
            mode = clean(completeness_filter).upper() or "ALL"
            if mode == "INCOMPLETE" and assessment["ready_for_publication_review"]:
                continue
            filter_map = {
                "MISSING_CATEGORY": "category_missing",
                "MISSING_STATUS": "status_missing",
                "MISSING_TYPE": "type_missing",
                "MISSING_STAGE": "stage_missing",
                "MISSING_FUNDING": "funding_missing",
            }
            if mode in filter_map and not assessment[filter_map[mode]]:
                continue
            if mode == "PUBLISHED_PENDING" and not (
                clean(row.get("publication_status")).upper() == "PUBLISHED"
                and self._has_pending_publication_review(clean(row.get("master_id")))
            ):
                continue
            filtered.append(row)

        filtered.sort(
            key=lambda row: (
                clean(row.get("ministry")).casefold(),
                clean(row.get("department")).casefold(),
                clean(row.get("scheme_name")).casefold(),
            )
        )
        return filtered

    def _has_pending_publication_review(self, master_id: str) -> bool:
        connection = self._connect()
        try:
            if not table_exists(connection, EDIT_TABLE):
                return False
            return connection.execute(
                f"SELECT 1 FROM {EDIT_TABLE} WHERE master_id=? AND write_result='PENDING_PUBLICATION_REVIEW' LIMIT 1",
                (master_id,),
            ).fetchone() is not None
        finally:
            connection.close()

    def completeness_dashboard(self, records: list[dict[str, Any]] | None = None) -> dict[str, int]:
        rows = records if records is not None else self.list_records()
        assessed = [row if "readiness_status" in row else {**row, **completeness(row)} for row in rows]
        return {
            "total_records": len(assessed),
            "category_missing": sum(bool(row["category_missing"]) for row in assessed),
            "status_missing": sum(bool(row["status_missing"]) for row in assessed),
            "type_missing": sum(bool(row["type_missing"]) for row in assessed),
            "stage_missing": sum(bool(row["stage_missing"]) for row in assessed),
            "funding_missing": sum(bool(row["funding_missing"]) for row in assessed),
            "official_source_missing": sum(bool(row["official_source_missing"]) for row in assessed),
            "parent_programme_missing": sum(bool(row["parent_programme_missing"]) for row in assessed),
            "ready_for_publication_review": sum(bool(row["ready_for_publication_review"]) for row in assessed),
        }

    def filter_options(self) -> dict[str, list[str]]:
        rows = self.list_records()
        return {
            "ministries": sorted(
                {clean(row.get("ministry")) for row in rows if clean(row.get("ministry"))}
            ),
            "departments": sorted(
                {clean(row.get("department")) for row in rows if clean(row.get("department"))}
            ),
        }

    def export_csv(self, records: list[dict[str, Any]]) -> bytes:
        output = io.StringIO(newline="")
        fields = [
            "master_id",
            "scheme_name",
            "ministry",
            "department",
            "source",
            "category",
            "status",
            "applicant_types",
            "startup_stages",
            "funding_minimum",
            "funding_maximum",
            "currency",
            "review_status",
            "publication_status",
            "source_table",
            "admin_note",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "master_id": clean(record.get("master_id")),
                    "scheme_name": clean(record.get("scheme_name")),
                    "ministry": clean(record.get("ministry")),
                    "department": clean(record.get("department")),
                    "source": clean(record.get("source")),
                    "category": clean(record_value(record, "admin_category", "record_kind")),
                    "status": clean(
                        record.get("scheme_status")
                        or record.get("application_status")
                        or record.get("programme_status")
                    ),
                    "applicant_types": ";".join(
                        normalized_list(record.get("applicant_types"))
                    ),
                    "startup_stages": ";".join(
                        normalized_list(record.get("startup_stages"))
                    ),
                    "funding_minimum": record.get("funding_minimum"),
                    "funding_maximum": record.get("funding_maximum"),
                    "currency": clean(record.get("currency")) or "INR",
                    "review_status": clean(record.get("review_status")),
                    "publication_status": clean(
                        record.get("publication_status")
                    ),
                    "source_table": clean(record.get("source_table")),
                    "admin_note": clean(record_value(record, "admin_note")),
                }
            )
        return output.getvalue().encode("utf-8-sig")

    def preview_csv_import(self, data: bytes) -> dict[str, Any]:
        text = data.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        current = {
            clean(row.get("master_id")): row
            for row in self.list_records()
        }
        errors: list[str] = []
        previews: list[dict[str, Any]] = []
        seen: set[str] = set()
        for number, row in enumerate(rows, 2):
            master_id = clean(row.get("master_id"))
            if not master_id or master_id not in current:
                errors.append(f"Row {number}: unknown master_id.")
                continue
            if master_id in seen:
                errors.append(f"Row {number}: duplicate master_id {master_id}.")
                continue
            seen.add(master_id)
            existing = current[master_id]
            immutable_checks = {
                "scheme_name": clean(existing.get("scheme_name")),
                "department": clean(existing.get("department")),
                "publication_status": clean(existing.get("publication_status")),
                "application_url": clean(record_value(existing, "application_url")),
                "official_source": clean(record_value(existing, "official_page_url", "official_source_url", "official_source")),
            }
            changed_immutable = [key for key, value in immutable_checks.items() if key in row and clean(row.get(key)) != value]
            if changed_immutable:
                errors.append(f"Row {number}: immutable field changed: {', '.join(changed_immutable)}.")
                continue
            try:
                preview = self.preview(
                    master_id=master_id,
                    source_table=clean(existing.get("source_table")),
                    selected_categories=[clean(row.get("category"))],
                    selected_statuses=[clean(row.get("status"))],
                    selected_applicant_types=normalized_list(row.get("applicant_types")),
                    selected_startup_stages=normalized_list(row.get("startup_stages")),
                    funding_minimum=self._csv_number(row.get("funding_minimum")),
                    funding_maximum=self._csv_number(row.get("funding_maximum")),
                    editor="CSV Admin",
                    note=clean(row.get("admin_note")),
                )
                previews.append(preview)
            except Exception as exc:
                errors.append(f"Row {number}: {exc}")
        return {"row_count": len(rows), "previews": previews, "errors": errors, "valid": bool(rows) and not errors}

    @staticmethod
    def _csv_number(value: Any) -> float | None:
        text = clean(value)
        if not text:
            return None
        return float(text.replace(",", ""))

    def apply_csv_import(self, import_preview: dict[str, Any], *, confirmation: str) -> list[dict[str, Any]]:
        if not import_preview.get("valid") or import_preview.get("errors"):
            raise ValueError("CSV import contains validation errors.")
        return [self.apply(payload, confirmation=confirmation) for payload in import_preview["previews"]]

    def public_dashboard_preview(self, record: dict[str, Any]) -> dict[str, Any]:
        assessment = completeness(record)
        minimum = record_value(record, "funding_minimum")
        maximum = record_value(record, "funding_maximum")
        application_status = clean(record_value(record, "application_status", "scheme_status", "programme_status")).upper()
        application_url = clean(record_value(record, "application_url"))
        return {
            "title": clean(record.get("scheme_name")),
            "department": clean(record.get("department") or record.get("ministry") or record.get("source")),
            "category": clean(record_value(record, "admin_category", "record_kind")),
            "status": application_status,
            "type": "; ".join(normalized_list(record_value(record, "applicant_types"))),
            "stage": "; ".join(normalized_list(record_value(record, "startup_stages"))),
            "funding_range": {"minimum": minimum, "maximum": maximum, "currency": clean(record.get("currency")) or "INR"},
            "official_reference_url": clean(record_value(record, "official_page_url", "official_source_url", "official_source")),
            "apply_button_eligible": application_status == "OPEN" and bool(application_url) and assessment["ready_for_publication_review"],
            "application_url": application_url if application_status == "OPEN" else "",
            "preview_only": True,
            "publication_action": "NONE",
        }

    def _current_record(
        self,
        connection: sqlite3.Connection,
        master_id: str,
        source_table: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if source_table == "admin_review_queue":
            row = connection.execute(
                "SELECT * FROM admin_review_queue WHERE master_id=?",
                (master_id,),
            ).fetchone()
            if row is None:
                raise KeyError(master_id)
            record = loads(row["validated_record_json"], {})
            return dict(row), record

        if source_table == "scheme_staging":
            row = connection.execute(
                "SELECT * FROM scheme_staging WHERE master_id=?",
                (master_id,),
            ).fetchone()
            if row is None:
                raise KeyError(master_id)
            record = loads(
                row["raw_record_json"]
                if "raw_record_json" in row.keys()
                else None,
                {},
            )
            return dict(row), record
        raise ValueError("Unsupported source table.")

    def preview(
        self,
        *,
        master_id: str,
        source_table: str,
        selected_categories: list[str],
        selected_statuses: list[str],
        selected_applicant_types: list[str] | None = None,
        selected_startup_stages: list[str] | None = None,
        funding_minimum: float | None = None,
        funding_maximum: float | None = None,
        editor: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        allowed_categories = set(self.config.get("categories", []))
        categories = [
            clean(value)
            for value in selected_categories
            if clean(value)
        ]
        if len(categories) != 1:
            raise ValueError("Select exactly one category checkbox.")
        category = categories[0]
        if category not in allowed_categories:
            raise ValueError("Unsupported category.")

        statuses = [
            clean(value)
            for value in selected_statuses
            if clean(value)
        ]
        if len(statuses) != 1:
            raise ValueError("Select exactly one status checkbox.")
        status_value = statuses[0]

        permanent = category in {"SCHEME", "PROGRAMME"}
        allowed_statuses = set(
            self.config.get(
                "scheme_programme_statuses"
                if permanent
                else "call_statuses",
                [],
            )
        )
        if status_value not in allowed_statuses:
            raise ValueError("The selected status does not match the category.")

        applicant_order = list(self.config.get("applicant_types", []))
        stage_order = list(self.config.get("startup_stages", []))
        applicant_selection = (
            applicant_order
            if selected_applicant_types is None
            else normalized_list(selected_applicant_types)
        )
        stage_selection = (
            stage_order
            if selected_startup_stages is None
            else normalized_list(selected_startup_stages)
        )
        applicant_types = [
            value for value in applicant_order
            if value in applicant_selection
        ]
        startup_stages = [
            value for value in stage_order
            if value in stage_selection
        ]
        if not applicant_types:
            raise ValueError(
                "Select All, Individual or Startup under Type."
            )
        if not startup_stages:
            raise ValueError(
                "Select All or at least one startup stage."
            )

        if funding_minimum is not None and funding_minimum < 0:
            raise ValueError("Funding minimum cannot be negative.")
        if funding_maximum is not None and funding_maximum < 0:
            raise ValueError("Funding maximum cannot be negative.")
        if (
            funding_minimum is not None
            and funding_maximum is not None
            and funding_minimum > funding_maximum
        ):
            raise ValueError(
                "Funding minimum cannot be greater than funding maximum."
            )
        if not clean(editor):
            raise ValueError("Admin name is required.")

        connection = self._connect()
        try:
            row, record = self._current_record(
                connection,
                clean(master_id),
                clean(source_table),
            )
        finally:
            connection.close()

        before = copy.deepcopy(record)
        after = copy.deepcopy(record)
        after["master_id"] = clean(master_id)
        after["scheme_name"] = clean(
            after.get("scheme_name")
            or row.get("scheme_name")
        )
        record_kind = clean(
            self.config.get("record_kind_map", {}).get(category)
        )
        after["record_kind"] = record_kind
        after["admin_category"] = category
        after["category_confirmed"] = True

        if permanent:
            after["programme_status"] = status_value
            after["scheme_status"] = status_value
            after["application_status"] = "NOT_APPLICABLE"
        else:
            after["application_status"] = status_value
            if category in {
                "HISTORICAL_REFERENCE",
                "SUPPORTING_DOCUMENT",
                "NON_CATALOGUE",
            }:
                after["application_url"] = ""

        funding = dict(after.get("funding_amount") or {})
        funding["minimum"] = funding_minimum
        funding["maximum"] = funding_maximum
        funding["currency"] = clean(
            funding.get("currency")
            or self.config.get("currency")
            or "INR"
        )
        after["funding_amount"] = funding
        after["funding_reviewed"] = True
        after["status_confirmed"] = True
        after["applicant_types"] = applicant_types
        after["type_confirmed"] = True
        after["applicant_type_scope"] = (
            "ALL" if applicant_types == applicant_order else "SELECTED"
        )
        after["startup_stages"] = startup_stages
        after["stage_confirmed"] = True
        after["startup_stage_scope"] = (
            "ALL" if startup_stages == stage_order else "SELECTED"
        )
        after["admin_note"] = clean(note)

        columns = {
            "master_id": clean(master_id),
            "scheme_name": after["scheme_name"],
            "record_kind": record_kind,
            "programme_status": clean(after.get("programme_status")),
            "application_status": clean(after.get("application_status")),
            "scheme_status": clean(after.get("scheme_status")),
            "funding_minimum": funding_minimum,
            "funding_maximum": funding_maximum,
            "currency": funding["currency"],
            "applicant_types_json": stable_json(applicant_types),
            "startup_stages_json": stable_json(startup_stages),
        }
        payload = {
            "version": VERSION,
            "master_id": clean(master_id),
            "source_table": clean(source_table),
            "category": category,
            "status_value": status_value,
            "applicant_types": applicant_types,
            "startup_stages": startup_stages,
            "editor": clean(editor),
            "note": clean(note),
            "before": before,
            "after": after,
            "columns": columns,
            "publication_action": "NONE",
        }
        payload["edit_id"] = (
            "quickedit_"
            + hashlib.sha256(
                stable_json(payload).encode("utf-8")
            ).hexdigest()[:24]
        )
        payload["confirmation_required"] = clean(
            self.config.get("confirmation_phrase")
        )
        return payload

    def _is_public(
        self,
        connection: sqlite3.Connection,
        master_id: str,
    ) -> bool:
        if not table_exists(connection, "scheme_staging"):
            return False
        columns = column_names(connection, "scheme_staging")
        checks: list[str] = []
        if "is_public" in columns:
            checks.append("COALESCE(is_public,0)=1")
        if "publication_status" in columns:
            checks.append(
                "UPPER(COALESCE(publication_status,''))='PUBLISHED'"
            )
        if not checks:
            return False
        row = connection.execute(
            f"""
            SELECT CASE WHEN ({' OR '.join(checks)})
                        THEN 1 ELSE 0 END
            FROM scheme_staging
            WHERE master_id=?
            """,
            (master_id,),
        ).fetchone()
        return bool(row and row[0])

    def _update_queue(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        now: str,
    ) -> None:
        after = payload["after"]
        columns = payload["columns"]
        record_hash = hashlib.sha256(
            stable_json(after).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            UPDATE admin_review_queue
            SET scheme_name=?,record_kind=?,programme_status=?,
                application_status=?,validated_record_json=?,
                record_hash=?,updated_at=?
            WHERE master_id=?
            """,
            (
                columns["scheme_name"],
                columns["record_kind"],
                columns["programme_status"],
                columns["application_status"],
                stable_json(after),
                record_hash,
                now,
                payload["master_id"],
            ),
        )

    def _update_staging(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        now: str,
    ) -> None:
        columns_available = column_names(connection, "scheme_staging")
        after = payload["after"]
        columns = payload["columns"]
        assignments: list[str] = []
        values: list[Any] = []
        for key in (
            "scheme_name",
            "record_kind",
            "programme_status",
            "application_status",
            "scheme_status",
            "funding_minimum",
            "funding_maximum",
            "currency",
        ):
            if key in columns_available:
                assignments.append(f"{key}=?")
                values.append(columns[key])
        for candidate in (
            "applicant_types_json",
            "applicant_type_json",
            "beneficiary_types_json",
        ):
            if candidate in columns_available:
                assignments.append(f"{candidate}=?")
                values.append(columns["applicant_types_json"])
                break
        for candidate in (
            "startup_stages_json",
            "startup_stage_json",
            "stages_json",
        ):
            if candidate in columns_available:
                assignments.append(f"{candidate}=?")
                values.append(columns["startup_stages_json"])
                break
        if "raw_record_json" in columns_available:
            assignments.append("raw_record_json=?")
            values.append(stable_json(after))
        if "record_hash" in columns_available:
            assignments.append("record_hash=?")
            values.append(
                hashlib.sha256(
                    stable_json(after).encode("utf-8")
                ).hexdigest()
            )
        if "last_loaded_at" in columns_available:
            assignments.append("last_loaded_at=?")
            values.append(now)
        if not assignments:
            raise RuntimeError("No editable staging columns were found.")
        values.append(payload["master_id"])
        connection.execute(
            f"""
            UPDATE scheme_staging
            SET {', '.join(assignments)}
            WHERE master_id=?
            """,
            values,
        )

    def apply(
        self,
        payload: dict[str, Any],
        *,
        confirmation: str,
    ) -> dict[str, Any]:
        expected = clean(self.config.get("confirmation_phrase"))
        if clean(confirmation) != expected:
            raise PermissionError(
                f'Exact confirmation required: "{expected}"'
            )

        current = self.preview(
            master_id=payload["master_id"],
            source_table=payload["source_table"],
            selected_categories=[payload["category"]],
            selected_statuses=[payload["status_value"]],
            selected_applicant_types=payload["applicant_types"],
            selected_startup_stages=payload["startup_stages"],
            funding_minimum=payload["columns"]["funding_minimum"],
            funding_maximum=payload["columns"]["funding_maximum"],
            editor=payload["editor"],
            note=payload["note"],
        )
        if current["edit_id"] != payload["edit_id"]:
            raise RuntimeError("The selected record changed after preview.")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_root = (
            self.paths.project_root.parent
            / f"SSIP_DB_Backup_v3_4_3_8_1_{timestamp}"
        )
        backup_path = create_consistent_backup(
            self.paths.database_path,
            backup_root,
        )

        connection = self._connect()
        try:
            self.ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            is_public = self._is_public(
                connection,
                current["master_id"],
            )
            now = utc_now()

            if current["source_table"] == "admin_review_queue":
                self._update_queue(connection, current, now)
                if (
                    table_exists(connection, "scheme_staging")
                    and connection.execute(
                        "SELECT 1 FROM scheme_staging WHERE master_id=?",
                        (current["master_id"],),
                    ).fetchone()
                    and not is_public
                ):
                    self._update_staging(connection, current, now)
                    write_result = "STAGING_UPDATED"
                elif is_public:
                    write_result = "PENDING_PUBLICATION_REVIEW"
                else:
                    write_result = "REVIEW_QUEUE_UPDATED"
            elif current["source_table"] == "scheme_staging":
                if is_public:
                    write_result = "PENDING_PUBLICATION_REVIEW"
                else:
                    self._update_staging(connection, current, now)
                    write_result = "STAGING_UPDATED"
            else:
                raise ValueError("Unsupported source table.")

            connection.execute(
                f"""
                INSERT INTO {EDIT_TABLE} (
                    edit_id,master_id,scheme_name,source_table,
                    category,record_kind,status_value,
                    funding_minimum,funding_maximum,currency,
                    applicant_types_json,startup_stages_json,
                    editor,note,before_json,after_json,
                    write_result,created_at,backup_path,
                    publication_action
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'NONE')
                """,
                (
                    current["edit_id"],
                    current["master_id"],
                    current["columns"]["scheme_name"],
                    current["source_table"],
                    current["category"],
                    current["columns"]["record_kind"],
                    current["status_value"],
                    current["columns"]["funding_minimum"],
                    current["columns"]["funding_maximum"],
                    current["columns"]["currency"],
                    stable_json(current["applicant_types"]),
                    stable_json(current["startup_stages"]),
                    current["editor"],
                    current["note"],
                    stable_json(current["before"]),
                    stable_json(current["after"]),
                    write_result,
                    now,
                    str(backup_path),
                ),
            )
            audit_payload = {
                **current,
                "write_result": write_result,
                "backup_path": str(backup_path),
                "created_at": now,
            }
            connection.execute(
                f"""
                INSERT INTO {AUDIT_TABLE} (
                    audit_id,edit_id,master_id,event,
                    editor,event_at,payload_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    "audit_"
                    + hashlib.sha256(
                        stable_json(audit_payload).encode("utf-8")
                    ).hexdigest()[:24],
                    current["edit_id"],
                    current["master_id"],
                    "QUICK_EDIT_SAVED",
                    current["editor"],
                    now,
                    stable_json(audit_payload),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "edit_id": current["edit_id"],
            "master_id": current["master_id"],
            "write_result": write_result,
            "backup_path": str(backup_path),
            "publication_action": "NONE",
            "public_visibility_changed": False,
        }

    def recent_edits(self, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            self.ensure_schema(connection)
            rows = connection.execute(
                f"""
                SELECT edit_id,master_id,scheme_name,category,
                       status_value,funding_minimum,funding_maximum,
                       applicant_types_json,startup_stages_json,
                       editor,write_result,created_at
                FROM {EDIT_TABLE}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()


def build_service(project_root: Path) -> AdminQuickEditorService:
    paths = QuickEditorPaths.defaults(project_root)
    config = json.loads(
        paths.config_path.read_text(encoding="utf-8-sig")
    )
    return AdminQuickEditorService(paths, config)
