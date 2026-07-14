from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.publication_control_service_v2_7_3_4 import (
    PublicationError,
    build_update_values,
    connect_database,
    read_scheme,
    scalar,
    transition_for,
    validate_current_state,
    verify_database,
    write_audit,
)


VERSION = "3.4.3.7.7"
SOURCE = "MeitY Startup Hub"
GOVERNANCE_ACTION = "withdraw-publication"
TARGET_IDS = (
    "meitycall_a95e53af41b5c53999cf",
    "meitycall_98f3c3720f15dae91ade",
    "meitycall_cbb7e8cd8fe24b00afd9",
    "meitycall_533fd1397d9885d223d2",
    "meitycall_37a5f7055e19110989f3",
    "meitycall_056b139f54fba2e7a8b3",
    "meitycall_a4a05a783de6e3478e54",
    "meitycall_b2b15a80eaf08c64193e",
    "meitycall_c53a5b2578e3b03d7291",
    "meitycall_0c7011d0b31e008b13b8",
    "meitycall_11ee67b180d2f208f8ef",
    "meitycall_ba1e7d64714d21401ed3",
    "meitycall_8d44c653724d98cb049d",
    "meitycall_f76675fa4a424f58ed0b",
    "meitycall_2f886d6194cb0b281a16",
    "meitycall_f6f817622dfc3035cf72",
)

