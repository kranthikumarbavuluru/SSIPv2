from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .call_agent import CallAgent
from .common import (
    atomic_write_csv, atomic_write_json, backup_file, clean, ensure_fields,
    find_column, normalized_identity, now_utc, read_csv, sha256_file
)
from .governance import GovernancePolicy
from .relevance_agent import StartupRelevanceAgent
from .role_agent import RecordRoleAgent
from .sector_agent import EvidenceSectorAgent

SERVICE_VERSION = "3.4.2.1"

def record_text(row: dict[str, str], cols: dict[str, str | None]) -> str:
    parts = []
    for key in ("name", "objective", "eligibility", "benefits", "support_type"):
        col = cols.get(key)
        if col:
            parts.append(clean(row.get(col, "")))
    return " ".join(parts)

def run(project_root: Path, config_path: Path, dry_run: bool = False) -> int:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    active = project_root / cfg["active_catalogue"]
    rows, fieldnames = read_csv(active)
    cols = {k: find_column(fieldnames, k) for k in (
        "id","name","objective","eligibility","benefits","official_url",
        "application_url","department","ministry","record_type","status",
        "sector","support_type"
    )}
    if not cols["id"] or not cols["name"]:
        raise RuntimeError("Catalogue must contain an ID and name column.")

    extra = [
        "sector", "primary_sector", "secondary_sectors", "sector_confidence",
        "sector_method", "sector_evidence", "sector_review_required",
        "record_role", "record_role_confidence", "record_role_reason",
        "startup_relevance_classification", "startup_relevance_score",
        "startup_beneficiary_evidence", "startup_access_evidence",
        "governance_decision", "public_catalogue_section", "governance_reason",
        "call_type", "parent_scheme_id", "governance_verified_at"
    ]
    ensure_fields(fieldnames, extra)

    taxonomy_path = project_root / cfg["taxonomy"]
    role_agent = RecordRoleAgent()
    relevance_agent = StartupRelevanceAgent()
    sector_agent = EvidenceSectorAgent(taxonomy_path)
    call_agent = CallAgent()
    policy = GovernancePolicy()

    public_rows = []
    call_rows = []
    review_rows = []
    quarantine_rows = []
    audit_rows = []
    dedupe_seen: dict[str, str] = {}

    for index, row in enumerate(rows, 1):
        name = clean(row.get(cols["name"], ""))
        text = record_text(row, cols)
        url = clean(row.get(cols["official_url"], "")) if cols["official_url"] else ""
        role = role_agent.classify(name, text, url)
        relevance = relevance_agent.classify(text)
        call = call_agent.classify(name, text)
        governance = policy.decide(role.role, relevance.classification, relevance.score, call.is_call)

        sector = sector_agent.classify(
            name,
            clean(row.get(cols["objective"], "")) if cols["objective"] else "",
            clean(row.get(cols["eligibility"], "")) if cols["eligibility"] else "",
            clean(row.get(cols["benefits"], "")) if cols["benefits"] else "",
            ""
        )

        row["sector"] = sector.primary
        row["primary_sector"] = sector.primary
        row["secondary_sectors"] = sector.secondary
        row["sector_confidence"] = f"{sector.confidence:.3f}"
        row["sector_method"] = sector.method
        row["sector_evidence"] = sector.evidence
        row["sector_review_required"] = str(sector.review_required).lower()
        row["record_role"] = role.role
        row["record_role_confidence"] = f"{role.confidence:.3f}"
        row["record_role_reason"] = role.reason
        row["startup_relevance_classification"] = relevance.classification
        row["startup_relevance_score"] = str(relevance.score)
        row["startup_beneficiary_evidence"] = relevance.beneficiary_hits
        row["startup_access_evidence"] = relevance.access_hits
        row["governance_decision"] = governance.decision
        row["public_catalogue_section"] = governance.public_section
        row["governance_reason"] = governance.reason
        row["call_type"] = call.call_type
        row["governance_verified_at"] = now_utc()

        identity = normalized_identity(name)
        duplicate_of = ""
        if identity:
            if identity in dedupe_seen:
                duplicate_of = dedupe_seen[identity]
                row["governance_decision"] = "QUARANTINE_DUPLICATE"
                row["governance_reason"] = f"Duplicate identity of {duplicate_of}"
            else:
                dedupe_seen[identity] = clean(row.get(cols["id"], ""))

        if row["governance_decision"] == "PUBLISH_SCHEME" and not sector.review_required:
            public_rows.append(row)
        elif row["governance_decision"] == "PUBLISH_SCHEME" and sector.review_required:
            row["governance_decision"] = "MANUAL_REVIEW"
            row["governance_reason"] = "Sector evidence requires review before public publication."
            review_rows.append(row)
        elif row["governance_decision"] == "PUBLISH_CALL_SEPARATELY":
            call_rows.append(row)
        elif row["governance_decision"] == "MANUAL_REVIEW" or sector.review_required:
            review_rows.append(row)
        else:
            quarantine_rows.append(row)

        audit_rows.append({
            "row_number": index,
            "master_id": clean(row.get(cols["id"], "")),
            "name": name,
            "record_role": role.role,
            "startup_relevance": relevance.classification,
            "relevance_score": relevance.score,
            "sector": sector.primary,
            "sector_confidence": sector.confidence,
            "sector_review_required": sector.review_required,
            "governance_decision": row["governance_decision"],
            "duplicate_of": duplicate_of,
        })

    run_id = now_utc().replace(":", "").replace("-", "").replace("+00:00", "Z") + "_" + uuid.uuid4().hex[:8]
    out_dir = project_root / "data" / "governance" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    audit_fields = list(audit_rows[0].keys()) if audit_rows else ["row_number"]
    atomic_write_csv(out_dir / "governance_audit.csv", audit_rows, audit_fields)
    atomic_write_csv(out_dir / "public_startup_schemes.csv", public_rows, fieldnames)
    atomic_write_csv(out_dir / "calls_and_opportunities.csv", call_rows, fieldnames)
    atomic_write_csv(out_dir / "manual_review_queue.csv", review_rows, fieldnames)
    atomic_write_csv(out_dir / "quarantine.csv", quarantine_rows, fieldnames)

    checks = {
        "input_rows_accounted_for": len(rows) == len(public_rows) + len(call_rows) + len(review_rows) + len(quarantine_rows),
        "public_rows_have_sector": all(clean(r.get("sector")) for r in public_rows),
        "public_rows_sector_fields_match": all(r.get("sector") == r.get("primary_sector") for r in public_rows),
        "no_navigation_in_public": all(r.get("record_role") != "NAVIGATION_OR_UTILITY" for r in public_rows),
        "no_supporting_documents_in_public": all(r.get("record_role") != "SUPPORTING_DOCUMENT" for r in public_rows),
        "no_sector_review_rows_in_public": all(r.get("sector_review_required") == "false" for r in public_rows),
        "calls_separated": all(r.get("governance_decision") == "PUBLISH_CALL_SEPARATELY" for r in call_rows),
        "public_count_minimum_met": len(public_rows) >= cfg["validation"]["minimum_public_scheme_count"],
    }
    passed = all(checks.values())

    summary = {
        "service_version": SERVICE_VERSION,
        "run_id": run_id,
        "input_rows": len(rows),
        "public_scheme_rows": len(public_rows),
        "call_rows": len(call_rows),
        "manual_review_rows": len(review_rows),
        "quarantine_rows": len(quarantine_rows),
        "role_distribution": dict(Counter(r["record_role"] for r in audit_rows)),
        "sector_distribution": dict(Counter(r["sector"] for r in public_rows)),
        "governance_distribution": dict(Counter(r["governance_decision"] for r in audit_rows)),
        "lm_studio_used": False,
        "dry_run": dry_run,
    }
    validation = {"passed": passed, "checks": checks}
    atomic_write_json(out_dir / "summary.json", summary)
    atomic_write_json(out_dir / "validation.json", validation)

    if not passed:
        print(json.dumps({"summary": summary, "validation": validation}, indent=2))
        return 2

    if not dry_run:
        backup_dir = project_root / "backups" / "governance" / run_id
        backup_file(active, backup_dir)
        atomic_write_csv(active, public_rows, fieldnames)
        atomic_write_csv(project_root / cfg["calls_output"], call_rows, fieldnames)
        atomic_write_json(project_root / "data/governance/current_manifest.json", {
            "run_id": run_id,
            "published_at": now_utc(),
            "active_catalogue": str(active),
            "public_rows": len(public_rows),
            "call_rows": len(call_rows),
            "active_catalogue_sha256": sha256_file(active),
            "validation": validation,
        })

    print(json.dumps({"summary": summary, "validation": validation}, indent=2))
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="config/catalogue_governance_v3_4_2_1.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps({
            "service_version": SERVICE_VERSION,
            "self_test_passed": True,
            "lm_studio_required": False,
            "agents": [
                "RecordRoleAgent", "StartupRelevanceAgent", "EvidenceSectorAgent",
                "CallAgent", "GovernancePolicy"
            ]
        }, indent=2))
        return 0
    root = Path(args.project_root).resolve()
    return run(root, root / args.config, args.dry_run)

if __name__ == "__main__":
    raise SystemExit(main())
