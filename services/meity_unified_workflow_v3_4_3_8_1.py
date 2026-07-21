from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "3.4.3.8.1"
OVERRIDE_TABLE = "meity_entity_classification_overrides_v3_4_3_8_0_7"
OVERRIDE_AUDIT_TABLE = (
    "meity_entity_classification_write_audit_v3_4_3_8_0_7"
)
PROJECTION_TABLE = "meity_unified_projection_v3_4_3_8_1"
PROJECTION_AUDIT_TABLE = "meity_unified_projection_audit_v3_4_3_8_1"


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def truthy(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def normalized_effective_type(value: str) -> str:
    token = clean(value).upper()
    if token in {
        "PERMANENT_PROGRAMME",
        "ACCELERATOR_PROGRAMME",
        "GRANT_PROGRAMME",
        "INCUBATION_PROGRAMME",
        "ECOSYSTEM_PROGRAMME",
        "IMPLEMENTATION_PROGRAMME",
        "PROGRAMME",
        "PROGRAM",
    }:
        return "PERMANENT_PROGRAMME"
    if token in {"PERMANENT_SCHEME", "SCHEME"}:
        return "PERMANENT_SCHEME"
    if token in {
        "CHALLENGE_CALL",
        "GRAND_CHALLENGE",
        "HACKATHON",
        "CHALLENGE",
    }:
        return "CHALLENGE_CALL"
    if token in {"ACCELERATOR_COHORT", "COHORT"}:
        return "ACCELERATOR_COHORT"
    if token in {
        "APPLICATION_CALL",
        "CALL",
        "EOI",
        "RFP",
        "IMPLEMENTATION_PARTNER_CALL",
    }:
        return "APPLICATION_CALL"
    if token in {
        "HISTORICAL_REFERENCE",
        "RESULT_ANNOUNCEMENT",
        "SUPPORTING_DOCUMENT",
        "INVALID_NON_CATALOGUE",
    }:
        return token
    return token or "SUPPORTING_DOCUMENT"


def record_kind_for(effective_type: str) -> str:
    return {
        "PERMANENT_PROGRAMME": "PROGRAMME",
        "PERMANENT_SCHEME": "SCHEME",
        "APPLICATION_CALL": "APPLICATION_CALL",
        "CHALLENGE_CALL": "CHALLENGE",
        "ACCELERATOR_COHORT": "APPLICATION_CALL",
        "HISTORICAL_REFERENCE": "HISTORICAL_REFERENCE",
        "RESULT_ANNOUNCEMENT": "HISTORICAL_REFERENCE",
        "SUPPORTING_DOCUMENT": "SUPPORTING_DOCUMENT",
        "INVALID_NON_CATALOGUE": "NON_CATALOGUE",
    }.get(effective_type, effective_type)


@dataclass(frozen=True)
class UnifiedMeitYPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    database_path: Path
    config_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "UnifiedMeitYPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_4",
            output_dir=root / "data/departments/meity/v3_4_3_8_1",
            database_path=root / "database/ssip_staging_v1.db",
            config_path=root / "config/meity_unified_workflow_v3_4_3_8_1.json",
        )


