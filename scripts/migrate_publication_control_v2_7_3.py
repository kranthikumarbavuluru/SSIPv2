#!/usr/bin/env python3
"""
SSIP v2.7.3 — Publication Control Database Migration

Purpose
-------
Adds a safe publication boundary to the existing SQLite staging database.

Safety properties
-----------------
* Non-destructive: existing scheme data is preserved.
* Idempotent: safe to run repeatedly.
* Dry-run support: all schema/data changes are rolled back.
* Automatic backup before an applied migration.
* Public visibility requires both:
      publication_status = 'PUBLISHED'
      is_public = 1
* Duplicate master_id values block the migration.
* Invalid publication-state combinations are rejected by database triggers.

Python: 3.10+
Database: SQLite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MIGRATION_VERSION = "2.7.3"
ALLOWED_PUBLICATION_STATUSES = (
    "STAGED",
    "READY_FOR_PUBLICATION",
    "PUBLISHED",
    "UNPUBLISHED",
    "ARCHIVED",
)
ALLOWED_ACTIONS = (
    "LOAD",
    "MARK_READY",
    "PUBLISH",
    "UNPUBLISH",
    "ARCHIVE",
    "RESTORE",
    "UPDATE",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MigrationError(RuntimeError):
    """Raised when the migration cannot proceed safely."""


@dataclass
class MigrationSummary:
    migration_version: str
    database: str
    mode: str
    backup_path: str | None
    scheme_count: int
    staged_count: int
    public_count: int
    duplicate_master_id_count: int
    missing_master_id_count: int
    columns_added: list[str]
    objects_created: list[str]
    verification_passed: bool
    completed_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quote_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(name):
        raise MigrationError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def connect_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def view_exists(connection: sqlite3.Connection, view_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'view' AND name = ?
        """,
        (view_name,),
    ).fetchone()
    return row is not None


def get_table_columns(
    connection: sqlite3.Connection, table_name: str
) -> dict[str, sqlite3.Row]:
    safe_name = quote_identifier(table_name)
    return {
        row["name"]: row
        for row in connection.execute(f"PRAGMA table_info({safe_name})").fetchall()
    }


def add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
    added_columns: list[str],
) -> None:
    columns = get_table_columns(connection, table_name)
    if column_name in columns:
        return

    safe_table = quote_identifier(table_name)
    safe_column = quote_identifier(column_name)
    connection.execute(
        f"ALTER TABLE {safe_table} ADD COLUMN {safe_column} {column_definition}"
    )
    added_columns.append(column_name)


def scalar(connection: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Any:
    row = connection.execute(sql, tuple(params)).fetchone()
    return None if row is None else row[0]


def duplicate_master_ids(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT master_id, COUNT(*) AS record_count
        FROM scheme_staging
        WHERE master_id IS NOT NULL AND TRIM(master_id) <> ''
        GROUP BY master_id
        HAVING COUNT(*) > 1
        ORDER BY record_count DESC, master_id
        """
    ).fetchall()


def missing_master_id_count(connection: sqlite3.Connection) -> int:
    return int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM scheme_staging
            WHERE master_id IS NULL OR TRIM(master_id) = ''
            """,
        )
        or 0
    )


def create_backup(database_path: Path, backup_dir: Path | None) -> Path:
    destination_dir = backup_dir or database_path.parent / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = destination_dir / f"{database_path.stem}_pre_v2_7_3_{timestamp}.db"

    # SQLite online backup API produces a consistent backup even when WAL is enabled.
    source = sqlite3.connect(str(database_path), timeout=30.0)
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    if not backup_path.exists() or backup_path.stat().st_size == 0:
        raise MigrationError("Database backup was not created successfully.")

    return backup_path


def script_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "UNAVAILABLE"


