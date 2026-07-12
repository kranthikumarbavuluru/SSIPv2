from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


logger = logging.getLogger(__name__)

HOTFIX_VERSION = "2.5.1"
MEITY_SOURCE_NAME = "MeitY Startup Hub"

DECISION_APPROVED = "APPROVED_FOR_DATABASE"
DECISION_ADMIN_REVIEW = "NEEDS_ADMIN_REVIEW"
DECISION_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
DECISION_REJECTED = "REJECTED"
REVIEW_DECISIONS = {DECISION_ADMIN_REVIEW, DECISION_MORE_EVIDENCE}
VALID_DECISIONS = {
    DECISION_APPROVED,
    DECISION_ADMIN_REVIEW,
    DECISION_MORE_EVIDENCE,
    DECISION_REJECTED,
}

AUDIT_TABLE = "meity_incremental_staging_audit_v2_5"

DEFAULT_CONFIG: dict[str, Any] = {
    "database_path": None,
    "approved_filename": "approved_for_database_v2_4.json",
    "review_filename": "admin_review_queue_v2_4.json",
    "rejected_filename": "rejected_scheme_records_v2_4.json",
    "summary_filename": "meity_incremental_staging_summary_v2_5.json",
    "audit_filename": "meity_incremental_staging_audit_v2_5.json",
    "failures_filename": "meity_incremental_staging_failures_v2_5.json",
    "plan_filename": "meity_incremental_staging_plan_v2_5.json",
    "backup_subdirectory": "backups",
    "busy_timeout_ms": 20000,
    "preserve_workflow_fields": True,
    "require_meity_source": True,
}

STAGING_TABLE_CANDIDATES = (
    "scheme_staging",
    "schemes_staging",
    "staging_schemes",
    "scheme_stage",
)
REVIEW_TABLE_CANDIDATES = (
    "admin_review_queue",
    "scheme_admin_review_queue",
    "validation_review_queue",
    "review_queue",
)

DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
EXCLUDED_SCAN_PARTS = {
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".git",
    "extraction_cache_v1",
    "backups",
    "backup",
}

MASTER_ID_COLUMNS = (
    "master_id",
    "scheme_master_id",
    "candidate_id",
    "external_id",
    "source_record_id",
)
SCHEME_NAME_COLUMNS = ("scheme_name", "canonical_name", "name", "title")
SOURCE_COLUMNS = ("source", "source_name", "authority", "source_authority")
URL_COLUMNS = ("official_page_url", "official_url", "source_url", "url")
PAYLOAD_COLUMNS = (
    "record_json",
    "payload_json",
    "data_json",
    "validated_record_json",
    "scheme_json",
    "raw_json",
    "json_payload",
    "record_payload",
    "validation_record_json",
    "scheme_data_json",
    "record_data_json",
    "raw_record_json",
    "scheme_data",
    "record_data",
    "payload",
)
FINGERPRINT_COLUMNS = (
    "validation_fingerprint",
    "load_fingerprint",
    "record_fingerprint",
    "record_hash",
    "fingerprint",
)

WORKFLOW_FIELD_TOKENS = {
    "status",
    "review_status",
    "queue_status",
    "admin_status",
    "admin_decision",
    "decision",
    "review_decision",
    "reviewed_by",
    "reviewer",
    "reviewer_id",
    "assigned_to",
    "assignee",
    "reviewed_at",
    "decided_at",
    "completed_at",
    "resolved_at",
    "admin_notes",
    "review_notes",
    "reviewer_notes",
    "decision_notes",
    "decision_note",
    "resolution_notes",
    "action_taken",
}

FINAL_WORKFLOW_VALUES = {
    "APPROVED",
    "REJECTED",
    "RESOLVED",
    "COMPLETED",
    "CLOSED",
    "PUBLISHED",
    "ACCEPTED",
    "DECLINED",
}

VOLATILE_KEYS = {
    "validated_at",
    "validation_metadata",
    "loaded_at",
    "staged_at",
    "updated_at",
    "created_at",
    "checked_at",
    "run_id",
    "action",
}


@dataclass(slots=True)
class ColumnInfo:
    name: str
    declared_type: str
    not_null: bool
    default_value: Any
    primary_key_position: int

    @property
    def is_integer_primary_key(self) -> bool:
        return self.primary_key_position > 0 and "INT" in self.declared_type.upper()


@dataclass(slots=True)
class TableAdapter:
    table_name: str
    columns: list[ColumnInfo]
    business_key_columns: tuple[str, ...]
    category: str


@dataclass(slots=True)
class LoadItem:
    category: str
    record: dict[str, Any]
    master_key: str
    decision: str
    fingerprint: str
    target_table: str | None


@dataclass(slots=True)
class StagingLoadResult:
    summary: dict[str, Any]
    audit: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    plan: list[dict[str, Any]]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split())


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(default)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalise_for_fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key_text = str(key)
            if key_text in VOLATILE_KEYS:
                continue
            if key_text == "validation_metadata" and isinstance(item, dict):
                item = {
                    inner_key: inner_value
                    for inner_key, inner_value in item.items()
                    if inner_key not in {"checked_at", "run_id", "action"}
                }
            output[key_text] = _normalise_for_fingerprint(item)
        return output
    if isinstance(value, list):
        return [_normalise_for_fingerprint(item) for item in value]
    return value