class MeitYUnifiedWorkflowService:
    def __init__(
        self,
        paths: UnifiedMeitYPaths,
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

    def _source_children(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
        )

    def _source_bundles(self) -> dict[str, dict[str, str]]:
        return {
            clean(row.get("bundle_id")): row
            for row in read_csv(
                self.paths.source_dir
                / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
            )
            if clean(row.get("bundle_id"))
        }

    def _active_overrides(self) -> dict[str, dict[str, Any]]:
        connection = self._connect()
        try:
            if not table_exists(connection, OVERRIDE_TABLE):
                return {}
            rows = connection.execute(
                f"""
                SELECT * FROM {OVERRIDE_TABLE}
                WHERE is_active=1
                ORDER BY created_at DESC
                """
            ).fetchall()
            return {clean(row["child_id"]): dict(row) for row in rows}
        finally:
            connection.close()

    def effective_inventory(self) -> list[dict[str, Any]]:
        bundles = self._source_bundles()
        overrides = self._active_overrides()
        rows: list[dict[str, Any]] = []

        programme_types = {
            "PERMANENT_PROGRAMME",
            "PERMANENT_SCHEME",
        }
        call_types = {
            "APPLICATION_CALL",
            "CHALLENGE_CALL",
            "ACCELERATOR_COHORT",
        }
        historical_types = {
            "HISTORICAL_REFERENCE",
            "RESULT_ANNOUNCEMENT",
        }

        for child in self._source_children():
            child_id = clean(child.get("child_id"))
            override = overrides.get(child_id)
            bundle = bundles.get(clean(child.get("bundle_id")), {})

            effective_type = normalized_effective_type(
                override.get("corrected_entity_type")
                if override
                else child.get("entity_type")
            )
            parent_name = clean(
                override.get("corrected_parent_scheme_name")
                if override
                else child.get("repaired_parent_scheme_name")
            )
            parent_id = clean(
                override.get("corrected_parent_master_id")
                if override
                else child.get("repaired_parent_master_id")
            )
            if effective_type in programme_types:
                section = "PROGRAMMES"
            elif effective_type in call_types:
                section = "CALLS_CHALLENGES"
            elif effective_type in historical_types:
                section = "HISTORICAL"
            elif effective_type in {
                "SUPPORTING_DOCUMENT",
                "INVALID_NON_CATALOGUE",
            }:
                section = "EXCLUDED_SUPPORTING"
            else:
                section = "CLASSIFICATION_REVIEW"

            information_url = clean(
                child.get("verified_information_url")
            )
            application_url = clean(
                child.get("verified_application_url")
            )
            temporal = clean(child.get("temporal_validation"))
            application_status = clean(
                child.get("safe_application_status")
                or child.get("application_status")
                or "VERIFICATION_REQUIRED"
            ).upper()
            link_complete = truthy(
                child.get("link_integrity_complete")
                or bundle.get("link_integrity_complete")
            )
            current_application_complete = truthy(
                bundle.get(
                    "current_application_integrity_complete"
                )
            )

            errors: list[str] = []
            warnings: list[str] = []

            if section in {
                "EXCLUDED_SUPPORTING",
                "CLASSIFICATION_REVIEW",
            }:
                errors.append("NON_CATALOGUE_CLASSIFICATION")
            if not information_url:
                errors.append("VERIFIED_INFORMATION_SOURCE_REQUIRED")
            if effective_type in call_types:
                if not parent_id:
                    errors.append("CALL_PARENT_PROGRAMME_REQUIRED")
                if temporal == "CURRENT_STATUS_EVIDENCE_COMPLETE":
                    if (
                        not current_application_complete
                        or not application_url
                    ):
                        errors.append(
                            "CURRENT_APPLICATION_INTEGRITY_REQUIRED"
                        )
                else:
                    warnings.append(
                        "CALL_IDENTITY_NOT_CURRENT_OPEN_STATUS"
                    )
                    application_url = ""
                    if application_status == "OPEN":
                        application_status = "VERIFICATION_REQUIRED"
            if effective_type in historical_types:
                application_url = ""
                application_status = "CLOSED"
            if effective_type in programme_types:
                application_url = ""
                if application_status not in {"OPEN", "CLOSED"}:
                    application_status = "NOT_APPLICABLE"
            if not link_complete:
                warnings.append("LINK_INTEGRITY_NOT_COMPLETE")

            eligible = not errors
            rows.append(
                {
                    **child,
                    "bundle_title": clean(bundle.get("bundle_title")),
                    "override_applied": bool(override),
                    "override_action_id": clean(
                        override.get("action_id") if override else ""
                    ),
                    "original_entity_type": clean(
                        child.get("entity_type")
                    ),
                    "effective_entity_type": effective_type,
                    "effective_record_kind": record_kind_for(
                        effective_type
                    ),
                    "effective_parent_scheme_name": parent_name,
                    "effective_parent_master_id": parent_id,
                    "dashboard_section": section,
                    "verified_information_url": information_url,
                    "verified_application_url": application_url,
                    "application_status": application_status,
                    "link_integrity_complete": link_complete,
                    "current_application_integrity_complete": (
                        current_application_complete
                    ),
                    "projection_eligible": eligible,
                    "projection_status": (
                        "ELIGIBLE" if eligible else "BLOCKED"
                    ),
                    "projection_errors": ";".join(errors),
                    "projection_warnings": ";".join(warnings),
                    "apply_action_allowed": bool(
                        effective_type in call_types
                        and application_status
                        in {"OPEN", "UPCOMING"}
                        and application_url
                        and current_application_complete
                    ),
                }
            )
        return rows

    def summary(self) -> dict[str, Any]:
        rows = self.effective_inventory()
        sections = Counter(row["dashboard_section"] for row in rows)
        return {
            "version": VERSION,
            "record_count": len(rows),
            "override_count": sum(
                1 for row in rows if row["override_applied"]
            ),
            "type_correction_count": sum(
                1
                for row in rows
                if row["override_applied"]
                and normalized_effective_type(
                    row["original_entity_type"]
                )
                != row["effective_entity_type"]
            ),
            "programme_count": sections.get("PROGRAMMES", 0),
            "call_challenge_count": sections.get(
                "CALLS_CHALLENGES",
                0,
            ),
            "historical_count": sections.get("HISTORICAL", 0),
            "excluded_supporting_count": sections.get(
                "EXCLUDED_SUPPORTING",
                0,
            ),
            "classification_review_count": sections.get(
                "CLASSIFICATION_REVIEW",
                0,
            ),
            "projection_eligible_count": sum(
                1 for row in rows if row["projection_eligible"]
            ),
            "projection_blocked_count": sum(
                1 for row in rows if not row["projection_eligible"]
            ),
            "apply_action_allowed_count": sum(
                1 for row in rows if row["apply_action_allowed"]
            ),
            "database_write_performed": False,
            "publication_performed": False,
            "public_visibility_changed": False,
        }

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PROJECTION_TABLE} (
                projection_id TEXT PRIMARY KEY,
                child_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                effective_entity_type TEXT NOT NULL,
                effective_record_kind TEXT NOT NULL,
                effective_parent_scheme_name TEXT,
                effective_parent_master_id TEXT,
                verified_information_url TEXT NOT NULL,
                verified_application_url TEXT,
                application_status TEXT,
                projection_status TEXT NOT NULL CHECK (
                    projection_status IN ('PENDING_ADMIN_REVIEW','SKIPPED')
                ),
                created_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                publication_action TEXT NOT NULL CHECK (
                    publication_action='NONE'
                )
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PROJECTION_AUDIT_TABLE} (
                audit_id TEXT PRIMARY KEY,
                projection_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK (
                    event IN (
                        'PROJECTED_TO_ADMIN_REVIEW',
                        'SKIPPED_EXISTING_DECISION',
                        'SKIPPED_STAGED_DUPLICATE'
                    )
                ),
                actor TEXT NOT NULL,
                event_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )

    def _queue_record(
        self,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        effective_type = row["effective_entity_type"]
        programme_status = (
            "SCHEME_INFORMATION_AVAILABLE"
            if effective_type
            in {"PERMANENT_PROGRAMME", "PERMANENT_SCHEME"}
            else (
                "HISTORICAL_REFERENCE"
                if effective_type
                in {"HISTORICAL_REFERENCE", "RESULT_ANNOUNCEMENT"}
                else "CALL_INFORMATION_AVAILABLE"
            )
        )
        application_url = (
            row["verified_application_url"]
            if row["apply_action_allowed"]
            else ""
        )
        funding = {
            "minimum": None,
            "maximum": None,
            "currency": "INR",
        }
        record = {
            "master_id": "meity_" + clean(row["child_id"]),
            "scheme_name": clean(row.get("canonical_name")),
            "short_name": "",
            "source": "MeitY Startup Hub",
            "ministry": (
                "Ministry of Electronics and Information "
                "Technology (MeitY)"
            ),
            "department": "",
            "implementing_agency": "MeitY Startup Hub",
            "record_kind": row["effective_record_kind"],
            "programme_status": programme_status,
            "application_status": row["application_status"],
            "scheme_status": (
                row["application_status"]
                if effective_type
                in {"PERMANENT_PROGRAMME", "PERMANENT_SCHEME"}
                and row["application_status"] in {"OPEN", "CLOSED"}
                else ""
            ),
            "geographic_scope": "India",
            "official_page_url": row["verified_information_url"],
            "application_url": application_url,
            "opening_date": clean(row.get("opening_date")),
            "closing_date": clean(row.get("closing_date")),
            "parent_master_id": clean(
                row.get("effective_parent_master_id")
            ),
            "parent_scheme_name": clean(
                row.get("effective_parent_scheme_name")
            ),
            "parent_resolution": (
                "CURATED_OFFICIAL_RELATIONSHIP"
                if row.get("effective_parent_master_id")
                else "NOT_APPLICABLE"
            ),
            "applicant_layer": clean(
                row.get("applicant_layer")
            ),
            "startup_relevance": clean(
                row.get("startup_relevance")
            ),
            "funding_amount": funding,
            "source_evidence": [
                {
                    "url": row["verified_information_url"],
                    "title": clean(
                        row.get("verified_information_title")
                        or row.get("canonical_name")
                    ),
                    "content_kind": clean(
                        row.get("verified_information_role")
                    ),
                    "evidence_text": clean(
                        row.get("status_evidence")
                        or row.get("evidence_excerpt")
                    ),
                }
            ],
            "status_basis": clean(
                row.get("status_basis")
                or row.get("temporal_validation")
            ),
            "status_evidence": clean(
                row.get("status_evidence")
                or row.get("evidence_excerpt")
            ),
            "last_verified_at": clean(
                row.get("last_verified_at")
            ),
            "validation": {
                "decision": "NEEDS_ADMIN_REVIEW",
                "validation_score": 0.9
                if row["override_applied"]
                else 0.75,
                "decision_reasons": [
                    "Projected from the governed MeitY classification "
                    "override workflow.",
                    "Publication remains a separate Admin decision.",
                ],
            },
        }
        return record

    def projection_plan(self) -> dict[str, Any]:
        rows = [
            row
            for row in self.effective_inventory()
            if row["projection_eligible"]
        ]
        plan_rows = [
            {
                "child_id": row["child_id"],
                "master_id": "meity_" + clean(row["child_id"]),
                "canonical_name": row["canonical_name"],
                "effective_entity_type": row[
                    "effective_entity_type"
                ],
                "effective_record_kind": row[
                    "effective_record_kind"
                ],
                "parent_master_id": row[
                    "effective_parent_master_id"
                ],
                "official_page_url": row[
                    "verified_information_url"
                ],
                "application_url": (
                    row["verified_application_url"]
                    if row["apply_action_allowed"]
                    else ""
                ),
                "application_status": row[
                    "application_status"
                ],
                "record_hash": hashlib.sha256(
                    stable_json(self._queue_record(row)).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            }
            for row in rows
        ]
        payload = {
            "version": VERSION,
            "rows": plan_rows,
            "eligible_count": len(plan_rows),
            "confirmation_required": clean(
                self.config.get("confirmation_phrase")
            ),
            "publication_action": "NONE",
        }
        payload["plan_signature"] = hashlib.sha256(
            stable_json(payload).encode("utf-8")
        ).hexdigest()
        return payload

    def apply_projection(
        self,
        *,
        expected_signature: str,
        confirmation: str,
        actor: str,
    ) -> dict[str, Any]:
        expected_phrase = clean(
            self.config.get("confirmation_phrase")
        )
        if clean(confirmation) != expected_phrase:
            raise PermissionError(
                f'Exact confirmation required: "{expected_phrase}"'
            )
        if not clean(actor):
            raise ValueError("Admin name is required.")

        plan = self.projection_plan()
        if clean(expected_signature) != plan["plan_signature"]:
            raise RuntimeError(
                "The MeitY projection plan changed after review."
            )

        rows_by_child = {
            clean(row["child_id"]): row
            for row in self.effective_inventory()
            if row["projection_eligible"]
        }
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )
        backup_root = (
            self.paths.project_root.parent
            / f"SSIP_DB_Backup_v3_4_3_8_1_{timestamp}"
        )
        backup_path = create_consistent_backup(
            self.paths.database_path,
            backup_root,
        )

        connection = self._connect()
        inserted = 0
        pending_updated = 0
        skipped_decisions = 0
        skipped_staged = 0
        now = utc_now()
        try:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")

            run_id = "meity_unified_" + uuid.uuid4().hex
            if table_exists(connection, "import_runs"):
                connection.execute(
                    """
                    INSERT INTO import_runs(
                        run_id,started_at,status,
                        approved_input_count,review_input_count,
                        rejected_input_count
                    ) VALUES (?,?,'RUNNING',0,?,0)
                    """,
                    (run_id, now, len(plan["rows"])),
                )

            for plan_row in plan["rows"]:
                child_id = clean(plan_row["child_id"])
                source_row = rows_by_child[child_id]
                record = self._queue_record(source_row)
                master_id = record["master_id"]
                projection_payload = {
                    "plan_signature": plan["plan_signature"],
                    "record": record,
                    "actor": clean(actor),
                }
                projection_id = (
                    "meityprojection_"
                    + hashlib.sha256(
                        stable_json(projection_payload).encode(
                            "utf-8"
                        )
                    ).hexdigest()[:24]
                )

                if (
                    table_exists(connection, "scheme_staging")
                    and connection.execute(
                        "SELECT 1 FROM scheme_staging WHERE master_id=?",
                        (master_id,),
                    ).fetchone()
                ):
                    skipped_staged += 1
                    event = "SKIPPED_STAGED_DUPLICATE"
                    projection_status = "SKIPPED"
                else:
                    existing = (
                        connection.execute(
                            """
                            SELECT review_status,record_hash
                            FROM admin_review_queue
                            WHERE master_id=?
                            """,
                            (master_id,),
                        ).fetchone()
                        if table_exists(
                            connection,
                            "admin_review_queue",
                        )
                        else None
                    )
                    rec_hash = hashlib.sha256(
                        stable_json(record).encode("utf-8")
                    ).hexdigest()
                    if existing and clean(
                        existing["review_status"]
                    ).upper() in {"APPROVED", "REJECTED"}:
                        skipped_decisions += 1
                        event = "SKIPPED_EXISTING_DECISION"
                        projection_status = "SKIPPED"
                    else:
                        priority = (
                            "HIGH"
                            if record["application_status"] == "OPEN"
                            else "NORMAL"
                        )
                        if existing:
                            if existing["record_hash"] == rec_hash:
                                event = "PROJECTED_TO_ADMIN_REVIEW"
                                projection_status = (
                                    "PENDING_ADMIN_REVIEW"
                                )
                            else:
                                connection.execute(
                                    """
                                    UPDATE admin_review_queue
                                    SET scheme_name=?,source=?,record_kind=?,
                                        programme_status=?,
                                        application_status=?,
                                        official_page_url=?,application_url=?,
                                        decision='NEEDS_ADMIN_REVIEW',
                                        review_status='PENDING',
                                        priority=?,
                                        decision_reasons_json=?,
                                        warnings_json=?,
                                        critical_flags_json=?,
                                        recommended_actions_json=?,
                                        validated_record_json=?,
                                        record_hash=?,updated_at=?,
                                        last_import_run_id=?
                                    WHERE master_id=?
                                    """,
                                    (
                                        record["scheme_name"],
                                        record["source"],
                                        record["record_kind"],
                                        record["programme_status"],
                                        record["application_status"],
                                        record["official_page_url"],
                                        record["application_url"],
                                        priority,
                                        stable_json(
                                            record["validation"][
                                                "decision_reasons"
                                            ]
                                        ),
                                        stable_json(
                                            [
                                                warning
                                                for warning in clean(
                                                    source_row.get(
                                                        "projection_warnings"
                                                    )
                                                ).split(";")
                                                if warning
                                            ]
                                        ),
                                        stable_json([]),
                                        stable_json(
                                            [
                                                "Verify classification, "
                                                "status, funding and parent "
                                                "relationship."
                                            ]
                                        ),
                                        stable_json(record),
                                        rec_hash,
                                        now,
                                        run_id,
                                        master_id,
                                    ),
                                )
                                pending_updated += 1
                            event = "PROJECTED_TO_ADMIN_REVIEW"
                            projection_status = (
                                "PENDING_ADMIN_REVIEW"
                            )
                        else:
                            connection.execute(
                                """
                                INSERT INTO admin_review_queue(
                                    master_id,scheme_name,source,record_kind,
                                    programme_status,application_status,
                                    official_page_url,application_url,
                                    decision,validation_score,review_status,
                                    priority,decision_reasons_json,
                                    warnings_json,critical_flags_json,
                                    recommended_actions_json,
                                    validated_record_json,record_hash,
                                    first_queued_at,updated_at,
                                    last_import_run_id
                                ) VALUES (
                                    ?,?,?,?,?,?,?,?,
                                    'NEEDS_ADMIN_REVIEW',?,
                                    'PENDING',?,?,?,?,?,?,?,?,?,?
                                )
                                """,
                                (
                                    master_id,
                                    record["scheme_name"],
                                    record["source"],
                                    record["record_kind"],
                                    record["programme_status"],
                                    record["application_status"],
                                    record["official_page_url"],
                                    record["application_url"],
                                    record["validation"][
                                        "validation_score"
                                    ],
                                    priority,
                                    stable_json(
                                        record["validation"][
                                            "decision_reasons"
                                        ]
                                    ),
                                    stable_json(
                                        [
                                            warning
                                            for warning in clean(
                                                source_row.get(
                                                    "projection_warnings"
                                                )
                                            ).split(";")
                                            if warning
                                        ]
                                    ),
                                    stable_json([]),
                                    stable_json(
                                        [
                                            "Verify classification, status, "
                                            "funding and parent relationship."
                                        ]
                                    ),
                                    stable_json(record),
                                    rec_hash,
                                    now,
                                    now,
                                    run_id,
                                ),
                            )
                            inserted += 1
                            event = "PROJECTED_TO_ADMIN_REVIEW"
                            projection_status = (
                                "PENDING_ADMIN_REVIEW"
                            )

                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {PROJECTION_TABLE} (
                        projection_id,child_id,master_id,canonical_name,
                        effective_entity_type,effective_record_kind,
                        effective_parent_scheme_name,
                        effective_parent_master_id,
                        verified_information_url,
                        verified_application_url,
                        application_status,projection_status,
                        created_at,actor,publication_action
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'NONE')
                    """,
                    (
                        projection_id,
                        child_id,
                        master_id,
                        record["scheme_name"],
                        source_row["effective_entity_type"],
                        source_row["effective_record_kind"],
                        source_row[
                            "effective_parent_scheme_name"
                        ],
                        source_row[
                            "effective_parent_master_id"
                        ],
                        source_row["verified_information_url"],
                        record["application_url"],
                        record["application_status"],
                        projection_status,
                        now,
                        clean(actor),
                    ),
                )
                audit_payload = {
                    "projection_id": projection_id,
                    "child_id": child_id,
                    "master_id": master_id,
                    "event": event,
                    "plan_signature": plan["plan_signature"],
                    "backup_path": str(backup_path),
                }
                connection.execute(
                    f"""
                    INSERT OR REPLACE INTO {PROJECTION_AUDIT_TABLE} (
                        audit_id,projection_id,child_id,event,
                        actor,event_at,payload_json
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        "audit_"
                        + hashlib.sha256(
                            stable_json(audit_payload).encode(
                                "utf-8"
                            )
                        ).hexdigest()[:24],
                        projection_id,
                        child_id,
                        event,
                        clean(actor),
                        now,
                        stable_json(audit_payload),
                    ),
                )

            if table_exists(connection, "import_runs"):
                connection.execute(
                    """
                    UPDATE import_runs
                    SET completed_at=?,status='COMPLETED',
                        summary_json=?
                    WHERE run_id=?
                    """,
                    (
                        utc_now(),
                        stable_json(
                            {
                                "source": (
                                    "MEITY_UNIFIED_CLASSIFICATION"
                                ),
                                "inserted_pending": inserted,
                                "updated_pending": pending_updated,
                                "skipped_existing_decisions": (
                                    skipped_decisions
                                ),
                                "skipped_staged_duplicates": (
                                    skipped_staged
                                ),
                                "publication_action": "NONE",
                            }
                        ),
                        run_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "version": VERSION,
            "plan_signature": plan["plan_signature"],
            "eligible_rows": len(plan["rows"]),
            "inserted_pending": inserted,
            "updated_pending": pending_updated,
            "skipped_existing_decisions": skipped_decisions,
            "skipped_staged_duplicates": skipped_staged,
            "backup_path": str(backup_path),
            "publication_action": "NONE",
            "public_visibility_changed": False,
        }

    def audit_rows(self, limit: int = 300) -> dict[str, list[dict[str, Any]]]:
        connection = self._connect()
        try:
            output: dict[str, list[dict[str, Any]]] = {
                "classification": [],
                "projection": [],
            }
            if table_exists(connection, OVERRIDE_TABLE):
                output["classification"] = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT child_id,canonical_name,
                               original_entity_type,
                               corrected_entity_type,actor,
                               created_at,status
                        FROM {OVERRIDE_TABLE}
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                ]
            if table_exists(connection, PROJECTION_AUDIT_TABLE):
                output["projection"] = [
                    dict(row)
                    for row in connection.execute(
                        f"""
                        SELECT child_id,event,actor,event_at
                        FROM {PROJECTION_AUDIT_TABLE}
                        ORDER BY event_at DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
                ]
            return output
        finally:
            connection.close()


def build_service(project_root: Path) -> MeitYUnifiedWorkflowService:
    paths = UnifiedMeitYPaths.defaults(project_root)
    config = json.loads(
        paths.config_path.read_text(encoding="utf-8-sig")
    )
    return MeitYUnifiedWorkflowService(paths, config)
