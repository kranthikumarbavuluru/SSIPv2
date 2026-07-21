from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.7"
OVERRIDE_TABLE = "meity_entity_classification_overrides_v3_4_3_8_0_7"
AUDIT_TABLE = "meity_entity_classification_write_audit_v3_4_3_8_0_7"


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


def contains_any(text: str, markers: Iterable[str]) -> list[str]:
    lowered = clean(text).casefold()
    return [marker for marker in markers if clean(marker).casefold() in lowered]


def classification_family(entity_type: str) -> str:
    value = clean(entity_type)
    if value in {
        "PERMANENT_PROGRAMME",
        "ACCELERATOR_PROGRAMME",
        "GRANT_PROGRAMME",
        "INCUBATION_PROGRAMME",
        "ECOSYSTEM_PROGRAMME",
        "IMPLEMENTATION_PROGRAMME",
    }:
        return "PERMANENT_PROGRAMME"
    if value == "PERMANENT_SCHEME":
        return "PERMANENT_SCHEME"
    if value in {
        "CHALLENGE_CALL",
        "GRAND_CHALLENGE",
        "HACKATHON",
    }:
        return "CHALLENGE_CALL"
    if value in {
        "APPLICATION_CALL",
        "EOI",
        "RFP",
        "IMPLEMENTATION_PARTNER_CALL",
    }:
        return "APPLICATION_CALL"
    if value == "ACCELERATOR_COHORT":
        return "ACCELERATOR_COHORT"
    if value in {
        "HISTORICAL_REFERENCE",
        "RESULT_ANNOUNCEMENT",
        "SUPPORTING_DOCUMENT",
        "INVALID_NON_CATALOGUE",
    }:
        return value
    return value


def effective_source_text(child: dict[str, Any]) -> str:
    return clean(
        " ".join(
            [
                clean(child.get("canonical_name")),
                clean(child.get("original_canonical_name")),
                clean(child.get("entity_type")),
                clean(child.get("verified_information_title")),
                clean(child.get("verified_information_role")),
                clean(child.get("status_evidence")),
                clean(child.get("evidence_excerpt")),
                clean(child.get("temporal_validation")),
                clean(child.get("safe_application_status")),
            ]
        )
    )


