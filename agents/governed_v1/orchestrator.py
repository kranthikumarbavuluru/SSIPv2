from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .call_discovery_agent import CallDiscoveryAgent
from .canonical_identity_agent import CanonicalIdentityAgent
from .common import (
    DOCUMENT_ROLES,
    MASTER_ROLES,
    PUBLIC_RELEVANCE_CLASSES,
    atomic_write_csv,
    atomic_write_json,
    canonical_key,
    clean,
    dashboard_public_ids,
    first,
    load_json,
    make_run_id,
    now_utc,
    read_csv,
    sha256_file,
    union_fields,
)
from .evidence_validation_agent import EvidenceValidationAgent
from .publication_guard_agent import PublicationGuardAgent
from .record_role_agent import RecordRoleAgent
from .sector_verification_agent import SectorVerificationAgent
from .source_fetch_agent import SourceFetchAgent
from .startup_relevance_agent import StartupRelevanceAgent


AGENT_FIELDS = [
    "record_role", "record_role_confidence", "record_role_reason",
    "scheme_master_id", "canonical_name", "official_abbreviation", "aliases",
    "historical_names", "scheme_family", "parent_scheme_id", "official_master_url",
    "identity_confidence", "identity_evidence", "identity_review_status",
    "startup_relevance_classification", "startup_relevance_confidence",
    "startup_beneficiary_evidence", "startup_access_evidence", "startup_relevance_reason",
    "primary_sector", "secondary_sectors", "sector_confidence", "sector_method",
    "sector_evidence", "sector_evidence_url", "sector_review_required", "sector_reason",
    "source_trusted", "evidence_validation_reason", "manual_review_required",
    "decision_reason", "duplicate_of", "governance_verified_at",
]

CALL_FIELDS = [
    "call_instance_id", "parent_scheme_id", "implementing_entity_id", "call_title",
    "call_type", "opening_date", "closing_date", "application_status",
    "eligible_beneficiaries", "application_url", "guidelines_url", "announcement_url",
    "source_url", "last_verified_at", "manual_review_required", "decision_reason",
]


