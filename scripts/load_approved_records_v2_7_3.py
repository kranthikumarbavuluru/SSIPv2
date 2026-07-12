#!/usr/bin/env python3
"""
SSIP v2.7.3 — Safe Approved-Record Database Loader

Loads only validated, approved records into scheme_staging while keeping every
new record private (STAGED + is_public=0).

Safety guarantees
-----------------
* Explicit --dry-run or --commit mode is mandatory.
* Input approval provenance is verified.
* All input rows are validated before the database transaction begins.
* Duplicate input master_id values stop the complete run.
* The database load is all-or-nothing.
* Re-running the same input is idempotent.
* Existing publication state is never changed by this loader.
* Published records are protected from automated content updates by default.
* Every committed load and record decision is auditable.
* Output CSV and JSON reports are generated for every run.

Python: 3.10+
Database: SQLite after SSIP v2.7.3 Step 1 migration
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

LOADER_VERSION = "2.7.3"
APPROVED_DECISION = "APPROVED_FOR_DATABASE"

PUBLICATION_COLUMNS = {
    "publication_status",
    "is_public",
    "published_at",
    "published_by",
    "unpublished_at",
    "unpublished_by",
    "publication_notes",
}
SYSTEM_MANAGED_COLUMNS = {
    "source_run_id",
    "record_version",
    "created_at",
    "updated_at",
}
NEVER_COPY_COLUMNS = PUBLICATION_COLUMNS | SYSTEM_MANAGED_COLUMNS

MANDATORY_INPUT_COLUMNS = {
    "master_id",
    "source",
    "canonical_name",
    "programme_status",
    "final_url",
}
DECISION_COLUMN_CANDIDATES = (
    "validation_decision",
    "decision",
    "final_decision",
    "database_decision",
)
MASTER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,127}$")


class SafeLoadError(RuntimeError):
    """Raised when a safe database load cannot continue."""


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
    started_at: str
    completed_at: str
    initiated_by: str
    output_directory: str
    error_message: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        is not None
    )


def view_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='view' AND name=?",
            (name,),
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


def scalar(
    connection: sqlite3.Connection,
    sql: str,
    params: Iterable[Any] = (),
) -> Any:
    row = connection.execute(sql, tuple(params)).fetchone()
    return None if row is None else row[0]


def normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def validate_url(value: str | None, field: str, row_number: int) -> str | None:
    if value is None:
        return None
    if any(char.isspace() for char in value):
        raise ValueError(f"row {row_number}: {field} contains whitespace")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"row {row_number}: {field} is not a valid HTTP(S) URL")
    return value


def coerce_for_sqlite(value: str | None, declared_type: str | None) -> Any:
    if value is None:
        return None
    declared = (declared_type or "").upper()
    try:
        if "INT" in declared:
            return int(value)
        if any(token in declared for token in ("REAL", "FLOA", "DOUB", "NUM")):
            return float(value)
    except ValueError:
        # Preserve the source value rather than silently dropping information.
        return value
    return value


def read_and_validate_input(
    input_path: Path,
) -> tuple[list[str], list[dict[str, str | None]], list[dict[str, str]]]:
    if not input_path.exists() or not input_path.is_file():
        raise SafeLoadError(f"Input CSV not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.reader(handle))

    if not raw_rows:
        raise SafeLoadError("Input CSV is empty.")

    original_headers = raw_rows[0]
    headers = [normalize_header(header) for header in original_headers]

    if any(not header for header in headers):
        raise SafeLoadError("Input CSV contains a blank column name.")
    if len(headers) != len(set(headers)):
        duplicates = sorted({h for h in headers if headers.count(h) > 1})
        raise SafeLoadError(
            "Input CSV contains duplicate normalized columns: " + ", ".join(duplicates)
        )

    missing = sorted(MANDATORY_INPUT_COLUMNS - set(headers))
    if missing:
        raise SafeLoadError(
            "Input CSV is missing mandatory columns: " + ", ".join(missing)
        )

    decision_column = next(
        (column for column in DECISION_COLUMN_CANDIDATES if column in headers),
        None,
    )
    filename_proves_approval = "approved_for_database" in input_path.name.lower()
    if decision_column is None and not filename_proves_approval:
        raise SafeLoadError(
            "Approval provenance not established. Use an approved_for_database CSV "
            "or include a validation_decision column."
        )

    rows: list[dict[str, str | None]] = []
    failures: list[dict[str, str]] = []
    seen_ids: dict[str, int] = {}

    for row_number, raw_values in enumerate(raw_rows[1:], start=2):
        if not any(str(value).strip() for value in raw_values):
            continue

        if len(raw_values) > len(headers):
            failures.append(
                {
                    "row_number": str(row_number),
                    "master_id": "",
                    "reason": "Row has more values than the CSV header.",
                }
            )
            continue

        padded = raw_values + [""] * (len(headers) - len(raw_values))
        row = {
            header: normalize_text(value)
            for header, value in zip(headers, padded)
        }

        master_id = row.get("master_id")
        try:
            if not master_id or not MASTER_ID_RE.fullmatch(master_id):
                raise ValueError(
                    f"row {row_number}: master_id must be 6-128 safe characters"
                )

            if master_id in seen_ids:
                raise ValueError(
                    f"row {row_number}: duplicate master_id; first seen at "
                    f"row {seen_ids[master_id]}"
                )
            seen_ids[master_id] = row_number

            for required in MANDATORY_INPUT_COLUMNS:
                if not row.get(required):
                    raise ValueError(f"row {row_number}: {required} is blank")

            if decision_column:
                decision = (row.get(decision_column) or "").upper()
                if decision != APPROVED_DECISION:
                    raise ValueError(
                        f"row {row_number}: {decision_column} is {decision!r}, "
                        f"not {APPROVED_DECISION}"
                    )

            row["final_url"] = validate_url(
                row.get("final_url"), "final_url", row_number
            )
            if "application_url" in row:
                row["application_url"] = validate_url(
                    row.get("application_url"), "application_url", row_number
                )

            rows.append(row)
        except ValueError as exc:
            failures.append(
                {
                    "row_number": str(row_number),
                    "master_id": master_id or "",
                    "reason": str(exc),
                }
            )

    if not rows and not failures:
        raise SafeLoadError("Input CSV contains no data rows.")

    return headers, rows, failures


def verify_database_ready(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    required_tables = {
        "scheme_staging",
        "database_load_runs",
        "safe_load_record_audit",
        "publication_audit_log",
    }
    missing_tables = sorted(
        name for name in required_tables if not table_exists(connection, name)
    )
    if missing_tables:
        raise SafeLoadError(
            "Database is not migrated to v2.7.3. Missing tables: "
            + ", ".join(missing_tables)
        )

    if not view_exists(connection, "public_schemes"):
        raise SafeLoadError("Database is missing the public_schemes safety view.")

    columns = table_columns(connection, "scheme_staging")
    required_columns = (
        MANDATORY_INPUT_COLUMNS
        | PUBLICATION_COLUMNS
        | SYSTEM_MANAGED_COLUMNS
    )
    missing_columns = sorted(required_columns - set(columns))
    if missing_columns:
        raise SafeLoadError(
            "scheme_staging is missing required v2.7.3 columns: "
            + ", ".join(missing_columns)
        )

    quick_check = scalar(connection, "PRAGMA quick_check")
    if quick_check != "ok":
        raise SafeLoadError(f"SQLite quick_check failed: {quick_check}")

    return columns


def row_as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else dict(row)


def comparable(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def map_input_to_database(
    input_row: dict[str, str | None],
    columns: dict[str, sqlite3.Row],
) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for name, value in input_row.items():
        if name not in columns or name in NEVER_COPY_COLUMNS:
            continue
        mapped[name] = coerce_for_sqlite(value, columns[name]["type"])
    return mapped


def write_run_start(
    connection: sqlite3.Connection,
    run_id: str,
    input_path: Path,
    input_hash: str,
    started_at: str,
    dry_run: bool,
    initiated_by: str,
    total_records: int,
) -> None:
    connection.execute(
        """
        INSERT INTO database_load_runs (
            run_id,
            loader_version,
            input_file,
            input_sha256,
            started_at,
            status,
            dry_run,
            total_records,
            initiated_by
        )
        VALUES (?, ?, ?, ?, ?, 'STARTED', ?, ?, ?)
        """,
        (
            run_id,
            LOADER_VERSION,
            str(input_path.resolve()),
            input_hash,
            started_at,
            int(dry_run),
            total_records,
            initiated_by,
        ),
    )


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
            run_id,
            master_id,
            action,
            result,
            reason,
            before_json,
            after_json,
            processed_at
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


def process_record(
    connection: sqlite3.Connection,
    run_id: str,
    input_row: dict[str, str | None],
    columns: dict[str, sqlite3.Row],
    protect_published: bool,
) -> RecordResult:
    now = utc_now()
    master_id = input_row["master_id"] or ""
    source = input_row["source"] or ""
    canonical_name = input_row["canonical_name"] or ""

    existing = connection.execute(
        "SELECT * FROM scheme_staging WHERE master_id = ?",
        (master_id,),
    ).fetchone()
    mapped = map_input_to_database(input_row, columns)

    if existing is None:
        insert_values = dict(mapped)
        insert_values.update(
            {
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
            }
        )

        names = list(insert_values)
        placeholders = ", ".join("?" for _ in names)
        quoted_names = ", ".join(f'"{name}"' for name in names)
        connection.execute(
            f"INSERT INTO scheme_staging ({quoted_names}) VALUES ({placeholders})",
            tuple(insert_values[name] for name in names),
        )
        after = row_as_dict(
            connection.execute(
                "SELECT * FROM scheme_staging WHERE master_id = ?",
                (master_id,),
            ).fetchone()
        )
        write_record_audit(
            connection,
            run_id,
            master_id,
            "INSERT",
            "ACCEPTED",
            "NEW_APPROVED_RECORD_STAGED",
            None,
            after,
            now,
        )
        return RecordResult(
            run_id=run_id,
            master_id=master_id,
            source=source,
            canonical_name=canonical_name,
            load_action="INSERT",
            result="ACCEPTED",
            reason="NEW_APPROVED_RECORD_STAGED",
            previous_publication_status=None,
            previous_is_public=None,
            record_version=1,
        )

    before = dict(existing)
    publication_status = comparable(existing["publication_status"])
    is_public = int(existing["is_public"])

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
            run_id=run_id,
            master_id=master_id,
            source=source,
            canonical_name=canonical_name,
            load_action="SKIP",
            result="SKIPPED",
            reason="PUBLISHED_RECORD_PROTECTED",
            previous_publication_status=publication_status,
            previous_is_public=is_public,
            record_version=int(existing["record_version"] or 1),
        )

    changed_values: dict[str, Any] = {}
    for name, value in mapped.items():
        if name == "master_id":
            continue
        if comparable(existing[name]) != comparable(value):
            changed_values[name] = value

    if not changed_values:
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
            run_id=run_id,
            master_id=master_id,
            source=source,
            canonical_name=canonical_name,
            load_action="SKIP",
            result="SKIPPED",
            reason="NO_CONTENT_CHANGES",
            previous_publication_status=publication_status,
            previous_is_public=is_public,
            record_version=int(existing["record_version"] or 1),
        )

    new_version = int(existing["record_version"] or 1) + 1
    changed_values["source_run_id"] = run_id
    changed_values["record_version"] = new_version
    changed_values["updated_at"] = now

    assignments = ", ".join(f'"{name}" = ?' for name in changed_values)
    connection.execute(
        f"UPDATE scheme_staging SET {assignments} WHERE master_id = ?",
        (*changed_values.values(), master_id),
    )
    after = row_as_dict(
        connection.execute(
            "SELECT * FROM scheme_staging WHERE master_id = ?",
            (master_id,),
        ).fetchone()
    )
    write_record_audit(
        connection,
        run_id,
        master_id,
        "UPDATE",
        "ACCEPTED",
        "APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED",
        before,
        after,
        now,
    )
    return RecordResult(
        run_id=run_id,
        master_id=master_id,
        source=source,
        canonical_name=canonical_name,
        load_action="UPDATE",
        result="ACCEPTED",
        reason="APPROVED_CONTENT_UPDATED_PUBLICATION_STATE_PRESERVED",
        previous_publication_status=publication_status,
        previous_is_public=is_public,
        record_version=new_version,
    )


def update_run_complete(
    connection: sqlite3.Connection,
    run_id: str,
    completed_at: str,
    results: list[RecordResult],
) -> None:
    inserted = sum(result.load_action == "INSERT" for result in results)
    updated = sum(result.load_action == "UPDATE" for result in results)
    skipped = sum(result.result == "SKIPPED" for result in results)
    failed = sum(result.result == "FAILED" for result in results)

    connection.execute(
        """
        UPDATE database_load_runs
        SET completed_at = ?,
            status = 'COMPLETED',
            inserted_records = ?,
            updated_records = ?,
            skipped_records = ?,
            failed_records = ?
        WHERE run_id = ?
        """,
        (completed_at, inserted, updated, skipped, failed, run_id),
    )


def persist_failed_run(
    database_path: Path,
    run_id: str,
    input_path: Path,
    input_hash: str,
    started_at: str,
    initiated_by: str,
    total_records: int,
    error_message: str,
) -> None:
    try:
        connection = connect_database(database_path)
        try:
            if not table_exists(connection, "database_load_runs"):
                return
            connection.execute(
                """
                INSERT OR REPLACE INTO database_load_runs (
                    run_id,
                    loader_version,
                    input_file,
                    input_sha256,
                    started_at,
                    completed_at,
                    status,
                    dry_run,
                    total_records,
                    failed_records,
                    error_message,
                    initiated_by
                )
                VALUES (?, ?, ?, ?, ?, ?, 'FAILED', 0, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    LOADER_VERSION,
                    str(input_path.resolve()),
                    input_hash,
                    started_at,
                    utc_now(),
                    total_records,
                    total_records,
                    error_message[:4000],
                    initiated_by,
                ),
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # Never hide the original loader failure with a secondary audit failure.
        pass


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def result_dicts(results: list[RecordResult]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]


