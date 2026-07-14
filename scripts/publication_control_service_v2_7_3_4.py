#!/usr/bin/env python3
"""
SSIP v2.7.3.4 â€” Publication Control Service

Provides explicit, audited state transitions for scheme publication.

Allowed workflow
----------------
STAGED -> READY_FOR_PUBLICATION -> PUBLISHED -> UNPUBLISHED
ARCHIVED may be entered only from a non-public state.
UNPUBLISHED -> READY_FOR_PUBLICATION through restore.
ARCHIVED -> STAGED through restore.

Safety guarantees
-----------------
* Write actions require explicit --dry-run or --commit.
* Publishing is allowed only from READY_FOR_PUBLICATION.
* Pre-publication quality gates are enforced.
* Public visibility requires PUBLISHED + is_public=1.
* Every committed state transition creates publication_audit_log.
* Every write is transactional and verifies expected public-count movement.
* Existing SQLite foreign keys and publication guard triggers stay enabled.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sqlite3
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

SERVICE_VERSION = "2.7.3.4"
ALLOWED_STATUSES = {
    "STAGED",
    "READY_FOR_PUBLICATION",
    "PUBLISHED",
    "UNPUBLISHED",
    "ARCHIVED",
}

WRITE_ACTIONS = {
    "mark-ready",
    "publish",
    "unpublish",
    "withdraw-publication",
    "archive",
    "restore",
}


class PublicationError(RuntimeError):
    pass


@dataclass
class GateResult:
    passed: bool
    blockers: list[str]
    warnings: list[str]


@dataclass
class ActionResult:
    service_version: str
    action_id: str
    action: str
    mode: str
    status: str
    database: str
    master_id: str
    scheme_name: str
    previous_publication_status: str
    new_publication_status: str
    previous_is_public: int
    new_is_public: int
    previous_record_version: int
    new_record_version: int
    public_count_before: int
    public_count_after: int
    action_by: str
    action_at: str
    reason: str
    quality_gate: dict[str, Any] | None
    error_message: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
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


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def verify_database(connection: sqlite3.Connection) -> None:
    required_tables = {"scheme_staging", "publication_audit_log"}
    missing_tables = sorted(
        table
        for table in required_tables
        if not object_exists(connection, "table", table)
    )
    if missing_tables:
        raise PublicationError(
            "Missing required table(s): " + ", ".join(missing_tables)
        )

    if not object_exists(connection, "view", "public_schemes"):
        raise PublicationError("Missing required public_schemes view.")

    required_columns = {
        "master_id",
        "scheme_name",
        "source",
        "programme_status",
        "official_page_url",
        "application_url",
        "validation_decision",
        "publication_status",
        "is_public",
        "published_at",
        "published_by",
        "unpublished_at",
        "unpublished_by",
        "publication_notes",
        "source_run_id",
        "record_version",
        "record_hash",
        "raw_record_json",
        "updated_at",
    }
    missing_columns = sorted(required_columns - table_columns(connection, "scheme_staging"))
    if missing_columns:
        raise PublicationError(
            "scheme_staging is missing required columns: "
            + ", ".join(missing_columns)
        )

    audit_required = {
        "master_id",
        "action",
        "previous_status",
        "new_status",
        "previous_is_public",
        "new_is_public",
        "action_by",
        "action_at",
        "reason",
        "source_run_id",
        "record_version",
        "metadata_json",
    }
    missing_audit = sorted(
        audit_required - table_columns(connection, "publication_audit_log")
    )
    if missing_audit:
        raise PublicationError(
            "publication_audit_log is missing columns: " + ", ".join(missing_audit)
        )

    quick_check = scalar(connection, "PRAGMA quick_check")
    if quick_check != "ok":
        raise PublicationError(f"SQLite quick_check failed: {quick_check}")


def read_scheme(connection: sqlite3.Connection, master_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM scheme_staging WHERE master_id=?",
        (master_id,),
    ).fetchone()
    if row is None:
        raise PublicationError(f"Scheme not found: {master_id}")
    return row


def valid_http_url(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text or any(char.isspace() for char in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)



def call_specific_quality_gate(row: sqlite3.Row) -> GateResult:
    blockers: list[str] = []
    warnings: list[str] = []

    keys = set(row.keys())
    record_kind = str(
        row["record_kind"] if "record_kind" in keys else ""
    ).strip().upper()
    if record_kind not in {"APPLICATION_CALL", "CHALLENGE"}:
        return GateResult(True, [], [])

    title = str(row["scheme_name"] or "").strip()
    title_key = " ".join(
        re.sub(r"[^a-z0-9]+", " ", title.casefold()).split()
    )
    official_url = str(row["official_page_url"] or "").strip()
    application_status = str(
        row["application_status"]
        if "application_status" in keys
        else ""
    ).strip().upper()

    try:
        payload = json.loads(str(row["raw_record_json"] or "{}"))
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    if application_status in {
        "",
        "VERIFICATION_REQUIRED",
        "STATUS_UNVERIFIED",
        "OPEN_STATUS_REQUIRES_DEADLINE_VERIFICATION",
    }:
        blockers.append(
            "application call status is not sufficiently verified for publication"
        )

    generic_titles = {
        "challenges",
        "event partner",
        "organisationprofile",
        "organisation profile",
        "press release all",
        "g20diaoverview",
        "g20 dia overview",
    }
    if (
        title_key in generic_titles
        or ".pdf" in title.casefold()
        or "%20" in title.casefold()
    ):
        blockers.append(
            "application call identity is generic, encoded or filename-derived"
        )

    path = urlparse(official_url).path.casefold().rstrip("/")
    if path in {
        "/challenges",
        "/event-partner",
        "/organisationprofile",
        "/press-release-all",
    }:
        blockers.append(
            "official_page_url is a directory or listing page, not an individual call"
        )

    parent_resolution = str(
        payload.get("parent_resolution") or ""
    ).strip().upper()
    parent_id = str(payload.get("parent_master_id") or "").strip()
    if (
        parent_resolution in {"", "UNRESOLVED", "UMBRELLA_ONLY_REVIEW"}
        and not parent_id
    ):
        blockers.append(
            "call parent relationship is unresolved and not approved as standalone"
        )

    applicant_layer = str(
        payload.get("applicant_layer") or ""
    ).strip().upper()
    if applicant_layer in {
        "",
        "REQUIRES_ADMIN_VERIFICATION",
        "UNKNOWN",
    }:
        blockers.append(
            "call applicant layer is not verified"
        )

    status_basis = str(payload.get("status_basis") or "").strip()
    status_evidence = str(
        payload.get("status_evidence") or ""
    ).strip()
    if not status_basis or not status_evidence:
        blockers.append(
            "call status basis and evidence are required"
        )

    closing_date = str(
        payload.get("closing_date")
        or (row["closing_date"] if "closing_date" in keys else "")
    ).strip()

    if application_status == "OPEN":
        if not valid_http_url(row["application_url"]):
            blockers.append(
                "open call requires a verified application_url"
            )
        if not closing_date:
            blockers.append(
                "open call requires a verified closing date"
            )
    elif application_status == "UPCOMING":
        opening_date = str(
            payload.get("opening_date")
            or (row["opening_date"] if "opening_date" in keys else "")
        ).strip()
        if not opening_date or not closing_date:
            blockers.append(
                "upcoming call requires verified opening and closing dates"
            )
    elif application_status == "CLOSED":
        if not closing_date and not status_evidence:
            blockers.append(
                "closed call requires historical deadline or closure evidence"
            )
    elif application_status not in {
        "OPEN",
        "UPCOMING",
        "CLOSED",
    }:
        blockers.append(
            "application call has an unsupported publication status"
        )

    return GateResult(
        passed=not blockers,
        blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
    )


def quality_gate(row: sqlite3.Row) -> GateResult:
    blockers: list[str] = []
    warnings: list[str] = []

    required_text = {
        "master_id": row["master_id"],
        "scheme_name": row["scheme_name"],
        "source": row["source"],
        "programme_status": row["programme_status"],
        "validation_decision": row["validation_decision"],
        "record_hash": row["record_hash"],
        "raw_record_json": row["raw_record_json"],
    }
    for field, value in required_text.items():
        if value is None or not str(value).strip():
            blockers.append(f"{field} is missing")

    if str(row["validation_decision"] or "").strip().upper() != "APPROVED_FOR_DATABASE":
        blockers.append("validation_decision is not APPROVED_FOR_DATABASE")

    if not valid_http_url(row["official_page_url"]):
        blockers.append("official_page_url is missing or invalid")

    application_url = row["application_url"]
    if application_url is None or not str(application_url).strip():
        warnings.append("application_url is unavailable")
    elif not valid_http_url(application_url):
        blockers.append("application_url is present but invalid")


    call_gate = call_specific_quality_gate(row)
    blockers.extend(call_gate.blockers)
    warnings.extend(call_gate.warnings)

    if str(row["publication_status"] or "") != "READY_FOR_PUBLICATION":
        blockers.append("publication_status is not READY_FOR_PUBLICATION")

    if int(row["is_public"] or 0) != 0:
        blockers.append("record is already public before publication")

    validation_score = row["validation_score"] if "validation_score" in row.keys() else None
    if validation_score is None:
        warnings.append("validation_score is unavailable")

    return GateResult(
        passed=not blockers,
        blockers=blockers,
        warnings=warnings,
    )


def validate_current_state(row: sqlite3.Row) -> None:
    status = str(row["publication_status"] or "")
    is_public = int(row["is_public"] or 0)

    if status not in ALLOWED_STATUSES:
        raise PublicationError(f"Invalid publication_status in database: {status!r}")
    if status == "PUBLISHED" and is_public != 1:
        raise PublicationError("Invalid state: PUBLISHED record is not public.")
    if status != "PUBLISHED" and is_public != 0:
        raise PublicationError(
            "Invalid state: non-PUBLISHED record has is_public=1."
        )


def transition_for(action: str, current_status: str) -> tuple[str, int]:
    transitions: dict[str, dict[str, tuple[str, int]]] = {
        "mark-ready": {
            "STAGED": ("READY_FOR_PUBLICATION", 0),
        },
        "publish": {
            "READY_FOR_PUBLICATION": ("PUBLISHED", 1),
        },
        "unpublish": {
            "PUBLISHED": ("UNPUBLISHED", 0),
        },
        "withdraw-publication": {
            "PUBLISHED": ("UNPUBLISHED", 0),
        },
        "archive": {
            "STAGED": ("ARCHIVED", 0),
            "READY_FOR_PUBLICATION": ("ARCHIVED", 0),
            "UNPUBLISHED": ("ARCHIVED", 0),
        },
        "restore": {
            "UNPUBLISHED": ("READY_FOR_PUBLICATION", 0),
            "ARCHIVED": ("STAGED", 0),
        },
    }

    action_transitions = transitions.get(action)
    if not action_transitions or current_status not in action_transitions:
        allowed_from = ", ".join(sorted(action_transitions or {})) or "none"
        raise PublicationError(
            f"Action {action!r} is not allowed from {current_status!r}. "
            f"Allowed source status(es): {allowed_from}."
        )
    return action_transitions[current_status]


def expected_public_delta(action: str) -> int:
    if action == "publish":
        return 1
    if action in {"unpublish", "withdraw-publication"}:
        return -1
    return 0


def build_update_values(
    action: str,
    new_status: str,
    new_is_public: int,
    actor: str,
    reason: str,
    now: str,
    current_version: int,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "publication_status": new_status,
        "is_public": new_is_public,
        "publication_notes": reason,
        "record_version": current_version + 1,
        "updated_at": now,
    }

    if action == "publish":
        values.update(
            {
                "published_at": now,
                "published_by": actor,
                "unpublished_at": None,
                "unpublished_by": None,
            }
        )
    elif action in {"unpublish", "withdraw-publication"}:
        values.update(
            {
                "unpublished_at": now,
                "unpublished_by": actor,
            }
        )
    elif action in {"mark-ready", "archive", "restore"}:
        # Publication history is retained. Visibility is controlled solely by
        # publication_status + is_public.
        pass

    return values


def write_audit(
    connection: sqlite3.Connection,
    *,
    master_id: str,
    action: str,
    previous_status: str,
    new_status: str,
    previous_is_public: int,
    new_is_public: int,
    actor: str,
    now: str,
    reason: str,
    source_run_id: Any,
    record_version: int,
    metadata: dict[str, Any],
) -> None:
    audit_action_map = {
        "mark-ready": "MARK_READY",
        "publish": "PUBLISH",
        "unpublish": "UNPUBLISH",
        "withdraw-publication": "UNPUBLISH",
        "archive": "ARCHIVE",
        "restore": "RESTORE",
    }
    connection.execute(
        """
        INSERT INTO publication_audit_log (
            master_id,
            action,
            previous_status,
            new_status,
            previous_is_public,
            new_is_public,
            action_by,
            action_at,
            reason,
            source_run_id,
            record_version,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            master_id,
            audit_action_map[action],
            previous_status,
            new_status,
            previous_is_public,
            new_is_public,
            actor,
            now,
            reason,
            source_run_id,
            record_version,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
        ),
    )


