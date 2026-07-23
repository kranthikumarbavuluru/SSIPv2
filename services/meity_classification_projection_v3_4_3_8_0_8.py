from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.8"
OVERRIDE_TABLE = "meity_entity_classification_overrides_v3_4_3_8_0_7"


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


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=field_list,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_list})


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type IN ('table','view') AND name = ?
            """,
            (name,),
        ).fetchone()
        is not None
    )


def core_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in (
        "scheme_staging",
        "admin_review_queue",
        "public_schemes",
        "publication_audit",
    ):
        if table_exists(connection, name):
            counts[name] = int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{name}"'
                ).fetchone()[0]
            )
    return counts


def create_consistent_backup(
    database_path: Path,
    backup_root: Path,
) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / database_path.name
    source = sqlite3.connect(database_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    return backup_path


@dataclass(frozen=True)
class ProjectionPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "ProjectionPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_4",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_8",
            config_path=(
                root
                / "config/meity_classification_projection_v3_4_3_8_0_8.json"
            ),
            database_path=root / "database/ssip_staging_v1.db",
        )


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ClassificationProjectionService:
    def __init__(
        self,
        paths: ProjectionPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config

    def _load_manifest(self) -> dict[str, Any]:
        path = (
            self.paths.source_dir
            / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        )
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _load_children(self) -> list[dict[str, str]]:
        return read_csv(
            self.paths.source_dir
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
        )

    def _load_bundles(self) -> dict[str, dict[str, str]]:
        return {
            clean(row.get("bundle_id")): row
            for row in read_csv(
                self.paths.source_dir
                / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
            )
            if clean(row.get("bundle_id"))
        }

    def _active_overrides(self) -> dict[str, dict[str, Any]]:
        if not self.paths.database_path.exists():
            return {}
        connection = sqlite3.connect(self.paths.database_path)
        connection.row_factory = sqlite3.Row
        try:
            if not table_exists(connection, OVERRIDE_TABLE):
                return {}
            rows = connection.execute(
                f"""
                SELECT *
                FROM {OVERRIDE_TABLE}
                WHERE is_active = 1
                ORDER BY created_at DESC
                """
            ).fetchall()
            return {row["child_id"]: dict(row) for row in rows}
        finally:
            connection.close()

    def effective_inventory(self) -> list[dict[str, Any]]:
        bundles = self._load_bundles()
        overrides = self._active_overrides()
        rows: list[dict[str, Any]] = []

        for child in self._load_children():
            child_id = clean(child.get("child_id"))
            bundle = bundles.get(clean(child.get("bundle_id")), {})
            override = overrides.get(child_id)

            effective_type = clean(
                override.get("corrected_entity_type")
                if override
                else child.get("entity_type")
            )
            effective_record_kind = clean(
                override.get("corrected_record_kind")
                if override
                else child.get("record_kind")
            )
            effective_parent_name = clean(
                override.get("corrected_parent_scheme_name")
                if override
                else child.get("repaired_parent_scheme_name")
            )
            effective_parent_id = clean(
                override.get("corrected_parent_master_id")
                if override
                else child.get("repaired_parent_master_id")
            )

            programme_types = set(
                self.config.get("programme_entity_types", [])
            )
            call_types = set(self.config.get("call_entity_types", []))
            historical_types = set(
                self.config.get("historical_entity_types", [])
            )
            excluded_types = set(
                self.config.get("excluded_entity_types", [])
            )

            if effective_type in programme_types:
                section = "PROGRAMMES"
            elif effective_type in call_types:
                section = "CALLS_CHALLENGES"
            elif effective_type in historical_types:
                section = "HISTORICAL"
            elif effective_type in excluded_types:
                section = "EXCLUDED_SUPPORTING"
            else:
                section = "CLASSIFICATION_REVIEW"

            temporal = clean(child.get("temporal_validation"))
            application_complete = truthy(
                bundle.get(
                    "current_application_integrity_complete",
                    ""
                )
            )
            link_complete = truthy(
                bundle.get("link_integrity_complete", "")
            )
            information_url = clean(
                child.get("verified_information_url")
            )
            application_url = clean(
                child.get("verified_application_url")
            )

            projection_errors: list[str] = []
            projection_warnings: list[str] = []

            if effective_type not in set(
                self.config.get("catalogue_entity_types", [])
            ):
                projection_errors.append(
                    "NON_CATALOGUE_OR_SUPPORTING_CLASSIFICATION"
                )

            if not information_url:
                projection_errors.append(
                    "VERIFIED_INFORMATION_SOURCE_REQUIRED"
                )

            if effective_type in call_types:
                if not effective_parent_id:
                    projection_errors.append(
                        "CALL_PARENT_PROGRAMME_REQUIRED"
                    )
                if temporal == clean(
                    self.config.get(
                        "current_call_temporal_state",
                        "CURRENT_STATUS_EVIDENCE_COMPLETE",
                    )
                ):
                    if not application_complete or not application_url:
                        projection_errors.append(
                            "CURRENT_APPLICATION_INTEGRITY_REQUIRED"
                        )
                else:
                    projection_warnings.append(
                        "CALL_IDENTITY_RETAINED_WITHOUT_CURRENT_OPEN_STATUS"
                    )

            if effective_type in historical_types and application_url:
                projection_errors.append(
                    "HISTORICAL_APPLICATION_ROUTE_NOT_ALLOWED"
                )

            if not link_complete:
                projection_warnings.append(
                    "LINK_INTEGRITY_NOT_COMPLETE"
                )

            projection_eligible = not projection_errors
            projection_status = (
                "ELIGIBLE"
                if projection_eligible
                else "BLOCKED"
            )

            rows.append(
                {
                    **child,
                    "bundle_title": clean(
                        bundle.get("bundle_title")
                    ),
                    "override_applied": bool(override),
                    "override_action_id": clean(
                        override.get("action_id") if override else ""
                    ),
                    "override_written_at": clean(
                        override.get("created_at") if override else ""
                    ),
                    "original_entity_type": clean(
                        child.get("entity_type")
                    ),
                    "effective_entity_type": effective_type,
                    "effective_record_kind": effective_record_kind,
                    "effective_parent_scheme_name": effective_parent_name,
                    "effective_parent_master_id": effective_parent_id,
                    "dashboard_section": section,
                    "verified_information_url": information_url,
                    "verified_application_url": application_url,
                    "link_integrity_complete": link_complete,
                    "current_application_integrity_complete": (
                        application_complete
                    ),
                    "projection_status": projection_status,
                    "projection_eligible": projection_eligible,
                    "projection_errors": ";".join(projection_errors),
                    "projection_warnings": ";".join(
                        projection_warnings
                    ),
                    "publication_status": "NOT_PUBLISHED",
                    "public_visibility": False,
                    "apply_action_allowed": False,
                }
            )
        return rows

    def build_preview(self) -> dict[str, Any]:
        rows = self.effective_inventory()
        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        fields = list(
            dict.fromkeys(
                key
                for row in rows
                for key in row.keys()
            )
        )
        write_csv(
            output_dir
            / "meity_effective_dashboard_preview_v3_4_3_8_0_8.csv",
            rows,
            fields,
        )
        write_csv(
            output_dir
            / "meity_staging_projection_eligible_v3_4_3_8_0_8.csv",
            [
                row
                for row in rows
                if truthy(row.get("projection_eligible"))
            ],
            fields,
        )
        write_csv(
            output_dir
            / "meity_staging_projection_blocked_v3_4_3_8_0_8.csv",
            [
                row
                for row in rows
                if not truthy(row.get("projection_eligible"))
            ],
            fields,
        )

        section_counts = Counter(
            row["dashboard_section"] for row in rows
        )
        effective_counts = Counter(
            row["effective_entity_type"] for row in rows
        )
        override_count = sum(
            1 for row in rows if truthy(row.get("override_applied"))
        )
        corrected_count = sum(
            1
            for row in rows
            if row["override_applied"]
            and row["effective_entity_type"]
            != row["original_entity_type"]
        )
        eligible_count = sum(
            1
            for row in rows
            if truthy(row.get("projection_eligible"))
        )
        blocked_count = len(rows) - eligible_count

        manifest = self._load_manifest()
        summary = {
            "version": VERSION,
            "generated_at": utc_now(),
            "record_count": len(rows),
            "override_count": override_count,
            "type_correction_count": corrected_count,
            "programme_count": section_counts.get("PROGRAMMES", 0),
            "call_challenge_count": section_counts.get(
                "CALLS_CHALLENGES",
                0,
            ),
            "historical_count": section_counts.get(
                "HISTORICAL",
                0,
            ),
            "excluded_supporting_count": section_counts.get(
                "EXCLUDED_SUPPORTING",
                0,
            ),
            "classification_review_count": section_counts.get(
                "CLASSIFICATION_REVIEW",
                0,
            ),
            "projection_eligible_count": eligible_count,
            "projection_blocked_count": blocked_count,
            "effective_entity_type_counts": dict(
                sorted(effective_counts.items())
            ),
            "source_link_integrity_signature": clean(
                manifest.get("link_integrity_signature")
            ),
            "database_write_performed": False,
            "publication_performed": False,
            "public_visibility_changed": False,
            "apply_action_allowed_count": 0,
        }
        signature_payload = {
            "summary": summary,
            "rows": rows,
        }
        summary["projection_signature"] = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()

        (
            output_dir
            / "meity_classification_projection_manifest_v3_4_3_8_0_8.json"
        ).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        (
            output_dir
            / "meity_signed_staging_projection_plan_v3_4_3_8_0_8.json"
        ).write_text(
            json.dumps(
                {
                    "summary": summary,
                    "eligible_rows": [
                        row
                        for row in rows
                        if truthy(row.get("projection_eligible"))
                    ],
                    "blocked_rows": [
                        row
                        for row in rows
                        if not truthy(row.get("projection_eligible"))
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return summary

    def _ensure_projection_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        table = clean(self.config.get("projection_table"))
        audit_table = clean(
            self.config.get("projection_audit_table")
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                projection_id TEXT PRIMARY KEY,
                projection_signature TEXT NOT NULL,
                child_id TEXT NOT NULL,
                bundle_id TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                effective_entity_type TEXT NOT NULL,
                effective_record_kind TEXT,
                effective_parent_scheme_name TEXT,
                effective_parent_master_id TEXT,
                verified_information_url TEXT NOT NULL,
                verified_application_url TEXT,
                temporal_validation TEXT,
                projection_status TEXT NOT NULL CHECK (
                    projection_status IN ('ACTIVE','SUPERSEDED')
                ),
                is_active INTEGER NOT NULL CHECK (is_active IN (0,1)),
                source_override_action_id TEXT,
                source_link_integrity_signature TEXT NOT NULL,
                created_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                publication_action TEXT NOT NULL CHECK (
                    publication_action = 'NONE'
                ),
                public_visibility INTEGER NOT NULL CHECK (
                    public_visibility = 0
                )
            )
            """
        )
        connection.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS
            ux_{table}_active_child
            ON {table}(child_id)
            WHERE is_active = 1
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {audit_table} (
                audit_id TEXT PRIMARY KEY,
                projection_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK (
                    event IN (
                        'STAGING_PROJECTION_WRITTEN',
                        'STAGING_PROJECTION_SUPERSEDED'
                    )
                ),
                actor TEXT NOT NULL,
                event_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )

    def apply_projection(
        self,
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

        summary = self.build_preview()
        if clean(expected_signature) != clean(
            summary.get("projection_signature")
        ):
            raise RuntimeError(
                "The staging projection plan changed after review."
            )

        rows = [
            row
            for row in self.effective_inventory()
            if truthy(row.get("projection_eligible"))
        ]
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%d_%H%M%S"
        )
        backup_root = (
            self.paths.project_root.parent
            / f"SSIP_DB_Backup_v3_4_3_8_0_8_{timestamp}"
        )
        backup_path = create_consistent_backup(
            self.paths.database_path,
            backup_root,
        )

        table = clean(self.config.get("projection_table"))
        audit_table = clean(
            self.config.get("projection_audit_table")
        )
        actor_value = clean(actor) or "Admin"

        connection = sqlite3.connect(self.paths.database_path)
        connection.row_factory = sqlite3.Row
        written = 0
        superseded = 0
        try:
            before_counts = core_table_counts(connection)
            self._ensure_projection_schema(connection)
            connection.execute("BEGIN IMMEDIATE")

            for row in rows:
                child_id = clean(row.get("child_id"))
                existing = connection.execute(
                    f"""
                    SELECT projection_id
                    FROM {table}
                    WHERE child_id = ? AND is_active = 1
                    """,
                    (child_id,),
                ).fetchone()

                projection_payload = {
                    "projection_signature": summary[
                        "projection_signature"
                    ],
                    "child_id": child_id,
                    "bundle_id": clean(row.get("bundle_id")),
                    "canonical_name": clean(
                        row.get("canonical_name")
                    ),
                    "effective_entity_type": clean(
                        row.get("effective_entity_type")
                    ),
                    "effective_record_kind": clean(
                        row.get("effective_record_kind")
                    ),
                    "effective_parent_scheme_name": clean(
                        row.get(
                            "effective_parent_scheme_name"
                        )
                    ),
                    "effective_parent_master_id": clean(
                        row.get(
                            "effective_parent_master_id"
                        )
                    ),
                    "verified_information_url": clean(
                        row.get("verified_information_url")
                    ),
                    "verified_application_url": clean(
                        row.get("verified_application_url")
                    ),
                    "temporal_validation": clean(
                        row.get("temporal_validation")
                    ),
                    "source_override_action_id": clean(
                        row.get("override_action_id")
                    ),
                    "source_link_integrity_signature": clean(
                        summary.get(
                            "source_link_integrity_signature"
                        )
                    ),
                    "actor": actor_value,
                }
                projection_id = (
                    "meityprojection_"
                    + hashlib.sha256(
                        stable_json(
                            projection_payload
                        ).encode("utf-8")
                    ).hexdigest()[:24]
                )

                if existing:
                    if existing["projection_id"] == projection_id:
                        continue
                    connection.execute(
                        f"""
                        UPDATE {table}
                        SET is_active = 0,
                            projection_status = 'SUPERSEDED'
                        WHERE projection_id = ?
                        """,
                        (existing["projection_id"],),
                    )
                    audit_payload = {
                        "old_projection_id": existing[
                            "projection_id"
                        ],
                        "new_projection_id": projection_id,
                    }
                    connection.execute(
                        f"""
                        INSERT INTO {audit_table} (
                            audit_id, projection_id, child_id,
                            event, actor, event_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "audit_"
                            + hashlib.sha256(
                                stable_json(
                                    audit_payload
                                ).encode("utf-8")
                            ).hexdigest()[:24],
                            existing["projection_id"],
                            child_id,
                            "STAGING_PROJECTION_SUPERSEDED",
                            actor_value,
                            utc_now(),
                            stable_json(audit_payload),
                        ),
                    )
                    superseded += 1

                created_at = utc_now()
                connection.execute(
                    f"""
                    INSERT OR IGNORE INTO {table} (
                        projection_id, projection_signature,
                        child_id, bundle_id, canonical_name,
                        effective_entity_type, effective_record_kind,
                        effective_parent_scheme_name,
                        effective_parent_master_id,
                        verified_information_url,
                        verified_application_url,
                        temporal_validation, projection_status,
                        is_active, source_override_action_id,
                        source_link_integrity_signature,
                        created_at, actor, publication_action,
                        public_visibility
                    ) VALUES (
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'NONE',0
                    )
                    """,
                    (
                        projection_id,
                        summary["projection_signature"],
                        child_id,
                        clean(row.get("bundle_id")),
                        clean(row.get("canonical_name")),
                        clean(
                            row.get("effective_entity_type")
                        ),
                        clean(
                            row.get("effective_record_kind")
                        ),
                        clean(
                            row.get(
                                "effective_parent_scheme_name"
                            )
                        ),
                        clean(
                            row.get(
                                "effective_parent_master_id"
                            )
                        ),
                        clean(
                            row.get(
                                "verified_information_url"
                            )
                        ),
                        clean(
                            row.get(
                                "verified_application_url"
                            )
                        ),
                        clean(row.get("temporal_validation")),
                        "ACTIVE",
                        1,
                        clean(row.get("override_action_id")),
                        summary[
                            "source_link_integrity_signature"
                        ],
                        created_at,
                        actor_value,
                    ),
                )
                if connection.total_changes:
                    audit_payload = {
                        **projection_payload,
                        "projection_id": projection_id,
                        "created_at": created_at,
                        "backup_path": str(backup_path),
                    }
                    connection.execute(
                        f"""
                        INSERT OR IGNORE INTO {audit_table} (
                            audit_id, projection_id, child_id,
                            event, actor, event_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "audit_"
                            + hashlib.sha256(
                                stable_json(
                                    audit_payload
                                ).encode("utf-8")
                            ).hexdigest()[:24],
                            projection_id,
                            child_id,
                            "STAGING_PROJECTION_WRITTEN",
                            actor_value,
                            created_at,
                            stable_json(audit_payload),
                        ),
                    )
                    written += 1

            after_counts = core_table_counts(connection)
            if before_counts != after_counts:
                raise RuntimeError(
                    "Core staging, review or publication table "
                    "counts changed."
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "version": VERSION,
            "projection_signature": summary[
                "projection_signature"
            ],
            "eligible_projection_rows": len(rows),
            "written_projection_rows": written,
            "superseded_projection_rows": superseded,
            "backup_path": str(backup_path),
            "core_table_counts_preserved": True,
            "database_write_scope": table,
            "publication_action": "NONE",
            "public_visibility_changed": False,
            "scheme_staging_modified": False,
            "admin_review_queue_modified": False,
            "public_schemes_modified": False,
        }


def build_service(
    project_root: Path,
) -> ClassificationProjectionService:
    paths = ProjectionPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return ClassificationProjectionService(paths, config)