RECLASSIFICATION_FIELDS = (
    "master_id",
    "scheme_name",
    "official_page_url",
    "current_publication_status",
    "current_is_public",
    "application_status",
    "classification",
    "classification_reason",
    "identity_quality",
    "republication_eligible",
    "required_next_action",
    "record_version",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def load_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def text_blob(row: sqlite3.Row) -> str:
    payload = load_json(row["raw_record_json"])
    fields = [
        row["scheme_name"],
        row["official_page_url"],
        row["application_status"],
        payload.get("status_evidence"),
        payload.get("status_basis"),
        payload.get("parent_scheme_name"),
        payload.get("parent_resolution"),
        payload.get("evidence_excerpt"),
        payload.get("objectives"),
        payload.get("benefits"),
        payload.get("source_evidence"),
    ]
    return clean(" ".join(str(item or "") for item in fields)).casefold()


def classify(row: sqlite3.Row) -> tuple[str, str, str, str]:
    title = clean(row["scheme_name"])
    title_key = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    url = clean(row["official_page_url"]).casefold()
    blob = text_blob(row)

    if (
        ".pdf" in title.casefold()
        or "%20" in title.casefold()
        or ".pdf" in url
        or title_key.endswith(" pdf")
    ):
        return (
            "RAW_DOCUMENT",
            "The identity is a raw or encoded document filename, not a curated call title.",
            "INVALID_PUBLIC_IDENTITY",
            "Extract the document, identify the real call instance and rebuild a canonical record.",
        )

    if any(token in title_key for token in ("press release", "news", "media")):
        return (
            "PRESS_RELEASE_OR_NEWS",
            "The page is a news or press-release listing rather than an application call.",
            "NON_CALL_PAGE",
            "Retain only as supporting evidence; do not republish as a call.",
        )

    if title_key in {
        "challenges",
        "event partner",
        "organisationprofile",
        "organisation profile",
    }:
        return (
            "NAVIGATION_OR_DIRECTORY",
            "The title and URL identify a directory, listing or navigation page.",
            "NON_CALL_PAGE",
            "Use the listing only to discover individual official call pages.",
        )

    if any(
        token in title_key
        for token in (
            "brussels",
            "summit",
            "vivatech",
            "g20diaoverview",
            "g20 dia overview",
        )
    ) or any(
        token in blob
        for token in (
            "summit",
            "delegation",
            "conference",
            "event date",
            "international market access",
        )
    ):
        return (
            "EVENT_OR_CONFERENCE",
            "The evidence describes an event, summit, delegation or conference, not a live application window.",
            "NON_CALL_PAGE",
            "Retain as ecosystem history only if separately governed.",
        )

    if "/schemes/" in url:
        return (
            "PERMANENT_SCHEME_PAGE",
            "The official URL is a permanent scheme page and must not be represented as a call instance.",
            "WRONG_ENTITY_TYPE",
            "Link the page to its permanent scheme identity and search separately for dated calls.",
        )

    call_markers = (
        "hackathon",
        "grand challenge",
        "startup program",
        "startup programme",
        "academy",
        "applications",
        "problem statement",
        "challenge",
    )
    if any(marker in blob for marker in call_markers):
        return (
            "VALID_CALL_INSTANCE",
            "The evidence supports a distinct programme, challenge or hackathon identity, but current status and dates remain unverified.",
            "CALL_IDENTITY_ONLY",
            "Rebuild as a historical or current call only after dates, applicant layer, page role and status are verified.",
        )

    return (
        "UNRESOLVED",
        "The available evidence is insufficient to determine whether this is a call, programme, event or directory.",
        "REQUIRES_MANUAL_REVIEW",
        "Inspect the official page and assign a governed entity type before any republication.",
    )


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


@dataclass(frozen=True)
class WithdrawalPaths:
    database_path: Path
    output_dir: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "WithdrawalPaths":
        root = project_root.resolve()
        return cls(
            database_path=root / "database/ssip_staging_v1.db",
            output_dir=(
                root
                / "data/departments/meity/v3_4_3_7_7"
            ),
        )


class MeitYEmergencyWithdrawal:
    def __init__(self, paths: WithdrawalPaths) -> None:
        self.paths = paths

    def _rows(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in TARGET_IDS)
        return connection.execute(
            f"""
            SELECT s.*,q.review_status
            FROM scheme_staging s
            LEFT JOIN admin_review_queue q
              ON q.master_id=s.master_id
            WHERE s.master_id IN ({placeholders})
            ORDER BY s.scheme_name
            """,
            TARGET_IDS,
        ).fetchall()

    def plan(self) -> dict[str, Any]:
        connection = sqlite3.connect(
            f"file:{self.paths.database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            verify_database(connection)
            rows = self._rows(connection)
            public_count_before = int(
                scalar(connection, "SELECT COUNT(*) FROM public_schemes")
                or 0
            )
        finally:
            connection.close()

        found = {str(row["master_id"]) for row in rows}
        missing = sorted(set(TARGET_IDS) - found)
        actions: list[dict[str, Any]] = []

        for row in rows:
            blockers: list[str] = []
            if clean(row["source"]) != SOURCE:
                blockers.append("source is not MeitY Startup Hub")
            if clean(row["record_kind"]).upper() != "APPLICATION_CALL":
                blockers.append("record_kind is not APPLICATION_CALL")
            if clean(row["publication_status"]).upper() != "PUBLISHED":
                blockers.append("publication_status is not PUBLISHED")
            if int(row["is_public"] or 0) != 1:
                blockers.append("is_public is not 1")
            if clean(row["application_status"]).upper() != "VERIFICATION_REQUIRED":
                blockers.append(
                    "application_status is not VERIFICATION_REQUIRED"
                )
            if clean(row["review_status"]).upper() != "APPROVED":
                blockers.append("admin review status is not APPROVED")

            classification, reason, identity_quality, next_action = classify(row)
            actions.append(
                {
                    "master_id": row["master_id"],
                    "scheme_name": row["scheme_name"],
                    "official_page_url": row["official_page_url"],
                    "current_publication_status": row["publication_status"],
                    "current_is_public": int(row["is_public"] or 0),
                    "application_status": row["application_status"],
                    "classification": classification,
                    "classification_reason": reason,
                    "identity_quality": identity_quality,
                    "republication_eligible": False,
                    "required_next_action": next_action,
                    "record_version": int(row["record_version"] or 1),
                    "eligible_for_withdrawal": not blockers,
                    "blockers": blockers,
                }
            )

        plan: dict[str, Any] = {
            "version": VERSION,
            "generated_at": utc_now(),
            "database": str(self.paths.database_path),
            "governance_action": GOVERNANCE_ACTION,
            "target_ids": list(TARGET_IDS),
            "target_count": len(TARGET_IDS),
            "found_count": len(rows),
            "missing_ids": missing,
            "eligible_count": sum(
                action["eligible_for_withdrawal"] for action in actions
            ),
            "blocked_count": sum(
                not action["eligible_for_withdrawal"] for action in actions
            ),
            "public_count_before": public_count_before,
            "expected_public_count_after": public_count_before - len(actions),
            "master_ids_preserved": True,
            "admin_decisions_modified": False,
            "records_deleted": False,
            "publication_performed": False,
            "actions": actions,
        }

        signature_payload = {
            "version": plan["version"],
            "governance_action": plan["governance_action"],
            "target_ids": plan["target_ids"],
            "public_count_before": plan["public_count_before"],
            "actions": [
                {
                    "master_id": action["master_id"],
                    "current_publication_status": action[
                        "current_publication_status"
                    ],
                    "current_is_public": action["current_is_public"],
                    "record_version": action["record_version"],
                    "classification": action["classification"],
                    "eligible_for_withdrawal": action[
                        "eligible_for_withdrawal"
                    ],
                    "blockers": action["blockers"],
                }
                for action in actions
            ],
        }
        plan["plan_signature"] = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()
        return plan

    def write_plan(self, plan: dict[str, Any]) -> dict[str, str]:
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = (
            self.paths.output_dir
            / "meity_emergency_withdrawal_plan_v3_4_3_7_7.json"
        )
        csv_path = (
            self.paths.output_dir
            / "meity_reclassification_queue_v3_4_3_7_7.csv"
        )
        summary_path = (
            self.paths.output_dir
            / "meity_reclassification_summary_v3_4_3_7_7.json"
        )

        json_path.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        write_csv(csv_path, plan["actions"], RECLASSIFICATION_FIELDS)

        counts: dict[str, int] = {}
        for action in plan["actions"]:
            classification = action["classification"]
            counts[classification] = counts.get(classification, 0) + 1
        summary = {
            "version": VERSION,
            "plan_signature": plan["plan_signature"],
            "classification_counts": counts,
            "republication_eligible_count": 0,
            "manual_rebuild_required_count": len(plan["actions"]),
            "database_modified": False,
            "publication_performed": False,
        }
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "plan": str(json_path),
            "reclassification_queue": str(csv_path),
            "summary": str(summary_path),
        }

    def apply(
        self,
        *,
        expected_signature: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if not expected_signature:
            raise PublicationError(
                "A reviewed withdrawal plan signature is required."
            )
        if not clean(actor):
            raise PublicationError("Actor identity is required.")
        if not clean(reason):
            raise PublicationError("Withdrawal reason is required.")

        reviewed = self.plan()
        if reviewed["plan_signature"] != expected_signature:
            raise PublicationError(
                "The MeitY withdrawal plan changed after review."
            )
        if reviewed["missing_ids"]:
            raise PublicationError(
                "Target records are missing: "
                + ", ".join(reviewed["missing_ids"])
            )
        if reviewed["blocked_count"]:
            blocked = [
                action["master_id"]
                for action in reviewed["actions"]
                if not action["eligible_for_withdrawal"]
            ]
            raise PublicationError(
                "Withdrawal preconditions failed for: "
                + ", ".join(blocked)
            )
        if reviewed["eligible_count"] != len(TARGET_IDS):
            raise PublicationError(
                "The reviewed plan does not contain exactly 16 eligible records."
            )

        now = utc_now()
        connection = connect_database(self.paths.database_path)
        try:
            verify_database(connection)
            connection.execute("BEGIN IMMEDIATE")
            public_before = int(
                scalar(connection, "SELECT COUNT(*) FROM public_schemes")
                or 0
            )
            results: list[dict[str, Any]] = []

            for planned in reviewed["actions"]:
                row = read_scheme(connection, planned["master_id"])
                validate_current_state(row)

                if (
                    clean(row["publication_status"]).upper() != "PUBLISHED"
                    or int(row["is_public"] or 0) != 1
                    or int(row["record_version"] or 1)
                    != planned["record_version"]
                ):
                    raise PublicationError(
                        "Optimistic-lock failure for "
                        + planned["master_id"]
                    )

                new_status, new_is_public = transition_for(
                    GOVERNANCE_ACTION,
                    str(row["publication_status"]),
                )
                previous_status = str(row["publication_status"])
                previous_public = int(row["is_public"] or 0)
                previous_version = int(row["record_version"] or 1)
                values = build_update_values(
                    GOVERNANCE_ACTION,
                    new_status,
                    new_is_public,
                    actor,
                    reason,
                    now,
                    previous_version,
                )
                assignments = ", ".join(
                    f'"{name}"=?' for name in values
                )
                connection.execute(
                    f"""
                    UPDATE scheme_staging
                    SET {assignments}
                    WHERE master_id=?
                    """,
                    (*values.values(), planned["master_id"]),
                )
                updated = read_scheme(connection, planned["master_id"])
                validate_current_state(updated)
                write_audit(
                    connection,
                    master_id=planned["master_id"],
                    action=GOVERNANCE_ACTION,
                    previous_status=previous_status,
                    new_status=new_status,
                    previous_is_public=previous_public,
                    new_is_public=new_is_public,
                    actor=actor,
                    now=now,
                    reason=reason,
                    source_run_id=updated["source_run_id"],
                    record_version=previous_version + 1,
                    metadata={
                        "service_version": VERSION,
                        "plan_signature": expected_signature,
                        "emergency_scope": "MEITY_APPLICATION_CALLS",
                        "classification": planned["classification"],
                        "records_deleted": False,
                        "admin_decision_preserved": True,
                    },
                )
                results.append(
                    {
                        "master_id": planned["master_id"],
                        "scheme_name": planned["scheme_name"],
                        "previous_status": previous_status,
                        "new_status": new_status,
                        "classification": planned["classification"],
                    }
                )

            public_after = int(
                scalar(connection, "SELECT COUNT(*) FROM public_schemes")
                or 0
            )
            expected_after = public_before - len(results)
            if public_after != expected_after:
                raise PublicationError(
                    "Public-count verification failed: "
                    f"expected {expected_after}, found {public_after}."
                )
            remaining = int(
                scalar(
                    connection,
                    """
                    SELECT COUNT(*)
                    FROM public_schemes
                    WHERE source=?
                      AND record_kind='APPLICATION_CALL'
                      AND master_id IN (
                        SELECT master_id
                        FROM scheme_staging
                        WHERE source=?
                          AND application_status='VERIFICATION_REQUIRED'
                      )
                    """,
                    (SOURCE, SOURCE),
                )
                or 0
            )
            if remaining != 0:
                raise PublicationError(
                    f"{remaining} withdrawn MeitY records remain public."
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        result = {
            "version": VERSION,
            "action_at": now,
            "actor": actor,
            "reason": reason,
            "plan_signature": expected_signature,
            "withdrawn_count": len(results),
            "public_count_before": public_before,
            "public_count_after": public_after,
            "remaining_public_target_count": 0,
            "master_ids_preserved": True,
            "admin_decisions_modified": False,
            "records_deleted": False,
            "publication_performed": False,
            "records": results,
        }
        report_path = (
            self.paths.output_dir
            / "meity_emergency_withdrawal_applied_v3_4_3_7_7.json"
        )
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        result["report_path"] = str(report_path)
        return result
