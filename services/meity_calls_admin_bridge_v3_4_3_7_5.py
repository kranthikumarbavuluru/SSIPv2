from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from database.staging_loader_v1 import stable_json, upsert_review_item
from services.organization_canonicalization_v3_4_3_7_4 import (
    canonicalize_organization_record,
)

VERSION = "3.4.3.7.5"
PROVIDER_ID = "meity_calls_v3_4_3_7_5"
OFFICIAL_HOSTS = {
    "msh.meity.gov.in",
    "api.meity.gov.in",
    "meity.gov.in",
    "www.meity.gov.in",
}


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).casefold()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_official(value: Any) -> bool:
    parsed = urlparse(clean(value))
    host = parsed.netloc.casefold().split(":", 1)[0]
    return parsed.scheme in {"http", "https"} and host in OFFICIAL_HOSTS


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass(frozen=True)
class MeitYCallsBridgePaths:
    project_root: Path
    source_queue_path: Path
    database_path: Path
    report_dir: Path

    @classmethod
    def defaults(
        cls,
        project_root: Path,
        database_path: Path | None = None,
    ) -> "MeitYCallsBridgePaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_queue_path=(
                root
                / "data/departments/meity/v3_4_3_7_5/"
                "meity_admin_review_queue_v3_4_3_7_5.csv"
            ),
            database_path=(
                database_path or root / "database/ssip_staging_v1.db"
            ).resolve(),
            report_dir=(
                root / "data/departments/meity/v3_4_3_7_5/admin_bridge"
            ),
        )


