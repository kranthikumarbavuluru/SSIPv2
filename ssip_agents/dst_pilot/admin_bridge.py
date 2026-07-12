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

from .common import clean


BRIDGE_VERSION = "1.0.0"
ACTION_INSERT = "INSERT_PENDING_REVIEW"
ACTION_UPDATE = "UPDATE_EXISTING_PENDING"
ACTION_SKIP_DECIDED = "SKIP_EXISTING_DECISION"
ACTION_SKIP_SEMANTIC = "SKIP_SEMANTIC_DUPLICATE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def split_values(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r";|\|", clean(value)) if part.strip()]


def iso_date(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return text


def optional_int(value: Any) -> int | None:
    text = clean(value).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def canonical_url(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    parsed = urlparse(text)
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse((parsed.scheme.casefold(), parsed.netloc.casefold(), path, "", parsed.query, ""))


def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).casefold()).strip()


def plan_signature(report: dict[str, Any]) -> str:
    """Fingerprint the exact actions a curator reviewed in a dry run."""
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def source_item(url: str, title: str, evidence: str = "") -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "content_kind": "pdf" if urlparse(url).path.casefold().endswith(".pdf") else "html",
        "evidence_text": evidence,
    }


@dataclass(frozen=True)
class BridgePaths:
    project_root: Path
    pilot_dir: Path
    database_path: Path
    report_dir: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "BridgePaths":
        root = project_root.resolve()
        pilot = root / "data/departments/dst/pilot_v1"
        return cls(
            project_root=root,
            pilot_dir=pilot,
            database_path=root / "database/ssip_staging_v1.db",
            report_dir=pilot / "admin_bridge",
        )


