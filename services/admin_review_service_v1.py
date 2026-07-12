from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
import sqlite3
import uuid
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from database.staging_loader_v1 import (
    record_hash,
    stable_json,
    upsert_approved_scheme,
    upsert_rejected_item,
)
from services.admin_verification_intelligence_v1 import verification_assessment


SERVICE_VERSION = "1.0.1"
ALLOWED_ACTIONS = {
    "SAVE_DRAFT",
    "APPROVE",
    "NEEDS_MORE_EVIDENCE",
    "REJECT",
    "REOPEN",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return copy.deepcopy(default)
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return copy.deepcopy(default)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class AdminReviewService:
    """Transactional service for reviewing SSIP staging records."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[1] / "database" / "ssip_staging_v1.db"
        self.database_path = Path(database_path or os.environ.get("SSIP_DB_PATH", default_path))
        if not self.database_path.exists():
            raise FileNotFoundError(f"Staging database not found: {self.database_path}")
        self.ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection and always close it after the operation.

        sqlite3.Connection's built-in context manager commits/rolls back but does
        not close the handle. Explicit closure is required on Windows so temporary
        databases can be deleted after tests.
        """
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_review_actions (
                    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    master_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    notes TEXT,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL,
                    service_version TEXT NOT NULL,
                    FOREIGN KEY(master_id) REFERENCES admin_review_queue(master_id)
                );

                CREATE INDEX IF NOT EXISTS idx_admin_review_actions_master_created
                    ON admin_review_actions(master_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_admin_review_actions_action_created
                    ON admin_review_actions(action, created_at DESC);
                """
            )

    def dashboard_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            queries = {
                "staged_schemes": "SELECT COUNT(*) FROM scheme_staging",
                "pending_reviews": "SELECT COUNT(*) FROM admin_review_queue WHERE review_status='PENDING'",
                "approved_reviews": "SELECT COUNT(*) FROM admin_review_queue WHERE review_status='APPROVED'",
                "rejected_reviews": "SELECT COUNT(*) FROM admin_review_queue WHERE review_status='REJECTED'",
                "rejected_records": "SELECT COUNT(*) FROM rejected_scheme_records",
                "review_actions": "SELECT COUNT(*) FROM admin_review_actions",
            }
            return {
                key: int(connection.execute(sql).fetchone()[0])
                for key, sql in queries.items()
            }

    def list_reviews(
        self,
        *,
        review_status: str = "PENDING",
        priority: str | None = None,
        decision: str | None = None,
        source: str | None = None,
        record_kind: str | None = None,
        applicant_layer: str | None = None,
        department: str | None = None,
        ministry: str | None = None,
        import_run: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if review_status and review_status != "ALL":
            clauses.append("review_status = ?")
            params.append(review_status)
        if priority and priority != "ALL":
            clauses.append("priority = ?")
            params.append(priority)
        if decision and decision != "ALL":
            clauses.append("decision = ?")
            params.append(decision)
        if source and source != "ALL":
            clauses.append("source = ?")
            params.append(source)
        if record_kind and record_kind != "ALL":
            clauses.append("record_kind = ?")
            params.append(record_kind)
        if applicant_layer and applicant_layer != "ALL":
            clauses.append("json_extract(validated_record_json, '$.applicant_layer') = ?")
            params.append(applicant_layer)
        if department and department != "ALL":
            clauses.append("json_extract(validated_record_json, '$.department') = ?")
            params.append(department)
        if ministry and ministry != "ALL":
            clauses.append("json_extract(validated_record_json, '$.ministry') = ?")
            params.append(ministry)
        if import_run and import_run != "ALL":
            clauses.append("last_import_run_id = ?")
            params.append(import_run)
        if search:
            clauses.append("(scheme_name LIKE ? OR master_id LIKE ? OR source LIKE ?)")
            term = f"%{search.strip()}%"
            params.extend([term, term, term])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT master_id, scheme_name, source, record_kind, programme_status,
                   application_status, official_page_url, application_url, decision,
                   validation_score, review_status, priority, warnings_json,
                   recommended_actions_json, updated_at, last_import_run_id,
                   json_extract(validated_record_json, '$.department') AS department,
                   json_extract(validated_record_json, '$.ministry') AS ministry,
                   json_extract(validated_record_json, '$.applicant_layer') AS applicant_layer,
                   json_extract(validated_record_json, '$.parent_scheme_name') AS parent_scheme_name
            FROM admin_review_queue
            {where}
            ORDER BY
                CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                CASE review_status WHEN 'PENDING' THEN 1 WHEN 'APPROVED' THEN 2 ELSE 3 END,
                validation_score DESC,
                scheme_name
        """
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["warnings"] = _loads(item.pop("warnings_json", None), [])
            item["recommended_actions"] = _loads(
                item.pop("recommended_actions_json", None), []
            )
            output.append(item)
        return output

    def filter_options(self) -> dict[str, list[str]]:
        with self._connect() as connection:
            sources = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT source FROM admin_review_queue WHERE source IS NOT NULL ORDER BY source"
                )
            ]
            decisions = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT decision FROM admin_review_queue WHERE decision IS NOT NULL ORDER BY decision"
                )
            ]
            record_kinds = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT record_kind FROM admin_review_queue WHERE record_kind IS NOT NULL ORDER BY record_kind"
                )
            ]
            applicant_layers = [
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT json_extract(validated_record_json, '$.applicant_layer')
                       FROM admin_review_queue
                       WHERE json_valid(validated_record_json)
                         AND json_extract(validated_record_json, '$.applicant_layer') IS NOT NULL
                       ORDER BY 1"""
                )
            ]
            departments = [
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT json_extract(validated_record_json, '$.department')
                       FROM admin_review_queue
                       WHERE json_valid(validated_record_json)
                         AND json_extract(validated_record_json, '$.department') IS NOT NULL
                       ORDER BY 1"""
                )
            ]
            ministries = [
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT json_extract(validated_record_json, '$.ministry')
                       FROM admin_review_queue
                       WHERE json_valid(validated_record_json)
                         AND json_extract(validated_record_json, '$.ministry') IS NOT NULL
                       ORDER BY 1"""
                )
            ]
            import_runs = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT last_import_run_id FROM admin_review_queue WHERE last_import_run_id IS NOT NULL ORDER BY last_import_run_id DESC"
                )
            ]
        return {
            "sources": sources,
            "decisions": decisions,
            "record_kinds": record_kinds,
            "applicant_layers": applicant_layers,
            "departments": departments,
            "ministries": ministries,
            "import_runs": import_runs,
        }

    def list_import_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT run_id,started_at,completed_at,status,approved_input_count,
                          review_input_count,rejected_input_count,summary_json
                   FROM import_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["summary"] = _loads(item.pop("summary_json", None), {})
            output.append(item)
        return output

    def list_actions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT a.action_id,a.master_id,q.scheme_name,a.action,a.reviewer,a.notes,
                          a.created_at,a.service_version
                   FROM admin_review_actions a
                   LEFT JOIN admin_review_queue q ON q.master_id=a.master_id
                   ORDER BY a.action_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def duplicate_candidates(self, master_id: str, record: dict[str, Any]) -> list[dict[str, str]]:
        target_url = str(record.get("official_page_url") or "").strip().casefold().rstrip("/")
        target_name = re.sub(r"[^a-z0-9]+", " ", str(record.get("scheme_name") or "").casefold()).strip()
        matches: list[dict[str, str]] = []
        with self._connect() as connection:
            for table in ("admin_review_queue", "scheme_staging"):
                status_column = "review_status" if table == "admin_review_queue" else "publication_status"
                rows = connection.execute(
                    f"SELECT master_id,scheme_name,official_page_url,{status_column} AS status FROM {table} WHERE master_id<>?",
                    (master_id,),
                ).fetchall()
                for row in rows:
                    url = str(row["official_page_url"] or "").strip().casefold().rstrip("/")
                    name = re.sub(r"[^a-z0-9]+", " ", str(row["scheme_name"] or "").casefold()).strip()
                    reason = "OFFICIAL_URL_MATCH" if target_url and url == target_url else (
                        "NORMALIZED_NAME_MATCH" if target_name and name == target_name else ""
                    )
                    if reason:
                        matches.append({
                            "master_id": row["master_id"], "scheme_name": row["scheme_name"],
                            "table": table, "status": row["status"] or "", "reason": reason,
                        })
        return matches

    def get_review(self, master_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM admin_review_queue WHERE master_id = ?", (master_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Review item not found: {master_id}")
        item = dict(row)
        for source_key, target_key, default in (
            ("decision_reasons_json", "decision_reasons", []),
            ("warnings_json", "warnings", []),
            ("critical_flags_json", "critical_flags", []),
            ("recommended_actions_json", "recommended_actions", []),
            ("validated_record_json", "validated_record", {}),
        ):
            item[target_key] = _loads(item.pop(source_key, None), default)
        item["history"] = self.get_history(master_id)
        return item

    def get_history(self, master_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT action_id, action, reviewer, notes, before_json, after_json,
                       created_at, service_version
                FROM admin_review_actions
                WHERE master_id = ?
                ORDER BY action_id DESC
                """,
                (master_id,),
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["before"] = _loads(item.pop("before_json", None), None)
            item["after"] = _loads(item.pop("after_json", None), None)
            history.append(item)
        return history

    def _current_queue_row(self, connection: sqlite3.Connection, master_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM admin_review_queue WHERE master_id = ?", (master_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Review item not found: {master_id}")
        return row

    @staticmethod
    def _validate_record(record: dict[str, Any], *, for_approval: bool = False) -> None:
        master_id = str(record.get("master_id") or "").strip()
        scheme_name = str(record.get("scheme_name") or "").strip()
        if not master_id:
            raise ValueError("master_id is required")
        if not scheme_name:
            raise ValueError("scheme_name is required")
        if for_approval:
            official_url = str(record.get("official_page_url") or "").strip()
            if not official_url.startswith(("http://", "https://")):
                raise ValueError("A valid official_page_url is required before approval")
            assessment = verification_assessment(record)
            if not assessment.ready_for_approval:
                raise ValueError(
                    "Approval blocked. Mandatory verification checks are missing: "
                    + " | ".join(assessment.blocking_gaps)
                )

    @staticmethod
    def _reviewer_name(reviewer: str) -> str:
        name = reviewer.strip()
        if not name:
            raise ValueError("Reviewer name is required")
        return name

    def _log_action(
        self,
        connection: sqlite3.Connection,
        *,
        master_id: str,
        action: str,
        reviewer: str,
        notes: str,
        before: Any,
        after: Any,
        created_at: str,
    ) -> None:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        connection.execute(
            """
            INSERT INTO admin_review_actions(
                master_id, action, reviewer, notes, before_json, after_json,
                created_at, service_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                action,
                reviewer,
                notes.strip() or None,
                stable_json(before) if before is not None else None,
                stable_json(after) if after is not None else None,
                created_at,
                SERVICE_VERSION,
            ),
        )

    @staticmethod
    def _queue_priority(decision: str, application_status: str | None) -> str:
        if application_status == "OPEN":
            return "HIGH"
        if decision == "NEEDS_MORE_EVIDENCE":
            return "MEDIUM"
        return "NORMAL"

    @staticmethod
    def _prepare_record(
        record: dict[str, Any],
        *,
        reviewer: str,
        notes: str,
        action: str,
        decision: str,
        reviewed_at: str,
    ) -> dict[str, Any]:
        prepared = copy.deepcopy(record)
        validation = dict(prepared.get("validation") or {})
        validation["decision"] = decision
        validation["admin_reviewed_at"] = reviewed_at
        validation["admin_reviewer"] = reviewer
        validation["admin_action"] = action
        if notes.strip():
            reasons = list(validation.get("decision_reasons") or [])
            reasons.append(notes.strip())
            validation["decision_reasons"] = reasons
        prepared["validation"] = validation
        prepared["admin_review"] = {
            "action": action,
            "reviewer": reviewer,
            "notes": notes.strip(),
            "reviewed_at": reviewed_at,
            "service_version": SERVICE_VERSION,
        }
        return prepared

    @staticmethod
    def _start_import_run(
        connection: sqlite3.Connection,
        *,
        action: str,
        started_at: str,
        approved_count: int = 0,
        rejected_count: int = 0,
    ) -> str:
        run_id = f"admin_{action.lower()}_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO import_runs(
                run_id, started_at, status, approved_input_count,
                review_input_count, rejected_input_count
            ) VALUES (?, ?, 'RUNNING', ?, 1, ?)
            """,
            (run_id, started_at, approved_count, rejected_count),
        )
        return run_id

    @staticmethod
    def _finish_import_run(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        completed_at: str,
        action: str,
        master_id: str,
    ) -> None:
        connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?, status = 'COMPLETED', summary_json = ?
            WHERE run_id = ?
            """,
            (
                completed_at,
                stable_json(
                    {
                        "source": "ADMIN_REVIEW_MODULE",
                        "action": action,
                        "master_id": master_id,
                        "service_version": SERVICE_VERSION,
                        "completed_at": completed_at,
                    }
                ),
                run_id,
            ),
        )

    def save_draft(
        self,
        master_id: str,
        edited_record: dict[str, Any],
        *,
        reviewer: str,
        notes: str = "",
    ) -> dict[str, Any]:
        reviewer = self._reviewer_name(reviewer)
        self._validate_record(edited_record)
        if str(edited_record["master_id"]) != master_id:
            raise ValueError("master_id cannot be changed")
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._current_queue_row(connection, master_id)
                before = _loads(row["validated_record_json"], {})
                prepared = self._prepare_record(
                    edited_record,
                    reviewer=reviewer,
                    notes=notes,
                    action="SAVE_DRAFT",
                    decision=str(row["decision"]),
                    reviewed_at=now,
                )
                rec_hash = record_hash(prepared)
                connection.execute(
                    """
                    UPDATE admin_review_queue
                    SET scheme_name=?, source=?, record_kind=?, programme_status=?,
                        application_status=?, official_page_url=?, application_url=?,
                        validated_record_json=?, record_hash=?, updated_at=?
                    WHERE master_id=?
                    """,
                    (
                        prepared.get("scheme_name"),
                        prepared.get("source"),
                        prepared.get("record_kind"),
                        prepared.get("programme_status"),
                        prepared.get("application_status"),
                        prepared.get("official_page_url"),
                        prepared.get("application_url"),
                        stable_json(prepared),
                        rec_hash,
                        now,
                        master_id,
                    ),
                )
                self._log_action(
                    connection,
                    master_id=master_id,
                    action="SAVE_DRAFT",
                    reviewer=reviewer,
                    notes=notes,
                    before=before,
                    after=prepared,
                    created_at=now,
                )
                connection.commit()
                return prepared
            except Exception:
                connection.rollback()
                raise

    def mark_needs_more_evidence(
        self,
        master_id: str,
        edited_record: dict[str, Any],
        *,
        reviewer: str,
        notes: str,
    ) -> dict[str, Any]:
        reviewer = self._reviewer_name(reviewer)
        if not notes.strip():
            raise ValueError("Notes are required when requesting more evidence")
        self._validate_record(edited_record)
        if str(edited_record["master_id"]) != master_id:
            raise ValueError("master_id cannot be changed")
        now = utc_now()
        prepared = self._prepare_record(
            edited_record,
            reviewer=reviewer,
            notes=notes,
            action="NEEDS_MORE_EVIDENCE",
            decision="NEEDS_MORE_EVIDENCE",
            reviewed_at=now,
        )
        priority = self._queue_priority(
            "NEEDS_MORE_EVIDENCE", prepared.get("application_status")
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._current_queue_row(connection, master_id)
                before = _loads(row["validated_record_json"], {})
                reasons = _loads(row["decision_reasons_json"], [])
                reasons.append(notes.strip())
                connection.execute(
                    """
                    UPDATE admin_review_queue
                    SET scheme_name=?, source=?, record_kind=?, programme_status=?,
                        application_status=?, official_page_url=?, application_url=?,
                        decision='NEEDS_MORE_EVIDENCE', review_status='PENDING',
                        priority=?, decision_reasons_json=?, validated_record_json=?,
                        record_hash=?, updated_at=?
                    WHERE master_id=?
                    """,
                    (
                        prepared.get("scheme_name"),
                        prepared.get("source"),
                        prepared.get("record_kind"),
                        prepared.get("programme_status"),
                        prepared.get("application_status"),
                        prepared.get("official_page_url"),
                        prepared.get("application_url"),
                        priority,
                        stable_json(reasons),
                        stable_json(prepared),
                        record_hash(prepared),
                        now,
                        master_id,
                    ),
                )
                self._log_action(
                    connection,
                    master_id=master_id,
                    action="NEEDS_MORE_EVIDENCE",
                    reviewer=reviewer,
                    notes=notes,
                    before=before,
                    after=prepared,
                    created_at=now,
                )
                connection.commit()
                return prepared
            except Exception:
                connection.rollback()
                raise

    def approve(
        self,
        master_id: str,
        edited_record: dict[str, Any],
        *,
        reviewer: str,
        notes: str = "",
    ) -> dict[str, Any]:
        reviewer = self._reviewer_name(reviewer)
        self._validate_record(edited_record, for_approval=True)
        if str(edited_record["master_id"]) != master_id:
            raise ValueError("master_id cannot be changed")
        duplicates = self.duplicate_candidates(master_id, edited_record)
        if duplicates:
            raise ValueError(
                "Approval blocked by possible duplicate records: "
                + " | ".join(
                    f"{item['scheme_name']} ({item['reason']})" for item in duplicates
                )
            )
        now = utc_now()
        prepared = self._prepare_record(
            edited_record,
            reviewer=reviewer,
            notes=notes,
            action="APPROVE",
            decision="APPROVED_FOR_DATABASE",
            reviewed_at=now,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._current_queue_row(connection, master_id)
                before = _loads(row["validated_record_json"], {})
                run_id = self._start_import_run(
                    connection,
                    action="APPROVE",
                    started_at=now,
                    approved_count=1,
                )
                upsert_approved_scheme(connection, prepared, run_id, now)
                validation = prepared.get("validation") or {}
                connection.execute(
                    """
                    UPDATE admin_review_queue
                    SET scheme_name=?, source=?, record_kind=?, programme_status=?,
                        application_status=?, official_page_url=?, application_url=?,
                        decision='APPROVED_FOR_DATABASE', validation_score=?,
                        review_status='APPROVED', priority='NORMAL',
                        validated_record_json=?, record_hash=?, updated_at=?,
                        last_import_run_id=?
                    WHERE master_id=?
                    """,
                    (
                        prepared.get("scheme_name"),
                        prepared.get("source"),
                        prepared.get("record_kind"),
                        prepared.get("programme_status"),
                        prepared.get("application_status"),
                        prepared.get("official_page_url"),
                        prepared.get("application_url"),
                        validation.get("validation_score"),
                        stable_json(prepared),
                        record_hash(prepared),
                        now,
                        run_id,
                        master_id,
                    ),
                )
                connection.execute(
                    "DELETE FROM rejected_scheme_records WHERE master_id = ?", (master_id,)
                )
                self._log_action(
                    connection,
                    master_id=master_id,
                    action="APPROVE",
                    reviewer=reviewer,
                    notes=notes,
                    before=before,
                    after=prepared,
                    created_at=now,
                )
                self._finish_import_run(
                    connection,
                    run_id=run_id,
                    completed_at=now,
                    action="APPROVE",
                    master_id=master_id,
                )
                connection.commit()
                return prepared
            except Exception:
                connection.rollback()
                raise

    def reject(
        self,
        master_id: str,
        edited_record: dict[str, Any],
        *,
        reviewer: str,
        notes: str,
    ) -> dict[str, Any]:
        reviewer = self._reviewer_name(reviewer)
        if not notes.strip():
            raise ValueError("Rejection reason is required")
        self._validate_record(edited_record)
        if str(edited_record["master_id"]) != master_id:
            raise ValueError("master_id cannot be changed")
        now = utc_now()
        prepared = self._prepare_record(
            edited_record,
            reviewer=reviewer,
            notes=notes,
            action="REJECT",
            decision="REJECTED",
            reviewed_at=now,
        )
        rejection_item = copy.deepcopy(prepared)
        rejection_item["decision"] = "REJECTED"
        rejection_item["decision_reasons"] = [notes.strip()]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._current_queue_row(connection, master_id)
                before = _loads(row["validated_record_json"], {})
                run_id = self._start_import_run(
                    connection,
                    action="REJECT",
                    started_at=now,
                    rejected_count=1,
                )
                upsert_rejected_item(connection, rejection_item, run_id, now)
                connection.execute("DELETE FROM scheme_staging WHERE master_id = ?", (master_id,))
                connection.execute(
                    """
                    UPDATE admin_review_queue
                    SET scheme_name=?, source=?, record_kind=?, programme_status=?,
                        application_status=?, official_page_url=?, application_url=?,
                        decision='REJECTED', review_status='REJECTED', priority='NORMAL',
                        decision_reasons_json=?, validated_record_json=?, record_hash=?,
                        updated_at=?, last_import_run_id=?
                    WHERE master_id=?
                    """,
                    (
                        prepared.get("scheme_name"),
                        prepared.get("source"),
                        prepared.get("record_kind"),
                        prepared.get("programme_status"),
                        prepared.get("application_status"),
                        prepared.get("official_page_url"),
                        prepared.get("application_url"),
                        stable_json([notes.strip()]),
                        stable_json(prepared),
                        record_hash(prepared),
                        now,
                        run_id,
                        master_id,
                    ),
                )
                self._log_action(
                    connection,
                    master_id=master_id,
                    action="REJECT",
                    reviewer=reviewer,
                    notes=notes,
                    before=before,
                    after=prepared,
                    created_at=now,
                )
                self._finish_import_run(
                    connection,
                    run_id=run_id,
                    completed_at=now,
                    action="REJECT",
                    master_id=master_id,
                )
                connection.commit()
                return prepared
            except Exception:
                connection.rollback()
                raise

    def reopen(
        self,
        master_id: str,
        *,
        reviewer: str,
        notes: str = "",
    ) -> None:
        reviewer = self._reviewer_name(reviewer)
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._current_queue_row(connection, master_id)
                before = _loads(row["validated_record_json"], {})
                application_status = row["application_status"]
                decision = "NEEDS_ADMIN_REVIEW"
                priority = self._queue_priority(decision, application_status)
                connection.execute(
                    """
                    UPDATE admin_review_queue
                    SET decision=?, review_status='PENDING', priority=?, updated_at=?
                    WHERE master_id=?
                    """,
                    (decision, priority, now, master_id),
                )
                self._log_action(
                    connection,
                    master_id=master_id,
                    action="REOPEN",
                    reviewer=reviewer,
                    notes=notes,
                    before=before,
                    after=before,
                    created_at=now,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
