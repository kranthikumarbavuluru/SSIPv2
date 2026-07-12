#!/usr/bin/env python3
"""
SSIP v2.7.3.3 — Foreign-Key-Aware Safe Loader Hotfix

Supports the actual SSIP scheme_staging schema, including:
* canonical_name -> scheme_name
* final_url -> official_page_url
* confidence_after_validation -> validation_score
* deadline -> closing_date
* mandatory legacy audit fields:
  record_hash, raw_record_json, first_loaded_at, last_loaded_at,
  last_import_run_id, validation_decision

The loader does not rename columns or publish records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

LOADER_VERSION = "2.7.3.3a"
APPROVED_DECISION = "APPROVED_FOR_DATABASE"

CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "master_id": ("master_id",),
    "source": ("source", "source_name", "agency", "organisation", "organization"),
    "canonical_name": (
        "canonical_name",
        "scheme_name",
        "scheme_title",
        "programme_name",
        "program_name",
        "name",
        "title",
    ),
    "programme_status": (
        "programme_status",
        "program_status",
        "current_status",
        "scheme_status",
        "status",
    ),
    "final_url": (
        "final_url",
        "official_page_url",
        "official_url",
        "official_scheme_url",
        "scheme_page_url",
        "source_page_url",
        "source_url",
        "best_available_url",
        "scheme_url",
        "webpage_url",
        "url",
    ),
    "application_url": (
        "application_url",
        "apply_url",
        "application_link",
        "apply_link",
        "registration_url",
    ),
}

INPUT_TO_DATABASE_ALIASES: dict[str, tuple[str, ...]] = {
    "confidence_after_validation": ("validation_score", "confidence_after_validation"),
    "confidence": ("validation_score", "confidence"),
    "deadline": ("closing_date", "deadline"),
    "opening_date": ("opening_date",),
    "closing_date": ("closing_date",),
    "ministry": ("ministry",),
    "department": ("department",),
    "implementing_agency": ("implementing_agency",),
    "record_kind": ("record_kind",),
    "application_status": ("application_status",),
    "scheme_status": ("scheme_status",),
    "geographic_scope": ("geographic_scope",),
    "funding_minimum": ("funding_minimum",),
    "funding_maximum": ("funding_maximum",),
    "currency": ("currency",),
    "beneficiary_support_minimum": ("beneficiary_support_minimum",),
    "beneficiary_support_maximum": ("beneficiary_support_maximum",),
    "intermediary_support_maximum": ("intermediary_support_maximum",),
    "scheme_corpus": ("scheme_corpus",),
}

REQUIRED_CONCEPTS = (
    "master_id",
    "source",
    "canonical_name",
    "programme_status",
    "final_url",
)

DECISION_INPUT_COLUMNS = (
    "validation_decision",
    "decision",
    "final_decision",
    "database_decision",
)

PUBLICATION_COLUMNS = {
    "publication_status",
    "is_public",
    "published_at",
    "published_by",
    "unpublished_at",
    "unpublished_by",
    "publication_notes",
}

LOAD_METADATA_COLUMNS = {
    "record_hash",
    "raw_record_json",
    "first_loaded_at",
    "last_loaded_at",
    "last_import_run_id",
    "source_run_id",
    "record_version",
    "created_at",
    "updated_at",
}

NEVER_COPY_DIRECTLY = PUBLICATION_COLUMNS | LOAD_METADATA_COLUMNS
MASTER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")


class SafeLoadError(RuntimeError):
    pass


@dataclass
class RecordResult:
    run_id: str
    master_id: str
    source: str
    canonical_name: str
    load_action: str
    result: str
    reason: str
    previous_publication_status: str | None = None
    previous_is_public: int | None = None
    record_version: int | None = None


@dataclass
class LoadSummary:
    loader_version: str
    run_id: str
    mode: str
    status: str
    database: str
    input_file: str
    input_sha256: str
    total_records: int
    inserted_records: int
    updated_records: int
    skipped_records: int
    failed_records: int
    protected_published_records: int
    unchanged_records: int
    public_count_before: int
    public_count_after: int
    schema_mapping: dict[str, str]
    synthesized_columns: list[str]
    started_at: str
    completed_at: str
    initiated_by: str
    output_directory: str
    error_message: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def canonical_json(row: dict[str, Any]) -> str:
    return json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def record_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connect_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def scalar(
    connection: sqlite3.Connection,
    sql: str,
    params: Iterable[Any] = (),
) -> Any:
    row = connection.execute(sql, tuple(params)).fetchone()
    return None if row is None else row[0]


def object_exists(connection: sqlite3.Connection, object_type: str, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
            (object_type, name),
        ).fetchone()
        is not None
    )


def table_columns(connection: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise SafeLoadError(f"Unsafe table name: {table!r}")
    return {
        row["name"]: row
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def quote_identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise SafeLoadError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def table_foreign_keys(
    connection: sqlite3.Connection,
    table: str,
) -> list[dict[str, Any]]:
    safe_table = quote_identifier(table)
    rows = connection.execute(f"PRAGMA foreign_key_list({safe_table})").fetchall()
    return [
        {
            "id": int(row["id"]),
            "seq": int(row["seq"]),
            "parent_table": row["table"],
            "from_column": row["from"],
            "to_column": row["to"],
            "on_update": row["on_update"],
            "on_delete": row["on_delete"],
            "match": row["match"],
        }
        for row in rows
    ]


def parent_value_exists(
    connection: sqlite3.Connection,
    parent_table: str,
    parent_column: str | None,
    value: Any,
) -> bool:
    if value is None:
        return True

    safe_table = quote_identifier(parent_table)
    if parent_column:
        safe_column = quote_identifier(parent_column)
    else:
        parent_info = connection.execute(
            f"PRAGMA table_info({safe_table})"
        ).fetchall()
        primary_keys = sorted(
            (row for row in parent_info if int(row["pk"]) > 0),
            key=lambda row: int(row["pk"]),
        )
        if len(primary_keys) != 1:
            raise SafeLoadError(
                f"Cannot safely resolve implicit parent key for {parent_table!r}."
            )
        safe_column = quote_identifier(primary_keys[0]["name"])

    return (
        connection.execute(
            f"SELECT 1 FROM {safe_table} WHERE {safe_column} = ? LIMIT 1",
            (value,),
        ).fetchone()
        is not None
    )


def apply_foreign_key_policy(
    connection: sqlite3.Connection,
    table: str,
    values: dict[str, Any],
    columns: dict[str, sqlite3.Row],
    *,
    is_update: bool,
) -> tuple[dict[str, Any], list[str]]:
    """
    Preserve FK enforcement while handling nullable loader-generated legacy
    run references.

    For last_import_run_id/source_run_id only:
    * insert: store NULL when the generated run_id is not present in the
      legacy parent run table;
    * update: leave the existing database value unchanged.

    All business-field FK violations remain fatal.
    """
    adjusted = dict(values)
    suppressed: list[str] = []
    generated_run_columns = {"last_import_run_id", "source_run_id"}

    foreign_keys = table_foreign_keys(connection, table)
    for foreign_key in foreign_keys:
        source_column = foreign_key["from_column"]
        if source_column not in adjusted:
            continue

        value = adjusted[source_column]
        if value is None:
            continue

        exists = parent_value_exists(
            connection,
            foreign_key["parent_table"],
            foreign_key["to_column"],
            value,
        )
        if exists:
            continue

        column = columns.get(source_column)
        nullable = column is not None and not bool(column["notnull"])

        if source_column in generated_run_columns and nullable:
            if is_update:
                adjusted.pop(source_column, None)
            else:
                adjusted[source_column] = None
            suppressed.append(source_column)
            continue

        raise SafeLoadError(
            "Foreign-key validation failed before database write: "
            f"{table}.{source_column}={value!r} has no parent row in "
            f"{foreign_key['parent_table']}.{foreign_key['to_column'] or '<primary-key>'}."
        )

    return adjusted, suppressed


def resolve_first_existing(
    candidates: Iterable[str],
    available: set[str],
) -> str | None:
    return next((candidate for candidate in candidates if candidate in available), None)


def resolve_schema(
    columns: dict[str, sqlite3.Row],
) -> tuple[dict[str, str], list[str], list[str]]:
    available = set(columns)
    mapping: dict[str, str] = {}
    missing: list[str] = []

    for concept, aliases in CONCEPT_ALIASES.items():
        match = resolve_first_existing(aliases, available)
        if match:
            mapping[concept] = match
        elif concept in REQUIRED_CONCEPTS:
            missing.append(concept)

    synthesized = [
        name
        for name in (
            "validation_decision",
            "record_hash",
            "raw_record_json",
            "first_loaded_at",
            "last_loaded_at",
            "last_import_run_id",
        )
        if name in available
    ]

    return mapping, missing, synthesized


def schema_report(connection: sqlite3.Connection) -> dict[str, Any]:
    if not object_exists(connection, "table", "scheme_staging"):
        return {
            "loader_version": LOADER_VERSION,
            "scheme_staging_exists": False,
            "database_ready": False,
            "error": "scheme_staging table does not exist",
        }

    columns = table_columns(connection, "scheme_staging")
    mapping, missing, synthesized = resolve_schema(columns)
    available = set(columns)

    required_publication_columns = PUBLICATION_COLUMNS | {
        "source_run_id",
        "record_version",
        "created_at",
        "updated_at",
    }
    missing_publication = sorted(required_publication_columns - available)

    required_objects = {
        "database_load_runs": object_exists(connection, "table", "database_load_runs"),
        "safe_load_record_audit": object_exists(
            connection, "table", "safe_load_record_audit"
        ),
        "publication_audit_log": object_exists(
            connection, "table", "publication_audit_log"
        ),
        "public_schemes": object_exists(connection, "view", "public_schemes"),
    }

    supported_required_columns = set(mapping.values()) | set(synthesized) | {
        "publication_status",
        "is_public",
        "source_run_id",
        "record_version",
        "created_at",
        "updated_at",
    }

    unsupported_not_null = []
    for name, column in columns.items():
        if column["pk"] and "INT" in (column["type"] or "").upper():
            continue
        if (
            column["notnull"]
            and column["dflt_value"] is None
            and name not in supported_required_columns
        ):
            unsupported_not_null.append(name)

    return {
        "loader_version": LOADER_VERSION,
        "scheme_staging_exists": True,
        "database_ready": (
            not missing
            and not missing_publication
            and not unsupported_not_null
            and all(required_objects.values())
        ),
        "resolved_field_mapping": mapping,
        "synthesized_columns": synthesized,
        "missing_required_concepts": missing,
        "missing_publication_columns": missing_publication,
        "unsupported_not_null_columns": unsupported_not_null,
        "required_objects": required_objects,
        "scheme_staging_foreign_keys": table_foreign_keys(
            connection, "scheme_staging"
        ),
        "safe_load_record_audit_foreign_keys": table_foreign_keys(
            connection, "safe_load_record_audit"
        ),
        "database_load_runs_foreign_keys": table_foreign_keys(
            connection, "database_load_runs"
        ),
        "scheme_staging_columns": [
            {
                "name": row["name"],
                "type": row["type"],
                "not_null": bool(row["notnull"]),
                "default_value": row["dflt_value"],
                "primary_key_position": row["pk"],
            }
            for row in columns.values()
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def validate_database(
    connection: sqlite3.Connection,
    output_dir: Path,
) -> tuple[dict[str, sqlite3.Row], dict[str, str], list[str]]:
    report = schema_report(connection)
    write_json(output_dir / "schema_compatibility_v2_7_3_3a.json", report)

    if not report.get("scheme_staging_exists"):
        raise SafeLoadError("Required table scheme_staging does not exist.")
    if report["missing_required_concepts"]:
        raise SafeLoadError(
            "No compatible database column was found for: "
            + ", ".join(report["missing_required_concepts"])
        )
    if report["missing_publication_columns"]:
        raise SafeLoadError(
            "Missing publication-control columns: "
            + ", ".join(report["missing_publication_columns"])
        )
    if report["unsupported_not_null_columns"]:
        raise SafeLoadError(
            "Unsupported mandatory database columns: "
            + ", ".join(report["unsupported_not_null_columns"])
        )

    missing_objects = [
        name for name, exists in report["required_objects"].items() if not exists
    ]
    if missing_objects:
        raise SafeLoadError(
            "Missing v2.7.3 database objects: " + ", ".join(missing_objects)
        )

    quick_check = scalar(connection, "PRAGMA quick_check")
    if quick_check != "ok":
        raise SafeLoadError(f"SQLite quick_check failed: {quick_check}")

    return (
        table_columns(connection, "scheme_staging"),
        dict(report["resolved_field_mapping"]),
        list(report["synthesized_columns"]),
    )


def validate_url(value: str | None, field: str, row_number: int) -> str | None:
    if value is None:
        return None
    if any(character.isspace() for character in value):
        raise ValueError(f"row {row_number}: {field} contains whitespace")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"row {row_number}: {field} is not a valid HTTP(S) URL")
    return value


def read_input(
    input_path: Path,
) -> tuple[list[dict[str, str | None]], list[dict[str, str]]]:
    if not input_path.exists() or not input_path.is_file():
        raise SafeLoadError(f"Input CSV not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    if not raw_rows:
        raise SafeLoadError("Input CSV is empty.")

    headers = [normalize_header(value) for value in raw_rows[0]]
    if any(not header for header in headers):
        raise SafeLoadError("Input CSV contains a blank header.")
    if len(headers) != len(set(headers)):
        duplicates = sorted({h for h in headers if headers.count(h) > 1})
        raise SafeLoadError(
            "Input CSV contains duplicate normalized headers: "
            + ", ".join(duplicates)
        )

    missing = sorted(set(REQUIRED_CONCEPTS) - set(headers))
    if missing:
        raise SafeLoadError(
            "Input CSV is missing required columns: " + ", ".join(missing)
        )

    decision_column = next(
        (name for name in DECISION_INPUT_COLUMNS if name in headers),
        None,
    )
    approved_filename = "approved_for_database" in input_path.name.lower()
    if not decision_column and not approved_filename:
        raise SafeLoadError(
            "Approval provenance not established. Use an approved_for_database "
            "CSV or include validation_decision."
        )

    valid: list[dict[str, str | None]] = []
    failures: list[dict[str, str]] = []
    seen: dict[str, int] = {}

    for row_number, values in enumerate(raw_rows[1:], start=2):
        if not any(str(value).strip() for value in values):
            continue

        if len(values) > len(headers):
            failures.append(
                {
                    "row_number": str(row_number),
                    "master_id": "",
                    "reason": "Row has more values than the CSV header.",
                }
            )
            continue

        padded = values + [""] * (len(headers) - len(values))
        row = {
            header: normalize_text(value)
            for header, value in zip(headers, padded)
        }

        master_id = row.get("master_id")
        try:
            if not master_id or not MASTER_ID_RE.fullmatch(master_id):
                raise ValueError(f"row {row_number}: invalid master_id")
            if master_id in seen:
                raise ValueError(
                    f"row {row_number}: duplicate master_id; first seen at "
                    f"row {seen[master_id]}"
                )
            seen[master_id] = row_number

            for concept in REQUIRED_CONCEPTS:
                if not row.get(concept):
                    raise ValueError(f"row {row_number}: {concept} is blank")

            if decision_column:
                decision = (row.get(decision_column) or "").upper()
                if decision != APPROVED_DECISION:
                    raise ValueError(
                        f"row {row_number}: validation decision {decision!r} "
                        f"is not {APPROVED_DECISION}"
                    )

            row["final_url"] = validate_url(
                row.get("final_url"), "final_url", row_number
            )
            if "application_url" in row:
                row["application_url"] = validate_url(
                    row.get("application_url"), "application_url", row_number
                )

            valid.append(row)
        except ValueError as exc:
            failures.append(
                {
                    "row_number": str(row_number),
                    "master_id": master_id or "",
                    "reason": str(exc),
                }
            )

    if not valid and not failures:
        raise SafeLoadError("Input CSV contains no data rows.")

    return valid, failures


def coerce(value: str | None, declared_type: str | None) -> Any:
    if value is None:
        return None
    declared = (declared_type or "").upper()
    try:
        if "INT" in declared:
            return int(float(value))
        if any(token in declared for token in ("REAL", "FLOA", "DOUB", "NUM")):
            return float(value)
    except ValueError:
        return value
    return value


def comparable(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def resolve_database_alias(
    input_name: str,
    available: set[str],
) -> str | None:
    candidates = INPUT_TO_DATABASE_ALIASES.get(input_name, (input_name,))
    return resolve_first_existing(candidates, available)


def map_business_values(
    row: dict[str, str | None],
    columns: dict[str, sqlite3.Row],
    mapping: dict[str, str],
) -> dict[str, Any]:
    available = set(columns)
    mapped: dict[str, Any] = {}

    for concept, database_column in mapping.items():
        if concept in row:
            mapped[database_column] = coerce(
                row.get(concept),
                columns[database_column]["type"],
            )

    for input_name, value in row.items():
        if input_name in REQUIRED_CONCEPTS:
            continue
        if input_name in DECISION_INPUT_COLUMNS:
            continue
        database_column = resolve_database_alias(input_name, available)
        if (
            database_column
            and database_column not in NEVER_COPY_DIRECTLY
            and database_column not in mapped
        ):
            mapped[database_column] = coerce(
                value,
                columns[database_column]["type"],
            )

    if "validation_decision" in available:
        mapped["validation_decision"] = APPROVED_DECISION

    return mapped


def complete_insert_values(
    business_values: dict[str, Any],
    row: dict[str, str | None],
    columns: dict[str, sqlite3.Row],
    run_id: str,
    now: str,
) -> dict[str, Any]:
    values = dict(business_values)
    raw_json = canonical_json(row)
    hash_value = record_hash(row)
    available = set(columns)

    defaults: dict[str, Any] = {
        "publication_status": "STAGED",
        "is_public": 0,
        "published_at": None,
        "published_by": None,
        "unpublished_at": None,
        "unpublished_by": None,
        "publication_notes": None,
        "source_run_id": run_id,
        "record_version": 1,
        "created_at": now,
        "updated_at": now,
        "record_hash": hash_value,
        "raw_record_json": raw_json,
        "first_loaded_at": now,
        "last_loaded_at": now,
        "last_import_run_id": run_id,
    }

    for name, value in defaults.items():
        if name in available:
            values[name] = value

    return values


def missing_required_insert_columns(
    columns: dict[str, sqlite3.Row],
    values: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for name, column in columns.items():
        if column["pk"] and "INT" in (column["type"] or "").upper():
            continue
        if (
            column["notnull"]
            and column["dflt_value"] is None
            and name not in values
        ):
            missing.append(name)
    return missing


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


def write_record_audit(
    connection: sqlite3.Connection,
    run_id: str,
    master_id: str,
    action: str,
    result: str,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    processed_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO safe_load_record_audit (
            run_id, master_id, action, result, reason,
            before_json, after_json, processed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            master_id,
            action,
            result,
            reason,
            json.dumps(before, ensure_ascii=False, default=str) if before else None,
            json.dumps(after, ensure_ascii=False, default=str) if after else None,
            processed_at,
        ),
    )


def process_row(
    connection: sqlite3.Connection,
    run_id: str,
    row: dict[str, str | None],
    columns: dict[str, sqlite3.Row],
    mapping: dict[str, str],
    protect_published: bool,
) -> RecordResult:
    now = utc_now()
    master_id = row["master_id"] or ""
    source = row["source"] or ""
    canonical_name = row["canonical_name"] or ""
    master_column = mapping["master_id"]

    existing = connection.execute(
        f'SELECT * FROM scheme_staging WHERE "{master_column}"=?',
        (master_id,),
    ).fetchone()

    business_values = map_business_values(row, columns, mapping)

    if existing is None:
        values = complete_insert_values(
            business_values,
            row,
            columns,
            run_id,
            now,
        )
        values, suppressed_fk_columns = apply_foreign_key_policy(
            connection,
            "scheme_staging",
            values,
            columns,
            is_update=False,
        )
        missing = missing_required_insert_columns(columns, values)
        if missing:
            raise SafeLoadError(
                f"Cannot insert {master_id}; mandatory database columns are "
                "not populated: " + ", ".join(missing)
            )

        names = list(values)
        quoted = ", ".join(f'"{name}"' for name in names)
        placeholders = ", ".join("?" for _ in names)
        connection.execute(
            f"INSERT INTO scheme_staging ({quoted}) VALUES ({placeholders})",
            tuple(values[name] for name in names),
        )
        after = row_dict(
            connection.execute(
                f'SELECT * FROM scheme_staging WHERE "{master_column}"=?',
                (master_id,),
            ).fetchone()
        )
        write_record_audit(
            connection,
            run_id,
            master_id,
            "INSERT",
            "ACCEPTED",
            (
                "NEW_APPROVED_RECORD_STAGED"
                if not suppressed_fk_columns
                else "NEW_APPROVED_RECORD_STAGED;"
                + "LEGACY_RUN_FK_SUPPRESSED:"
                + ",".join(sorted(suppressed_fk_columns))
            ),
            None,
            after,
            now,
        )
        return RecordResult(
            run_id,
            master_id,
            source,
            canonical_name,
            "INSERT",
            "ACCEPTED",
            (
                "NEW_APPROVED_RECORD_STAGED"
                if not suppressed_fk_columns
                else "NEW_APPROVED_RECORD_STAGED;"
                + "LEGACY_RUN_FK_SUPPRESSED:"
                + ",".join(sorted(suppressed_fk_columns))
            ),
            None,
            None,
            1,
        )

    before = dict(existing)
    publication_status = comparable(existing["publication_status"])
    is_public = int(existing["is_public"] or 0)
    current_version = int(existing["record_version"] or 1)

    if protect_published and (
        publication_status == "PUBLISHED" or is_public == 1
    ):
        write_record_audit(
            connection,
            run_id,
            master_id,
            "SKIP",
            "SKIPPED",
            "PUBLISHED_RECORD_PROTECTED",
            before,
            None,
            now,
        )
        return RecordResult(
            run_id,
            master_id,
            source,
            canonical_name,
            "SKIP",
            "SKIPPED",
            "PUBLISHED_RECORD_PROTECTED",
            publication_status,
            is_public,
            current_version,
        )

    changed: dict[str, Any] = {}
    for name, value in business_values.items():
        if name == master_column:
            continue
        if comparable(existing[name]) != comparable(value):
            changed[name] = value

    if not changed:
        write_record_audit(
            connection,
            run_id,
            master_id,
            "SKIP",
            "SKIPPED",
            "NO_CONTENT_CHANGES",
            before,
            None,
            now,
        )
        return RecordResult(
            run_id,
            master_id,
            source,
            canonical_name,
            "SKIP",
            "SKIPPED",
            "NO_CONTENT_CHANGES",
            publication_status,
            is_public,
            current_version,
        )

    new_version = current_version + 1
    available = set(columns)
    metadata_updates: dict[str, Any] = {
        "source_run_id": run_id,
        "record_version": new_version,
        "updated_at": now,
        "record_hash": record_hash(row),
        "raw_record_json": canonical_json(row),
        "last_loaded_at": now,
        "last_import_run_id": run_id,
    }
    for name, value in metadata_updates.items():
        if name in available:
            changed[name] = value

    changed, suppressed_fk_columns = apply_foreign_key_policy(
        connection,
        "scheme_staging",
        changed,
        columns,
        is_update=True,
    )

    assignments = ", ".join(f'"{name}"=?' for name in changed)
    connection.execute(
        f'UPDATE scheme_staging SET {assignments} '
        f'WHERE "{master_column}"=?',
        (*changed.values(), master_id),
    )

    after = row_dict(
        connection.execute(
            f'SELECT * FROM scheme_staging WHERE "{master_column}"=?',
            (master_id,),
        ).fetchone()
    )
    write_record_audit(
        connection,
        run_id,
        master_id,
        "UPDATE",
        "ACCEPTED",
        (
            "APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED"
            if not suppressed_fk_columns
            else "APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED;"
            + "LEGACY_RUN_FK_SUPPRESSED:"
            + ",".join(sorted(suppressed_fk_columns))
        ),
        before,
        after,
        now,
    )
    return RecordResult(
        run_id,
        master_id,
        source,
        canonical_name,
        "UPDATE",
        "ACCEPTED",
        (
            "APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED"
            if not suppressed_fk_columns
            else "APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED;"
            + "LEGACY_RUN_FK_SUPPRESSED:"
            + ",".join(sorted(suppressed_fk_columns))
        ),
        publication_status,
        is_public,
        new_version,
    )


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_dir: Path,
    summary: LoadSummary,
    results: list[RecordResult],
    failures: list[dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in results]
    fields = list(RecordResult.__dataclass_fields__)

    write_csv(
        output_dir / "safe_load_accepted_v2_7_3_3a.csv",
        [row for row in rows if row["result"] == "ACCEPTED"],
        fields,
    )
    write_csv(
        output_dir / "safe_load_skipped_v2_7_3_3a.csv",
        [row for row in rows if row["result"] == "SKIPPED"],
        fields,
    )
    write_csv(
        output_dir / "safe_load_failed_v2_7_3_3a.csv",
        failures,
        ["row_number", "master_id", "reason"],
    )
    write_csv(
        output_dir / "safe_load_audit_v2_7_3_3a.csv",
        rows,
        fields,
    )
    write_json(
        output_dir / "safe_load_summary_v2_7_3_3a.json",
        asdict(summary),
    )


def failed_summary(
    *,
    run_id: str,
    mode: str,
    database: Path,
    input_path: Path,
    input_hash: str,
    output_dir: Path,
    initiated_by: str,
    started_at: str,
    total_records: int,
    failed_records: int,
    schema_mapping: dict[str, str],
    synthesized: list[str],
    status: str,
    error: str,
) -> LoadSummary:
    return LoadSummary(
        loader_version=LOADER_VERSION,
        run_id=run_id,
        mode=mode,
        status=status,
        database=str(database.resolve()),
        input_file=str(input_path.resolve()),
        input_sha256=input_hash,
        total_records=total_records,
        inserted_records=0,
        updated_records=0,
        skipped_records=0,
        failed_records=failed_records,
        protected_published_records=0,
        unchanged_records=0,
        public_count_before=0,
        public_count_after=0,
        schema_mapping=schema_mapping,
        synthesized_columns=synthesized,
        started_at=started_at,
        completed_at=utc_now(),
        initiated_by=initiated_by,
        output_directory=str(output_dir.resolve()),
        error_message=error,
    )


def run_loader(
    input_path: Path,
    database: Path,
    output_dir: Path,
    commit: bool,
    initiated_by: str,
    protect_published: bool = True,
) -> tuple[LoadSummary, list[RecordResult], list[dict[str, str]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    run_id = uuid.uuid4().hex
    mode = "COMMIT" if commit else "DRY_RUN"
    input_hash = sha256_file(input_path) if input_path.exists() else "UNAVAILABLE"

    rows, validation_failures = read_input(input_path)
    if validation_failures:
        summary = failed_summary(
            run_id=run_id,
            mode=mode,
            database=database,
            input_path=input_path,
            input_hash=input_hash,
            output_dir=output_dir,
            initiated_by=initiated_by,
            started_at=started_at,
            total_records=len(rows) + len(validation_failures),
            failed_records=len(validation_failures),
            schema_mapping={},
            synthesized=[],
            status="INPUT_VALIDATION_FAILED",
            error="Input validation failed; no database changes were made.",
        )
        write_outputs(output_dir, summary, [], validation_failures)
        return summary, [], validation_failures

    if not database.exists() or not database.is_file():
        raise SafeLoadError(f"Database not found: {database}")

    connection = connect_database(database)
    results: list[RecordResult] = []
    mapping: dict[str, str] = {}
    synthesized: list[str] = []
    public_before = 0

    try:
        columns, mapping, synthesized = validate_database(connection, output_dir)
        public_before = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO database_load_runs (
                run_id, loader_version, input_file, input_sha256,
                started_at, status, dry_run, total_records, initiated_by
            )
            VALUES (?, ?, ?, ?, ?, 'STARTED', ?, ?, ?)
            """,
            (
                run_id,
                LOADER_VERSION,
                str(input_path.resolve()),
                input_hash,
                started_at,
                int(not commit),
                len(rows),
                initiated_by,
            ),
        )

        for row in rows:
            results.append(
                process_row(
                    connection,
                    run_id,
                    row,
                    columns,
                    mapping,
                    protect_published,
                )
            )

        public_after = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )
        if public_after != public_before:
            raise SafeLoadError(
                "Publication boundary violation: public count changed from "
                f"{public_before} to {public_after}."
            )

        completed_at = utc_now()
        inserted = sum(item.load_action == "INSERT" for item in results)
        updated = sum(item.load_action == "UPDATE" for item in results)
        skipped = sum(item.result == "SKIPPED" for item in results)

        connection.execute(
            """
            UPDATE database_load_runs
            SET completed_at=?,
                status='COMPLETED',
                inserted_records=?,
                updated_records=?,
                skipped_records=?,
                failed_records=0
            WHERE run_id=?
            """,
            (completed_at, inserted, updated, skipped, run_id),
        )

        if commit:
            connection.commit()
            status = "COMPLETED"
        else:
            connection.rollback()
            status = "DRY_RUN_ROLLED_BACK"

        summary = LoadSummary(
            loader_version=LOADER_VERSION,
            run_id=run_id,
            mode=mode,
            status=status,
            database=str(database.resolve()),
            input_file=str(input_path.resolve()),
            input_sha256=input_hash,
            total_records=len(rows),
            inserted_records=inserted,
            updated_records=updated,
            skipped_records=skipped,
            failed_records=0,
            protected_published_records=sum(
                item.reason == "PUBLISHED_RECORD_PROTECTED" for item in results
            ),
            unchanged_records=sum(
                item.reason == "NO_CONTENT_CHANGES" for item in results
            ),
            public_count_before=public_before,
            public_count_after=public_after,
            schema_mapping=mapping,
            synthesized_columns=synthesized,
            started_at=started_at,
            completed_at=completed_at,
            initiated_by=initiated_by,
            output_directory=str(output_dir.resolve()),
        )
        write_outputs(output_dir, summary, results, [])
        return summary, results, []
    except Exception as exc:
        connection.rollback()
        summary = failed_summary(
            run_id=run_id,
            mode=mode,
            database=database,
            input_path=input_path,
            input_hash=input_hash,
            output_dir=output_dir,
            initiated_by=initiated_by,
            started_at=started_at,
            total_records=len(rows),
            failed_records=len(rows),
            schema_mapping=mapping,
            synthesized=synthesized,
            status="FAILED",
            error=str(exc),
        )
        failure_rows = [
            {
                "row_number": "",
                "master_id": row.get("master_id") or "",
                "reason": str(exc),
            }
            for row in rows
        ]
        write_outputs(output_dir, summary, [], failure_rows)
        raise
    finally:
        connection.close()