class DSTAdminBridge:
    """Translate the isolated DST pilot queue into the existing admin-review contract."""

    def __init__(self, paths: BridgePaths) -> None:
        self.paths = paths

    def _programme_item(self, row: dict[str, str], queue: dict[str, str]) -> dict[str, Any]:
        sectors = [row["primary_sector"], *split_values(row["secondary_sectors"])]
        sectors = [value for value in sectors if clean(value)]
        parent_id = clean(row["parent_master_id"])
        record_kind = "UMBRELLA_PROGRAMME" if row["entity_type"] == "UMBRELLA_PROGRAMME" else (
            "FUND" if row["entity_type"] == "FUND_SCHEME" else "SCHEME_OR_PROGRAMME"
        )
        reasons = split_values(queue["reasons"])
        warnings = []
        if row["sector_scope"] == "UNKNOWN":
            warnings.append("Sector scope is unknown and must not be inferred without official evidence.")
        record: dict[str, Any] = {
            "master_id": row["master_id"],
            "scheme_name": row["canonical_name"],
            "short_name": row["code"],
            "source": "DST",
            "ministry": "Ministry of Science and Technology",
            "department": "Department of Science and Technology",
            "implementing_agency": "Department of Science and Technology",
            "record_kind": record_kind,
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "application_status": "NOT_APPLICABLE",
            "scheme_status": "REFERENCE_PROGRAMME",
            "geographic_scope": "National (India)",
            "official_page_url": row["official_master_url"],
            "application_url": None,
            "opening_date": None,
            "closing_date": None,
            "scheme_type": [row["entity_type"].replace("_", " ").title()],
            "target_beneficiaries": [row["public_classification"].replace("_", " ").title()],
            "startup_stage": [],
            "sector": sectors,
            "states_or_uts": [],
            "objectives": [row["evidence_text"]],
            "eligibility": [],
            "benefits": [],
            "funding_amount": {
                "minimum": None, "maximum": None, "currency": "INR",
                "funding_types": [], "amount_mentions": [],
                "beneficiary_support": {"minimum": None, "maximum": None},
                "intermediary_support_maximum": None, "scheme_corpus": None,
            },
            "application_process": [], "selection_process": [], "required_documents": [],
            "guideline_urls": [], "contact_details": [],
            "source_evidence": [source_item(row["official_master_url"], row["canonical_name"], row["evidence_text"])],
            "field_evidence": {
                "identity": row["evidence_text"],
                "sector_scope": row["sector_scope"],
            },
            "quality_flags": warnings,
            "parent_master_id": parent_id or None,
            "parent_scheme_name": "",
            "entity_type": row["entity_type"],
            "public_classification": row["public_classification"],
            "sector_scope": row["sector_scope"],
            "startup_relevance": row["public_classification"],
            "applicant_layer": "PROGRAMME_IDENTITY",
            "last_verified_at": None,
            "validation": {
                "decision": "NEEDS_ADMIN_REVIEW", "validation_score": None,
                "warnings": warnings, "critical_flags": [], "corrections": [],
            },
        }
        return {
            "master_id": row["master_id"], "scheme_name": row["canonical_name"], "source": "DST",
            "record_kind": record_kind, "programme_status": record["programme_status"],
            "application_status": record["application_status"],
            "official_page_url": row["official_master_url"], "application_url": None,
            "decision": "NEEDS_ADMIN_REVIEW", "validation_score": None,
            "priority": queue["priority"], "decision_reasons": reasons, "warnings": warnings,
            "critical_flags": [],
            "recommended_admin_actions": ["Verify identity, hierarchy, evidence and sector scope before approval."],
            "validated_record": record,
        }

    def _call_item(
        self,
        row: dict[str, str],
        queue: dict[str, str],
        programme_names: dict[str, str],
    ) -> dict[str, Any]:
        parent_id = clean(row["parent_master_id"])
        parent_name = programme_names.get(parent_id, "")
        sectors = [row["primary_sector"], *split_values(row["secondary_sectors"])]
        sectors = [value for value in sectors if clean(value)]
        reasons = split_values(queue["reasons"])
        warnings: list[str] = []
        if row["parent_resolution"] in {"UNRESOLVED", "UMBRELLA_ONLY_REVIEW"}:
            warnings.append("Permanent parent scheme requires curator resolution.")
        if row["startup_relevance"] == "REVIEW_REQUIRED":
            warnings.append("Startup applicability requires curator confirmation.")
        if row["sector_scope"] == "UNKNOWN":
            warnings.append("No official sector evidence is stored; do not infer a sector.")
        if row["application_status"] == "OPEN" and not row["status_evidence"] and not row["closing_date"]:
            warnings.append("Open status requires explicit official evidence before approval.")

        official_url = clean(row["detail_url"]) or clean(row["source_container_url"])
        source_evidence: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for url, title, evidence in (
            (official_url, "Official call page", row["status_evidence"] or row["startup_relevance_reason"]),
            (row["application_url"], "Official application route", row["status_evidence"]),
            (row["guideline_url"], "Official guidelines", row["evidence_note"]),
            (row["attachment_url"], "Official attachment", row["evidence_note"]),
        ):
            key = canonical_url(url)
            if key and key not in seen_urls:
                seen_urls.add(key)
                source_evidence.append(source_item(clean(url), title, clean(evidence)))

        applicant_layer = row["applicant_layer"]
        if applicant_layer == "INTERMEDIARY_IMPLEMENTER":
            beneficiaries = ["Incubators, institutions and programme implementation partners"]
        elif applicant_layer == "DIRECT_BENEFICIARY":
            beneficiaries = ["Startups, innovators and other directly eligible applicants"]
        else:
            beneficiaries = ["Applicant class requires curator verification"]

        funding_maximum = optional_int(row["funding_maximum"])
        record: dict[str, Any] = {
            "master_id": row["call_id"], "scheme_name": row["call_title"], "short_name": "",
            "source": "DST", "ministry": "Ministry of Science and Technology",
            "department": "Department of Science and Technology",
            "implementing_agency": clean(row["implementing_entity"]) or "Department of Science and Technology",
            "record_kind": "APPLICATION_CALL",
            "programme_status": "CALL_INFORMATION_CURRENT" if row["application_status"] in {"OPEN", "UPCOMING"} else "HISTORICAL_CALL_REFERENCE",
            "application_status": row["application_status"],
            "scheme_status": "OPEN_FOR_APPLICATIONS" if row["application_status"] == "OPEN" else row["application_status"],
            "geographic_scope": "National (India)", "official_page_url": official_url,
            "application_url": clean(row["application_url"]) or None,
            "opening_date": iso_date(row["opening_date"]), "closing_date": iso_date(row["closing_date"]),
            "scheme_type": [row["call_type"].replace("_", " ").title()],
            "target_beneficiaries": beneficiaries,
            "startup_stage": split_values(row["startup_stage"].replace("_", " ")),
            "sector": sectors, "states_or_uts": [],
            "objectives": [row["startup_relevance_reason"]] if row["startup_relevance_reason"] else [],
            "eligibility": [row["eligible_applicants"]] if row["eligible_applicants"] else [],
            "benefits": [row["funding_summary"]] if row["funding_summary"] else [],
            "funding_amount": {
                "minimum": None, "maximum": funding_maximum, "currency": "INR",
                "funding_types": [], "amount_mentions": [row["funding_summary"]] if row["funding_summary"] else [],
                "beneficiary_support": {"minimum": None, "maximum": funding_maximum},
                "intermediary_support_maximum": None, "scheme_corpus": None,
            },
            "application_process": [f"Apply through {row['application_url']}"] if row["application_url"] else [],
            "selection_process": [], "required_documents": [],
            "guideline_urls": [row["guideline_url"]] if row["guideline_url"] else [],
            "contact_details": [], "source_evidence": source_evidence,
            "field_evidence": {
                "application_status": row["status_evidence"] or row["status_reason"],
                "startup_relevance": row["startup_relevance_reason"],
                "parent_relationship": row["parent_resolution_reason"],
                "sector": row["sector_reason"],
            },
            "quality_flags": warnings,
            "parent_master_id": parent_id or None, "parent_scheme_name": parent_name,
            "parent_resolution": row["parent_resolution"],
            "implementing_entity": clean(row["implementing_entity"]) or None,
            "implementation_role": clean(row["implementation_role"]) or None,
            "applicant_layer": applicant_layer, "startup_relevance": row["startup_relevance"],
            "sector_scope": row["sector_scope"], "status_basis": clean(row["status_basis"]) or None,
            "status_evidence": clean(row["status_evidence"]) or None,
            "last_verified_at": clean(row["last_verified_at"]) or clean(row["source_fetched_at"]) or None,
            "validation": {
                "decision": "NEEDS_ADMIN_REVIEW", "validation_score": None,
                "warnings": warnings, "critical_flags": [], "corrections": [],
            },
        }
        return {
            "master_id": row["call_id"], "scheme_name": row["call_title"], "source": "DST",
            "record_kind": "APPLICATION_CALL", "programme_status": record["programme_status"],
            "application_status": row["application_status"], "official_page_url": official_url,
            "application_url": clean(row["application_url"]) or None,
            "decision": "NEEDS_ADMIN_REVIEW", "validation_score": None,
            "priority": queue["priority"], "decision_reasons": reasons, "warnings": warnings,
            "critical_flags": [],
            "recommended_admin_actions": [
                "Verify beneficiary layer, parent scheme, status evidence, sectors and official links before approval."
            ],
            "validated_record": record,
        }

    def build_items(self) -> list[dict[str, Any]]:
        programmes = read_csv(self.paths.pilot_dir / "dst_programme_hierarchy_v1.csv")
        calls = read_csv(self.paths.pilot_dir / "dst_individual_calls_v1.csv")
        queue_rows = read_csv(self.paths.pilot_dir / "dst_curation_queue_v1.csv")
        queue = {row["entity_id"]: row for row in queue_rows}
        programme_names = {row["master_id"]: row["canonical_name"] for row in programmes}
        programme_by_id = {row["master_id"]: row for row in programmes}
        call_by_id = {row["call_id"]: row for row in calls}
        items: list[dict[str, Any]] = []
        for queue_row in queue_rows:
            entity_id = queue_row["entity_id"]
            if queue_row["entity_type"] == "PROGRAMME":
                items.append(self._programme_item(programme_by_id[entity_id], queue_row))
            else:
                items.append(self._call_item(call_by_id[entity_id], queue_row, programme_names))
        return items

    @staticmethod
    def _existing(connection: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
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
                reference = {"master_id": item["master_id"], "scheme_name": item["scheme_name"], "table": table, "status": item["status"]}
                url = canonical_url(item["official_page_url"])
                if url:
                    by_url.setdefault(url, []).append(reference)
                name = normalized_name(item["scheme_name"])
                if name and clean(item["source"]).casefold() == "dst":
                    by_name.setdefault(name, []).append(reference)
        return by_id, by_url, by_name

    def plan(self) -> dict[str, Any]:
        items = self.build_items()
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
                    matches = [{"master_id": existing["master_id"], "scheme_name": existing["scheme_name"], "table": existing["table"], "status": existing["status"]}]
            else:
                url = canonical_url(item.get("official_page_url"))
                matches = list(by_url.get(url, [])) if url else []
                if not matches:
                    matches = list(by_name.get(normalized_name(item["scheme_name"]), []))
                action = ACTION_SKIP_SEMANTIC if matches else ACTION_INSERT
            actions.append({
                "master_id": master_id, "scheme_name": item["scheme_name"],
                "record_kind": item["record_kind"], "application_status": item["application_status"],
                "action": action, "matches": matches, "item": item,
            })
        counts = Counter(row["action"] for row in actions)
        return {
            "bridge_version": BRIDGE_VERSION, "generated_at": utc_now(), "dry_run": True,
            "database_path": str(self.paths.database_path.resolve()),
            "source_queue_count": len(items), "proposed_insert_count": counts[ACTION_INSERT],
            "proposed_update_count": counts[ACTION_UPDATE],
            "skipped_existing_decision_count": counts[ACTION_SKIP_DECIDED],
            "skipped_semantic_duplicate_count": counts[ACTION_SKIP_SEMANTIC],
            "database_modified": False, "actions": actions,
        }

    def run(self, *, apply: bool = False, expected_signature: str | None = None) -> dict[str, Any]:
        report = self.plan()
        report["plan_signature"] = plan_signature(report)
        self.paths.report_dir.mkdir(parents=True, exist_ok=True)
        if apply:
            if expected_signature and report["plan_signature"] != expected_signature:
                raise RuntimeError(
                    "The DST import plan changed after the reviewed dry run. Run and review a new dry run before importing."
                )
            run_id = "dst_admin_bridge_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
                report.update({"dry_run": False, "database_modified": True, "run_id": run_id, "completed_at": completed_at})
                connection.execute(
                    "UPDATE import_runs SET completed_at=?,status='COMPLETED',summary_json=? WHERE run_id=?",
                    (completed_at, stable_json({key: value for key, value in report.items() if key != "actions"}), run_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        report_path = self.paths.report_dir / ("dst_admin_bridge_apply_v1.json" if apply else "dst_admin_bridge_dry_run_v1.json")
        temporary = report_path.with_suffix(report_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8-sig")
        temporary.replace(report_path)
        report["report_path"] = str(report_path.resolve())
        return report