class GovernedAgentOrchestrator:
    def __init__(self, project_root: Path, config_path: Path | None = None) -> None:
        self.project_root = project_root.resolve()
        self.config_path = (config_path or self.project_root / "config/governed_agents_v1.json").resolve()
        self.config = load_json(self.config_path)
        self.active_path = self.project_root / self.config["active_catalogue"]
        self.role_agent = RecordRoleAgent(self.project_root / self.config["record_role_rules"])
        self.identity_agent = CanonicalIdentityAgent()
        self.relevance_agent = StartupRelevanceAgent(self.project_root / self.config["startup_relevance_rules"])
        self.sector_agent = SectorVerificationAgent(self.project_root / self.config["sector_taxonomy"])
        self.call_agent = CallDiscoveryAgent()
        self.evidence_agent = EvidenceValidationAgent(self.project_root / self.config["official_domain_allowlist"])
        self.guard = PublicationGuardAgent()
        allowlist = load_json(self.project_root / self.config["official_domain_allowlist"])
        network = self.config.get("network", {})
        self.fetch_agent = SourceFetchAgent(
            allowlist.get("domains", []),
            enabled=bool(network.get("enabled", False)),
            respect_robots_txt=bool(network.get("respect_robots_txt", True)),
            minimum_delay_seconds=float(network.get("minimum_delay_seconds", 2.0)),
            timeout_seconds=int(network.get("timeout_seconds", 20)),
        )

    @staticmethod
    def _identity_fields(identity: Any) -> dict[str, str]:
        return {
            "scheme_master_id": identity.scheme_master_id,
            "canonical_name": identity.canonical_name,
            "official_abbreviation": identity.official_abbreviation,
            "aliases": identity.aliases,
            "historical_names": identity.historical_names,
            "scheme_family": identity.scheme_family,
            "parent_scheme_id": identity.parent_scheme_id,
            "official_master_url": identity.official_master_url,
            "identity_confidence": f"{identity.identity_confidence:.3f}",
            "identity_evidence": identity.identity_evidence,
            "identity_review_status": identity.identity_review_status,
        }

    def _record_state(self, summary: dict[str, Any], validation: dict[str, Any]) -> None:
        database = self.project_root / self.config["state_database"]
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS governed_runs (
                    run_id TEXT PRIMARY KEY,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    input_record_count INTEGER NOT NULL,
                    public_candidate_count INTEGER NOT NULL,
                    call_count INTEGER NOT NULL,
                    manual_review_count INTEGER NOT NULL,
                    quarantine_count INTEGER NOT NULL,
                    validation_result TEXT NOT NULL,
                    active_catalogue_sha256_before TEXT NOT NULL,
                    active_catalogue_sha256_after TEXT NOT NULL,
                    active_catalogue_modified INTEGER NOT NULL,
                    lm_studio_used INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO governed_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["run_id"], summary["start_time"], summary["end_time"],
                    summary["input_record_count"], summary["public_candidate_count"],
                    summary["call_count"], summary["manual_review_count"],
                    summary["quarantine_count"], str(validation["passed"]),
                    summary["active_catalogue_sha256_before"],
                    summary["active_catalogue_sha256_after"],
                    int(summary["active_catalogue_modified"]), int(summary["lm_studio_used"]),
                    json.dumps(summary, ensure_ascii=False), json.dumps(validation, ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def run_preview(self, selected_run_id: str | None = None) -> dict[str, Any]:
        started = now_utc()
        current_run_id = selected_run_id or make_run_id()
        run_dir = self.project_root / self.config["run_root"] / current_run_id
        if run_dir.exists():
            raise FileExistsError(f"Run directory already exists: {run_dir}")
        run_dir.mkdir(parents=True)

        before_hash = sha256_file(self.active_path)
        snapshot_path = run_dir / "input_snapshot.csv"
        self.fetch_agent.snapshot(self.active_path, snapshot_path)
        rows, source_fields = read_csv(snapshot_path)
        active_rows, _ = read_csv(self.active_path)
        active_names = {
            first(row, "master_id", "scheme_master_id"): first(row, "scheme_name", "canonical_name")
            for row in active_rows
        }
        active_public_ids = dashboard_public_ids(self.project_root, self.active_path)

        inventory: list[dict[str, str]] = []
        master_rows: list[dict[str, str]] = []
        for source_row in rows:
            row = dict(source_row)
            role = self.role_agent.classify(row)
            row.update({
                "record_role": role.role,
                "record_role_confidence": f"{role.confidence:.3f}",
                "record_role_reason": role.reason,
                "governance_verified_at": now_utc(),
            })
            if role.role in MASTER_ROLES:
                row.update(self._identity_fields(self.identity_agent.create_master(row)))
                master_rows.append(row)
            inventory.append(row)

        canonical_candidates: list[dict[str, str]] = []
        startup_relevant: list[dict[str, str]] = []
        call_instances: list[dict[str, str]] = []
        ecosystem_entities: list[dict[str, str]] = []
        supporting_documents: list[dict[str, str]] = []
        quarantined: list[dict[str, str]] = []
        manual_review: list[dict[str, str]] = []
        publication_candidate: list[dict[str, str]] = []
        sector_evidence: list[dict[str, str]] = []
        field_evidence: list[dict[str, str]] = []
        identity_seen: dict[str, str] = {}

        for row in inventory:
            role = first(row, "record_role")
            relevance = self.relevance_agent.classify(row, role)
            row.update({
                "startup_relevance_classification": relevance.classification,
                "startup_relevance_confidence": f"{relevance.confidence:.3f}",
                "startup_beneficiary_evidence": relevance.beneficiary_evidence,
                "startup_access_evidence": relevance.access_evidence,
                "startup_relevance_reason": relevance.reason,
            })
            call = self.call_agent.classify(row, role)
            if call.is_call:
                parent_id, parent_reason = self.identity_agent.resolve_call_parent(row, master_rows)
                call_row = self.call_agent.build(row, parent_id, call.call_type)
                call_row["manual_review_required"] = str(not bool(parent_id)).lower()
                call_row["decision_reason"] = f"{call.reason} {parent_reason}"
                call_instances.append(call_row)
                continue

            if role in DOCUMENT_ROLES or role in {"REPORT_OR_PUBLICATION"}:
                row["decision_reason"] = "Evidence/supporting material retained outside the scheme catalogue."
                supporting_documents.append(row)
                continue
            if role in {"INCUBATOR_OR_HUB", "IMPLEMENTING_ENTITY"} or relevance.classification == "STARTUP_ECOSYSTEM_MISSION":
                row["decision_reason"] = "Ecosystem entity/mission retained outside direct scheme counts."
                ecosystem_entities.append(row)
                continue
            if role not in MASTER_ROLES:
                row["decision_reason"] = f"Role {role} is not publishable as a scheme."
                if role == "MANUAL_ROLE_REVIEW":
                    row["manual_review_required"] = "true"
                    manual_review.append(row)
                else:
                    quarantined.append(row)
                continue

            sector = self.sector_agent.classify(row)
            row.update({
                "sector": sector.primary_sector,
                "primary_sector": sector.primary_sector,
                "secondary_sectors": sector.secondary_sectors,
                "sector_confidence": f"{sector.confidence:.3f}",
                "sector_method": sector.method,
                "sector_evidence": sector.evidence,
                "sector_evidence_url": sector.evidence_url,
                "sector_review_required": str(sector.review_required).lower(),
                "sector_reason": sector.reason,
            })
            evidence = self.evidence_agent.validate(row)
            row["source_trusted"] = str(evidence.trusted_domain).lower()
            row["evidence_validation_reason"] = evidence.reason
            identity_key = canonical_key(first(row, "canonical_name"))
            duplicate_of = identity_seen.get(identity_key, "") if identity_key else ""
            if identity_key and not duplicate_of:
                identity_seen[identity_key] = first(row, "scheme_master_id")
            row["duplicate_of"] = duplicate_of
            review_required = (
                relevance.review_required
                or sector.review_required
                or not evidence.valid
                or bool(duplicate_of)
                or first(row, "identity_review_status") == "IDENTITY_REVIEW_REQUIRED"
            )
            row["manual_review_required"] = str(review_required).lower()
            canonical_candidates.append(row)
            sector_evidence.append({
                "scheme_master_id": first(row, "scheme_master_id"),
                "canonical_name": first(row, "canonical_name"),
                "primary_sector": sector.primary_sector,
                "secondary_sectors": sector.secondary_sectors,
                "sector_confidence": f"{sector.confidence:.3f}",
                "sector_method": sector.method,
                "sector_evidence": sector.evidence,
                "sector_evidence_url": sector.evidence_url,
                "sector_review_required": str(sector.review_required).lower(),
                "sector_verified_at": now_utc(),
            })
            for field_name, evidence_value in (
                ("canonical_name", first(row, "identity_evidence")),
                ("official_source", first(row, "official_master_url")),
                ("startup_relevance", f"{relevance.beneficiary_evidence}; {relevance.access_evidence}".strip("; ")),
                ("primary_sector", sector.evidence),
            ):
                field_evidence.append({
                    "scheme_master_id": first(row, "scheme_master_id"),
                    "field_name": field_name,
                    "field_value": first(row, field_name, "canonical_name", "primary_sector"),
                    "evidence": evidence_value,
                    "evidence_url": first(row, "official_master_url", "sector_evidence_url"),
                    "confidence": first(row, "identity_confidence", "sector_confidence"),
                    "verified_at": now_utc(),
                })
            if relevance.classification in PUBLIC_RELEVANCE_CLASSES:
                startup_relevant.append(row)
                if not review_required:
                    row["decision_reason"] = "All deterministic publication gates passed."
                    publication_candidate.append(row)
                else:
                    row["decision_reason"] = "Candidate is relevant but one or more evidence/identity/sector gates require review."
                    manual_review.append(row)
            elif relevance.review_required:
                row["decision_reason"] = relevance.reason
                manual_review.append(row)
            else:
                row["decision_reason"] = relevance.reason
                quarantined.append(row)

        after_hash = sha256_file(self.active_path)
        active_unchanged = before_hash == after_hash
        taxonomy = self.sector_agent.allowed
        guard = self.guard.validate(
            publication_candidate,
            call_instances,
            active_public_ids,
            snapshot_path.exists(),
            active_unchanged,
            taxonomy,
        )

        candidate_ids = {first(row, "scheme_master_id", "master_id") for row in publication_candidate}
        comparison: list[dict[str, str]] = []
        for master_id in sorted(active_public_ids | candidate_ids):
            in_active = master_id in active_public_ids
            in_candidate = master_id in candidate_ids
            comparison.append({
                "master_id": master_id,
                "canonical_name": active_names.get(master_id, next((first(row, "canonical_name") for row in publication_candidate if first(row, "scheme_master_id") == master_id), "")),
                "in_active_catalogue": str(in_active).lower(),
                "in_publication_candidate": str(in_candidate).lower(),
                "change_type": "UNCHANGED" if in_active and in_candidate else ("ADD" if in_candidate else "PROPOSED_REMOVAL_REQUIRES_APPROVAL"),
            })

        output_fields = union_fields(source_fields + AGENT_FIELDS, inventory)
        atomic_write_csv(run_dir / "classified_inventory.csv", inventory, output_fields)
        atomic_write_csv(run_dir / "canonical_scheme_candidates.csv", canonical_candidates, output_fields)
        atomic_write_csv(run_dir / "startup_relevant_schemes.csv", startup_relevant, output_fields)
        atomic_write_csv(run_dir / "call_instances.csv", call_instances, CALL_FIELDS)
        atomic_write_csv(run_dir / "ecosystem_entities.csv", ecosystem_entities, output_fields)
        atomic_write_csv(run_dir / "supporting_documents.csv", supporting_documents, output_fields)
        atomic_write_csv(run_dir / "quarantined_records.csv", quarantined, output_fields)
        atomic_write_csv(run_dir / "manual_review_queue.csv", manual_review, output_fields)
        atomic_write_csv(run_dir / "sector_evidence.csv", sector_evidence, [
            "scheme_master_id", "canonical_name", "primary_sector", "secondary_sectors",
            "sector_confidence", "sector_method", "sector_evidence", "sector_evidence_url",
            "sector_review_required", "sector_verified_at",
        ])
        atomic_write_csv(run_dir / "field_evidence.csv", field_evidence, [
            "scheme_master_id", "field_name", "field_value", "evidence", "evidence_url",
            "confidence", "verified_at",
        ])
        atomic_write_csv(run_dir / "comparison_with_active.csv", comparison, [
            "master_id", "canonical_name", "in_active_catalogue", "in_publication_candidate", "change_type",
        ])
        atomic_write_csv(run_dir / "publication_candidate.csv", publication_candidate, output_fields)
        deletion_rows = [
            {
                "master_id": row["master_id"], "canonical_name": row["canonical_name"],
                "proposed_action": "", "reason": "", "approved_by": "", "approval_date": "",
            }
            for row in comparison if row["change_type"] == "PROPOSED_REMOVAL_REQUIRES_APPROVAL"
        ]
        atomic_write_csv(run_dir / "deletion_approval_template.csv", deletion_rows, [
            "master_id", "canonical_name", "proposed_action", "reason", "approved_by", "approval_date",
        ])
        atomic_write_csv(run_dir / "publication_approval_template.csv", [{
            "run_id": current_run_id,
            "proposed_action": "",
            "reason": "",
            "approved_by": "",
            "approval_date": "",
        }], ["run_id", "proposed_action", "reason", "approved_by", "approval_date"])

        validation = {"passed": guard.passed, "checks": guard.checks, "details": guard.details}
        ended = now_utc()
        summary = {
            "version": self.config["version"],
            "run_id": current_run_id,
            "run_directory": str(run_dir),
            "start_time": started,
            "end_time": ended,
            "input_record_count": len(rows),
            "dashboard_main_scheme_count": len(active_public_ids),
            "classified_record_count": len(inventory),
            "canonical_candidate_count": len(canonical_candidates),
            "startup_relevant_count": len(startup_relevant),
            "public_candidate_count": len(publication_candidate),
            "call_count": len(call_instances),
            "ecosystem_entity_count": len(ecosystem_entities),
            "supporting_document_count": len(supporting_documents),
            "manual_review_count": len(manual_review),
            "quarantine_count": len(quarantined),
            "validation_result": "PASSED" if guard.passed else "REVIEW_REQUIRED",
            "role_distribution": dict(Counter(first(row, "record_role") for row in inventory)),
            "relevance_distribution": dict(Counter(first(row, "startup_relevance_classification") for row in inventory)),
            "active_catalogue_sha256_before": before_hash,
            "active_catalogue_sha256_after": after_hash,
            "active_catalogue_modified": not active_unchanged,
            "network_used": False,
            "lm_studio_used": False,
            "published": False,
        }
        atomic_write_json(run_dir / "validation.json", validation)
        atomic_write_json(run_dir / "summary.json", summary)
        self._record_state(summary, validation)
        manifest = {
            "run_id": current_run_id,
            "run_directory": str(run_dir),
            "created_at": ended,
            "validation_result": summary["validation_result"],
            "active_catalogue_sha256": after_hash,
            "published": False,
        }
        atomic_write_json(self.project_root / self.config["preview_manifest"], manifest)
        atomic_write_json(self.project_root / self.config["log_root"] / f"{current_run_id}.json", summary)
        if not active_unchanged:
            raise RuntimeError("Protected active catalogue changed during preview execution.")
        return {"summary": summary, "validation": validation, "output_paths": sorted(str(path) for path in run_dir.iterdir())}