def write_outputs(
    output_dir: Path,
    summary: LoadSummary,
    results: list[RecordResult],
    validation_failures: list[dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    result_rows = result_dicts(results)
    result_fields = list(asdict(RecordResult(
        run_id="",
        master_id="",
        source="",
        canonical_name="",
        load_action="",
        result="",
        reason="",
    )).keys())

    accepted = [row for row in result_rows if row["result"] == "ACCEPTED"]
    skipped = [row for row in result_rows if row["result"] == "SKIPPED"]

    write_csv(
        output_dir / "safe_load_accepted_v2_7_3.csv",
        accepted,
        result_fields,
    )
    write_csv(
        output_dir / "safe_load_skipped_v2_7_3.csv",
        skipped,
        result_fields,
    )
    write_csv(
        output_dir / "safe_load_failed_v2_7_3.csv",
        validation_failures,
        ["row_number", "master_id", "reason"],
    )
    write_csv(
        output_dir / "safe_load_audit_v2_7_3.csv",
        result_rows,
        result_fields,
    )

    (output_dir / "safe_load_summary_v2_7_3.json").write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_loader(
    input_path: Path,
    database_path: Path,
    output_dir: Path,
    commit: bool,
    initiated_by: str,
    protect_published: bool = True,
) -> tuple[LoadSummary, list[RecordResult], list[dict[str, str]]]:
    started_at = utc_now()
    run_id = uuid.uuid4().hex
    mode = "COMMIT" if commit else "DRY_RUN"

    if not database_path.exists() or not database_path.is_file():
        raise SafeLoadError(f"Database not found: {database_path}")

    input_hash = sha256_file(input_path)
    _, rows, validation_failures = read_and_validate_input(input_path)

    if validation_failures:
        summary = LoadSummary(
            loader_version=LOADER_VERSION,
            run_id=run_id,
            mode=mode,
            status="INPUT_VALIDATION_FAILED",
            database=str(database_path.resolve()),
            input_file=str(input_path.resolve()),
            input_sha256=input_hash,
            total_records=len(rows) + len(validation_failures),
            inserted_records=0,
            updated_records=0,
            skipped_records=0,
            failed_records=len(validation_failures),
            protected_published_records=0,
            unchanged_records=0,
            public_count_before=0,
            public_count_after=0,
            started_at=started_at,
            completed_at=utc_now(),
            initiated_by=initiated_by,
            output_directory=str(output_dir.resolve()),
            error_message="One or more input rows failed validation. No database changes made.",
        )
        write_outputs(output_dir, summary, [], validation_failures)
        if commit:
            persist_failed_run(
                database_path,
                run_id,
                input_path,
                input_hash,
                started_at,
                initiated_by,
                len(rows) + len(validation_failures),
                summary.error_message or "Input validation failed",
            )
        return summary, [], validation_failures

    connection = connect_database(database_path)
    results: list[RecordResult] = []
    public_before = 0

    try:
        columns = verify_database_ready(connection)
        public_before = int(scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0)

        connection.execute("BEGIN IMMEDIATE")
        write_run_start(
            connection,
            run_id,
            input_path,
            input_hash,
            started_at,
            not commit,
            initiated_by,
            len(rows),
        )

        for row in rows:
            results.append(
                process_record(
                    connection,
                    run_id,
                    row,
                    columns,
                    protect_published=protect_published,
                )
            )

        public_after = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )
        if public_after != public_before:
            raise SafeLoadError(
                "Publication boundary violation: safe load changed the public record count "
                f"from {public_before} to {public_after}."
            )

        invalid_states = int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM scheme_staging
                WHERE (publication_status = 'PUBLISHED' AND is_public <> 1)
                   OR (publication_status <> 'PUBLISHED' AND is_public <> 0)
                """,
            )
            or 0
        )
        if invalid_states:
            raise SafeLoadError(
                f"Post-load publication verification found {invalid_states} invalid state(s)."
            )

        completed_at = utc_now()
        update_run_complete(connection, run_id, completed_at, results)

        if commit:
            connection.commit()
            status = "COMPLETED"
        else:
            connection.rollback()
            status = "DRY_RUN_ROLLED_BACK"

        inserted = sum(result.load_action == "INSERT" for result in results)
        updated = sum(result.load_action == "UPDATE" for result in results)
        skipped = sum(result.result == "SKIPPED" for result in results)
        protected = sum(
            result.reason == "PUBLISHED_RECORD_PROTECTED" for result in results
        )
        unchanged = sum(result.reason == "NO_CONTENT_CHANGES" for result in results)

        summary = LoadSummary(
            loader_version=LOADER_VERSION,
            run_id=run_id,
            mode=mode,
            status=status,
            database=str(database_path.resolve()),
            input_file=str(input_path.resolve()),
            input_sha256=input_hash,
            total_records=len(rows),
            inserted_records=inserted,
            updated_records=updated,
            skipped_records=skipped,
            failed_records=0,
            protected_published_records=protected,
            unchanged_records=unchanged,
            public_count_before=public_before,
            public_count_after=public_after,
            started_at=started_at,
            completed_at=completed_at,
            initiated_by=initiated_by,
            output_directory=str(output_dir.resolve()),
        )
        write_outputs(output_dir, summary, results, [])
        return summary, results, []
    except Exception as exc:
        connection.rollback()
        if commit:
            persist_failed_run(
                database_path,
                run_id,
                input_path,
                input_hash,
                started_at,
                initiated_by,
                len(rows),
                str(exc),
            )
        raise
    finally:
        connection.close()


def create_self_test_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE scheme_staging (
                master_id TEXT NOT NULL,
                source TEXT,
                canonical_name TEXT,
                programme_status TEXT,
                final_url TEXT,
                application_url TEXT,
                confidence_after_validation REAL,
                publication_status TEXT NOT NULL DEFAULT 'STAGED',
                is_public INTEGER NOT NULL DEFAULT 0,
                published_at TEXT,
                published_by TEXT,
                unpublished_at TEXT,
                unpublished_by TEXT,
                publication_notes TEXT,
                source_run_id TEXT,
                record_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE UNIQUE INDEX ux_scheme_staging_master_id
            ON scheme_staging(master_id);

            CREATE TRIGGER trg_scheme_staging_publication_guard_insert
            BEFORE INSERT ON scheme_staging
            BEGIN
                SELECT CASE
                    WHEN NEW.publication_status = 'PUBLISHED' AND NEW.is_public <> 1
                    THEN RAISE(ABORT, 'PUBLISHED records must be public')
                    WHEN NEW.publication_status <> 'PUBLISHED' AND NEW.is_public <> 0
                    THEN RAISE(ABORT, 'Only PUBLISHED records may be public')
                END;
            END;

            CREATE TRIGGER trg_scheme_staging_publication_guard_update
            BEFORE UPDATE OF publication_status, is_public ON scheme_staging
            BEGIN
                SELECT CASE
                    WHEN NEW.publication_status = 'PUBLISHED' AND NEW.is_public <> 1
                    THEN RAISE(ABORT, 'PUBLISHED records must be public')
                    WHEN NEW.publication_status <> 'PUBLISHED' AND NEW.is_public <> 0
                    THEN RAISE(ABORT, 'Only PUBLISHED records may be public')
                END;
            END;

            CREATE VIEW public_schemes AS
            SELECT *
            FROM scheme_staging
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
                processed_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES database_load_runs(run_id)
            );
            """
        )
        now = utc_now()
        connection.executemany(
            """
            INSERT INTO scheme_staging (
                master_id, source, canonical_name, programme_status,
                final_url, publication_status, is_public,
                published_at, published_by,
                record_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "EXIST001",
                    "DST",
                    "Old Scheme Name",
                    "SCHEME_INFORMATION_AVAILABLE",
                    "https://example.gov/old",
                    "STAGED",
                    0,
                    None,
                    None,
                    1,
                    now,
                    now,
                ),
                (
                    "PUBLIC01",
                    "BIRAC",
                    "Published Scheme",
                    "SCHEME_INFORMATION_AVAILABLE",
                    "https://example.gov/public",
                    "PUBLISHED",
                    1,
                    now,
                    "ADMIN",
                    2,
                    now,
                    now,
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def create_self_test_csv(path: Path) -> None:
    rows = [
        {
            "master_id": "EXIST001",
            "source": "DST",
            "canonical_name": "Updated Scheme Name",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "final_url": "https://example.gov/updated",
            "application_url": "https://example.gov/apply",
            "confidence_after_validation": "1.0",
            "validation_decision": APPROVED_DECISION,
        },
        {
            "master_id": "NEW00001",
            "source": "DST",
            "canonical_name": "New Approved Scheme",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "final_url": "https://example.gov/new",
            "application_url": "",
            "confidence_after_validation": "0.95",
            "validation_decision": APPROVED_DECISION,
        },
        {
            "master_id": "PUBLIC01",
            "source": "BIRAC",
            "canonical_name": "Attempted Automated Change",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "final_url": "https://example.gov/public-new",
            "application_url": "",
            "confidence_after_validation": "1.0",
            "validation_decision": APPROVED_DECISION,
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def self_test() -> dict[str, Any]:
    report: dict[str, Any] = {
        "loader_version": LOADER_VERSION,
        "tests": {},
        "passed": False,
    }

    with tempfile.TemporaryDirectory(prefix="ssip_v273_loader_") as temp_dir:
        temp = Path(temp_dir)
        database = temp / "ssip.db"
        input_csv = temp / "approved_for_database_self_test.csv"
        dry_outputs = temp / "dry"
        commit_outputs = temp / "commit"
        rerun_outputs = temp / "rerun"

        create_self_test_database(database)
        create_self_test_csv(input_csv)

        dry_summary, _, _ = run_loader(
            input_csv,
            database,
            dry_outputs,
            commit=False,
            initiated_by="SELF_TEST",
        )
        report["tests"]["dry_run_counts_correct"] = (
            dry_summary.inserted_records == 1
            and dry_summary.updated_records == 1
            and dry_summary.skipped_records == 1
        )

        connection = connect_database(database)
        try:
            report["tests"]["dry_run_rolled_back"] = (
                scalar(
                    connection,
                    "SELECT canonical_name FROM scheme_staging WHERE master_id='EXIST001'",
                )
                == "Old Scheme Name"
                and int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM scheme_staging WHERE master_id='NEW00001'",
                    )
                    or 0
                )
                == 0
                and int(
                    scalar(connection, "SELECT COUNT(*) FROM database_load_runs") or 0
                )
                == 0
            )
        finally:
            connection.close()

        commit_summary, _, _ = run_loader(
            input_csv,
            database,
            commit_outputs,
            commit=True,
            initiated_by="SELF_TEST",
        )
        report["tests"]["commit_counts_correct"] = (
            commit_summary.inserted_records == 1
            and commit_summary.updated_records == 1
            and commit_summary.skipped_records == 1
            and commit_summary.protected_published_records == 1
        )

        connection = connect_database(database)
        try:
            new_state = connection.execute(
                """
                SELECT publication_status, is_public, record_version
                FROM scheme_staging
                WHERE master_id='NEW00001'
                """
            ).fetchone()
            existing_state = connection.execute(
                """
                SELECT canonical_name, publication_status, is_public, record_version
                FROM scheme_staging
                WHERE master_id='EXIST001'
                """
            ).fetchone()
            public_state = connection.execute(
                """
                SELECT canonical_name, publication_status, is_public, record_version
                FROM scheme_staging
                WHERE master_id='PUBLIC01'
                """
            ).fetchone()

            report["tests"]["new_record_private"] = (
                new_state["publication_status"] == "STAGED"
                and int(new_state["is_public"]) == 0
                and int(new_state["record_version"]) == 1
            )
            report["tests"]["existing_staged_record_updated"] = (
                existing_state["canonical_name"] == "Updated Scheme Name"
                and existing_state["publication_status"] == "STAGED"
                and int(existing_state["is_public"]) == 0
                and int(existing_state["record_version"]) == 2
            )
            report["tests"]["published_record_protected"] = (
                public_state["canonical_name"] == "Published Scheme"
                and public_state["publication_status"] == "PUBLISHED"
                and int(public_state["is_public"]) == 1
                and int(public_state["record_version"]) == 2
            )
            report["tests"]["public_count_unchanged"] = (
                int(scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0)
                == 1
            )
            report["tests"]["audit_rows_committed"] = (
                int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM safe_load_record_audit",
                    )
                    or 0
                )
                == 3
            )
        finally:
            connection.close()

        rerun_summary, _, _ = run_loader(
            input_csv,
            database,
            rerun_outputs,
            commit=True,
            initiated_by="SELF_TEST",
        )
        report["tests"]["rerun_idempotent"] = (
            rerun_summary.inserted_records == 0
            and rerun_summary.updated_records == 0
            and rerun_summary.skipped_records == 3
            and rerun_summary.unchanged_records == 2
            and rerun_summary.protected_published_records == 1
        )

        required_outputs = {
            "safe_load_accepted_v2_7_3.csv",
            "safe_load_skipped_v2_7_3.csv",
            "safe_load_failed_v2_7_3.csv",
            "safe_load_audit_v2_7_3.csv",
            "safe_load_summary_v2_7_3.json",
        }
        report["tests"]["reports_created"] = required_outputs.issubset(
            {path.name for path in commit_outputs.iterdir()}
        )

    report["passed"] = all(bool(value) for value in report["tests"].values())
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SSIP v2.7.3 safe approved-record database loader."
    )
    parser.add_argument("--input", type=Path, help="Approved validation CSV.")
    parser.add_argument("--database", type=Path, help="SSIP SQLite database.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/incremental/v2_7_3_safe_load"),
        help="Directory for CSV and JSON reports.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Process and verify the complete load, then roll it back.",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="Commit the complete transactional load.",
    )

    parser.add_argument(
        "--initiated-by",
        default=os.environ.get("USERNAME")
        or os.environ.get("USER")
        or "SSIP_ADMIN",
        help="Administrator identity recorded in load audit.",
    )
    parser.add_argument(
        "--allow-published-update",
        action="store_true",
        help=(
            "Allow approved content fields of published records to be updated. "
            "Publication state is still preserved. Not recommended for routine loads."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run isolated loader safety tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if args.self_test:
            result = self_test()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["passed"] else 1

        if args.input is None or args.database is None:
            raise SafeLoadError(
                "--input and --database are required unless --self-test is used."
            )
        if not args.dry_run and not args.commit:
            raise SafeLoadError(
                "Choose one explicit mode: --dry-run or --commit. "
                "No database changes were made."
            )

        summary, _, failures = run_loader(
            input_path=args.input,
            database_path=args.database,
            output_dir=args.output_dir,
            commit=bool(args.commit),
            initiated_by=args.initiated_by,
            protect_published=not args.allow_published_update,
        )
        print(json.dumps(asdict(summary), indent=2, ensure_ascii=False))

        if failures or summary.status in {"INPUT_VALIDATION_FAILED"}:
            return 1
        return 0
    except (SafeLoadError, sqlite3.Error, OSError, csv.Error) as exc:
        payload = {
            "loader_version": LOADER_VERSION,
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "completed_at": utc_now(),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