def run_action(
    *,
    database: Path,
    master_id: str,
    action: str,
    actor: str,
    reason: str,
    commit: bool,
    expected_status: str | None = None,
) -> ActionResult:
    if not database.exists() or not database.is_file():
        raise PublicationError(f"Database not found: {database}")
    if not actor.strip():
        raise PublicationError("--action-by cannot be blank.")
    if not reason.strip():
        raise PublicationError("--reason cannot be blank.")

    action_id = uuid.uuid4().hex
    mode = "COMMIT" if commit else "DRY_RUN"
    now = utc_now()
    connection = connect_database(database)

    try:
        verify_database(connection)
        connection.execute("BEGIN IMMEDIATE")

        row = read_scheme(connection, master_id)
        validate_current_state(row)

        previous_status = str(row["publication_status"])
        previous_is_public = int(row["is_public"])
        previous_version = int(row["record_version"] or 1)

        if expected_status and previous_status != expected_status:
            raise PublicationError(
                f"Optimistic-lock failure: expected status {expected_status!r}, "
                f"found {previous_status!r}."
            )

        new_status, new_is_public = transition_for(action, previous_status)

        gate: GateResult | None = None
        if action == "publish":
            gate = quality_gate(row)
            if not gate.passed:
                raise PublicationError(
                    "Pre-publication quality gate failed: "
                    + "; ".join(gate.blockers)
                )

        public_before = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )

        update_values = build_update_values(
            action=action,
            new_status=new_status,
            new_is_public=new_is_public,
            actor=actor,
            reason=reason,
            now=now,
            current_version=previous_version,
        )
        assignments = ", ".join(f'"{name}"=?' for name in update_values)
        connection.execute(
            f"UPDATE scheme_staging SET {assignments} WHERE master_id=?",
            (*update_values.values(), master_id),
        )

        updated = read_scheme(connection, master_id)
        validate_current_state(updated)

        public_after = int(
            scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
        )
        expected_after = public_before + expected_public_delta(action)
        if public_after != expected_after:
            raise PublicationError(
                "Public-count verification failed: expected "
                f"{expected_after}, found {public_after}."
            )

        metadata = {
            "service_version": SERVICE_VERSION,
            "action_id": action_id,
            "mode": mode,
            "quality_gate": asdict(gate) if gate else None,
            "before": {
                "publication_status": previous_status,
                "is_public": previous_is_public,
                "record_version": previous_version,
            },
            "after": {
                "publication_status": new_status,
                "is_public": new_is_public,
                "record_version": previous_version + 1,
            },
        }
        write_audit(
            connection,
            master_id=master_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            previous_is_public=previous_is_public,
            new_is_public=new_is_public,
            actor=actor,
            now=now,
            reason=reason,
            source_run_id=updated["source_run_id"],
            record_version=previous_version + 1,
            metadata=metadata,
        )

        result = ActionResult(
            service_version=SERVICE_VERSION,
            action_id=action_id,
            action=action,
            mode=mode,
            status="COMPLETED" if commit else "DRY_RUN_ROLLED_BACK",
            database=str(database.resolve()),
            master_id=master_id,
            scheme_name=str(updated["scheme_name"]),
            previous_publication_status=previous_status,
            new_publication_status=new_status,
            previous_is_public=previous_is_public,
            new_is_public=new_is_public,
            previous_record_version=previous_version,
            new_record_version=previous_version + 1,
            public_count_before=public_before,
            public_count_after=public_after,
            action_by=actor,
            action_at=now,
            reason=reason,
            quality_gate=asdict(gate) if gate else None,
        )

        if commit:
            connection.commit()
        else:
            connection.rollback()

        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def status_report(database: Path, master_id: str | None = None) -> dict[str, Any]:
    if not database.exists() or not database.is_file():
        raise PublicationError(f"Database not found: {database}")
    connection = connect_database(database)
    try:
        verify_database(connection)
        counts = [
            {
                "publication_status": row["publication_status"],
                "is_public": int(row["is_public"]),
                "record_count": int(row["record_count"]),
            }
            for row in connection.execute(
                """
                SELECT publication_status, is_public, COUNT(*) AS record_count
                FROM scheme_staging
                GROUP BY publication_status, is_public
                ORDER BY publication_status, is_public
                """
            ).fetchall()
        ]
        payload: dict[str, Any] = {
            "service_version": SERVICE_VERSION,
            "database": str(database.resolve()),
            "publication_counts": counts,
            "public_schemes_count": int(
                scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0
            ),
            "publication_audit_count": int(
                scalar(connection, "SELECT COUNT(*) FROM publication_audit_log")
                or 0
            ),
        }
        if master_id:
            row = read_scheme(connection, master_id)
            payload["scheme"] = {
                "master_id": row["master_id"],
                "scheme_name": row["scheme_name"],
                "source": row["source"],
                "programme_status": row["programme_status"],
                "official_page_url": row["official_page_url"],
                "application_url": row["application_url"],
                "validation_decision": row["validation_decision"],
                "validation_score": row["validation_score"]
                if "validation_score" in row.keys()
                else None,
                "publication_status": row["publication_status"],
                "is_public": int(row["is_public"]),
                "record_version": int(row["record_version"] or 1),
                "published_at": row["published_at"],
                "published_by": row["published_by"],
                "unpublished_at": row["unpublished_at"],
                "unpublished_by": row["unpublished_by"],
                "quality_gate_preview": asdict(quality_gate(row)),
            }
        return payload
    finally:
        connection.close()