def transparent_classification(
    child: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    text = effective_source_text(child)
    entity_type = clean(child.get("entity_type"))
    temporal = clean(child.get("temporal_validation"))
    info_role = clean(child.get("verified_information_role"))
    application_url = clean(child.get("verified_application_url"))
    closing_date = clean(child.get("closing_date"))

    programme_markers = contains_any(
        text, config.get("programme_title_markers", [])
    )
    call_markers = contains_any(
        text, config.get("call_title_markers", [])
    )
    challenge_markers = contains_any(
        text, config.get("challenge_title_markers", [])
    )
    historical_markers = contains_any(
        text, config.get("historical_markers", [])
    )

    reasons: list[dict[str, Any]] = []
    suggested = ""
    confidence = 0.0

    def add(passed: bool, code: str, label: str) -> None:
        reasons.append(
            {
                "passed": bool(passed),
                "code": code,
                "label": label,
            }
        )

    if temporal == "HISTORICAL_BY_TITLE_OR_DEADLINE":
        suggested = "HISTORICAL_REFERENCE"
        confidence = 0.95
        add(True, "TEMPORAL_HISTORICAL", "Past year or deadline evidence was found")
        add(not bool(application_url), "NO_CURRENT_APPLY", "No verified current Apply route")
    elif "RESULT" in entity_type or info_role == "RESULT_NOTICE":
        suggested = "RESULT_ANNOUNCEMENT"
        confidence = 0.92
        add(True, "RESULT_ROLE", "The page is a result or selection announcement")
        add(not bool(application_url), "NO_CURRENT_APPLY", "No verified current Apply route")
    elif entity_type in {
        "PERMANENT_PROGRAMME",
        "ACCELERATOR_PROGRAMME",
        "GRANT_PROGRAMME",
        "INCUBATION_PROGRAMME",
        "ECOSYSTEM_PROGRAMME",
        "IMPLEMENTATION_PROGRAMME",
    }:
        suggested = "PERMANENT_PROGRAMME"
        confidence = 0.86
        add(True, "UPSTREAM_PROGRAMME_TYPE", "The upstream identity is a programme")
        add(bool(programme_markers), "PROGRAMME_MARKERS", "Programme or scheme markers appear in the title or page")
        add(not bool(closing_date), "NO_CALL_DEADLINE", "No call closing date is proven")
        add(not bool(application_url), "NO_CURRENT_APPLY", "No verified current Apply route")
    elif entity_type == "PERMANENT_SCHEME":
        suggested = "PERMANENT_SCHEME"
        confidence = 0.88
        add(True, "UPSTREAM_SCHEME_TYPE", "The upstream identity is a permanent scheme")
        add(bool(programme_markers), "SCHEME_MARKERS", "Scheme or programme markers appear")
        add(not bool(closing_date), "NO_CALL_DEADLINE", "No call closing date is proven")
    elif entity_type in {"CHALLENGE_CALL", "GRAND_CHALLENGE", "HACKATHON"} or challenge_markers:
        suggested = "CHALLENGE_CALL"
        confidence = 0.9 if challenge_markers else 0.78
        add(bool(challenge_markers), "CHALLENGE_MARKERS", "Challenge, grand challenge or hackathon wording was found")
        add(bool(closing_date), "DEADLINE_PRESENT", "A closing date is present")
        add(bool(application_url), "APPLY_ROUTE_VERIFIED", "A verified application route is present")
    elif entity_type in {"ACCELERATOR_COHORT"} or "cohort" in [m.casefold() for m in call_markers]:
        suggested = "ACCELERATOR_COHORT"
        confidence = 0.84
        add(True, "COHORT_MARKER", "A cohort or application-window identity was found")
        add(bool(closing_date), "DEADLINE_PRESENT", "A closing date is present")
        add(bool(application_url), "APPLY_ROUTE_VERIFIED", "A verified application route is present")
    elif entity_type in {
        "APPLICATION_CALL",
        "EOI",
        "RFP",
        "IMPLEMENTATION_PARTNER_CALL",
    } or call_markers:
        suggested = "APPLICATION_CALL"
        confidence = 0.86 if call_markers else 0.75
        add(bool(call_markers), "CALL_MARKERS", "Applications-invited, EOI, RFP or cohort wording was found")
        add(bool(closing_date), "DEADLINE_PRESENT", "A closing date is present")
        add(bool(application_url), "APPLY_ROUTE_VERIFIED", "A verified application route is present")
    elif info_role in {"GUIDELINE_DOCUMENT", "SUPPORTING_DOCUMENT"}:
        suggested = "SUPPORTING_DOCUMENT"
        confidence = 0.9
        add(True, "SUPPORTING_ROLE", "The verified page role is supporting evidence")
        add(not bool(application_url), "NO_CURRENT_APPLY", "No verified current Apply route")
    elif historical_markers:
        suggested = "HISTORICAL_REFERENCE"
        confidence = 0.7
        add(True, "HISTORICAL_MARKERS", "Past-year or result wording was found")
        add(not bool(application_url), "NO_CURRENT_APPLY", "No verified current Apply route")
    else:
        suggested = "SUPPORTING_DOCUMENT"
        confidence = 0.45
        add(False, "IDENTITY_NOT_PROVEN", "A permanent scheme, call or historical identity was not proven")
        add(bool(clean(child.get("verified_information_url"))), "OFFICIAL_SOURCE", "An official source was verified")

    labels = config.get("entity_type_labels", {})
    return {
        "suggested_entity_type": suggested,
        "suggested_label": labels.get(suggested, suggested),
        "classification_confidence": round(confidence, 2),
        "classification_reasons": reasons,
        "positive_reason_count": sum(1 for row in reasons if row["passed"]),
        "negative_reason_count": sum(1 for row in reasons if not row["passed"]),
        "programme_markers": ";".join(programme_markers),
        "call_markers": ";".join(call_markers),
        "challenge_markers": ";".join(challenge_markers),
        "historical_markers": ";".join(historical_markers),
    }


@dataclass(frozen=True)
class ClassificationPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    config_path: Path
    database_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "ClassificationPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0_4",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_7",
            config_path=root / "config/meity_transparent_classification_v3_4_3_8_0_7.json",
            database_path=root / "database/ssip_staging_v1.db",
        )


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_children(paths: ClassificationPaths) -> list[dict[str, str]]:
    return read_csv(
        paths.source_dir
        / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
    )