class MeitYCallsAdminBridge:
    def __init__(self, paths: MeitYCallsBridgePaths) -> None:
        self.paths = paths

    def validate_rows(self, rows: list[dict[str, str]]) -> None:
        seen: set[str] = set()
        for row in rows:
            master_id = clean(row.get("master_id"))
            if not master_id.startswith("meitycall_"):
                raise RuntimeError(f"Invalid MeitY call ID: {master_id!r}")
            if master_id in seen:
                raise RuntimeError(f"Duplicate MeitY call ID: {master_id}")
            seen.add(master_id)

            if clean(row.get("record_kind")) != "APPLICATION_CALL":
                raise RuntimeError(f"Unexpected record kind: {master_id}")
            if clean(row.get("permanent_scheme_or_call")) != "CALL_INSTANCE":
                raise RuntimeError(
                    f"Permanent scheme found in call queue: {master_id}"
                )
            if not is_official(row.get("official_source_url")):
                raise RuntimeError(f"Non-official evidence URL: {master_id}")

            application = clean(row.get("application_url"))
            if application and not is_official(application):
                raise RuntimeError(
                    f"Non-official application URL: {master_id}"
                )
            if (
                application
                and clean(row.get("application_status")) != "OPEN_VERIFIED"
            ):
                raise RuntimeError(
                    "Application route present without OPEN_VERIFIED: "
                    f"{master_id}"
                )

    def build_item(self, row: dict[str, str]) -> dict[str, Any]:
        strict_open = (
            clean(row.get("application_status")) == "OPEN_VERIFIED"
            and clean(row.get("verified_current")).casefold() == "true"
        )
        application_url = (
            clean(row.get("application_url")) if strict_open else None
        )

        warnings = [
            flag
            for flag in clean(row.get("quality_flags")).split(";")
            if flag
        ]
        if not strict_open:
            warnings.append(
                "No public Apply action until current dated evidence and "
                "an official application route are verified."
            )

        evidence_url = clean(row["official_source_url"])
        source_evidence = [
            {
                "url": evidence_url,
                "title": clean(row.get("evidence_title"))
                or "Official MeitY call evidence",
                "content_kind": (
                    "pdf" if evidence_url.casefold().endswith(".pdf") else "html"
                ),
                "evidence_text": clean(row.get("evidence_excerpt")),
            }
        ]

        record: dict[str, Any] = {
            "master_id": clean(row["master_id"]),
            "scheme_name": clean(row["canonical_name"]),
            "short_name": "",
            "source": "MeitY Startup Hub",
            "ministry": (
                "Ministry of Electronics and Information Technology (MeitY)"
            ),
            "department": None,
            "implementing_agency": "MeitY Startup Hub",
            "record_kind": "APPLICATION_CALL",
            "programme_status": "CALL_INFORMATION_AVAILABLE",
            "application_status": (
                "OPEN"
                if strict_open
                else "CLOSED"
                if clean(row.get("application_status"))
                == "CLOSED_OR_DEADLINE_PASSED"
                else "VERIFICATION_REQUIRED"
            ),
            "scheme_status": "CALL_INSTANCE",
            "geographic_scope": "National (India)",
            "official_page_url": evidence_url,
            "application_url": application_url,
            "opening_date": clean(row.get("opening_date")) or None,
            "closing_date": clean(row.get("deadline")) or None,
            "scheme_type": ["Time-bound MeitY call"],
            "target_beneficiaries": (
                [clean(row.get("eligible_applicants"))]
                if clean(row.get("eligible_applicants"))
                else []
            ),
            "startup_stage": [],
            "sector": [],
            "states_or_uts": [],
            "objectives": (
                [clean(row.get("evidence_excerpt"))]
                if clean(row.get("evidence_excerpt"))
                else []
            ),
            "eligibility": [],
            "benefits": [],
            "funding_amount": {
                "minimum": None,
                "maximum": None,
                "currency": "INR",
                "funding_types": [],
                "amount_mentions": [],
                "beneficiary_support": {
                    "minimum": None,
                    "maximum": None,
                },
                "intermediary_support_maximum": None,
                "scheme_corpus": None,
            },
            "application_process": [],
            "selection_process": [],
            "required_documents": [],
            "guideline_urls": (
                [evidence_url] if evidence_url.casefold().endswith(".pdf") else []
            ),
            "contact_details": [],
            "source_evidence": source_evidence,
            "field_evidence": {
                "identity": evidence_url,
                "application_status": clean(row.get("status_evidence")),
                "status_basis": clean(row.get("status_basis")),
                "evidence_hash": clean(row.get("evidence_hash")),
            },
            "quality_flags": warnings,
            "parent_master_id": clean(row.get("parent_master_id")) or None,
            "parent_scheme_name": clean(row.get("parent_scheme_name")),
            "parent_resolution": clean(row.get("parent_resolution")),
            "entity_type": "CALL_INSTANCE",
            "permanent_scheme_or_call": "CALL_INSTANCE",
            "startup_relevance": clean(row.get("startup_relevance"))
            or "REVIEW_REQUIRED",
            "applicant_layer": clean(row.get("applicant_layer"))
            or "REQUIRES_ADMIN_VERIFICATION",
            "sector_scope": clean(row.get("sector_scope")) or "UNKNOWN",
            "status_basis": clean(row.get("status_basis")),
            "status_evidence": clean(row.get("status_evidence")),
            "last_verified_at": utc_now(),
            "validation": {
                "decision": "NEEDS_ADMIN_REVIEW",
                "validation_score": float(
                    clean(row.get("confidence")) or 0
                ),
                "warnings": warnings,
                "critical_flags": [],
                "corrections": [],
            },
        }
        record = canonicalize_organization_record(record)

        return {
            "master_id": record["master_id"],
            "scheme_name": record["scheme_name"],
            "source": record["source"],
            "record_kind": record["record_kind"],
            "programme_status": record["programme_status"],
            "application_status": record["application_status"],
            "official_page_url": evidence_url,
            "application_url": application_url,
            "decision": "NEEDS_ADMIN_REVIEW",
            "validation_score": record["validation"]["validation_score"],
            "priority": "HIGH" if strict_open else "NORMAL",
            "decision_reasons": [
                "Verify this time-bound call separately from its permanent "
                "parent scheme.",
                "Confirm the parent, applicant layer, deadline and current "
                "application status.",
            ],
            "warnings": warnings,
            "critical_flags": [],
            "recommended_admin_actions": [
                "Open the official MeitY evidence.",
                "Confirm the call-to-parent relationship or approve as a "
                "standalone official call.",
                "Do not expose Apply unless current dated evidence and route "
                "are verified.",
            ],
            "validated_record": record,
        }

    def build_items(self) -> list[dict[str, Any]]:
        if not self.paths.source_queue_path.exists():
            raise FileNotFoundError(
                "MeitY calls queue not found: "
                f"{self.paths.source_queue_path}"
            )
        rows = read_rows(self.paths.source_queue_path)
        self.validate_rows(rows)
        return sorted(
            [self.build_item(row) for row in rows],
            key=lambda item: (
                normalized(item["scheme_name"]),
                item["master_id"],
            ),
        )

    def connect_read_only(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.paths.database_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def existing_records(
        connection: sqlite3.Connection,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, list[dict[str, Any]]],
        dict[str, list[dict[str, Any]]],
    ]:
        by_id: dict[str, dict[str, Any]] = {}
        by_url: dict[str, list[dict[str, Any]]] = {}
        by_name: dict[str, list[dict[str, Any]]] = {}

        for table in ("admin_review_queue", "scheme_staging"):
            status_column = (
                "review_status"
                if table == "admin_review_queue"
                else "publication_status"
            )
            rows = connection.execute(
                f"""
                SELECT master_id,scheme_name,official_page_url,
                       {status_column} AS status
                FROM {table}
                """
            ).fetchall()

            for row in rows:
                item = dict(row)
                item["table"] = table
                if table == "admin_review_queue":
                    by_id[item["master_id"]] = item

                reference = {
                    "master_id": item["master_id"],
                    "scheme_name": item["scheme_name"],
                    "table": table,
                    "status": item["status"],
                }
                url = clean(item["official_page_url"]).casefold()
                if url:
                    by_url.setdefault(url, []).append(reference)
                name = normalized(item["scheme_name"])
                if name:
                    by_name.setdefault(name, []).append(reference)

        return by_id, by_url, by_name

    def plan(self) -> dict[str, Any]:
        items = self.build_items()
        connection = self.connect_read_only()
        try:
            by_id, by_url, by_name = self.existing_records(connection)
        finally:
            connection.close()

        actions: list[dict[str, Any]] = []
        for item in items:
            current = by_id.get(item["master_id"])
            matches: list[dict[str, Any]] = []

            if current:
                action = (
                    "UPDATE_EXISTING_PENDING_CALL"
                    if current["status"] == "PENDING"
                    else "SKIP_EXISTING_DECISION"
                )
                matches = [current]
            else:
                matches = [
                    *by_url.get(
                        clean(item["official_page_url"]).casefold(),
                        [],
                    ),
                    *by_name.get(
                        normalized(item["scheme_name"]),
                        [],
                    ),
                ]
                matches = list(
                    {
                        (match["table"], match["master_id"]): match
                        for match in matches
                    }.values()
                )
                action = (
                    "SKIP_SEMANTIC_DUPLICATE"
                    if matches
                    else "INSERT_PENDING_CALL_REVIEW"
                )

            actions.append(
                {
                    "master_id": item["master_id"],
                    "scheme_name": item["scheme_name"],
                    "record_kind": "APPLICATION_CALL",
                    "application_status": item["application_status"],
                    "action": action,
                    "matches": matches,
                    "item": item,
                }
            )

        report: dict[str, Any] = {
            "version": VERSION,
            "provider_id": PROVIDER_ID,
            "generated_at": utc_now(),
            "source_queue_count": len(items),
            "proposed_insert_count": sum(
                action["action"] == "INSERT_PENDING_CALL_REVIEW"
                for action in actions
            ),
            "proposed_update_count": sum(
                action["action"] == "UPDATE_EXISTING_PENDING_CALL"
                for action in actions
            ),
            "skipped_semantic_duplicate_count": sum(
                action["action"] == "SKIP_SEMANTIC_DUPLICATE"
                for action in actions
            ),
            "skipped_existing_decision_count": sum(
                action["action"] == "SKIP_EXISTING_DECISION"
                for action in actions
            ),
            "application_call_count": len(items),
            "verified_current_call_count": sum(
                item["validated_record"].get("application_status") == "OPEN"
                for item in items
            ),
            "public_application_route_count": sum(
                bool(item.get("application_url")) for item in items
            ),
            "database_modified": False,
            "publication_performed": False,
            "actions": actions,
        }
        report["plan_signature"] = hashlib.sha256(
            stable_json(
                [
                    {
                        "master_id": action["master_id"],
                        "action": action["action"],
                        "item": action["item"],
                    }
                    for action in actions
                ]
            ).encode("utf-8")
        ).hexdigest()
        return report

    @staticmethod
    def ensure_import_run(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        loaded_at: str,
        review_count: int,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO import_runs(
                run_id,started_at,completed_at,status,
                approved_input_count,review_input_count,
                rejected_input_count,summary_json
            ) VALUES (?,?,?,'COMPLETED',0,?,0,?)
            """,
            (
                run_id,
                loaded_at,
                loaded_at,
                review_count,
                stable_json(
                    {
                        "source": PROVIDER_ID,
                        "version": VERSION,
                    }
                ),
            ),
        )

    def run(
        self,
        *,
        apply: bool = False,
        expected_signature: str | None = None,
    ) -> dict[str, Any]:
        report = self.plan()

        if not apply:
            self.write_report(report, "dry_run")
            return report

        if not expected_signature:
            raise ValueError("A reviewed dry-run signature is required")
        if report["plan_signature"] != expected_signature:
            raise RuntimeError("The MeitY calls plan changed after review.")

        writable_actions = [
            action
            for action in report["actions"]
            if action["action"]
            in {
                "INSERT_PENDING_CALL_REVIEW",
                "UPDATE_EXISTING_PENDING_CALL",
            }
        ]
        run_id = (
            "meity_calls_v34375_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        loaded_at = utc_now()

        connection = sqlite3.connect(self.paths.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")

        try:
            connection.execute("BEGIN IMMEDIATE")
            self.ensure_import_run(
                connection,
                run_id=run_id,
                loaded_at=loaded_at,
                review_count=len(writable_actions),
            )
            for action in writable_actions:
                upsert_review_item(
                    connection,
                    action["item"],
                    run_id,
                    loaded_at,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        result = dict(report)
        result["database_modified"] = True
        result["run_id"] = run_id
        result["applied_count"] = len(writable_actions)
        self.write_report(result, "applied")
        return result

    def write_report(
        self,
        report: dict[str, Any],
        suffix: str,
    ) -> None:
        self.paths.report_dir.mkdir(parents=True, exist_ok=True)
        path = (
            self.paths.report_dir
            / f"meity_calls_admin_bridge_{suffix}_v3_4_3_7_5.json"
        )
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