def list_schemes(
    database: Path,
    publication_status: str | None,
    limit: int,
) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise PublicationError("--limit must be between 1 and 1000.")
    if publication_status and publication_status not in ALLOWED_STATUSES:
        raise PublicationError(
            "Invalid --publication-status. Allowed: "
            + ", ".join(sorted(ALLOWED_STATUSES))
        )

    connection = connect_database(database)
    try:
        verify_database(connection)
        params: list[Any] = []
        where = ""
        if publication_status:
            where = "WHERE publication_status=?"
            params.append(publication_status)
        params.append(limit)
        rows = connection.execute(
            f"""
            SELECT
                master_id,
                scheme_name,
                source,
                programme_status,
                validation_decision,
                publication_status,
                is_public,
                record_version,
                official_page_url,
                application_url
            FROM scheme_staging
            {where}
            ORDER BY source, scheme_name
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return {
            "service_version": SERVICE_VERSION,
            "database": str(database.resolve()),
            "filter_publication_status": publication_status,
            "record_count": len(rows),
            "records": [dict(row) for row in rows],
        }
    finally:
        connection.close()


def create_test_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;

            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                source TEXT,
                programme_status TEXT,
                official_page_url TEXT,
                application_url TEXT,
                validation_score REAL,
                validation_decision TEXT NOT NULL,
                publication_status TEXT NOT NULL DEFAULT 'STAGED',
                is_public INTEGER NOT NULL DEFAULT 0,
                published_at TEXT,
                published_by TEXT,
                unpublished_at TEXT,
                unpublished_by TEXT,
                publication_notes TEXT,
                source_run_id TEXT,
                record_version INTEGER NOT NULL DEFAULT 1,
                record_hash TEXT NOT NULL,
                raw_record_json TEXT NOT NULL,
                updated_at TEXT
            );

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
                metadata_json TEXT,
                FOREIGN KEY(master_id) REFERENCES scheme_staging(master_id)
            );

            CREATE VIEW public_schemes AS
            SELECT * FROM scheme_staging
            WHERE publication_status='PUBLISHED' AND is_public=1;

            CREATE TRIGGER publication_guard_insert
            BEFORE INSERT ON scheme_staging
            BEGIN
                SELECT CASE
                    WHEN NEW.publication_status='PUBLISHED' AND NEW.is_public<>1
                    THEN RAISE(ABORT, 'published must be public')
                    WHEN NEW.publication_status<>'PUBLISHED' AND NEW.is_public<>0
                    THEN RAISE(ABORT, 'nonpublished must be private')
                END;
            END;

            CREATE TRIGGER publication_guard_update
            BEFORE UPDATE OF publication_status,is_public,published_at,published_by
            ON scheme_staging
            BEGIN
                SELECT CASE
                    WHEN NEW.publication_status='PUBLISHED' AND NEW.is_public<>1
                    THEN RAISE(ABORT, 'published must be public')
                    WHEN NEW.publication_status<>'PUBLISHED' AND NEW.is_public<>0
                    THEN RAISE(ABORT, 'nonpublished must be private')
                    WHEN NEW.publication_status='PUBLISHED'
                     AND (
                        NEW.published_at IS NULL OR TRIM(NEW.published_at)=''
                        OR NEW.published_by IS NULL OR TRIM(NEW.published_by)=''
                     )
                    THEN RAISE(ABORT, 'publication metadata required')
                END;
            END;
            """
        )
        connection.executemany(
            """
            INSERT INTO scheme_staging (
                master_id, scheme_name, source, programme_status,
                official_page_url, application_url, validation_score,
                validation_decision, publication_status, is_public,
                record_version, record_hash, raw_record_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'STAGED', 0, 1, ?, ?, ?)
            """,
            [
                (
                    "TEST0001",
                    "Ready Test Scheme",
                    "DST",
                    "SCHEME_INFORMATION_AVAILABLE",
                    "https://example.gov/scheme",
                    "https://example.gov/apply",
                    1.0,
                    "APPROVED_FOR_DATABASE",
                    "hash1",
                    "{}",
                    utc_now(),
                ),
                (
                    "TEST0002",
                    "Blocked Test Scheme",
                    "DST",
                    "SCHEME_INFORMATION_AVAILABLE",
                    None,
                    None,
                    1.0,
                    "APPROVED_FOR_DATABASE",
                    "hash2",
                    "{}",
                    utc_now(),
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def self_test() -> dict[str, Any]:
    result: dict[str, Any] = {
        "service_version": SERVICE_VERSION,
        "tests": {},
        "passed": False,
    }

    with tempfile.TemporaryDirectory(prefix="ssip_publication_") as temp_name:
        database = Path(temp_name) / "publication.db"
        create_test_database(database)

        dry_ready = run_action(
            database=database,
            master_id="TEST0001",
            action="mark-ready",
            actor="SELF_TEST",
            reason="Dry readiness test",
            commit=False,
        )
        result["tests"]["dry_run_rolls_back"] = (
            dry_ready.status == "DRY_RUN_ROLLED_BACK"
            and dry_ready.new_publication_status == "READY_FOR_PUBLICATION"
        )

        connection = connect_database(database)
        try:
            result["tests"]["dry_run_no_change"] = (
                scalar(
                    connection,
                    "SELECT publication_status FROM scheme_staging WHERE master_id='TEST0001'",
                )
                == "STAGED"
                and int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM publication_audit_log",
                    )
                    or 0
                )
                == 0
            )
        finally:
            connection.close()

        ready = run_action(
            database=database,
            master_id="TEST0001",
            action="mark-ready",
            actor="SELF_TEST",
            reason="Passed admin readiness review",
            commit=True,
        )
        result["tests"]["mark_ready_committed"] = (
            ready.new_publication_status == "READY_FOR_PUBLICATION"
            and ready.new_is_public == 0
        )

        publish_dry = run_action(
            database=database,
            master_id="TEST0001",
            action="publish",
            actor="SELF_TEST",
            reason="Dry publication test",
            commit=False,
            expected_status="READY_FOR_PUBLICATION",
        )
        result["tests"]["publish_gate_passed"] = (
            publish_dry.quality_gate is not None
            and publish_dry.quality_gate["passed"]
            and publish_dry.public_count_after == 1
        )

        published = run_action(
            database=database,
            master_id="TEST0001",
            action="publish",
            actor="SELF_TEST",
            reason="Approved for public portal",
            commit=True,
            expected_status="READY_FOR_PUBLICATION",
        )
        result["tests"]["published_visible"] = (
            published.new_publication_status == "PUBLISHED"
            and published.new_is_public == 1
            and published.public_count_after == 1
        )

        unpublish = run_action(
            database=database,
            master_id="TEST0001",
            action="unpublish",
            actor="SELF_TEST",
            reason="Temporary withdrawal",
            commit=True,
            expected_status="PUBLISHED",
        )
        result["tests"]["unpublish_removes_visibility"] = (
            unpublish.new_publication_status == "UNPUBLISHED"
            and unpublish.new_is_public == 0
            and unpublish.public_count_after == 0
        )

        restored = run_action(
            database=database,
            master_id="TEST0001",
            action="restore",
            actor="SELF_TEST",
            reason="Return to publication review",
            commit=True,
            expected_status="UNPUBLISHED",
        )
        result["tests"]["restore_to_ready"] = (
            restored.new_publication_status == "READY_FOR_PUBLICATION"
        )

        blocked = False
        try:
            run_action(
                database=database,
                master_id="TEST0002",
                action="mark-ready",
                actor="SELF_TEST",
                reason="Admin review",
                commit=True,
            )
            run_action(
                database=database,
                master_id="TEST0002",
                action="publish",
                actor="SELF_TEST",
                reason="Should be blocked",
                commit=True,
            )
        except PublicationError as exc:
            blocked = "quality gate failed" in str(exc).lower()
        result["tests"]["invalid_official_url_blocks_publish"] = blocked

        connection = connect_database(database)
        try:
            result["tests"]["audit_log_complete"] = (
                int(
                    scalar(
                        connection,
                        "SELECT COUNT(*) FROM publication_audit_log",
                    )
                    or 0
                )
                == 5
            )
        finally:
            connection.close()

    result["passed"] = all(bool(value) for value in result["tests"].values())
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SSIP v2.7.3.4 publication control service."
    )
    parser.add_argument(
        "command",
        choices=sorted(WRITE_ACTIONS | {"status", "list"}),
        nargs="?",
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--master-id")
    parser.add_argument(
        "--action-by",
        default=os.environ.get("USERNAME")
        or os.environ.get("USER")
        or "SSIP_ADMIN",
    )
    parser.add_argument("--reason")
    parser.add_argument("--expected-status")
    parser.add_argument("--publication-status")
    parser.add_argument("--limit", type=int, default=100)

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--commit", action="store_true")

    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def output_payload(payload: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    print(text)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    try:
        if args.self_test:
            payload = self_test()
            output_payload(payload, args.output)
            return 0 if payload["passed"] else 1

        if args.command is None:
            raise PublicationError("A command is required unless --self-test is used.")
        if args.database is None:
            raise PublicationError("--database is required.")

        if args.command == "status":
            payload = status_report(args.database, args.master_id)
            output_payload(payload, args.output)
            return 0

        if args.command == "list":
            payload = list_schemes(
                args.database,
                args.publication_status,
                args.limit,
            )
            output_payload(payload, args.output)
            return 0

        if args.master_id is None:
            raise PublicationError("--master-id is required for write actions.")
        if args.reason is None:
            raise PublicationError("--reason is required for write actions.")
        if not args.dry_run and not args.commit:
            raise PublicationError(
                "Choose --dry-run or --commit explicitly for write actions."
            )
        if args.expected_status and args.expected_status not in ALLOWED_STATUSES:
            raise PublicationError(
                "Invalid --expected-status. Allowed: "
                + ", ".join(sorted(ALLOWED_STATUSES))
            )

        result = run_action(
            database=args.database,
            master_id=args.master_id,
            action=args.command,
            actor=args.action_by,
            reason=args.reason,
            commit=bool(args.commit),
            expected_status=args.expected_status,
        )
        output_payload(asdict(result), args.output)
        return 0
    except (PublicationError, sqlite3.Error, OSError) as exc:
        payload = {
            "service_version": SERVICE_VERSION,
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "completed_at": utc_now(),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