def load_bundles(paths: ClassificationPaths) -> list[dict[str, str]]:
    return read_csv(
        paths.source_dir
        / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
    )


def build_transparent_inventory(
    paths: ClassificationPaths,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    bundles = {
        clean(row.get("bundle_id")): row
        for row in load_bundles(paths)
    }
    rows: list[dict[str, Any]] = []
    for child in load_children(paths):
        explanation = transparent_classification(child, config)
        bundle = bundles.get(clean(child.get("bundle_id")), {})
        rows.append(
            {
                **child,
                **explanation,
                "bundle_title": clean(bundle.get("bundle_title")),
                "link_integrity_signature": clean(
                    bundle.get("link_integrity_signature")
                ),
                "safe_positive_decision_allowed": clean(
                    bundle.get("safe_positive_decision_allowed")
                ),
            }
        )
    return rows


def ensure_write_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OVERRIDE_TABLE} (
            action_id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL,
            child_id TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            original_entity_type TEXT NOT NULL,
            corrected_entity_type TEXT NOT NULL,
            corrected_record_kind TEXT NOT NULL,
            original_parent_scheme_name TEXT,
            corrected_parent_scheme_name TEXT,
            original_parent_master_id TEXT,
            corrected_parent_master_id TEXT,
            correction_reason TEXT NOT NULL,
            admin_note TEXT NOT NULL,
            actor TEXT NOT NULL,
            source_link_integrity_signature TEXT NOT NULL,
            source_manifest_signature TEXT NOT NULL,
            created_at TEXT NOT NULL,
            supersedes_action_id TEXT,
            is_active INTEGER NOT NULL CHECK (is_active IN (0,1)),
            publication_action TEXT NOT NULL CHECK (publication_action = 'NONE'),
            status TEXT NOT NULL CHECK (
                status IN ('ACTIVE_OVERRIDE','SUPERSEDED')
            )
        )
        """
    )
    connection.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS
        ux_{OVERRIDE_TABLE}_active_child
        ON {OVERRIDE_TABLE}(child_id)
        WHERE is_active = 1
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
            audit_id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL,
            child_id TEXT NOT NULL,
            event TEXT NOT NULL CHECK (
                event IN ('CLASSIFICATION_OVERRIDE_WRITTEN',
                          'CLASSIFICATION_OVERRIDE_SUPERSEDED')
            ),
            actor TEXT NOT NULL,
            event_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )


def core_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    counts: dict[str, int] = {}
    for name in (
        "scheme_staging",
        "admin_review_queue",
        "public_schemes",
        "publication_audit",
    ):
        if name in names:
            counts[name] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            )
    return counts


def create_consistent_backup(database_path: Path, backup_root: Path) -> Path:
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


def action_id(payload: dict[str, Any]) -> str:
    return "meityclass_" + hashlib.sha256(
        stable_json(payload).encode("utf-8")
    ).hexdigest()[:24]


class ClassificationWriteGate:
    def __init__(
        self,
        paths: ClassificationPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config

    def _manifest(self) -> dict[str, Any]:
        path = (
            self.paths.source_dir
            / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        )
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def inventory(self) -> list[dict[str, Any]]:
        return build_transparent_inventory(self.paths, self.config)

    def active_overrides(self) -> dict[str, dict[str, Any]]:
        if not self.paths.database_path.exists():
            return {}
        connection = sqlite3.connect(self.paths.database_path)
        connection.row_factory = sqlite3.Row
        try:
            ensure_write_schema(connection)
            rows = connection.execute(
                f"""
                SELECT * FROM {OVERRIDE_TABLE}
                WHERE is_active = 1
                ORDER BY created_at DESC
                """
            ).fetchall()
            return {row["child_id"]: dict(row) for row in rows}
        finally:
            connection.close()

    def preview(
        self,
        child_id: str,
        corrected_entity_type: str,
        corrected_parent_scheme_name: str,
        corrected_parent_master_id: str,
        admin_note: str,
        actor: str,
    ) -> dict[str, Any]:
        allowed = set(self.config.get("allowed_entity_types", []))
        if corrected_entity_type not in allowed:
            raise ValueError("Unsupported corrected entity type.")

        inventory = {
            clean(row.get("child_id")): row for row in self.inventory()
        }
        child = inventory.get(clean(child_id))
        if child is None:
            raise ValueError("Unknown MeitY child record.")

        original_type = clean(child.get("entity_type"))
        semantic_change = (
            classification_family(corrected_entity_type)
            != classification_family(original_type)
        )
        if semantic_change and not clean(admin_note):
            raise ValueError(
                "An Admin note is required when changing the entity type."
            )

        if corrected_entity_type in {
            "PERMANENT_PROGRAMME",
            "PERMANENT_SCHEME",
            "HISTORICAL_REFERENCE",
            "RESULT_ANNOUNCEMENT",
            "SUPPORTING_DOCUMENT",
            "INVALID_NON_CATALOGUE",
        }:
            corrected_parent_scheme_name = ""
            corrected_parent_master_id = ""

        record_kind = clean(
            self.config.get("record_kind_map", {}).get(
                corrected_entity_type
            )
        )
        manifest = self._manifest()

        payload = {
            "version": VERSION,
            "bundle_id": clean(child.get("bundle_id")),
            "child_id": clean(child.get("child_id")),
            "canonical_name": clean(child.get("canonical_name")),
            "original_entity_type": original_type,
            "corrected_entity_type": corrected_entity_type,
            "corrected_record_kind": record_kind,
            "original_parent_scheme_name": clean(
                child.get("repaired_parent_scheme_name")
            ),
            "corrected_parent_scheme_name": clean(
                corrected_parent_scheme_name
            ),
            "original_parent_master_id": clean(
                child.get("repaired_parent_master_id")
            ),
            "corrected_parent_master_id": clean(
                corrected_parent_master_id
            ),
            "correction_reason": (
                "ADMIN_TYPE_CORRECTION"
                if semantic_change
                else "ADMIN_TYPE_CONFIRMATION"
            ),
            "admin_note": clean(admin_note),
            "actor": clean(actor) or "Admin",
            "source_link_integrity_signature": clean(
                child.get("link_integrity_signature")
            ),
            "source_manifest_signature": clean(
                manifest.get("link_integrity_signature")
            ),
            "publication_action": "NONE",
        }
        payload["action_id"] = action_id(payload)
        payload["write_confirmation_required"] = clean(
            self.config.get("confirmation_phrase")
        )
        payload["database_write_scope"] = (
            f"{OVERRIDE_TABLE},{AUDIT_TABLE}"
        )
        payload["publication_write_scope"] = "NONE"
        return payload

    def apply(
        self,
        preview_payload: dict[str, Any],
        confirmation: str,
    ) -> dict[str, Any]:
        expected = clean(self.config.get("confirmation_phrase"))
        if clean(confirmation) != expected:
            raise PermissionError(
                f'Exact confirmation required: "{expected}"'
            )

        current_preview = self.preview(
            child_id=clean(preview_payload.get("child_id")),
            corrected_entity_type=clean(
                preview_payload.get("corrected_entity_type")
            ),
            corrected_parent_scheme_name=clean(
                preview_payload.get("corrected_parent_scheme_name")
            ),
            corrected_parent_master_id=clean(
                preview_payload.get("corrected_parent_master_id")
            ),
            admin_note=clean(preview_payload.get("admin_note")),
            actor=clean(preview_payload.get("actor")),
        )
        if current_preview["action_id"] != clean(
            preview_payload.get("action_id")
        ):
            raise RuntimeError(
                "The classification plan changed after review."
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_root = (
            self.paths.project_root.parent
            / f"SSIP_DB_Backup_v3_4_3_8_0_7_{timestamp}"
        )
        backup_path = create_consistent_backup(
            self.paths.database_path,
            backup_root,
        )

        connection = sqlite3.connect(self.paths.database_path)
        connection.row_factory = sqlite3.Row
        try:
            ensure_write_schema(connection)
            before_counts = core_table_counts(connection)
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                f"""
                SELECT action_id FROM {OVERRIDE_TABLE}
                WHERE child_id = ? AND is_active = 1
                """,
                (current_preview["child_id"],),
            ).fetchone()
            supersedes = existing["action_id"] if existing else ""

            if existing:
                connection.execute(
                    f"""
                    UPDATE {OVERRIDE_TABLE}
                    SET is_active = 0, status = 'SUPERSEDED'
                    WHERE action_id = ?
                    """,
                    (supersedes,),
                )
                audit_payload = {
                    "superseded_action_id": supersedes,
                    "new_action_id": current_preview["action_id"],
                }
                connection.execute(
                    f"""
                    INSERT INTO {AUDIT_TABLE} (
                        audit_id, action_id, child_id, event,
                        actor, event_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "audit_" + hashlib.sha256(
                            stable_json(audit_payload).encode("utf-8")
                        ).hexdigest()[:24],
                        supersedes,
                        current_preview["child_id"],
                        "CLASSIFICATION_OVERRIDE_SUPERSEDED",
                        current_preview["actor"],
                        utc_now(),
                        stable_json(audit_payload),
                    ),
                )

            created_at = utc_now()
            connection.execute(
                f"""
                INSERT INTO {OVERRIDE_TABLE} (
                    action_id, bundle_id, child_id, canonical_name,
                    original_entity_type, corrected_entity_type,
                    corrected_record_kind, original_parent_scheme_name,
                    corrected_parent_scheme_name, original_parent_master_id,
                    corrected_parent_master_id, correction_reason,
                    admin_note, actor, source_link_integrity_signature,
                    source_manifest_signature, created_at,
                    supersedes_action_id, is_active,
                    publication_action, status
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE_OVERRIDE'
                )
                """,
                (
                    current_preview["action_id"],
                    current_preview["bundle_id"],
                    current_preview["child_id"],
                    current_preview["canonical_name"],
                    current_preview["original_entity_type"],
                    current_preview["corrected_entity_type"],
                    current_preview["corrected_record_kind"],
                    current_preview["original_parent_scheme_name"],
                    current_preview["corrected_parent_scheme_name"],
                    current_preview["original_parent_master_id"],
                    current_preview["corrected_parent_master_id"],
                    current_preview["correction_reason"],
                    current_preview["admin_note"],
                    current_preview["actor"],
                    current_preview["source_link_integrity_signature"],
                    current_preview["source_manifest_signature"],
                    created_at,
                    supersedes,
                    1,
                    "NONE",
                ),
            )
            audit_payload = {
                **current_preview,
                "backup_path": str(backup_path),
                "created_at": created_at,
            }
            connection.execute(
                f"""
                INSERT INTO {AUDIT_TABLE} (
                    audit_id, action_id, child_id, event,
                    actor, event_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "audit_" + hashlib.sha256(
                        stable_json(audit_payload).encode("utf-8")
                    ).hexdigest()[:24],
                    current_preview["action_id"],
                    current_preview["child_id"],
                    "CLASSIFICATION_OVERRIDE_WRITTEN",
                    current_preview["actor"],
                    created_at,
                    stable_json(audit_payload),
                ),
            )

            after_counts = core_table_counts(connection)
            if before_counts != after_counts:
                raise RuntimeError(
                    "A core staging, review or publication table count changed."
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            **current_preview,
            "written": True,
            "backup_path": str(backup_path),
            "core_table_counts_preserved": True,
            "publication_action": "NONE",
            "public_visibility_changed": False,
            "created_at": created_at,
        }


def build_service(project_root: Path) -> ClassificationWriteGate:
    paths = ClassificationPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return ClassificationWriteGate(paths, config)
