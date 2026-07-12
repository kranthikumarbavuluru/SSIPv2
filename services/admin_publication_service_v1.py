from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from scripts.publication_control_service_v2_7_3_4 import (
    PublicationError,
    build_update_values,
    connect_database,
    quality_gate,
    read_scheme,
    scalar,
    transition_for,
    utc_now,
    validate_current_state,
    verify_database,
    write_audit,
)
from services.admin_verification_intelligence_v1 import verification_assessment


SERVICE_VERSION = "1.0.0"
ACTION_STATUS = {"mark-ready": "STAGED", "publish": "READY_FOR_PUBLICATION"}


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def publication_plan_signature(plan: dict[str, Any]) -> str:
    payload = {
        "action": plan["action"],
        "selected_ids": plan["selected_ids"],
        "records": [
            {
                "master_id": row["master_id"],
                "publication_status": row["publication_status"],
                "record_version": row["record_version"],
                "eligible": row["eligible"],
                "blockers": row["blockers"],
            }
            for row in plan["records"]
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AdminPublicationService:
    """Readiness-aware, atomic bulk publication control for the Admin UI."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if not self.database_path.exists():
            raise FileNotFoundError(f"Staging database not found: {self.database_path}")

    def status_counts(self) -> dict[str, int]:
        connection = connect_database(self.database_path)
        try:
            return {
                str(row["publication_status"]): int(row["count"])
                for row in connection.execute(
                    "SELECT publication_status,COUNT(*) AS count FROM scheme_staging GROUP BY publication_status"
                )
            }
        finally:
            connection.close()

    def list_public_records(self) -> list[dict[str, Any]]:
        connection = connect_database(self.database_path)
        try:
            rows = connection.execute(
                """SELECT master_id,scheme_name,source,record_kind,publication_status,is_public,
                          published_at,published_by,publication_notes,record_version
                   FROM scheme_staging WHERE publication_status='PUBLISHED'
                   ORDER BY source,scheme_name"""
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def list_audit(self, *, limit: int = 500) -> list[dict[str, Any]]:
        connection = connect_database(self.database_path)
        try:
            rows = connection.execute(
                """SELECT p.audit_id,p.master_id,s.scheme_name,p.action,p.previous_status,p.new_status,
                          p.action_by,p.action_at,p.reason,p.record_version
                   FROM publication_audit_log p
                   LEFT JOIN scheme_staging s ON s.master_id=p.master_id
                   ORDER BY p.audit_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def plan(self, action: str, master_ids: Iterable[str] | None = None) -> dict[str, Any]:
        if action not in ACTION_STATUS:
            raise ValueError(f"Unsupported publication action: {action}")
        selected_ids = sorted({str(item).strip() for item in master_ids or [] if str(item).strip()})
        source_status = ACTION_STATUS[action]
        connection = connect_database(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            verify_database(connection)
            params: list[Any] = [source_status]
            selected_clause = ""
            if selected_ids:
                selected_clause = f" AND s.master_id IN ({','.join('?' for _ in selected_ids)})"
                params.extend(selected_ids)
            rows = connection.execute(
                f"""SELECT s.*,q.review_status
                    FROM scheme_staging s
                    LEFT JOIN admin_review_queue q ON q.master_id=s.master_id
                    WHERE s.publication_status=? {selected_clause}
                    ORDER BY s.source,s.scheme_name""",
                params,
            ).fetchall()
        finally:
            connection.close()

        records: list[dict[str, Any]] = []
        found_ids: set[str] = set()
        for row in rows:
            found_ids.add(str(row["master_id"]))
            blockers: list[str] = []
            warnings: list[str] = []
            if str(row["review_status"] or "") != "APPROVED":
                blockers.append("admin review status is not APPROVED")
            if str(row["validation_decision"] or "") != "APPROVED_FOR_DATABASE":
                blockers.append("validation decision is not APPROVED_FOR_DATABASE")
            assessment = verification_assessment(_loads(row["raw_record_json"]))
            blockers.extend(assessment.blocking_gaps)
            warnings.extend(assessment.warnings)
            if action == "publish":
                gate = quality_gate(row)
                blockers.extend(gate.blockers)
                warnings.extend(gate.warnings)
            records.append({
                "master_id": row["master_id"], "scheme_name": row["scheme_name"],
                "source": row["source"], "record_kind": row["record_kind"],
                "publication_status": row["publication_status"], "record_version": int(row["record_version"] or 1),
                "review_status": row["review_status"] or "", "eligible": not blockers,
                "blockers": list(dict.fromkeys(blockers)), "warnings": list(dict.fromkeys(warnings)),
            })
        for missing_id in sorted(set(selected_ids) - found_ids):
            records.append({
                "master_id": missing_id, "scheme_name": "Record not in expected publication state",
                "source": "", "record_kind": "", "publication_status": "STATE_CHANGED",
                "record_version": 0, "review_status": "", "eligible": False,
                "blockers": [f"record is no longer {source_status}"], "warnings": [],
            })
        plan = {
            "service_version": SERVICE_VERSION, "action": action,
            "source_status": source_status, "selected_ids": selected_ids,
            "records": sorted(records, key=lambda item: item["master_id"]),
        }
        plan["eligible_ids"] = [row["master_id"] for row in plan["records"] if row["eligible"]]
        plan["excluded_ids"] = [row["master_id"] for row in plan["records"] if not row["eligible"]]
        plan["signature"] = publication_plan_signature(plan)
        return plan

    def bulk_action(
        self,
        *,
        action: str,
        master_ids: Iterable[str],
        actor: str,
        reason: str,
        expected_signature: str,
    ) -> dict[str, Any]:
        selected_ids = sorted({str(item).strip() for item in master_ids if str(item).strip()})
        if not selected_ids:
            raise PublicationError("Select at least one publication record.")
        if not actor.strip():
            raise PublicationError("Publisher identity is required.")
        if not reason.strip():
            raise PublicationError("Publication notes are required.")
        plan = self.plan(action, selected_ids)
        if plan["signature"] != expected_signature:
            raise PublicationError("Publication plan changed. Run and review a new preflight.")
        if plan["excluded_ids"]:
            raise PublicationError("Selected records failed publication readiness: " + ", ".join(plan["excluded_ids"]))

        now = utc_now()
        bulk_id = "bulk_publication_" + uuid.uuid4().hex
        connection = connect_database(self.database_path)
        try:
            verify_database(connection)
            connection.execute("BEGIN IMMEDIATE")
            public_before = int(scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0)
            results: list[dict[str, Any]] = []
            for planned in plan["records"]:
                row = read_scheme(connection, planned["master_id"])
                validate_current_state(row)
                if str(row["publication_status"]) != plan["source_status"] or int(row["record_version"] or 1) != planned["record_version"]:
                    raise PublicationError(f"Optimistic-lock failure for {planned['master_id']}.")
                new_status, new_is_public = transition_for(action, str(row["publication_status"]))
                if action == "publish":
                    gate = quality_gate(row)
                    if not gate.passed:
                        raise PublicationError(f"Quality gate failed for {planned['master_id']}: " + "; ".join(gate.blockers))
                previous_status = str(row["publication_status"])
                previous_public = int(row["is_public"] or 0)
                previous_version = int(row["record_version"] or 1)
                values = build_update_values(action, new_status, new_is_public, actor, reason, now, previous_version)
                assignments = ", ".join(f'"{name}"=?' for name in values)
                connection.execute(
                    f"UPDATE scheme_staging SET {assignments} WHERE master_id=?",
                    (*values.values(), planned["master_id"]),
                )
                updated = read_scheme(connection, planned["master_id"])
                validate_current_state(updated)
                metadata = {
                    "service_version": SERVICE_VERSION, "bulk_id": bulk_id, "bulk_size": len(plan["records"]),
                    "plan_signature": expected_signature,
                }
                write_audit(
                    connection, master_id=planned["master_id"], action=action,
                    previous_status=previous_status, new_status=new_status,
                    previous_is_public=previous_public, new_is_public=new_is_public,
                    actor=actor, now=now, reason=reason,
                    source_run_id=updated["source_run_id"], record_version=previous_version + 1,
                    metadata=metadata,
                )
                results.append({
                    "master_id": planned["master_id"], "scheme_name": planned["scheme_name"],
                    "previous_status": previous_status, "new_status": new_status,
                })
            public_after = int(scalar(connection, "SELECT COUNT(*) FROM public_schemes") or 0)
            expected_after = public_before + (len(results) if action == "publish" else 0)
            if public_after != expected_after:
                raise PublicationError(f"Bulk public-count verification failed: expected {expected_after}, found {public_after}.")
            connection.commit()
            return {
                "bulk_id": bulk_id, "action": action, "record_count": len(results),
                "actor": actor, "reason": reason, "action_at": now,
                "public_count_before": public_before, "public_count_after": public_after,
                "records": results,
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
