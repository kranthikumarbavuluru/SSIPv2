from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "3.4.3.7.4"
MINISTRY_LEVEL_LABEL = "Ministry-level programme"

MINISTRY_SCIENCE_TECH = "Ministry of Science and Technology"
MINISTRY_MEITY = "Ministry of Electronics and Information Technology (MeitY)"
MINISTRY_COMMERCE = "Ministry of Commerce and Industry"

DEPARTMENT_DST = "Department of Science and Technology (DST)"
DEPARTMENT_DPIIT = "Department for Promotion of Industry and Internal Trade (DPIIT)"
DEPARTMENT_DBT = "Department of Biotechnology (DBT)"


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _clean(value: Any) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text or None


MINISTRY_ALIASES = {
    _normalized("Ministry of Science and Technology"): MINISTRY_SCIENCE_TECH,
    _normalized("Ministry of Science & Technology"): MINISTRY_SCIENCE_TECH,
    _normalized("Ministry of Electronics and Information Technology"): MINISTRY_MEITY,
    _normalized("Ministry of Electronics and Information Technology (MeitY)"): MINISTRY_MEITY,
    _normalized("MeitY"): MINISTRY_MEITY,
    _normalized("Ministry of Commerce and Industry"): MINISTRY_COMMERCE,
    _normalized("Ministry of Commerce & Industry"): MINISTRY_COMMERCE,
}

DEPARTMENT_ALIASES = {
    _normalized("Department of Science and Technology"): DEPARTMENT_DST,
    _normalized("Department of Science and Technology (DST)"): DEPARTMENT_DST,
    _normalized("Department of Science ad Technology"): DEPARTMENT_DST,
    _normalized("DST"): DEPARTMENT_DST,
    _normalized("Department for Promotion of Industry and Internal Trade"): DEPARTMENT_DPIIT,
    _normalized("Department for Promotion of Industry and Internal Trade (DPIIT)"): DEPARTMENT_DPIIT,
    _normalized("DPIIT"): DEPARTMENT_DPIIT,
    _normalized("Department of Industrial Policy and Promotion"): DEPARTMENT_DPIIT,
    _normalized("Department of Biotechnology"): DEPARTMENT_DBT,
    _normalized("Department of Biotechnology (DBT)"): DEPARTMENT_DBT,
    _normalized("DBT"): DEPARTMENT_DBT,
}

MEITY_SOURCE_ALIASES = {
    _normalized("MeitY Startup Hub"),
    _normalized("Ministry of Electronics and Information Technology"),
    _normalized("Ministry of Electronics and Information Technology (MeitY)"),
}
DST_SOURCE_ALIASES = {
    _normalized("DST"),
    _normalized("Department of Science and Technology"),
    _normalized("Department of Science and Technology (DST)"),
}
DPIIT_SOURCE_ALIASES = {
    _normalized("DPIIT"),
    _normalized("Startup India"),
    _normalized("Department for Promotion of Industry and Internal Trade"),
}
DBT_SOURCE_ALIASES = {
    _normalized("DBT"),
    _normalized("BIRAC"),
    _normalized("Department of Biotechnology"),
}


def canonical_payload_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_tokens(record: dict[str, Any]) -> set[str]:
    return {
        _normalized(record.get("source")),
        _normalized(record.get("implementing_agency")),
        _normalized(record.get("implementing_entity")),
    } - {""}


