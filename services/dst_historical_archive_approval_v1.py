from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from ssip_dashboard.dst_history import DSTHistoricalArchive, load_dst_historical_archive


SERVICE_VERSION = "1.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DSTHistoricalArchiveApprovalService:
    """Transactional sample-review and publication control for the DST archive."""

    def __init__(self, database_path: str | Path, project_root: str | Path) -> None:
        self.database_path = Path(database_path)
        self.project_root = Path(project_root)
        self.archive: DSTHistoricalArchive = load_dst_historical_archive(self.project_root)
        self.manifest = self.archive.manifest
        self.batch_id = f"dst_historical_v1_{self.manifest['signature'][:16]}"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def schema_ready(self) -> bool:
        connection = self._connect()
        try:
            required = {
                "historical_archive_batches",
                "historical_call_archive",
                "historical_archive_actions",
            }
            present = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?)",
                    tuple(sorted(required)),
                )
            }
            return present == required
        finally:
            connection.close()

    def status(self) -> dict[str, Any]:
        if not self.schema_ready():
            return {
                "schema_ready": False,
                "batch_id": self.batch_id,
                "approval_status": "MIGRATION_REQUIRED",
                "archive_records": 0,
                "public_records": 0,
            }
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM historical_archive_batches WHERE batch_id=?",
                (self.batch_id,),
            ).fetchone()
            return {
                "schema_ready": True,
                "batch_id": self.batch_id,
                "approval_status": str(row["approval_status"]) if row else "PREVIEW",
                "reviewed_by": str(row["reviewed_by"] or "") if row else "",
                "reviewed_at": str(row["reviewed_at"] or "") if row else "",
                "archive_records": int(connection.execute(
                    "SELECT COUNT(*) FROM historical_call_archive WHERE batch_id=?",
                    (self.batch_id,),
                ).fetchone()[0]),
                "public_records": int(connection.execute(
                    "SELECT COUNT(*) FROM historical_call_archive WHERE batch_id=? AND is_public=1",
                    (self.batch_id,),
                ).fetchone()[0]),
            }
        finally:
            connection.close()

    def _validate_manifest(self, expected_signature: str) -> None:
        if expected_signature != self.manifest["signature"]:
            raise ValueError("Historical archive manifest changed. Refresh and review the new sample.")
        if self.manifest["exception_count"]:
            raise ValueError("Archive contains unresolved exceptions and cannot be approved.")
        if len(self.archive.historical_records) != self.manifest["qualified_historical_calls"]:
            raise ValueError("Qualified archive count does not match the signed manifest.")

    def review_sample(
        self,
        *,
        reviewer: str,
        notes: str,
        expected_signature: str,
        reviewed_sample_ids: list[str],
    ) -> dict[str, Any]:
        if not self.schema_ready():
            raise RuntimeError("Historical archive migration is not installed.")
        self._validate_manifest(expected_signature)
        reviewer = reviewer.strip()
        notes = notes.strip()
        if not reviewer or not notes:
            raise ValueError("Reviewer identity and review notes are required.")
        expected_sample = sorted(self.manifest["sample_ids"])
        if sorted(set(reviewed_sample_ids)) != expected_sample:
            raise ValueError("The complete signed stratified sample must be confirmed.")

        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT approval_status FROM historical_archive_batches WHERE batch_id=?",
                (self.batch_id,),
            ).fetchone()
            previous = str(existing[0]) if existing else "PREVIEW"
            if previous == "APPROVED":
                raise ValueError("This archive batch is already published.")
            connection.execute(
                """
                INSERT INTO historical_archive_batches (
                    batch_id,department_code,service_version,source_path,manifest_signature,
                    normalized_count,qualified_count,current_excluded_count,exception_count,
                    sample_count,approval_status,reviewed_by,reviewed_at,review_notes,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    approval_status='SAMPLE_REVIEWED', reviewed_by=excluded.reviewed_by,
                    reviewed_at=excluded.reviewed_at, review_notes=excluded.review_notes
                """,
                (
                    self.batch_id, "DST", SERVICE_VERSION, str(self.archive.source_path),
                    self.manifest["signature"], self.manifest["total_normalized_calls"],
                    self.manifest["qualified_historical_calls"], self.manifest["current_calls_excluded"],
                    self.manifest["exception_count"], len(expected_sample), "SAMPLE_REVIEWED",
                    reviewer, now, notes, now,
                ),
            )
            connection.execute("DELETE FROM historical_call_archive WHERE batch_id=?", (self.batch_id,))
            for item in self.archive.historical_records:
                call = item.call
                connection.execute(
                    """
                    INSERT INTO historical_call_archive (
                        batch_id,call_id,department_code,call_title,closing_date,closing_year,
                        archive_state,relevance_group,applicant_layer,parent_master_id,primary_sector,
                        secondary_sectors,detail_url,last_verified_at,warnings_json,record_payload_json,
                        is_public,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
                    """,
                    (
                        self.batch_id, call.call_id, "DST", call.call_title, call.closing_date,
                        item.closing_year, item.archive_state, item.relevance_group, call.applicant_layer,
                        call.parent_master_id, call.primary_sector, call.secondary_sectors,
                        call.detail_url, call.last_verified_at, json.dumps(item.warnings, ensure_ascii=False),
                        json.dumps(asdict(call), ensure_ascii=False, sort_keys=True), now,
                    ),
                )
            connection.execute(
                """
                INSERT INTO historical_archive_actions (
                    batch_id,action,previous_status,new_status,action_by,action_at,reason,
                    manifest_signature,metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.batch_id, "REVIEW_SAMPLE", previous, "SAMPLE_REVIEWED", reviewer,
                    now, notes, self.manifest["signature"],
                    json.dumps({"sample_ids": expected_sample, "sample_count": len(expected_sample)}),
                ),
            )
            inserted = int(connection.execute(
                "SELECT COUNT(*) FROM historical_call_archive WHERE batch_id=?", (self.batch_id,)
            ).fetchone()[0])
            if inserted != self.manifest["qualified_historical_calls"]:
                raise RuntimeError(f"Archive import verification failed: expected {self.manifest['qualified_historical_calls']}, found {inserted}.")
            connection.commit()
            return {"batch_id": self.batch_id, "status": "SAMPLE_REVIEWED", "record_count": inserted}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def publish(
        self,
        *,
        publisher: str,
        notes: str,
        expected_signature: str,
    ) -> dict[str, Any]:
        if not self.schema_ready():
            raise RuntimeError("Historical archive migration is not installed.")
        self._validate_manifest(expected_signature)
        publisher = publisher.strip()
        notes = notes.strip()
        if not publisher or not notes:
            raise ValueError("Publisher identity and publication notes are required.")
        now = utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT approval_status FROM historical_archive_batches WHERE batch_id=?",
                (self.batch_id,),
            ).fetchone()
            if not batch or str(batch[0]) != "SAMPLE_REVIEWED":
                raise ValueError("The signed 36-record sample must be approved before publication.")
            archive_count = int(connection.execute(
                "SELECT COUNT(*) FROM historical_call_archive WHERE batch_id=?", (self.batch_id,)
            ).fetchone()[0])
            if archive_count != self.manifest["qualified_historical_calls"]:
                raise ValueError("Archive record count no longer matches the signed manifest.")
            connection.execute(
                "UPDATE historical_call_archive SET is_public=1 WHERE batch_id=?",
                (self.batch_id,),
            )
            connection.execute(
                """UPDATE historical_archive_batches
                   SET approval_status='APPROVED', reviewed_by=?, reviewed_at=?, review_notes=?
                   WHERE batch_id=?""",
                (publisher, now, notes, self.batch_id),
            )
            connection.execute(
                """
                INSERT INTO historical_archive_actions (
                    batch_id,action,previous_status,new_status,action_by,action_at,reason,
                    manifest_signature,metadata_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.batch_id, "PUBLISH_ARCHIVE", "SAMPLE_REVIEWED", "APPROVED",
                    publisher, now, notes, self.manifest["signature"],
                    json.dumps({"published_count": archive_count}),
                ),
            )
            public_count = int(connection.execute(
                "SELECT COUNT(*) FROM public_historical_calls WHERE batch_id=?", (self.batch_id,)
            ).fetchone()[0])
            if public_count != archive_count:
                raise RuntimeError("Public historical-call count verification failed.")
            connection.commit()
            return {"batch_id": self.batch_id, "status": "APPROVED", "public_count": public_count}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