def inspect_database(database: Path, output_dir: Path) -> dict[str, Any]:
    if not database.exists() or not database.is_file():
        raise SafeLoadError(f"Database not found: {database}")
    connection = connect_database(database)
    try:
        report = schema_report(connection)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "schema_compatibility_v2_7_3_3a.json", report)
        return report
    finally:
        connection.close()


def create_exact_production_schema(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;

            CREATE TABLE import_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL
            );

            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                short_name TEXT,
                source TEXT,
                ministry TEXT,
                department TEXT,
                implementing_agency TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                scheme_status TEXT,
                geographic_scope TEXT,
                official_page_url TEXT,
                application_url TEXT,
                opening_date TEXT,
                closing_date TEXT,
                validation_score REAL,
                validation_decision TEXT NOT NULL,
                publication_status TEXT NOT NULL DEFAULT 'STAGED',
                funding_minimum INTEGER,
                funding_maximum INTEGER,
                currency TEXT,
                beneficiary_support_minimum INTEGER,
                beneficiary_support_maximum INTEGER,
                intermediary_support_maximum INTEGER,
                scheme_corpus INTEGER,
                record_hash TEXT NOT NULL,
                raw_record_json TEXT NOT NULL,
                first_loaded_at TEXT NOT NULL,
                last_loaded_at TEXT NOT NULL,
                last_import_run_id TEXT,
                is_public INTEGER NOT NULL DEFAULT 0,
                published_at TEXT,
                published_by TEXT,
                unpublished_at TEXT,
                unpublished_by TEXT,
                publication_notes TEXT,
                source_run_id TEXT,
                record_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (last_import_run_id)
                    REFERENCES import_runs(run_id)
                    ON UPDATE CASCADE
                    ON DELETE SET NULL
            );

            CREATE VIEW public_schemes AS
            SELECT * FROM scheme_staging
            WHERE publication_status='PUBLISHED' AND is_public=1;

            CREATE TABLE publication_audit_log (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_status TEXT,
                new_status TEXT NOT NULL,
                previous_is_public INTEGER,
                new_is_public INTEGER NOT NULL,
                action_by TEXT NOT NULL,
                action_at TEXT NOT NULL,
                reason TEXT,
                source_run_id TEXT,
                record_version INTEGER,
                metadata_json TEXT
            );

            CREATE TABLE database_load_runs (
                run_id TEXT PRIMARY KEY,
                loader_version TEXT NOT NULL,
                input_file TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                dry_run INTEGER NOT NULL,
                total_records INTEGER NOT NULL DEFAULT 0,
                inserted_records INTEGER NOT NULL DEFAULT 0,
                updated_records INTEGER NOT NULL DEFAULT 0,
                skipped_records INTEGER NOT NULL DEFAULT 0,
                failed_records INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                initiated_by TEXT NOT NULL
            );

            CREATE TABLE safe_load_record_audit (
                record_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                master_id TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                reason TEXT,
                before_json TEXT,
                after_json TEXT,
                processed_at TEXT NOT NULL
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def create_test_csv(path: Path) -> None:
    rows = [
        {
            "master_id": "23290a8aab541138ab07",
            "source": "DST",
            "canonical_name": "Mega Facilities for Basic Research Scheme",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "final_url": "https://dst.gov.in/mega-facilities-basic-research-scheme",
            "application_url": "https://dst.gov.in/announcement/applications-invited-throughout-year",
            "confidence_after_validation": "1.000",
            "validation_decision": APPROVED_DECISION,
        }
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def self_test() -> dict[str, Any]:
    result: dict[str, Any] = {
        "loader_version": LOADER_VERSION,
        "tests": {},
        "passed": False,
    }

    with tempfile.TemporaryDirectory(prefix="ssip_v2732_") as temporary:
        temp = Path(temporary)
        database = temp / "production_schema.db"
        input_csv = temp / "approved_for_database_test.csv"
        output_dir = temp / "output"

        create_exact_production_schema(database)
        create_test_csv(input_csv)

        report = inspect_database(database, output_dir)
        result["tests"]["production_schema_ready"] = report["database_ready"]
        result["tests"]["final_url_maps_to_official_page_url"] = (
            report["resolved_field_mapping"]["final_url"] == "official_page_url"
        )
        result["tests"]["mandatory_audit_fields_synthesized"] = set(
            (
                "validation_decision",
                "record_hash",
                "raw_record_json",
                "first_loaded_at",
                "last_loaded_at",
                "last_import_run_id",
            )
        ).issubset(set(report["synthesized_columns"]))

        dry, _, _ = run_loader(
            input_csv,
            database,
            output_dir,
            commit=False,
            initiated_by="SELF_TEST",
        )
        result["tests"]["dry_run_passed"] = (
            dry.status == "DRY_RUN_ROLLED_BACK"
            and dry.inserted_records == 1
            and dry.failed_records == 0
            and dry.public_count_before == dry.public_count_after == 0
        )

        connection = connect_database(database)
        try:
            result["tests"]["dry_run_rolled_back"] = (
                int(scalar(connection, "SELECT COUNT(*) FROM scheme_staging") or 0)
                == 0
            )
        finally:
            connection.close()

        committed, _, _ = run_loader(
            input_csv,
            database,
            output_dir,
            commit=True,
            initiated_by="SELF_TEST",
        )
        result["tests"]["commit_passed"] = (
            committed.status == "COMPLETED"
            and committed.inserted_records == 1
            and committed.failed_records == 0
        )

        connection = connect_database(database)
        try:
            row = connection.execute(
                """
                SELECT *
                FROM scheme_staging
                WHERE master_id='23290a8aab541138ab07'
                """
            ).fetchone()
            result["tests"]["field_mapping_correct"] = (
                row["scheme_name"]
                == "Mega Facilities for Basic Research Scheme"
                and row["official_page_url"]
                == "https://dst.gov.in/mega-facilities-basic-research-scheme"
                and float(row["validation_score"]) == 1.0
                and row["validation_decision"] == APPROVED_DECISION
            )
            result["tests"]["legacy_metadata_populated"] = all(
                row[name]
                for name in (
                    "record_hash",
                    "raw_record_json",
                    "first_loaded_at",
                    "last_loaded_at",
                )
            )
            result["tests"]["nullable_legacy_run_fk_safely_suppressed"] = (
                row["last_import_run_id"] is None
            )
            result["tests"]["new_record_private"] = (
                row["publication_status"] == "STAGED"
                and int(row["is_public"]) == 0
            )
        finally:
            connection.close()

        rerun, _, _ = run_loader(
            input_csv,
            database,
            output_dir,
            commit=True,
            initiated_by="SELF_TEST",
        )
        result["tests"]["rerun_idempotent"] = (
            rerun.inserted_records == 0
            and rerun.updated_records == 0
            and rerun.skipped_records == 1
            and rerun.unchanged_records == 1
        )

    result["passed"] = all(bool(value) for value in result["tests"].values())
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SSIP v2.7.3.3 foreign-key-aware safe approved loader."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/incremental/v2_7_3_safe_load"),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--commit", action="store_true")

    parser.add_argument("--inspect-schema", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--initiated-by",
        default=os.environ.get("USERNAME")
        or os.environ.get("USER")
        or "SSIP_ADMIN",
    )
    parser.add_argument("--allow-published-update", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.self_test:
            payload = self_test()
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0 if payload["passed"] else 1

        if args.inspect_schema:
            if args.database is None:
                raise SafeLoadError("--database is required with --inspect-schema")
            payload = inspect_database(args.database, args.output_dir)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0 if payload.get("database_ready") else 1

        if args.input is None or args.database is None:
            raise SafeLoadError("--input and --database are required.")
        if not args.dry_run and not args.commit:
            raise SafeLoadError("Choose --dry-run or --commit explicitly.")

        summary, _, failures = run_loader(
            input_path=args.input,
            database=args.database,
            output_dir=args.output_dir,
            commit=bool(args.commit),
            initiated_by=args.initiated_by,
            protect_published=not args.allow_published_update,
        )
        print(json.dumps(asdict(summary), indent=2, ensure_ascii=False))
        return 0 if not failures and summary.status not in {
            "FAILED",
            "INPUT_VALIDATION_FAILED",
        } else 1

    except (SafeLoadError, sqlite3.Error, OSError, csv.Error) as exc:
        print(
            json.dumps(
                {
                    "loader_version": LOADER_VERSION,
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "completed_at": utc_now(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