def create_schema_objects(
    connection: sqlite3.Connection, objects_created: list[str]
) -> None:
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_scheme_staging_master_id
        ON scheme_staging(master_id)
        """
    )
    objects_created.append("ux_scheme_staging_master_id")

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scheme_staging_public_visibility
        ON scheme_staging(publication_status, is_public)
        """
    )
    objects_created.append("ix_scheme_staging_public_visibility")

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_scheme_staging_source_publication
        ON scheme_staging(source, publication_status)
        """
    )
    objects_created.append("ix_scheme_staging_source_publication")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            applied_by TEXT NOT NULL,
            database_path TEXT NOT NULL,
            backup_path TEXT,
            script_sha256 TEXT NOT NULL
        )
        """
    )
    objects_created.append("schema_migrations")

    allowed_actions_sql = ", ".join(
        "'" + action.replace("'", "''") + "'" for action in ALLOWED_ACTIONS
    )
    allowed_statuses_sql = ", ".join(
        "'" + status.replace("'", "''") + "'"
        for status in ALLOWED_PUBLICATION_STATUSES
    )

    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS publication_audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id TEXT NOT NULL,
            action TEXT NOT NULL
                CHECK (action IN ({allowed_actions_sql})),
            previous_status TEXT,
            new_status TEXT NOT NULL
                CHECK (new_status IN ({allowed_statuses_sql})),
            previous_is_public INTEGER,
            new_is_public INTEGER NOT NULL CHECK (new_is_public IN (0, 1)),
            action_by TEXT NOT NULL,
            action_at TEXT NOT NULL,
            reason TEXT,
            source_run_id TEXT,
            record_version INTEGER,
            metadata_json TEXT,
            FOREIGN KEY (master_id)
                REFERENCES scheme_staging(master_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        )
        """
    )
    objects_created.append("publication_audit_log")

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_publication_audit_master_time
        ON publication_audit_log(master_id, action_at DESC)
        """
    )
    objects_created.append("ix_publication_audit_master_time")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS database_load_runs (
            run_id TEXT PRIMARY KEY,
            loader_version TEXT NOT NULL,
            input_file TEXT NOT NULL,
            input_sha256 TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('STARTED', 'COMPLETED', 'ROLLED_BACK', 'FAILED')),
            dry_run INTEGER NOT NULL CHECK (dry_run IN (0, 1)),
            total_records INTEGER NOT NULL DEFAULT 0,
            inserted_records INTEGER NOT NULL DEFAULT 0,
            updated_records INTEGER NOT NULL DEFAULT 0,
            skipped_records INTEGER NOT NULL DEFAULT 0,
            failed_records INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            initiated_by TEXT NOT NULL
        )
        """
    )
    objects_created.append("database_load_runs")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS safe_load_record_audit (
            record_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            master_id TEXT,
            action TEXT NOT NULL
                CHECK (action IN ('INSERT', 'UPDATE', 'SKIP', 'FAIL')),
            result TEXT NOT NULL
                CHECK (result IN ('ACCEPTED', 'SKIPPED', 'FAILED')),
            reason TEXT,
            before_json TEXT,
            after_json TEXT,
            processed_at TEXT NOT NULL,
            FOREIGN KEY (run_id)
                REFERENCES database_load_runs(run_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        )
        """
    )
    objects_created.append("safe_load_record_audit")

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_safe_load_record_audit_run
        ON safe_load_record_audit(run_id, result)
        """
    )
    objects_created.append("ix_safe_load_record_audit_run")


def create_publication_guards(
    connection: sqlite3.Connection, objects_created: list[str]
) -> None:
    allowed_status_sql = ", ".join(
        "'" + status.replace("'", "''") + "'"
        for status in ALLOWED_PUBLICATION_STATUSES
    )

    connection.execute("DROP TRIGGER IF EXISTS trg_scheme_staging_publication_guard_insert")
    connection.execute(
        f"""
        CREATE TRIGGER trg_scheme_staging_publication_guard_insert
        BEFORE INSERT ON scheme_staging
        BEGIN
            SELECT CASE
                WHEN NEW.publication_status IS NULL
                  OR NEW.publication_status NOT IN ({allowed_status_sql})
                THEN RAISE(ABORT, 'Invalid publication_status')
            END;

            SELECT CASE
                WHEN NEW.is_public IS NULL OR NEW.is_public NOT IN (0, 1)
                THEN RAISE(ABORT, 'is_public must be 0 or 1')
            END;

            SELECT CASE
                WHEN NEW.publication_status = 'PUBLISHED' AND NEW.is_public <> 1
                THEN RAISE(ABORT, 'PUBLISHED records must have is_public = 1')
                WHEN NEW.publication_status <> 'PUBLISHED' AND NEW.is_public <> 0
                THEN RAISE(ABORT, 'Only PUBLISHED records may have is_public = 1')
            END;

            SELECT CASE
                WHEN NEW.publication_status = 'PUBLISHED'
                 AND (
                    NEW.published_at IS NULL OR TRIM(NEW.published_at) = ''
                    OR NEW.published_by IS NULL OR TRIM(NEW.published_by) = ''
                 )
                THEN RAISE(ABORT, 'Published records require published_at and published_by')
            END;
        END
        """
    )
    objects_created.append("trg_scheme_staging_publication_guard_insert")

    connection.execute("DROP TRIGGER IF EXISTS trg_scheme_staging_publication_guard_update")
    connection.execute(
        f"""
        CREATE TRIGGER trg_scheme_staging_publication_guard_update
        BEFORE UPDATE OF publication_status, is_public, published_at, published_by
        ON scheme_staging
        BEGIN
            SELECT CASE
                WHEN NEW.publication_status IS NULL
                  OR NEW.publication_status NOT IN ({allowed_status_sql})
                THEN RAISE(ABORT, 'Invalid publication_status')
            END;

            SELECT CASE
                WHEN NEW.is_public IS NULL OR NEW.is_public NOT IN (0, 1)
                THEN RAISE(ABORT, 'is_public must be 0 or 1')
            END;

            SELECT CASE
                WHEN NEW.publication_status = 'PUBLISHED' AND NEW.is_public <> 1
                THEN RAISE(ABORT, 'PUBLISHED records must have is_public = 1')
                WHEN NEW.publication_status <> 'PUBLISHED' AND NEW.is_public <> 0
                THEN RAISE(ABORT, 'Only PUBLISHED records may have is_public = 1')
            END;

            SELECT CASE
                WHEN NEW.publication_status = 'PUBLISHED'
                 AND (
                    NEW.published_at IS NULL OR TRIM(NEW.published_at) = ''
                    OR NEW.published_by IS NULL OR TRIM(NEW.published_by) = ''
                 )
                THEN RAISE(ABORT, 'Published records require published_at and published_by')
            END;
        END
        """
    )
    objects_created.append("trg_scheme_staging_publication_guard_update")

    connection.execute("DROP VIEW IF EXISTS public_schemes")
    connection.execute(
        """
        CREATE VIEW public_schemes AS
        SELECT *
        FROM scheme_staging
        WHERE publication_status = 'PUBLISHED'
          AND is_public = 1
        """
    )
    objects_created.append("public_schemes")


def verify_migration(connection: sqlite3.Connection) -> dict[str, Any]:
    required_columns = {
        "publication_status",
        "is_public",
        "published_at",
        "published_by",
        "unpublished_at",
        "unpublished_by",
        "publication_notes",
        "source_run_id",
        "record_version",
        "created_at",
        "updated_at",
    }
    existing_columns = set(get_table_columns(connection, "scheme_staging"))
    missing_columns = sorted(required_columns - existing_columns)

    invalid_state_count = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM scheme_staging
            WHERE publication_status IS NULL
               OR publication_status NOT IN (
                    'STAGED',
                    'READY_FOR_PUBLICATION',
                    'PUBLISHED',
                    'UNPUBLISHED',
                    'ARCHIVED'
               )
               OR is_public NOT IN (0, 1)
               OR (publication_status = 'PUBLISHED' AND is_public <> 1)
               OR (publication_status <> 'PUBLISHED' AND is_public <> 0)
               OR (
                    publication_status = 'PUBLISHED'
                    AND (
                        published_at IS NULL OR TRIM(published_at) = ''
                        OR published_by IS NULL OR TRIM(published_by) = ''
                    )
               )
            """,
        )
        or 0
    )

    required_tables = {
        "schema_migrations",
        "publication_audit_log",
        "database_load_runs",
        "safe_load_record_audit",
    }
    missing_tables = sorted(
        name for name in required_tables if not table_exists(connection, name)
    )

    public_view_exists = view_exists(connection, "public_schemes")

    return {
        "missing_columns": missing_columns,
        "missing_tables": missing_tables,
        "public_view_exists": public_view_exists,
        "invalid_state_count": invalid_state_count,
        "passed": not missing_columns
        and not missing_tables
        and public_view_exists
        and invalid_state_count == 0,
    }