def canonicalize_organization_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied record with conservative organization normalization."""
    output = copy.deepcopy(record)
    source_tokens = _source_tokens(output)

    ministry_raw = _clean(output.get("ministry"))
    department_raw = _clean(output.get("department"))
    ministry_key = _normalized(ministry_raw)
    department_key = _normalized(department_raw)

    ministry = MINISTRY_ALIASES.get(ministry_key, ministry_raw)
    department = DEPARTMENT_ALIASES.get(department_key, department_raw)

    meity_signal = (
        ministry == MINISTRY_MEITY
        or bool(source_tokens & MEITY_SOURCE_ALIASES)
        or department_key in {
            _normalized("Ministry of Electronics and Information Technology"),
            _normalized("Ministry of Electronics and Information Technology (MeitY)"),
            _normalized("MeitY"),
        }
    )
    dst_signal = department == DEPARTMENT_DST or bool(source_tokens & DST_SOURCE_ALIASES)
    dpiit_signal = department == DEPARTMENT_DPIIT or bool(source_tokens & DPIIT_SOURCE_ALIASES)
    dbt_signal = department == DEPARTMENT_DBT or bool(source_tokens & DBT_SOURCE_ALIASES)

    if meity_signal:
        ministry = MINISTRY_MEITY
        if department_key in {
            "",
            _normalized("Ministry of Electronics and Information Technology"),
            _normalized("Ministry of Electronics and Information Technology (MeitY)"),
            _normalized("MeitY"),
            _normalized(MINISTRY_LEVEL_LABEL),
        }:
            department = None
        output["organization_level"] = "MINISTRY"
    elif dst_signal:
        ministry = MINISTRY_SCIENCE_TECH
        department = DEPARTMENT_DST
        output["organization_level"] = "DEPARTMENT"
    elif dpiit_signal:
        ministry = MINISTRY_COMMERCE
        department = DEPARTMENT_DPIIT
        output["organization_level"] = "DEPARTMENT"
    elif dbt_signal:
        ministry = MINISTRY_SCIENCE_TECH
        department = DEPARTMENT_DBT
        output["organization_level"] = "DEPARTMENT"
    else:
        output.setdefault(
            "organization_level",
            "DEPARTMENT" if department else "MINISTRY" if ministry else "UNRESOLVED",
        )

    output["ministry"] = ministry
    output["department"] = department
    return output


@dataclass(frozen=True)
class CanonicalizationChange:
    table_name: str
    master_id: str
    scheme_name: str
    old_ministry: str | None
    new_ministry: str | None
    old_department: str | None
    new_department: str | None
    old_hash: str
    new_hash: str
    new_record: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "master_id": self.master_id,
            "scheme_name": self.scheme_name,
            "old_ministry": self.old_ministry,
            "new_ministry": self.new_ministry,
            "old_department": self.old_department,
            "new_department": self.new_department,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
        }


class OrganizationCanonicalizationService:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.exists():
            raise FileNotFoundError(f"SSIP database not found: {self.database_path}")

    @staticmethod
    def _connect_read_only(path: Path) -> sqlite3.Connection:
        uri = f"file:{path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return copy.deepcopy(value)
        if not value:
            return {}
        payload = json.loads(str(value))
        if not isinstance(payload, dict):
            raise ValueError("Operational organization payload must be a JSON object")
        return payload

    def _collect_changes(self, connection: sqlite3.Connection) -> list[CanonicalizationChange]:
        changes: list[CanonicalizationChange] = []

        admin_rows = connection.execute(
            """
            SELECT master_id,scheme_name,validated_record_json,record_hash
            FROM admin_review_queue
            ORDER BY master_id
            """
        ).fetchall()
        for row in admin_rows:
            before = self._parse_json(row["validated_record_json"])
            after = canonicalize_organization_record(before)
            if (
                _clean(before.get("ministry")) != _clean(after.get("ministry"))
                or _clean(before.get("department")) != _clean(after.get("department"))
                or before.get("organization_level") != after.get("organization_level")
            ):
                changes.append(
                    CanonicalizationChange(
                        table_name="admin_review_queue",
                        master_id=str(row["master_id"]),
                        scheme_name=str(row["scheme_name"] or ""),
                        old_ministry=_clean(before.get("ministry")),
                        new_ministry=_clean(after.get("ministry")),
                        old_department=_clean(before.get("department")),
                        new_department=_clean(after.get("department")),
                        old_hash=str(row["record_hash"] or ""),
                        new_hash=canonical_payload_hash(after),
                        new_record=after,
                    )
                )

        staging_rows = connection.execute(
            """
            SELECT master_id,scheme_name,ministry,department,raw_record_json,record_hash
            FROM scheme_staging
            ORDER BY master_id
            """
        ).fetchall()
        for row in staging_rows:
            before = self._parse_json(row["raw_record_json"])
            # The structured columns are authoritative fallbacks for older rows.
            if not _clean(before.get("ministry")):
                before["ministry"] = row["ministry"]
            if not _clean(before.get("department")):
                before["department"] = row["department"]
            after = canonicalize_organization_record(before)
            if (
                _clean(row["ministry"]) != _clean(after.get("ministry"))
                or _clean(row["department"]) != _clean(after.get("department"))
                or before.get("organization_level") != after.get("organization_level")
            ):
                changes.append(
                    CanonicalizationChange(
                        table_name="scheme_staging",
                        master_id=str(row["master_id"]),
                        scheme_name=str(row["scheme_name"] or ""),
                        old_ministry=_clean(row["ministry"]),
                        new_ministry=_clean(after.get("ministry")),
                        old_department=_clean(row["department"]),
                        new_department=_clean(after.get("department")),
                        old_hash=str(row["record_hash"] or ""),
                        new_hash=canonical_payload_hash(after),
                        new_record=after,
                    )
                )
        return changes

    @staticmethod
    def _signature(changes: list[CanonicalizationChange]) -> str:
        payload = json.dumps(
            [change.as_dict() for change in changes],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def plan(self) -> dict[str, Any]:
        connection = self._connect_read_only(self.database_path)
        try:
            changes = self._collect_changes(connection)
        finally:
            connection.close()

        table_counts: dict[str, int] = {}
        for change in changes:
            table_counts[change.table_name] = table_counts.get(change.table_name, 0) + 1

        report = {
            "version": VERSION,
            "database_path": str(self.database_path),
            "dry_run": True,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "change_count": len(changes),
            "table_counts": table_counts,
            "master_ids_preserved": True,
            "application_fields_modified": False,
            "publication_fields_modified": False,
            "audit_history_modified": False,
            "database_modified": False,
            "changes": [change.as_dict() for change in changes],
        }
        report["plan_signature"] = self._signature(changes)
        return report

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS organization_canonicalization_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                table_name TEXT NOT NULL,
                master_id TEXT NOT NULL,
                scheme_name TEXT,
                old_ministry TEXT,
                new_ministry TEXT,
                old_department TEXT,
                new_department TEXT,
                old_hash TEXT NOT NULL,
                new_hash TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                version TEXT NOT NULL,
                UNIQUE(run_id, table_name, master_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_org_canonicalization_master
                ON organization_canonicalization_audit(master_id, applied_at DESC)
            """
        )

    def apply(self, expected_signature: str) -> dict[str, Any]:
        if not expected_signature:
            raise ValueError("A reviewed dry-run signature is required")

        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            connection.execute("BEGIN IMMEDIATE")
            changes = self._collect_changes(connection)
            signature = self._signature(changes)
            if signature != expected_signature:
                raise RuntimeError(
                    "The organization canonicalization plan changed after review; run a new dry run."
                )

            self._ensure_schema(connection)
            run_id = "organization_canonicalization_" + datetime.now(
                timezone.utc
            ).strftime("%Y%m%dT%H%M%SZ")
            applied_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

            for change in changes:
                payload = json.dumps(
                    change.new_record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if change.table_name == "admin_review_queue":
                    connection.execute(
                        """
                        UPDATE admin_review_queue
                        SET validated_record_json=?,record_hash=?,updated_at=?
                        WHERE master_id=?
                        """,
                        (payload, change.new_hash, applied_at, change.master_id),
                    )
                elif change.table_name == "scheme_staging":
                    connection.execute(
                        """
                        UPDATE scheme_staging
                        SET ministry=?,department=?,raw_record_json=?,record_hash=?,last_loaded_at=?
                        WHERE master_id=?
                        """,
                        (
                            change.new_ministry,
                            change.new_department,
                            payload,
                            change.new_hash,
                            applied_at,
                            change.master_id,
                        ),
                    )
                else:
                    raise RuntimeError(f"Unsupported canonicalization table: {change.table_name}")

                connection.execute(
                    """
                    INSERT INTO organization_canonicalization_audit(
                        run_id,table_name,master_id,scheme_name,
                        old_ministry,new_ministry,old_department,new_department,
                        old_hash,new_hash,applied_at,version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        change.table_name,
                        change.master_id,
                        change.scheme_name,
                        change.old_ministry,
                        change.new_ministry,
                        change.old_department,
                        change.new_department,
                        change.old_hash,
                        change.new_hash,
                        applied_at,
                        VERSION,
                    ),
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        result = self.plan()
        result.update(
            {
                "dry_run": False,
                "database_modified": bool(changes),
                "applied_change_count": len(changes),
                "run_id": run_id,
                "applied_at": applied_at,
                "pre_apply_signature": expected_signature,
            }
        )
        return result
