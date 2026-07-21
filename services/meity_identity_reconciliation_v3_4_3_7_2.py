from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from database.staging_loader_v1 import stable_json, upsert_review_item
from services.meity_admin_bridge_v3_4_3_7_1 import MeitYAdminBridge, MeitYBridgePaths


BRIDGE_VERSION = "3.4.3.7.2"
PROVIDER_ID = "meity_v3_4_3_7_2"

ACTION_INSERT = "INSERT_PENDING_REVIEW"
ACTION_UPDATE = "UPDATE_EXISTING_PENDING"
ACTION_SKIP_DECIDED = "SKIP_EXISTING_DECISION"
ACTION_SKIP_SEMANTIC = "SKIP_SEMANTIC_DUPLICATE"
ACTION_RECONCILE_INSERT = "INSERT_PENDING_CANONICAL_REPLACEMENT"

SASACT_ID = "194b7ba77d6b53f30b91"
GENESIS_ID = "94f8ab0a070a6ff15fce"
TARGET_IDS = {SASACT_ID, GENESIS_ID}
EXPECTED_LEGACY_IDS = {
    GENESIS_ID: "190830c31088c57ffdbc",
    SASACT_ID: "e3abff4124f05a31f188",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def canonical_url(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    parsed = urlparse(text)
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).casefold()).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def reconciliation_plan_signature(report: dict[str, Any]) -> str:
    payload = [
        {
            "master_id": action["master_id"],
            "action": action["action"],
            "validated_record": action["item"].get("validated_record", {}),
            "reconciliation": action.get("reconciliation"),
        }
        for action in report.get("actions", [])
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MeitYReconciliationPaths:
    project_root: Path
    source_queue_path: Path
    reconciliation_map_path: Path
    database_path: Path
    migration_path: Path
    report_dir: Path

    @classmethod
    def defaults(
        cls,
        project_root: Path,
        database_path: Path | None = None,
    ) -> "MeitYReconciliationPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_queue_path=(
                root
                / "data/departments/meity/v3_4_3_7/"
                "meity_admin_review_queue_v3_4_3_7.csv"
            ),
            reconciliation_map_path=(
                root
                / "data/departments/meity/v3_4_3_7_2/"
                "meity_legacy_identity_reconciliation_v3_4_3_7_2.csv"
            ),
            database_path=(
                database_path or root / "database/ssip_staging_v1.db"
            ).resolve(),
            migration_path=(
                root
                / "database/migrations/"
                "20260714_meity_legacy_identity_reconciliation_v3_4_3_7_2.sql"
            ),
            report_dir=(
                root
                / "data/departments/meity/v3_4_3_7_2/admin_bridge"
            ),
        )