def perform_migration(
    connection: sqlite3.Connection,
    database_path: Path,
    backup_path: Path | None,
    applied_by: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    if not table_exists(connection, "scheme_staging"):
        raise MigrationError(
            "Required table 'scheme_staging' does not exist. "
            "Run the earlier SSIP database staging loader first."
        )

    columns = get_table_columns(connection, "scheme_staging")
    if "master_id" not in columns:
        raise MigrationError(
            "Table 'scheme_staging' does not contain the required master_id column."
        )

    added_columns: list[str] = []
    objects_created: list[str] = []

    add_column_if_missing(
        connection,
        "scheme_staging",
        "publication_status",
        "TEXT NOT NULL DEFAULT 'STAGED'",
        added_columns,
    )
    add_column_if_missing(
        connection,
        "scheme_staging",
        "is_public",
        "INTEGER NOT NULL DEFAULT 0",
        added_columns,
    )
    add_column_if_missing(
        connection, "scheme_staging", "published_at", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "published_by", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "unpublished_at", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "unpublished_by", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "publication_notes", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "source_run_id", "TEXT", added_columns
    )
    add_column_if_missing(
        connection,
        "scheme_staging",
        "record_version",
        "INTEGER NOT NULL DEFAULT 1",
        added_columns,
    )
    add_column_if_missing(
        connection, "scheme_staging", "created_at", "TEXT", added_columns
    )
    add_column_if_missing(
        connection, "scheme_staging", "updated_at", "TEXT", added_columns
    )

    now = utc_now()

    # Safe backfill: no existing row becomes publicly visible.
    connection.execute(
        """
        UPDATE scheme_staging
        SET publication_status = 'STAGED'
        WHERE publication_status IS NULL
           OR TRIM(publication_status) = ''
           OR publication_status NOT IN (
                'STAGED',
                'READY_FOR_PUBLICATION',
                'PUBLISHED',
                'UNPUBLISHED',
                'ARCHIVED'
           )
        """
    )
    connection.execute(
        """
        UPDATE scheme_staging
        SET is_public = CASE
            WHEN publication_status = 'PUBLISHED'
             AND published_at IS NOT NULL AND TRIM(published_at) <> ''
             AND published_by IS NOT NULL AND TRIM(published_by) <> ''
            THEN 1
            ELSE 0
        END
        """
    )
    connection.execute(
        """
        UPDATE scheme_staging
        SET publication_status = 'STAGED',
            is_public = 0
        WHERE publication_status = 'PUBLISHED'
          AND (
                published_at IS NULL OR TRIM(published_at) = ''
                OR published_by IS NULL OR TRIM(published_by) = ''
          )
        """
    )
    connection.execute(
        """
        UPDATE scheme_staging
        SET record_version = 1
        WHERE record_version IS NULL OR record_version < 1
        """
    )
    connection.execute(
        """
        UPDATE scheme_staging
        SET created_at = ?
        WHERE created_at IS NULL OR TRIM(created_at) = ''
        """,
        (now,),
    )
    connection.execute(
        """
        UPDATE scheme_staging
        SET updated_at = ?
        WHERE updated_at IS NULL OR TRIM(updated_at) = ''
        """,
        (now,),
    )

    missing_ids = missing_master_id_count(connection)
    if missing_ids:
        raise MigrationError(
            f"Migration stopped: {missing_ids} scheme_staging row(s) have no master_id."
        )

    duplicates = duplicate_master_ids(connection)
    if duplicates:
        sample = ", ".join(
            f"{row['master_id']} ({row['record_count']})" for row in duplicates[:10]
        )
        raise MigrationError(
            "Migration stopped because duplicate master_id values exist: " + sample
        )

    create_schema_objects(connection, objects_created)
    create_publication_guards(connection, objects_created)

    connection.execute(
        """
        INSERT INTO schema_migrations (
            migration_version,
            applied_at,
            applied_by,
            database_path,
            backup_path,
            script_sha256
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(migration_version) DO UPDATE SET
            applied_at = excluded.applied_at,
            applied_by = excluded.applied_by,
            database_path = excluded.database_path,
            backup_path = excluded.backup_path,
            script_sha256 = excluded.script_sha256
        """,
        (
            MIGRATION_VERSION,
            now,
            applied_by,
            str(database_path.resolve()),
            str(backup_path.resolve()) if backup_path else None,
            script_sha256(),
        ),
    )

    verification = verify_migration(connection)
    if not verification["passed"]:
        raise MigrationError(
            "Post-migration verification failed: "
            + json.dumps(verification, ensure_ascii=False)
        )

    return added_columns, objects_created, verification


def run_migration(
    database_path: Path,
    apply_changes: bool,
    backup_dir: Path | None,
    applied_by: str,
) -> MigrationSummary:
    if not database_path.exists():
        raise MigrationError(f"Database not found: {database_path}")
    if not database_path.is_file():
        raise MigrationError(f"Database path is not a file: {database_path}")

    backup_path: Path | None = None
    if apply_changes:
        backup_path = create_backup(database_path, backup_dir)

    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        added_columns, objects_created, verification = perform_migration(
            connection=connection,
            database_path=database_path,
            backup_path=backup_path,
            applied_by=applied_by,
        )

        scheme_count = int(
            scalar(connection, "SELECT COUNT(*) FROM scheme_staging") or 0
        )
        staged_count = int(
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM scheme_staging
                WHERE publication_status = 'STAGED' AND is_public = 0
                """,
            )
            or 0
        )
        public_count = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )
        duplicate_count = len(duplicate_master_ids(connection))
        missing_count = missing_master_id_count(connection)

        summary = MigrationSummary(
            migration_version=MIGRATION_VERSION,
            database=str(database_path.resolve()),
            mode="APPLY" if apply_changes else "DRY_RUN",
            backup_path=str(backup_path.resolve()) if backup_path else None,
            scheme_count=scheme_count,
            staged_count=staged_count,
            public_count=public_count,
            duplicate_master_id_count=duplicate_count,
            missing_master_id_count=missing_count,
            columns_added=added_columns,
            objects_created=objects_created,
            verification_passed=bool(verification["passed"]),
            completed_at=utc_now(),
        )

        if apply_changes:
            connection.commit()
        else:
            connection.rollback()

        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def self_test() -> dict[str, Any]:
    results: dict[str, Any] = {
        "migration_version": MIGRATION_VERSION,
        "tests": {},
        "passed": False,
    }

    with tempfile.TemporaryDirectory(prefix="ssip_v273_") as temp_dir:
        db_path = Path(temp_dir) / "test_ssip.db"
        connection = sqlite3.connect(str(db_path))
        try:
            connection.execute(
                """
                CREATE TABLE scheme_staging (
                    master_id TEXT,
                    source TEXT,
                    canonical_name TEXT,
                    programme_status TEXT,
                    final_url TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO scheme_staging (
                    master_id, source, canonical_name, programme_status, final_url
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        "TEST001",
                        "DST",
                        "Test Scheme One",
                        "SCHEME_INFORMATION_AVAILABLE",
                        "https://example.gov/scheme-one",
                    ),
                    (
                        "TEST002",
                        "BIRAC",
                        "Test Scheme Two",
                        "CALL_INFORMATION_CURRENT",
                        "https://example.gov/scheme-two",
                    ),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        dry_run_summary = run_migration(
            database_path=db_path,
            apply_changes=False,
            backup_dir=None,
            applied_by="SELF_TEST",
        )
        results["tests"]["dry_run_verified"] = dry_run_summary.verification_passed

        check = sqlite3.connect(str(db_path))
        try:
            columns_after_dry_run = {
                row[1] for row in check.execute("PRAGMA table_info(scheme_staging)")
            }
        finally:
            check.close()
        results["tests"]["dry_run_rolled_back"] = (
            "publication_status" not in columns_after_dry_run
        )

        apply_summary = run_migration(
            database_path=db_path,
            apply_changes=True,
            backup_dir=Path(temp_dir) / "backups",
            applied_by="SELF_TEST",
        )
        results["tests"]["apply_verified"] = apply_summary.verification_passed
        results["tests"]["backup_created"] = bool(
            apply_summary.backup_path
            and Path(apply_summary.backup_path).exists()
        )

        check = connect_database(db_path)
        try:
            staged = int(
                scalar(
                    check,
                    """
                    SELECT COUNT(*)
                    FROM scheme_staging
                    WHERE publication_status = 'STAGED' AND is_public = 0
                    """,
                )
                or 0
            )
            public = int(scalar(check, "SELECT COUNT(*) FROM public_schemes") or 0)
            results["tests"]["existing_rows_are_staged"] = staged == 2
            results["tests"]["public_view_is_empty"] = public == 0

            invalid_state_blocked = False
            try:
                check.execute(
                    """
                    UPDATE scheme_staging
                    SET is_public = 1
                    WHERE master_id = 'TEST001'
                    """
                )
            except sqlite3.IntegrityError:
                invalid_state_blocked = True
            finally:
                check.rollback()
            results["tests"]["invalid_public_state_blocked"] = invalid_state_blocked

            duplicate_blocked = False
            try:
                check.execute(
                    """
                    INSERT INTO scheme_staging (
                        master_id,
                        source,
                        canonical_name,
                        programme_status,
                        final_url,
                        publication_status,
                        is_public,
                        record_version,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        'TEST001',
                        'DST',
                        'Duplicate',
                        'SCHEME_INFORMATION_AVAILABLE',
                        'https://example.gov/duplicate',
                        'STAGED',
                        0,
                        1,
                        ?,
                        ?
                    )
                    """,
                    (utc_now(), utc_now()),
                )
            except sqlite3.IntegrityError:
                duplicate_blocked = True
            finally:
                check.rollback()
            results["tests"]["duplicate_master_id_blocked"] = duplicate_blocked

            now = utc_now()
            check.execute(
                """
                UPDATE scheme_staging
                SET publication_status = 'PUBLISHED',
                    is_public = 1,
                    published_at = ?,
                    published_by = ?,
                    updated_at = ?,
                    record_version = record_version + 1
                WHERE master_id = 'TEST001'
                """,
                (now, "SELF_TEST", now),
            )
            check.commit()

            public_after_publish = int(
                scalar(check, "SELECT COUNT(*) FROM public_schemes") or 0
            )
            results["tests"]["explicit_publish_visible"] = public_after_publish == 1
        finally:
            check.close()

    results["passed"] = all(bool(value) for value in results["tests"].values())
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SSIP v2.7.3 safe publication-control database migration."
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Path to the SSIP SQLite database.",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute and verify the migration, then roll back all changes.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Back up the database and commit the migration.",
    )

    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="Optional backup directory. Default: <database folder>/backups",
    )
    parser.add_argument(
        "--applied-by",
        default=os.environ.get("USERNAME")
        or os.environ.get("USER")
        or "SSIP_ADMIN",
        help="Administrator identity recorded in schema_migrations.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="Optional JSON output path for the migration summary.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run isolated migration safety tests.",
    )
    return parser.parse_args()


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()

    try:
        if args.self_test:
            payload = self_test()
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if args.summary_output:
                write_summary(args.summary_output, payload)
            return 0 if payload["passed"] else 1

        if args.database is None:
            raise MigrationError("--database is required unless --self-test is used.")

        if not args.dry_run and not args.apply:
            raise MigrationError(
                "Choose one mode explicitly: --dry-run or --apply. "
                "No database changes were made."
            )

        summary = run_migration(
            database_path=args.database,
            apply_changes=bool(args.apply),
            backup_dir=args.backup_dir,
            applied_by=args.applied_by,
        )
        payload = asdict(summary)
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        if args.summary_output:
            write_summary(args.summary_output, payload)

        return 0
    except (MigrationError, sqlite3.Error, OSError) as exc:
        error_payload = {
            "migration_version": MIGRATION_VERSION,
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "completed_at": utc_now(),
        }
        print(json.dumps(error_payload, indent=2, ensure_ascii=False), file=sys.stderr)
        if args.summary_output:
            write_summary(args.summary_output, error_payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
