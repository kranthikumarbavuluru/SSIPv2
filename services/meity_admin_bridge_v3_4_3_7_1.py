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


BRIDGE_VERSION = "3.4.3.7.1"
PROVIDER_ID = "meity_v3_4_3_7"
ACTION_INSERT = "INSERT_PENDING_REVIEW"
ACTION_UPDATE = "UPDATE_EXISTING_PENDING"
ACTION_SKIP_DECIDED = "SKIP_EXISTING_DECISION"
ACTION_SKIP_SEMANTIC = "SKIP_SEMANTIC_DUPLICATE"
TARGET_IDS = {"194b7ba77d6b53f30b91", "94f8ab0a070a6ff15fce"}
APPLICATION_SENTINELS = {
    "",
    "NO_CURRENT_APPLICATION_ROUTE",
    "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
    "NOT_AVAILABLE",
    "N/A",
    "NONE",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def split_values(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r";|\|", clean(value)) if part.strip()]


def canonical_url(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    parsed = urlparse(text)
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse((parsed.scheme.casefold(), parsed.netloc.casefold(), path, "", parsed.query, ""))


def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).casefold()).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _is_application_sentinel(value: Any) -> bool:
    return clean(value).upper() in APPLICATION_SENTINELS


def _source_evidence(row: dict[str, str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, title in (
        (row.get("official_source_url"), "Official MeitY scheme page"),
        (row.get("canonical_scheme_url"), "Canonical MeitY scheme page"),
        (row.get("guidelines_url"), "Official MeitY guidelines"),
    ):
        rendered = clean(url)
        key = canonical_url(rendered)
        if not key or key in seen:
            continue
        parsed = urlparse(rendered)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not parsed.netloc.casefold().endswith("meity.gov.in"):
            continue
        seen.add(key)
        output.append(
            {
                "url": rendered,
                "title": title,
                "content_kind": "pdf" if parsed.path.casefold().endswith(".pdf") else "html",
                "evidence_text": clean(row.get("objective_summary"))
                or clean(row.get("eligibility_summary"))
                or clean(row.get("benefit_summary")),
            }
        )
    return output


def plan_signature(report: dict[str, Any]) -> str:
    payload = [
        {
            "master_id": action["master_id"],
            "action": action["action"],
            "record_hash": action["item"].get("validated_record", {}),
        }
        for action in report.get("actions", [])
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MeitYBridgePaths:
    project_root: Path
    source_queue_path: Path
    database_path: Path
    report_dir: Path

    @classmethod
    def defaults(cls, project_root: Path, database_path: Path | None = None) -> "MeitYBridgePaths":
        root = project_root.resolve()
        source_dir = root / "data/departments/meity/v3_4_3_7"
        return cls(
            project_root=root,
            source_queue_path=source_dir / "meity_admin_review_queue_v3_4_3_7.csv",
            database_path=(database_path or root / "database/ssip_staging_v1.db").resolve(),
            report_dir=root / "data/departments/meity/v3_4_3_7_1/admin_bridge",
        )


class MeitYAdminBridge:
    """Expose the governed SASACT/GENESIS gate through the existing admin intake contract."""

    def __init__(self, paths: MeitYBridgePaths) -> None:
        self.paths = paths

    def _validate_source_rows(self, rows: list[dict[str, str]]) -> None:
        ids = [clean(row.get("master_id")) for row in rows]
        if len(rows) != 2 or set(ids) != TARGET_IDS or len(set(ids)) != 2:
            raise RuntimeError(
                "MeitY v3.4.3.7 intake must contain exactly SASACT and GENESIS once each."
            )
        for row in rows:
            if clean(row.get("source")) != "MeitY Startup Hub":
                raise RuntimeError(f"Unexpected source for {row.get('master_id')}: {row.get('source')!r}")
            if clean(row.get("permanent_scheme_or_call")) != "PERMANENT_SCHEME":
                raise RuntimeError(
                    f"MeitY intake contains a non-permanent identity: {row.get('master_id')}"
                )
            if clean(row.get("candidate_change_type")) != "ADD":
                raise RuntimeError(f"Unexpected candidate change type: {row.get('master_id')}")
            if clean(row.get("admin_decision")):
                raise RuntimeError(
                    "The file-based gate already contains an admin decision. "
                    "Import through the Admin workspace only after reviewing a fresh signed plan."
                )
            evidence = _source_evidence(row)
            if not evidence:
                raise RuntimeError(f"No official MeitY evidence URL is available for {row.get('master_id')}")

    def _build_item(self, row: dict[str, str]) -> dict[str, Any]:
        master_id = clean(row["master_id"])
        name = clean(row.get("canonical_name")) or clean(row.get("display_name"))
        programme_status = clean(row.get("programme_status"))
        application_status = clean(row.get("application_status"))
        application_url = None if _is_application_sentinel(row.get("application_url")) else clean(row.get("application_url")) or None
        warnings = split_values(row.get("blocking_flags"))
        if application_status == "APPLICATION_STATUS_REQUIRES_VERIFICATION":
            warnings.append("Current application status requires curator verification; no Apply action is permitted.")
        if application_status == "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED":
            warnings.append("Historical scheme reference only; no current application route is asserted.")
        if not clean(row.get("objective_summary")):
            warnings.append("Objective summary is not yet populated in the governed review queue.")
        warnings.append("Sector evidence remains unknown and must not be inferred during admin review.")

        objective = clean(row.get("objective_summary"))
        eligibility = clean(row.get("eligibility_summary"))
        benefit = clean(row.get("benefit_summary"))
        official_page = clean(row.get("official_source_url")) or clean(row.get("canonical_scheme_url"))
        source_evidence = _source_evidence(row)
        recommendation = clean(row.get("review_recommendation"))

        record: dict[str, Any] = {
            "master_id": master_id,
            "scheme_name": name,
            "short_name": name,
            "source": "MeitY Startup Hub",
            "ministry": clean(row.get("ministry")) or "Ministry of Electronics and Information Technology (MeitY)",
            "department": clean(row.get("department")) or "Ministry of Electronics and Information Technology (MeitY)",
            "implementing_agency": "MeitY Startup Hub",
            "record_kind": "SCHEME_OR_PROGRAMME",
            "programme_status": programme_status,
            "application_status": application_status,
            "scheme_status": "HISTORICAL_INFORMATION_ONLY" if "HISTORICAL" in programme_status else "SCHEME_INFORMATION_AVAILABLE",
            "geographic_scope": "National (India)",
            "official_page_url": official_page,
            "application_url": application_url,
            "opening_date": clean(row.get("opening_date")) or None,
            "closing_date": clean(row.get("deadline")) or None,
            "scheme_type": ["Permanent Scheme"],
            "target_beneficiaries": [eligibility] if eligibility else ["Startup beneficiary details require curator verification"],
            "startup_stage": [],
            "sector": [],
            "states_or_uts": [],
            "objectives": [objective] if objective else [],
            "eligibility": [eligibility] if eligibility else [],
            "benefits": [benefit] if benefit else [],
            "funding_amount": {
                "minimum": None,
                "maximum": None,
                "currency": "INR",
                "funding_types": [],
                "amount_mentions": [benefit] if benefit else [],
                "beneficiary_support": {"minimum": None, "maximum": None},
                "intermediary_support_maximum": None,
                "scheme_corpus": None,
            },
            "application_process": [],
            "selection_process": [],
            "required_documents": [],
            "guideline_urls": [item["url"] for item in source_evidence if item["content_kind"] == "pdf"],
            "contact_details": [],
            "source_evidence": source_evidence,
            "field_evidence": {
                "identity": official_page,
                "programme_status": application_status,
                "evidence_hash": clean(row.get("evidence_hash")),
                "candidate_row_hash": clean(row.get("candidate_row_hash")),
            },
            "quality_flags": warnings,
            "parent_master_id": None,
            "parent_scheme_name": "",
            "entity_type": clean(row.get("entity_type")) or "SCHEME",
            "permanent_scheme_or_call": "PERMANENT_SCHEME",
            "startup_relevance": clean(row.get("startup_relevance")) or "REVIEW_REQUIRED",
            "applicant_layer": "REQUIRES_ADMIN_VERIFICATION",
            "sector_scope": "UNKNOWN",
            "last_verified_at": clean(row.get("reviewed_at")) or None,
            "review_id": clean(row.get("review_id")),
            "upstream_review_recommendation": recommendation,
            "validation": {
                "decision": "NEEDS_ADMIN_REVIEW",
                "validation_score": None,
                "warnings": warnings,
                "critical_flags": [],
                "corrections": [],
            },
        }

        reasons = [
            "Verify permanent scheme identity, official evidence, beneficiary layer and application status.",
            "Keep time-bound calls, cohorts and application windows separate from this permanent scheme record.",
        ]
        if recommendation:
            reasons.append(f"Upstream governed recommendation: {recommendation}.")

        return {
            "master_id": master_id,
            "scheme_name": name,
            "source": "MeitY Startup Hub",
            "record_kind": "SCHEME_OR_PROGRAMME",
            "programme_status": programme_status,
            "application_status": application_status,
            "official_page_url": official_page,
            "application_url": application_url,
            "decision": "NEEDS_ADMIN_REVIEW",
            "validation_score": None,
            "priority": "HIGH" if application_status == "APPLICATION_STATUS_REQUIRES_VERIFICATION" else "NORMAL",
            "decision_reasons": reasons,
            "warnings": warnings,
            "critical_flags": [],
            "recommended_admin_actions": [
                "Review the official MeitY scheme page and stored evidence.",
                "Confirm whether the record is current, historical or umbrella information.",
                "Do not add an Apply action without a separately verified current call or application window.",
            ],
            "validated_record": record,
        }

    def build_items(self) -> list[dict[str, Any]]:
        if not self.paths.source_queue_path.exists():
            raise FileNotFoundError(f"MeitY admin queue not found: {self.paths.source_queue_path}")
        rows = read_csv(self.paths.source_queue_path)
        self._validate_source_rows(rows)
        items = [self._build_item(row) for row in rows]
        items.sort(key=lambda item: item["scheme_name"].casefold())
        return items

    @staticmethod
    def _existing(
        connection: sqlite3.Connection,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
        by_id: dict[str, dict[str, Any]] = {}
        by_url: dict[str, list[dict[str, str]]] = {}
        by_name: dict[str, list[dict[str, str]]] = {}
        for table in ("admin_review_queue", "scheme_staging"):
            raw_column = "validated_record_json" if table == "admin_review_queue" else "raw_record_json"
            status_column = "review_status" if table == "admin_review_queue" else "publication_status"
            rows = connection.execute(
                f"SELECT master_id,scheme_name,source,official_page_url,{status_column} AS status,{raw_column} AS raw_json FROM {table}"
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
                url = canonical_url(item["official_page_url"])
                if url:
                    by_url.setdefault(url, []).append(reference)
                source = clean(item["source"]).casefold()
                name = normalized_name(item["scheme_name"])
                if name and ("meity" in source or "electronics and information technology" in source):
                    by_name.setdefault(name, []).append(reference)
        return by_id, by_url, by_name

    def plan(self) -> dict[str, Any]:
        items = self.build_items()
        if not self.paths.database_path.exists():
            raise FileNotFoundError(f"Admin staging database not found: {self.paths.database_path}")
        uri = f"file:{self.paths.database_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            by_id, by_url, by_name = self._existing(connection)
        finally:
            connection.close()

        actions: list[dict[str, Any]] = []
        for item in items:
            master_id = item["master_id"]
            existing = by_id.get(master_id)
            matches: list[dict[str, str]] = []
            if existing:
                if existing["status"] == "PENDING":
                    action = ACTION_UPDATE
                else:
                    action = ACTION_SKIP_DECIDED
                    matches = [
                        {
                            "master_id": existing["master_id"],
                            "scheme_name": existing["scheme_name"],
                            "table": existing["table"],
                            "status": existing["status"],
                        }
                    ]
            else:
                url = canonical_url(item.get("official_page_url"))
                matches = list(by_url.get(url, [])) if url else []
                if not matches:
                    matches = list(by_name.get(normalized_name(item["scheme_name"]), []))
                action = ACTION_SKIP_SEMANTIC if matches else ACTION_INSERT
            actions.append(
                {
                    "master_id": master_id,
                    "scheme_name": item["scheme_name"],
                    "record_kind": item["record_kind"],
                    "application_status": item["application_status"],
                    "action": action,
                    "matches": matches,
                    "item": item,
                }
            )

        counts = Counter(row["action"] for row in actions)
        report = {
            "bridge_version": BRIDGE_VERSION,
            "provider_id": PROVIDER_ID,
            "generated_at": utc_now(),
            "dry_run": True,
            "database_path": str(self.paths.database_path.resolve()),
            "source_queue_path": str(self.paths.source_queue_path.resolve()),
            "source_queue_count": len(items),
            "permanent_scheme_count": len(items),
            "application_call_count": 0,
            "verified_current_call_count": 0,
            "proposed_insert_count": counts[ACTION_INSERT],
            "proposed_update_count": counts[ACTION_UPDATE],
            "skipped_existing_decision_count": counts[ACTION_SKIP_DECIDED],
            "skipped_semantic_duplicate_count": counts[ACTION_SKIP_SEMANTIC],
            "database_modified": False,
            "publication_performed": False,
            "actions": actions,
        }
        report["plan_signature"] = plan_signature(report)
        return report

    def run(self, *, apply: bool = False, expected_signature: str | None = None) -> dict[str, Any]:
        report = self.plan()
        if apply:
            if not expected_signature:
                raise RuntimeError("A reviewed dry-run signature is required before importing MeitY records.")
            if report["plan_signature"] != expected_signature:
                raise RuntimeError(
                    "The MeitY import plan changed after the reviewed dry run. "
                    "Run and review a new dry run before importing."
                )
            run_id = "meity_admin_bridge_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            loaded_at = utc_now()
            connection = sqlite3.connect(self.paths.database_path, timeout=30)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """INSERT INTO import_runs(run_id,started_at,status,approved_input_count,review_input_count,rejected_input_count)
                       VALUES (?,?,'RUNNING',0,?,0)""",
                    (run_id, loaded_at, report["proposed_insert_count"] + report["proposed_update_count"]),
                )
                for action in report["actions"]:
                    if action["action"] in {ACTION_INSERT, ACTION_UPDATE}:
                        upsert_review_item(connection, action["item"], run_id, loaded_at)
                completed_at = utc_now()
                report.update(
                    {
                        "dry_run": False,
                        "database_modified": True,
                        "run_id": run_id,
                        "completed_at": completed_at,
                    }
                )
                connection.execute(
                    "UPDATE import_runs SET completed_at=?,status='COMPLETED',summary_json=? WHERE run_id=?",
                    (
                        completed_at,
                        stable_json({key: value for key, value in report.items() if key != "actions"}),
                        run_id,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

            self.paths.report_dir.mkdir(parents=True, exist_ok=True)
            report_path = self.paths.report_dir / "meity_admin_bridge_apply_v3_4_3_7_1.json"
            temporary = report_path.with_suffix(report_path.suffix + ".tmp")
            temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8-sig")
            temporary.replace(report_path)
            report["report_path"] = str(report_path.resolve())
        return report