def record_fingerprint(record: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _normalise_for_fingerprint(dict(record)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MeityIncrementalStagingLoaderV25:
    """Incrementally load v2.4 MeitY validation decisions into SQLite.

    The loader discovers and introspects the existing v1 database rather than
    hard-coding a database filename or exact table column list. Approved records
    are upserted into the existing staging table. Review and more-evidence records
    are upserted into the existing admin-review queue. Rejected records are audit
    only. Every database mutation is transaction-bound and preceded by a SQLite
    online backup.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        config_path: Path | None = None,
        database_path: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.config = dict(DEFAULT_CONFIG)
        if config_path is None:
            config_path = self.project_root / "config" / "meity_staging_loader_v2_5.json"
        file_config = load_json(config_path, default={})
        if isinstance(file_config, dict):
            self.config.update(file_config)

        configured_database = database_path or self.config.get("database_path")
        self.explicit_database_path = (
            self._resolve_project_path(configured_database)
            if configured_database
            else None
        )

    def _resolve_project_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.project_root / path).resolve()

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _first_present(candidates: Iterable[str], available: set[str]) -> str | None:
        lookup = {name.casefold(): name for name in available}
        for candidate in candidates:
            if candidate.casefold() in lookup:
                return lookup[candidate.casefold()]
        return None

    def _inspect_database_candidate(self, path: Path) -> dict[str, Any] | None:
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=3)
            try:
                tables = self._table_names(connection)
            finally:
                connection.close()
        except sqlite3.Error:
            return None

        staging = self._first_present(STAGING_TABLE_CANDIDATES, tables)
        review = self._first_present(REVIEW_TABLE_CANDIDATES, tables)
        score = 0
        if review:
            score += 120
        if staging:
            score += 100
        if "schemes" in {name.casefold() for name in tables}:
            score += 30
        if "review_actions" in {name.casefold() for name in tables}:
            score += 20
        if AUDIT_TABLE.casefold() in {name.casefold() for name in tables}:
            score += 10
        score += min(15, len(tables))
        path_text = str(path).casefold()
        if any(token in path_text for token in ("backup", "pre_v", ".bak")):
            score -= 80

        return {
            "path": path,
            "score": score,
            "tables": sorted(tables),
            "staging_table": staging,
            "review_table": review,
        }

    def _database_candidates(self) -> list[Path]:
        likely = [
            self.data_dir / "ssip.db",
            self.data_dir / "ssip.sqlite",
            self.data_dir / "ssip.sqlite3",
            self.data_dir / "ssip_staging.db",
            self.data_dir / "scheme_staging.db",
            self.data_dir / "staging.db",
            self.project_root / "ssip.db",
            self.project_root / "database" / "ssip.db",
            self.project_root / "db" / "ssip.db",
        ]
        candidates: list[Path] = []
        seen: set[Path] = set()
        for path in likely:
            resolved = path.resolve()
            if resolved.exists() and resolved not in seen:
                candidates.append(resolved)
                seen.add(resolved)

        for path in self.project_root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in DB_SUFFIXES:
                continue
            try:
                relative_parts = {part.casefold() for part in path.relative_to(self.project_root).parts}
            except ValueError:
                relative_parts = set()
            if relative_parts & EXCLUDED_SCAN_PARTS:
                continue
            resolved = path.resolve()
            if resolved not in seen:
                candidates.append(resolved)
                seen.add(resolved)
        return candidates

    def discover_database(self) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
        if self.explicit_database_path is not None:
            if not self.explicit_database_path.exists():
                raise FileNotFoundError(
                    f"Configured database does not exist: {self.explicit_database_path}"
                )
            inspection = self._inspect_database_candidate(self.explicit_database_path)
            if inspection is None:
                raise ValueError(f"Not a readable SQLite database: {self.explicit_database_path}")
            return self.explicit_database_path, inspection, [inspection]

        inspections = [
            item
            for path in self._database_candidates()
            if (item := self._inspect_database_candidate(path)) is not None
        ]
        inspections.sort(
            key=lambda item: (
                -int(item["score"]),
                len(str(item["path"])),
                str(item["path"]).casefold(),
            )
        )
        if not inspections:
            raise FileNotFoundError(
                "No SQLite database was found under the SSIP project. "
                "Use --database with the existing staging database path."
            )

        best = inspections[0]
        if not best.get("review_table") and not best.get("staging_table"):
            raise ValueError(
                "SQLite databases were found, but none contains a recognised "
                "scheme staging or admin review queue table. Use --database to "
                "select the correct database."
            )
        return Path(best["path"]), best, inspections

    @staticmethod
    def _columns(connection: sqlite3.Connection, table_name: str) -> list[ColumnInfo]:
        rows = connection.execute(
            f"PRAGMA table_info({quote_identifier(table_name)})"
        ).fetchall()
        return [
            ColumnInfo(
                name=str(row[1]),
                declared_type=str(row[2] or ""),
                not_null=bool(row[3]),
                default_value=row[4],
                primary_key_position=int(row[5] or 0),
            )
            for row in rows
        ]

    @staticmethod
    def _find_column(columns: Sequence[ColumnInfo], candidates: Iterable[str]) -> str | None:
        lookup = {column.name.casefold(): column.name for column in columns}
        for candidate in candidates:
            if candidate.casefold() in lookup:
                return lookup[candidate.casefold()]
        return None

    def _build_adapter(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        category: str,
    ) -> TableAdapter:
        columns = self._columns(connection, table_name)
        if not columns:
            raise ValueError(f"Target table has no columns: {table_name}")

        master_id = self._find_column(columns, MASTER_ID_COLUMNS)
        if master_id:
            business_key = (master_id,)
        else:
            source = self._find_column(columns, SOURCE_COLUMNS)
            scheme_name = self._find_column(columns, SCHEME_NAME_COLUMNS)
            if source and scheme_name:
                business_key = (source, scheme_name)
            else:
                url = self._find_column(columns, URL_COLUMNS)
                if url:
                    business_key = (url,)
                else:
                    raise ValueError(
                        f"Cannot identify a duplicate-safe business key for table "
                        f"{table_name}. Expected master_id, source+scheme_name, or URL."
                    )
        return TableAdapter(
            table_name=table_name,
            columns=columns,
            business_key_columns=business_key,
            category=category,
        )

    @staticmethod
    def _record_decision(record: Mapping[str, Any]) -> str:
        for key in ("validation_decision", "decision", "validation_status"):
            value = normalize_space(record.get(key)).upper()
            if value in VALID_DECISIONS:
                return value
        return ""

    @staticmethod
    def _record_master_key(record: Mapping[str, Any]) -> str:
        master_id = normalize_space(record.get("master_id"))
        if master_id:
            return master_id
        source = normalize_space(record.get("source")).casefold()
        scheme_name = normalize_space(record.get("scheme_name")).casefold()
        official_url = normalize_space(record.get("official_page_url")).casefold()
        fallback = "|".join((source, scheme_name, official_url))
        return "fallback:" + hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _load_record_list(path: Path) -> list[dict[str, Any]]:
        payload = load_json(path, default=[])
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON list in {path}, got {type(payload).__name__}")
        return [item for item in payload if isinstance(item, dict)]

    def _load_items(
        self,
        *,
        approved_path: Path,
        review_path: Path,
        rejected_path: Path,
        staging_table: str | None,
        review_table: str | None,
    ) -> tuple[list[LoadItem], list[dict[str, Any]]]:
        inputs = (
            ("approved", approved_path, DECISION_APPROVED, staging_table),
            ("review", review_path, None, review_table),
            ("rejected", rejected_path, DECISION_REJECTED, None),
        )
        failures: list[dict[str, Any]] = []
        items_by_key: dict[str, LoadItem] = {}

        for category, path, expected_decision, target_table in inputs:
            records = self._load_record_list(path)
            for position, record in enumerate(records):
                master_key = self._record_master_key(record)
                source = normalize_space(record.get("source"))
                decision = self._record_decision(record)

                if self.config.get("require_meity_source", True) and source.casefold() != MEITY_SOURCE_NAME.casefold():
                    failures.append(
                        {
                            "category": category,
                            "input_path": str(path),
                            "position": position,
                            "master_key": master_key,
                            "scheme_name": record.get("scheme_name"),
                            "error_type": "NON_MEITY_RECORD_IN_INCREMENTAL_INPUT",
                            "error_message": f"Expected source '{MEITY_SOURCE_NAME}', got '{source}'.",
                        }
                    )
                    continue

                if category == "review" and decision not in REVIEW_DECISIONS:
                    failures.append(
                        {
                            "category": category,
                            "input_path": str(path),
                            "position": position,
                            "master_key": master_key,
                            "scheme_name": record.get("scheme_name"),
                            "error_type": "INVALID_REVIEW_DECISION",
                            "error_message": f"Expected one of {sorted(REVIEW_DECISIONS)}, got '{decision or 'missing'}'.",
                        }
                    )
                    continue
                if expected_decision and decision != expected_decision:
                    failures.append(
                        {
                            "category": category,
                            "input_path": str(path),
                            "position": position,
                            "master_key": master_key,
                            "scheme_name": record.get("scheme_name"),
                            "error_type": "DECISION_FILE_MISMATCH",
                            "error_message": f"Expected decision '{expected_decision}', got '{decision or 'missing'}'.",
                        }
                    )
                    continue
                if target_table is None and category != "rejected":
                    failures.append(
                        {
                            "category": category,
                            "input_path": str(path),
                            "position": position,
                            "master_key": master_key,
                            "scheme_name": record.get("scheme_name"),
                            "error_type": "TARGET_TABLE_NOT_FOUND",
                            "error_message": f"No target table was detected for {category} records.",
                        }
                    )
                    continue

                item = LoadItem(
                    category=category,
                    record=copy.deepcopy(record),
                    master_key=master_key,
                    decision=decision,
                    fingerprint=record_fingerprint(record),
                    target_table=target_table,
                )
                existing = items_by_key.get(master_key)
                if existing is not None:
                    failures.append(
                        {
                            "category": category,
                            "input_path": str(path),
                            "position": position,
                            "master_key": master_key,
                            "scheme_name": record.get("scheme_name"),
                            "error_type": "DUPLICATE_OR_CONFLICTING_INCREMENTAL_RECORD",
                            "error_message": (
                                f"The same record appears in both '{existing.category}' and "
                                f"'{category}' incremental inputs."
                            ),
                        }
                    )
                    continue
                items_by_key[master_key] = item

        return list(items_by_key.values()), failures

    @staticmethod
    def _json_text(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _priority(record: Mapping[str, Any]) -> str:
        decision = MeityIncrementalStagingLoaderV25._record_decision(record)
        programme_status = normalize_space(record.get("programme_status")).upper()
        reasons = {normalize_space(item).upper() for item in (record.get("validation_reasons") or [])}
        if decision == DECISION_MORE_EVIDENCE:
            return "HIGH"
        if "CONFLICT" in programme_status or any("CONFLICT" in reason for reason in reasons):
            return "HIGH"
        score = float(record.get("validation_score") or 0.0)
        return "MEDIUM" if score < 0.85 else "NORMAL"

    @staticmethod
    def _serialise_value(value: Any, column: ColumnInfo) -> Any:
        if value is None:
            return None
        declared = column.declared_type.upper()
        if isinstance(value, (dict, list, tuple, set)):
            return MeityIncrementalStagingLoaderV25._json_text(value)
        if isinstance(value, bool):
            return int(value)
        if "INT" in declared:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        if any(token in declared for token in ("REAL", "FLOA", "DOUB", "NUM")):
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def _recommended_actions(record: Mapping[str, Any], decision: str) -> list[str]:
        explicit = record.get("recommended_actions")
        if isinstance(explicit, list):
            return [normalize_space(item) for item in explicit if normalize_space(item)]

        programme_status = normalize_space(record.get("programme_status")).upper()
        if decision == DECISION_MORE_EVIDENCE:
            return ["Collect missing official-source evidence and revalidate the record."]
        if "CONFLICT" in programme_status:
            return [
                "Resolve the status or deadline conflict using the official MeitY source.",
                "Confirm the current application status before publication.",
            ]
        if decision == DECISION_ADMIN_REVIEW:
            return ["Review the validation reasons and official-source evidence before approval."]
        return []

    @staticmethod
    def _should_preserve_on_update(adapter: TableAdapter, column_name: str) -> bool:
        lower = column_name.casefold()
        if lower in {"created_at", "queued_at", "staged_at", "first_queued_at", "first_loaded_at"}:
            return True
        if lower == "decision":
            # In the production v1 review queue, `decision` is the validator's
            # decision while `review_status` stores the administrator workflow.
            available = {column.name.casefold() for column in adapter.columns}
            return "review_status" not in available
        return lower in WORKFLOW_FIELD_TOKENS

    def _column_value(
        self,
        *,
        column: ColumnInfo,
        item: LoadItem,
        now: str,
        run_id: str,
        is_insert: bool,
    ) -> tuple[bool, Any]:
        name = column.name
        lower = name.casefold()
        record = item.record

        if lower in {key.casefold() for key in PAYLOAD_COLUMNS}:
            return True, self._json_text(record)
        if lower in {key.casefold() for key in FINGERPRINT_COLUMNS}:
            return True, item.fingerprint
        if lower in {key.casefold() for key in MASTER_ID_COLUMNS}:
            return True, normalize_space(record.get("master_id")) or item.master_key
        if lower in {"scheme_id", "entity_id", "record_key"} and "INT" not in column.declared_type.upper():
            return True, normalize_space(record.get("master_id")) or item.master_key
        if lower in {key.casefold() for key in SCHEME_NAME_COLUMNS}:
            value = normalize_space(record.get("scheme_name") or record.get("canonical_name"))
            return bool(value), value
        if lower in {key.casefold() for key in SOURCE_COLUMNS}:
            value = normalize_space(record.get("source"))
            return bool(value), value
        if lower in {key.casefold() for key in URL_COLUMNS}:
            value = normalize_space(
                record.get("official_page_url")
                or record.get("application_url")
                or record.get("best_available_url")
            )
            return bool(value), value

        direct_lookup = {str(key).casefold(): value for key, value in record.items()}
        if lower in direct_lookup:
            return True, self._serialise_value(direct_lookup[lower], column)

        aliases: dict[str, Any] = {
            "validation_decision": item.decision,
            "validator_decision": item.decision,
            "validation_status": item.decision,
            "validation_score": record.get("validation_score"),
            "extraction_confidence": record.get("extraction_confidence"),
            "programme_status": record.get("programme_status"),
            "program_status": record.get("programme_status"),
            "quality_flags": record.get("quality_flags") or [],
            "quality_flags_json": record.get("quality_flags") or [],
            "validation_reasons": record.get("validation_reasons") or [],
            "validation_reasons_json": record.get("validation_reasons") or [],
            "decision_reasons_json": record.get("validation_reasons") or [],
            "reasons": record.get("validation_reasons") or [],
            "reasons_json": record.get("validation_reasons") or [],
            "warnings": record.get("warnings") or record.get("quality_flags") or [],
            "warnings_json": record.get("warnings") or record.get("quality_flags") or [],
            "critical_flags": record.get("critical_flags") or [],
            "critical_flags_json": record.get("critical_flags") or [],
            "recommended_actions": self._recommended_actions(record, item.decision),
            "recommended_actions_json": self._recommended_actions(record, item.decision),
            "validation_checks": record.get("validation_checks") or {},
            "validation_checks_json": record.get("validation_checks") or {},
            "priority": self._priority(record),
            "queue_priority": self._priority(record),
            "run_id": run_id,
            "loader_run_id": run_id,
            "loader_version": HOTFIX_VERSION,
            "hotfix_version": HOTFIX_VERSION,
            "updated_at": now,
            "modified_at": now,
            "last_updated_at": now,
            "loaded_at": now,
            "last_loaded_at": now,
            "staged_at": now,
            "queued_at": now,
            "submitted_at": now,
            "enqueued_at": now,
            "created_at": now,
            "last_import_run_id": run_id,
            "import_run_id": run_id,
            "review_type": "VALIDATION",
            "queue_type": "VALIDATION",
            "record_type": "SCHEME",
            "is_active": 1,
            "active": 1,
        }
        if is_insert and lower in {"first_queued_at", "first_loaded_at"}:
            return True, now

        if lower in aliases and aliases[lower] is not None:
            return True, self._serialise_value(aliases[lower], column)

        if is_insert and item.category == "review":
            if lower in {"review_status", "queue_status", "admin_status", "status"}:
                return True, "PENDING"
            if lower == "decision":
                return True, item.decision
        if is_insert and item.category == "approved":
            if lower in {"staging_status", "stage_status", "status"}:
                return True, "STAGED"
            if lower == "decision":
                return True, item.decision

        if column.primary_key_position > 0 and not column.is_integer_primary_key:
            return True, uuid.uuid4().hex

        if is_insert and column.not_null and column.default_value is None:
            if lower in {"record_id", "review_id", "queue_id", "staging_id", "item_id", "entity_key"}:
                return True, uuid.uuid4().hex
            if lower.endswith("_uuid"):
                return True, uuid.uuid4().hex

        return False, None

    def _build_values(
        self,
        *,
        adapter: TableAdapter,
        item: LoadItem,
        now: str,
        run_id: str,
        is_insert: bool,
        existing_row: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        values: dict[str, Any] = {}
        missing_required: list[str] = []

        for column in adapter.columns:
            if column.is_integer_primary_key:
                continue
            if not is_insert and column.primary_key_position > 0:
                continue
            if not is_insert and self.config.get("preserve_workflow_fields", True):
                if self._should_preserve_on_update(adapter, column.name):
                    continue

            available, value = self._column_value(
                column=column,
                item=item,
                now=now,
                run_id=run_id,
                is_insert=is_insert,
            )
            if available:
                values[column.name] = value
                continue

            if is_insert and column.not_null and column.default_value is None:
                missing_required.append(column.name)

        if not is_insert:
            # Ensure an update changes at least one safe timestamp or payload field.
            if not values:
                for column in adapter.columns:
                    if column.name.casefold() in {"updated_at", "modified_at", "last_updated_at"}:
                        values[column.name] = now
                        break

        return values, missing_required

    @staticmethod
    def _business_key_values(adapter: TableAdapter, item: LoadItem) -> tuple[Any, ...]:
        record = item.record
        values: list[Any] = []
        for column in adapter.business_key_columns:
            lower = column.casefold()
            if lower in {key.casefold() for key in MASTER_ID_COLUMNS}:
                values.append(normalize_space(record.get("master_id")) or item.master_key)
            elif lower in {key.casefold() for key in SOURCE_COLUMNS}:
                values.append(normalize_space(record.get("source")))
            elif lower in {key.casefold() for key in SCHEME_NAME_COLUMNS}:
                values.append(normalize_space(record.get("scheme_name")))
            elif lower in {key.casefold() for key in URL_COLUMNS}:
                values.append(normalize_space(record.get("official_page_url")))
            else:
                values.append(record.get(column))
        return tuple(values)

    @staticmethod
    def _select_existing(
        connection: sqlite3.Connection,
        adapter: TableAdapter,
        key_values: Sequence[Any],
    ) -> sqlite3.Row | None:
        where = " AND ".join(
            f"{quote_identifier(column)} = ?" for column in adapter.business_key_columns
        )
        return connection.execute(
            f"SELECT * FROM {quote_identifier(adapter.table_name)} WHERE {where} LIMIT 1",
            tuple(key_values),
        ).fetchone()

    @staticmethod
    def _workflow_state(row: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
        details: dict[str, Any] = {}
        final = False
        keys = set(row.keys()) if hasattr(row, "keys") else set(row)
        for field in WORKFLOW_FIELD_TOKENS:
            if field not in keys:
                continue
            value = row[field]
            if value not in (None, ""):
                details[field] = value
                if normalize_space(value).upper() in FINAL_WORKFLOW_VALUES:
                    final = True
        return final, details

    @staticmethod
    def _create_audit_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(AUDIT_TABLE)} (
                audit_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                master_key TEXT NOT NULL,
                master_id TEXT,
                scheme_name TEXT,
                source TEXT,
                input_category TEXT NOT NULL,
                validation_decision TEXT,
                target_table TEXT,
                target_business_key_json TEXT,
                action TEXT NOT NULL,
                validation_fingerprint TEXT NOT NULL,
                previous_fingerprint TEXT,
                workflow_preserved_json TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{AUDIT_TABLE}_master "
            f"ON {quote_identifier(AUDIT_TABLE)} (master_key, target_table, created_at)"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{AUDIT_TABLE}_fingerprint "
            f"ON {quote_identifier(AUDIT_TABLE)} (validation_fingerprint, target_table)"
        )

    @staticmethod
    def _latest_audit(
        connection: sqlite3.Connection,
        *,
        master_key: str,
        target_table: str | None,
    ) -> sqlite3.Row | None:
        tables = MeityIncrementalStagingLoaderV25._table_names(connection)
        if AUDIT_TABLE not in tables:
            return None
        return connection.execute(
            f"""
            SELECT * FROM {quote_identifier(AUDIT_TABLE)}
            WHERE master_key = ? AND COALESCE(target_table, '') = COALESCE(?, '')
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (master_key, target_table),
        ).fetchone()

    @staticmethod
    def _insert_row(
        connection: sqlite3.Connection,
        adapter: TableAdapter,
        values: Mapping[str, Any],
    ) -> int | None:
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO {quote_identifier(adapter.table_name)} "
            f"({', '.join(quote_identifier(column) for column in columns)}) "
            f"VALUES ({placeholders})"
        )
        cursor = connection.execute(sql, tuple(values[column] for column in columns))
        return cursor.lastrowid

    @staticmethod
    def _update_row(
        connection: sqlite3.Connection,
        adapter: TableAdapter,
        values: Mapping[str, Any],
        key_values: Sequence[Any],
    ) -> int:
        if not values:
            return 0
        set_clause = ", ".join(
            f"{quote_identifier(column)} = ?" for column in values
        )
        where = " AND ".join(
            f"{quote_identifier(column)} = ?" for column in adapter.business_key_columns
        )
        cursor = connection.execute(
            f"UPDATE {quote_identifier(adapter.table_name)} SET {set_clause} WHERE {where}",
            tuple(values[column] for column in values) + tuple(key_values),
        )
        return cursor.rowcount

    @staticmethod
    def _insert_audit_row(connection: sqlite3.Connection, audit: Mapping[str, Any]) -> None:
        columns = [
            "audit_id",
            "run_id",
            "master_key",
            "master_id",
            "scheme_name",
            "source",
            "input_category",
            "validation_decision",
            "target_table",
            "target_business_key_json",
            "action",
            "validation_fingerprint",
            "previous_fingerprint",
            "workflow_preserved_json",
            "details_json",
            "created_at",
        ]
        connection.execute(
            f"INSERT INTO {quote_identifier(AUDIT_TABLE)} "
            f"({', '.join(quote_identifier(column) for column in columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(audit.get(column) for column in columns),
        )

    @staticmethod
    def _online_backup(database_path: Path, backup_path: Path, busy_timeout_ms: int) -> None:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(database_path, timeout=max(5, busy_timeout_ms / 1000))
        destination = sqlite3.connect(backup_path)
        try:
            source.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            source.backup(destination)
        finally:
            destination.close()
            source.close()

    def _preflight_item(
        self,
        *,
        adapter: TableAdapter | None,
        item: LoadItem,
        now: str,
        run_id: str,
    ) -> list[str]:
        if item.category == "rejected":
            return []
        if adapter is None:
            return ["TARGET_TABLE_NOT_AVAILABLE"]
        _, missing = self._build_values(
            adapter=adapter,
            item=item,
            now=now,
            run_id=run_id,
            is_insert=True,
        )
        return missing

    def run(
        self,
        *,
        approved_path: Path | None = None,
        review_path: Path | None = None,
        rejected_path: Path | None = None,
        output_dir: Path | None = None,
        dry_run: bool = False,
        database_path: Path | None = None,
    ) -> StagingLoadResult:
        run_id = uuid.uuid4().hex
        started_at = utc_now_iso()
        output_dir = (output_dir or self.data_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        approved_path = (approved_path or self.data_dir / self.config["approved_filename"]).resolve()
        review_path = (review_path or self.data_dir / self.config["review_filename"]).resolve()
        rejected_path = (rejected_path or self.data_dir / self.config["rejected_filename"]).resolve()

        for path in (approved_path, review_path, rejected_path):
            if not path.exists():
                raise FileNotFoundError(f"Required incremental validation file not found: {path}")

        if database_path is not None:
            self.explicit_database_path = Path(database_path).resolve()
        db_path, db_inspection, db_candidates = self.discover_database()

        connection = sqlite3.connect(
            db_path,
            timeout=max(5, int(self.config["busy_timeout_ms"]) / 1000),
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={int(self.config['busy_timeout_ms'])}")
        try:
            tables = self._table_names(connection)
            staging_table = self._first_present(STAGING_TABLE_CANDIDATES, tables)
            review_table = self._first_present(REVIEW_TABLE_CANDIDATES, tables)

            staging_adapter = (
                self._build_adapter(connection, table_name=staging_table, category="approved")
                if staging_table
                else None
            )
            review_adapter = (
                self._build_adapter(connection, table_name=review_table, category="review")
                if review_table
                else None
            )

            items, failures = self._load_items(
                approved_path=approved_path,
                review_path=review_path,
                rejected_path=rejected_path,
                staging_table=staging_table,
                review_table=review_table,
            )

            now = utc_now_iso()
            for item in items:
                adapter = (
                    staging_adapter
                    if item.category == "approved"
                    else review_adapter
                    if item.category == "review"
                    else None
                )
                missing = self._preflight_item(
                    adapter=adapter,
                    item=item,
                    now=now,
                    run_id=run_id,
                )
                if missing:
                    failures.append(
                        {
                            "category": item.category,
                            "master_key": item.master_key,
                            "scheme_name": item.record.get("scheme_name"),
                            "error_type": "UNMAPPED_REQUIRED_DATABASE_COLUMNS",
                            "error_message": (
                                f"Table {adapter.table_name if adapter else item.target_table} "
                                f"has required columns that could not be mapped: {missing}"
                            ),
                            "missing_columns": missing,
                        }
                    )

            if failures:
                summary = self._build_summary(
                    run_id=run_id,
                    started_at=started_at,
                    database_path=db_path,
                    database_inspection=db_inspection,
                    database_candidates=db_candidates,
                    staging_adapter=staging_adapter,
                    review_adapter=review_adapter,
                    items=items,
                    audit=[],
                    failures=failures,
                    dry_run=dry_run,
                    database_committed=False,
                    backup_path=None,
                    input_paths={
                        "approved": approved_path,
                        "review": review_path,
                        "rejected": rejected_path,
                    },
                    output_dir=output_dir,
                )
                plan = self._plan_payload(items, staging_adapter, review_adapter)
                self._write_outputs(output_dir, summary, [], failures, plan)
                return StagingLoadResult(summary=summary, audit=[], failures=failures, plan=plan)

            plan: list[dict[str, Any]] = []
            audit_rows: list[dict[str, Any]] = []

            # Plan using the current database state. No schema changes occur here.
            for item in items:
                adapter = (
                    staging_adapter
                    if item.category == "approved"
                    else review_adapter
                    if item.category == "review"
                    else None
                )
                previous_fingerprint = None
                existing_row = None
                key_values: tuple[Any, ...] = ()
                if adapter is not None:
                    key_values = self._business_key_values(adapter, item)
                    existing_row = self._select_existing(connection, adapter, key_values)
                latest = self._latest_audit(
                    connection,
                    master_key=item.master_key,
                    target_table=item.target_table,
                )
                if latest is not None:
                    previous_fingerprint = latest["validation_fingerprint"]

                if latest is not None and previous_fingerprint == item.fingerprint:
                    action = "REUSED_UNCHANGED"
                elif item.category == "rejected":
                    action = "RECORDED_REJECTION_ONLY"
                elif existing_row is None:
                    action = "INSERTED_NEW"
                else:
                    final, _ = self._workflow_state(existing_row)
                    action = "UPDATED_PRESERVED_FINAL_WORKFLOW" if final else "UPDATED_EXISTING"

                plan.append(
                    {
                        "master_key": item.master_key,
                        "master_id": item.record.get("master_id"),
                        "scheme_name": item.record.get("scheme_name"),
                        "source": item.record.get("source"),
                        "input_category": item.category,
                        "validation_decision": item.decision,
                        "target_table": item.target_table,
                        "target_business_key": list(key_values),
                        "planned_action": action,
                        "validation_fingerprint": item.fingerprint,
                        "previous_fingerprint": previous_fingerprint,
                    }
                )

            backup_path: Path | None = None
            database_committed = False
            if not dry_run:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = self.data_dir / str(self.config["backup_subdirectory"])
                backup_path = backup_dir / (
                    f"{db_path.stem}.pre_v2_5_{timestamp}_{run_id[:8]}{db_path.suffix}"
                )
                connection.close()
                self._online_backup(db_path, backup_path, int(self.config["busy_timeout_ms"]))

                connection = sqlite3.connect(
                    db_path,
                    timeout=max(5, int(self.config["busy_timeout_ms"]) / 1000),
                )
                connection.row_factory = sqlite3.Row
                connection.execute(f"PRAGMA busy_timeout={int(self.config['busy_timeout_ms'])}")
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._create_audit_table(connection)

                    for item, planned in zip(items, plan):
                        adapter = (
                            staging_adapter
                            if item.category == "approved"
                            else review_adapter
                            if item.category == "review"
                            else None
                        )
                        key_values = (
                            self._business_key_values(adapter, item) if adapter else ()
                        )
                        existing_row = (
                            self._select_existing(connection, adapter, key_values)
                            if adapter
                            else None
                        )
                        latest = self._latest_audit(
                            connection,
                            master_key=item.master_key,
                            target_table=item.target_table,
                        )
                        previous_fingerprint = (
                            str(latest["validation_fingerprint"]) if latest else None
                        )
                        workflow_preserved: dict[str, Any] = {}
                        details: dict[str, Any] = {}

                        if latest is not None and previous_fingerprint == item.fingerprint:
                            action = "REUSED_UNCHANGED"
                        elif item.category == "rejected":
                            action = "RECORDED_REJECTION_ONLY"
                        elif adapter is None:
                            raise RuntimeError(
                                f"Adapter disappeared for category {item.category}"
                            )
                        elif existing_row is None:
                            values, missing = self._build_values(
                                adapter=adapter,
                                item=item,
                                now=now,
                                run_id=run_id,
                                is_insert=True,
                            )
                            if missing:
                                raise RuntimeError(
                                    f"Required columns became unmappable for {adapter.table_name}: {missing}"
                                )
                            row_id = self._insert_row(connection, adapter, values)
                            details = {"inserted_rowid": row_id, "written_columns": sorted(values)}
                            action = "INSERTED_NEW"
                        else:
                            final, workflow_preserved = self._workflow_state(existing_row)
                            values, _ = self._build_values(
                                adapter=adapter,
                                item=item,
                                now=now,
                                run_id=run_id,
                                is_insert=False,
                                existing_row=existing_row,
                            )
                            updated_count = self._update_row(
                                connection,
                                adapter,
                                values,
                                key_values,
                            )
                            details = {
                                "updated_row_count": updated_count,
                                "written_columns": sorted(values),
                            }
                            action = (
                                "UPDATED_PRESERVED_FINAL_WORKFLOW"
                                if final
                                else "UPDATED_EXISTING"
                            )

                        audit = {
                            "audit_id": uuid.uuid4().hex,
                            "run_id": run_id,
                            "master_key": item.master_key,
                            "master_id": normalize_space(item.record.get("master_id")) or None,
                            "scheme_name": normalize_space(item.record.get("scheme_name")) or None,
                            "source": normalize_space(item.record.get("source")) or None,
                            "input_category": item.category,
                            "validation_decision": item.decision,
                            "target_table": item.target_table,
                            "target_business_key_json": self._json_text(list(key_values)),
                            "action": action,
                            "validation_fingerprint": item.fingerprint,
                            "previous_fingerprint": previous_fingerprint,
                            "workflow_preserved_json": self._json_text(workflow_preserved),
                            "details_json": self._json_text(details),
                            "created_at": now,
                        }
                        self._insert_audit_row(connection, audit)
                        audit_rows.append(
                            {
                                **audit,
                                "target_business_key": list(key_values),
                                "workflow_preserved": workflow_preserved,
                                "details": details,
                            }
                        )

                    connection.commit()
                    database_committed = True
                except Exception:
                    connection.rollback()
                    raise
            else:
                audit_rows = [
                    {
                        "audit_id": None,
                        "run_id": run_id,
                        "master_key": item["master_key"],
                        "master_id": item["master_id"],
                        "scheme_name": item["scheme_name"],
                        "source": item["source"],
                        "input_category": item["input_category"],
                        "validation_decision": item["validation_decision"],
                        "target_table": item["target_table"],
                        "target_business_key": item["target_business_key"],
                        "action": item["planned_action"],
                        "validation_fingerprint": item["validation_fingerprint"],
                        "previous_fingerprint": item["previous_fingerprint"],
                        "dry_run": True,
                    }
                    for item in plan
                ]

            summary = self._build_summary(
                run_id=run_id,
                started_at=started_at,
                database_path=db_path,
                database_inspection=db_inspection,
                database_candidates=db_candidates,
                staging_adapter=staging_adapter,
                review_adapter=review_adapter,
                items=items,
                audit=audit_rows,
                failures=[],
                dry_run=dry_run,
                database_committed=database_committed,
                backup_path=backup_path,
                input_paths={
                    "approved": approved_path,
                    "review": review_path,
                    "rejected": rejected_path,
                },
                output_dir=output_dir,
            )
            self._write_outputs(output_dir, summary, audit_rows, [], plan)
            return StagingLoadResult(
                summary=summary,
                audit=audit_rows,
                failures=[],
                plan=plan,
            )
        finally:
            try:
                connection.close()
            except Exception:
                pass

    @staticmethod
    def _adapter_summary(adapter: TableAdapter | None) -> dict[str, Any] | None:
        if adapter is None:
            return None
        return {
            "table_name": adapter.table_name,
            "category": adapter.category,
            "business_key_columns": list(adapter.business_key_columns),
            "columns": [
                {
                    "name": column.name,
                    "declared_type": column.declared_type,
                    "not_null": column.not_null,
                    "default_value": column.default_value,
                    "primary_key_position": column.primary_key_position,
                }
                for column in adapter.columns
            ],
        }

    @staticmethod
    def _plan_payload(
        items: Sequence[LoadItem],
        staging_adapter: TableAdapter | None,
        review_adapter: TableAdapter | None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in items:
            adapter = (
                staging_adapter
                if item.category == "approved"
                else review_adapter
                if item.category == "review"
                else None
            )
            output.append(
                {
                    "master_key": item.master_key,
                    "master_id": item.record.get("master_id"),
                    "scheme_name": item.record.get("scheme_name"),
                    "input_category": item.category,
                    "validation_decision": item.decision,
                    "target_table": adapter.table_name if adapter else None,
                    "validation_fingerprint": item.fingerprint,
                }
            )
        return output

    def _build_summary(
        self,
        *,
        run_id: str,
        started_at: str,
        database_path: Path,
        database_inspection: Mapping[str, Any],
        database_candidates: Sequence[Mapping[str, Any]],
        staging_adapter: TableAdapter | None,
        review_adapter: TableAdapter | None,
        items: Sequence[LoadItem],
        audit: Sequence[Mapping[str, Any]],
        failures: Sequence[Mapping[str, Any]],
        dry_run: bool,
        database_committed: bool,
        backup_path: Path | None,
        input_paths: Mapping[str, Path],
        output_dir: Path,
    ) -> dict[str, Any]:
        action_counter = Counter(str(row.get("action")) for row in audit)
        category_counter = Counter(item.category for item in items)
        decision_counter = Counter(item.decision for item in items)
        return {
            "hotfix_version": HOTFIX_VERSION,
            "run_id": run_id,
            "source": MEITY_SOURCE_NAME,
            "started_at": started_at,
            "generated_at": utc_now_iso(),
            "dry_run": dry_run,
            "database_committed": database_committed,
            "input_record_count": len(items),
            "approved_input_count": category_counter.get("approved", 0),
            "review_input_count": category_counter.get("review", 0),
            "rejected_input_count": category_counter.get("rejected", 0),
            "decisions": dict(decision_counter),
            "actions": dict(action_counter),
            "inserted_new_count": action_counter.get("INSERTED_NEW", 0),
            "updated_existing_count": action_counter.get("UPDATED_EXISTING", 0),
            "updated_preserving_final_workflow_count": action_counter.get(
                "UPDATED_PRESERVED_FINAL_WORKFLOW", 0
            ),
            "reused_unchanged_count": action_counter.get("REUSED_UNCHANGED", 0),
            "rejection_audit_only_count": action_counter.get(
                "RECORDED_REJECTION_ONLY", 0
            ),
            "failure_count": len(failures),
            "incremental_input_is_meity_only": all(
                normalize_space(item.record.get("source")).casefold()
                == MEITY_SOURCE_NAME.casefold()
                for item in items
            ),
            "database_path": str(database_path),
            "database_backup_path": str(backup_path) if backup_path else None,
            "detected_staging_table": staging_adapter.table_name if staging_adapter else None,
            "detected_review_table": review_adapter.table_name if review_adapter else None,
            "staging_adapter": self._adapter_summary(staging_adapter),
            "review_adapter": self._adapter_summary(review_adapter),
            "database_candidate_count": len(database_candidates),
            "database_detection": {
                "selected_score": database_inspection.get("score"),
                "selected_tables": database_inspection.get("tables"),
                "candidates": [
                    {
                        "path": str(item.get("path")),
                        "score": item.get("score"),
                        "staging_table": item.get("staging_table"),
                        "review_table": item.get("review_table"),
                    }
                    for item in database_candidates[:10]
                ],
            },
            "input_paths": {key: str(path) for key, path in input_paths.items()},
            "output_paths": {
                "summary": str(output_dir / self.config["summary_filename"]),
                "audit": str(output_dir / self.config["audit_filename"]),
                "failures": str(output_dir / self.config["failures_filename"]),
                "plan": str(output_dir / self.config["plan_filename"]),
            },
        }

    def _write_outputs(
        self,
        output_dir: Path,
        summary: Mapping[str, Any],
        audit: Sequence[Mapping[str, Any]],
        failures: Sequence[Mapping[str, Any]],
        plan: Sequence[Mapping[str, Any]],
    ) -> None:
        atomic_write_json(output_dir / self.config["summary_filename"], summary)
        atomic_write_json(output_dir / self.config["audit_filename"], list(audit))
        atomic_write_json(output_dir / self.config["failures_filename"], list(failures))
        atomic_write_json(output_dir / self.config["plan_filename"], list(plan))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SSIP MeitY Incremental Staging Loader v2.5"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="SSIP project root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Optional explicit path to the existing SQLite staging database.",
    )
    parser.add_argument("--approved", type=Path, default=None)
    parser.add_argument("--review", type=Path, default=None)
    parser.add_argument("--rejected", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect, validate, and plan the load without changing the database.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    loader = MeityIncrementalStagingLoaderV25(
        project_root=args.project_root,
        database_path=args.database,
    )
    result = loader.run(
        approved_path=args.approved,
        review_path=args.review,
        rejected_path=args.rejected,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        database_path=args.database,
    )
    print(json.dumps(result.summary, ensure_ascii=False, indent=2))
    if result.failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