class MeitYLegacyIdentityReconciliationBridge:
    """Reconcile two legacy rejected aliases with governed canonical IDs."""

    def __init__(self, paths: MeitYReconciliationPaths) -> None:
        self.paths = paths
        base_paths = MeitYBridgePaths(
            project_root=paths.project_root,
            source_queue_path=paths.source_queue_path,
            database_path=paths.database_path,
            report_dir=paths.report_dir,
        )
        self.base_bridge = MeitYAdminBridge(base_paths)

    def _mapping(self) -> dict[str, dict[str, str]]:
        if not self.paths.reconciliation_map_path.exists():
            raise FileNotFoundError(
                "MeitY reconciliation map not found: "
                f"{self.paths.reconciliation_map_path}"
            )
        rows = read_csv(self.paths.reconciliation_map_path)
        by_canonical = {
            clean(row.get("canonical_master_id")): row
            for row in rows
        }
        if len(rows) != 2 or set(by_canonical) != TARGET_IDS:
            raise RuntimeError(
                "The reconciliation map must contain exactly the governed "
                "SASACT and GENESIS canonical IDs."
            )

        for canonical_id, expected_legacy_id in EXPECTED_LEGACY_IDS.items():
            row = by_canonical[canonical_id]
            if clean(row.get("legacy_master_id")) != expected_legacy_id:
                raise RuntimeError(
                    f"Unexpected legacy mapping for {canonical_id}."
                )
            if clean(row.get("required_legacy_table")) != "admin_review_queue":
                raise RuntimeError(
                    "Legacy identities must be reconciled from admin_review_queue."
                )
            if clean(row.get("required_legacy_status")).upper() != "REJECTED":
                raise RuntimeError(
                    "Only explicitly REJECTED legacy identities may be reconciled."
                )
            if not clean(row.get("reconciliation_reason")):
                raise RuntimeError(
                    f"Missing reconciliation reason for {canonical_id}."
                )
        return by_canonical

    def build_items(self) -> list[dict[str, Any]]:
        items = self.base_bridge.build_items()
        ids = {item["master_id"] for item in items}
        if len(items) != 2 or ids != TARGET_IDS:
            raise RuntimeError(
                "The governed source queue must contain exactly SASACT and "
                "GENESIS once each."
            )
        for item in items:
            if item["record_kind"] != "SCHEME_OR_PROGRAMME":
                raise RuntimeError(
                    "Calls cannot be reconciled as permanent scheme identities."
                )
            if item.get("application_url"):
                raise RuntimeError(
                    "No application route may be introduced in v3.4.3.7.2."
                )
        return items

    @staticmethod
    def _all_records(
        connection: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for table in ("admin_review_queue", "scheme_staging"):
            status_column = (
                "review_status"
                if table == "admin_review_queue"
                else "publication_status"
            )
            raw_column = (
                "validated_record_json"
                if table == "admin_review_queue"
                else "raw_record_json"
            )
            rows = connection.execute(
                f"""
                SELECT master_id,scheme_name,source,official_page_url,
                       {status_column} AS status,{raw_column} AS raw_json
                FROM {table}
                """
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["table"] = table
                output.append(item)
        return output

    @staticmethod
    def _semantic_matches(
        item: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_url = canonical_url(item.get("official_page_url"))
        target_name = normalized_name(item.get("scheme_name"))
        matches: list[dict[str, Any]] = []
        for record in records:
            if record["master_id"] == item["master_id"]:
                continue
            url_match = (
                bool(target_url)
                and canonical_url(record.get("official_page_url")) == target_url
            )
            name_match = (
                bool(target_name)
                and normalized_name(record.get("scheme_name")) == target_name
            )
            if url_match or name_match:
                match = dict(record)
                match["reason"] = (
                    "OFFICIAL_URL_MATCH"
                    if url_match
                    else "NORMALIZED_NAME_MATCH"
                )
                matches.append(match)
        return matches

    def plan(self) -> dict[str, Any]:
        items = self.build_items()
        mapping = self._mapping()

        if not self.paths.database_path.exists():
            raise FileNotFoundError(
                f"Admin staging database not found: {self.paths.database_path}"
            )

        uri = (
            "file:"
            + self.paths.database_path.resolve().as_posix()
            + "?mode=ro"
        )
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            records = self._all_records(connection)
        finally:
            connection.close()

        by_id: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_id.setdefault(record["master_id"], []).append(record)

        actions: list[dict[str, Any]] = []
        for item in items:
            canonical_id = item["master_id"]
            row_mapping = mapping[canonical_id]
            canonical_existing = by_id.get(canonical_id, [])
            matches: list[dict[str, Any]] = []
            reconciliation: dict[str, Any] | None = None

            if canonical_existing:
                preferred = canonical_existing[0]
                matches = canonical_existing
                if (
                    preferred["table"] == "admin_review_queue"
                    and clean(preferred["status"]).upper() == "PENDING"
                ):
                    action = ACTION_UPDATE
                else:
                    action = ACTION_SKIP_DECIDED
            else:
                matches = self._semantic_matches(item, records)
                legacy_id = clean(row_mapping["legacy_master_id"])
                legacy_rows = [
                    record
                    for record in records
                    if record["master_id"] == legacy_id
                    and record["table"] == "admin_review_queue"
                ]
                if len(legacy_rows) != 1:
                    raise RuntimeError(
                        f"Expected one legacy admin row {legacy_id} for "
                        f"{canonical_id}; found {len(legacy_rows)}."
                    )

                legacy = legacy_rows[0]
                if clean(legacy["status"]).upper() != "REJECTED":
                    raise RuntimeError(
                        f"Legacy identity {legacy_id} must remain REJECTED "
                        "before reconciliation."
                    )
                if normalized_name(legacy["scheme_name"]) != normalized_name(
                    row_mapping["canonical_name"]
                ):
                    raise RuntimeError(
                        f"Legacy name does not match mapping for {canonical_id}."
                    )
                if canonical_url(legacy["official_page_url"]) != canonical_url(
                    row_mapping["official_page_url"]
                ):
                    raise RuntimeError(
                        "Legacy official URL does not match mapping for "
                        f"{canonical_id}."
                    )

                unexpected = [
                    match
                    for match in matches
                    if not (
                        match["master_id"] == legacy_id
                        and match["table"] == "admin_review_queue"
                        and clean(match["status"]).upper() == "REJECTED"
                    )
                ]
                if unexpected:
                    action = ACTION_SKIP_SEMANTIC
                else:
                    action = ACTION_RECONCILE_INSERT
                    reconciliation = {
                        "legacy_master_id": legacy_id,
                        "canonical_master_id": canonical_id,
                        "canonical_name": clean(
                            row_mapping["canonical_name"]
                        ),
                        "legacy_table": "admin_review_queue",
                        "legacy_status": "REJECTED",
                        "official_page_url": clean(
                            row_mapping["official_page_url"]
                        ),
                        "reconciliation_reason": clean(
                            row_mapping["reconciliation_reason"]
                        ),
                        "legacy_snapshot": {
                            "master_id": legacy["master_id"],
                            "scheme_name": legacy["scheme_name"],
                            "source": legacy.get("source"),
                            "official_page_url": legacy.get(
                                "official_page_url"
                            ),
                            "status": legacy.get("status"),
                            "raw_json": legacy.get("raw_json"),
                        },
                    }
                    item["validated_record"][
                        "legacy_identity_reconciliation"
                    ] = {
                        key: value
                        for key, value in reconciliation.items()
                        if key != "legacy_snapshot"
                    }
                    item["decision_reasons"].append(
                        "A prior rejected discovery identity is preserved "
                        "as a reconciled legacy alias."
                    )
                    item["recommended_admin_actions"].append(
                        "Review the canonical record independently; the "
                        "legacy rejection remains immutable."
                    )

            actions.append(
                {
                    "master_id": canonical_id,
                    "scheme_name": item["scheme_name"],
                    "record_kind": item["record_kind"],
                    "application_status": item["application_status"],
                    "action": action,
                    "matches": [
                        {
                            "master_id": match["master_id"],
                            "scheme_name": match["scheme_name"],
                            "table": match["table"],
                            "status": clean(match["status"]),
                            "reason": match.get("reason", ""),
                        }
                        for match in matches
                    ],
                    "reconciliation": reconciliation,
                    "item": item,
                }
            )

        counts = Counter(action["action"] for action in actions)
        report = {
            "bridge_version": BRIDGE_VERSION,
            "provider_id": PROVIDER_ID,
            "generated_at": utc_now(),
            "dry_run": True,
            "database_path": str(self.paths.database_path.resolve()),
            "source_queue_path": str(
                self.paths.source_queue_path.resolve()
            ),
            "reconciliation_map_path": str(
                self.paths.reconciliation_map_path.resolve()
            ),
            "source_queue_count": len(items),
            "permanent_scheme_count": len(items),
            "application_call_count": 0,
            "verified_current_call_count": 0,
            "proposed_insert_count": (
                counts[ACTION_INSERT]
                + counts[ACTION_RECONCILE_INSERT]
            ),
            "proposed_update_count": counts[ACTION_UPDATE],
            "skipped_existing_decision_count": (
                counts[ACTION_SKIP_DECIDED]
                + counts[ACTION_RECONCILE_INSERT]
            ),
            "legacy_rejection_history_protected_count": counts[
                ACTION_RECONCILE_INSERT
            ],
            "reconciliation_count": counts[ACTION_RECONCILE_INSERT],
            "skipped_semantic_duplicate_count": counts[
                ACTION_SKIP_SEMANTIC
            ],
            "database_modified": False,
            "publication_performed": False,
            "actions": actions,
        }
        report["plan_signature"] = reconciliation_plan_signature(report)
        return report

    def run(
        self,
        *,
        apply: bool = False,
        expected_signature: str | None = None,
    ) -> dict[str, Any]:
        report = self.plan()
        if not apply:
            return report

        if not expected_signature:
            raise RuntimeError(
                "A reviewed dry-run signature is required before importing "
                "reconciled identities."
            )
        if report["plan_signature"] != expected_signature:
            raise RuntimeError(
                "The MeitY reconciliation plan changed after the reviewed "
                "dry run. Run and review a new dry run before importing."
            )

        writable = {
            ACTION_INSERT,
            ACTION_UPDATE,
            ACTION_RECONCILE_INSERT,
        }
        write_actions = [
            action
            for action in report["actions"]
            if action["action"] in writable
        ]
        if not write_actions:
            report.update(
                {
                    "dry_run": False,
                    "database_modified": False,
                    "completed_at": utc_now(),
                }
            )
            return report

        if not self.paths.migration_path.exists():
            raise FileNotFoundError(
                f"Reconciliation migration not found: "
                f"{self.paths.migration_path}"
            )

        run_id = (
            "meity_identity_reconciliation_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        loaded_at = utc_now()
        connection = sqlite3.connect(
            self.paths.database_path,
            timeout=30,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(
                self.paths.migration_path.read_text(encoding="utf-8")
            )
            connection.execute(
                """
                INSERT INTO import_runs(
                    run_id,started_at,status,approved_input_count,
                    review_input_count,rejected_input_count
                ) VALUES (?,?,'RUNNING',0,?,0)
                """,
                (run_id, loaded_at, len(write_actions)),
            )

            for action in write_actions:
                reconciliation = action.get("reconciliation")
                if action["action"] == ACTION_RECONCILE_INSERT:
                    current = connection.execute(
                        """
                        SELECT master_id,scheme_name,source,
                               official_page_url,review_status,
                               validated_record_json
                        FROM admin_review_queue
                        WHERE master_id=?
                        """,
                        (reconciliation["legacy_master_id"],),
                    ).fetchone()
                    if (
                        current is None
                        or clean(current["review_status"]).upper()
                        != "REJECTED"
                    ):
                        raise RuntimeError(
                            "A legacy rejection changed after dry run; "
                            "reconciliation aborted."
                        )

                upsert_review_item(
                    connection,
                    action["item"],
                    run_id,
                    loaded_at,
                )

                if action["action"] == ACTION_RECONCILE_INSERT:
                    connection.execute(
                        """
                        INSERT INTO identity_reconciliations(
                            legacy_master_id,canonical_master_id,
                            canonical_name,legacy_table,legacy_status,
                            official_page_url,reconciliation_reason,
                            mapping_version,legacy_snapshot_json,
                            created_at,import_run_id
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(
                            legacy_master_id,canonical_master_id
                        ) DO NOTHING
                        """,
                        (
                            reconciliation["legacy_master_id"],
                            reconciliation["canonical_master_id"],
                            reconciliation["canonical_name"],
                            reconciliation["legacy_table"],
                            reconciliation["legacy_status"],
                            reconciliation["official_page_url"],
                            reconciliation["reconciliation_reason"],
                            BRIDGE_VERSION,
                            stable_json(
                                reconciliation["legacy_snapshot"]
                            ),
                            loaded_at,
                            run_id,
                        ),
                    )

            completed_at = utc_now()
            report.update(
                {
                    "dry_run": False,
                    "database_modified": True,
                    "run_id": run_id,
                    "completed_at": completed_at,
                }
            )
            summary = {
                key: value
                for key, value in report.items()
                if key != "actions"
            }
            connection.execute(
                """
                UPDATE import_runs
                SET completed_at=?,status='COMPLETED',summary_json=?
                WHERE run_id=?
                """,
                (completed_at, stable_json(summary), run_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        self.paths.report_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        report_path = (
            self.paths.report_dir
            / "meity_identity_reconciliation_apply_v3_4_3_7_2.json"
        )
        temporary = report_path.with_suffix(
            report_path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8-sig",
        )
        temporary.replace(report_path)
        report["report_path"] = str(report_path.resolve())
        return report
