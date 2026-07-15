from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "3.4.3.8.1"
EDIT_TABLE = "admin_quick_edit_requests_v3_4_3_8_1"
AUDIT_TABLE = "admin_quick_edit_audit_v3_4_3_8_1"


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
                ]
            ).casefold()
            if keyword_key and keyword_key not in haystack:
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
        funding_minimum: float | None,
        funding_maximum: float | None,
        editor: str,
        note: str,
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
        }
        payload = {
            "version": VERSION,
            "master_id": clean(master_id),
            "source_table": clean(source_table),
            "category": category,
            "status_value": status_value,
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
                    editor,note,before_json,after_json,
                    write_result,created_at,backup_path,
                    publication_action
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'NONE')
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
