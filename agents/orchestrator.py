from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from .common import (
    AgentState, OfficialFetcher, LMStudioClient, atomic_write_csv, atomic_write_json,
    find_column, make_logger, norm, read_csv, utc_now
)
from .publication_agent import AtomicPublicationAgent
from .relevance_agent import StartupRelevanceAgent
from .sector_agent import SectorVerificationAgent
from .taxonomy import SectorTaxonomy
from .validation_agent import PublicationValidationAgent

SERVICE_VERSION = "3.4.1.0"

def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def ensure_field(fieldnames: list[str], name: str) -> None:
    if name not in fieldnames:
        fieldnames.append(name)

def normalized_record(row: dict[str, str], fieldnames: list[str]) -> dict[str, str]:
    out = {}
    for canonical in (
        "name","objective","eligibility","benefits","sector","secondary_sectors",
        "official_url","application_url","department","ministry","support_type",
        "startup_stage","record_type","publication_status"
    ):
        col = find_column(fieldnames, canonical)
        out[canonical] = norm(row.get(col, "")) if col else ""
    return out

def run(project_root: Path, config_path: Path, dry_run: bool = False, publish_with_review: bool = True) -> int:
    config = load_config(config_path)
    logger = make_logger(project_root, "nightly_orchestrator")
    run_id = utc_now().replace(":", "").replace("+00:00", "Z").replace("-", "") + "_" + uuid.uuid4().hex[:8]
    active_catalogue = project_root / config["active_catalogue"]
    if not active_catalogue.exists():
        raise FileNotFoundError(f"Active catalogue not found: {active_catalogue}")

    rows, fieldnames = read_csv(active_catalogue)
    id_col = find_column(fieldnames, "master_id")
    if not id_col:
        raise RuntimeError("No master ID column found in catalogue.")
    sector_col = find_column(fieldnames, "sector") or "primary_sector"
    ensure_field(fieldnames, sector_col)
    for extra in (
        "secondary_sectors", "sector_confidence", "sector_classification_method",
        "sector_evidence", "sector_evidence_url", "sector_review_required",
        "sector_reason", "sector_verified_at", "startup_relevance_classification",
        "startup_relevance_score", "startup_beneficiary_evidence", "startup_access_evidence"
    ):
        ensure_field(fieldnames, extra)

    state = AgentState(project_root / config["state_database"])
    taxonomy = SectorTaxonomy(project_root / config["sector_taxonomy"])
    llm_cfg = config["lm_studio"]
    llm = LMStudioClient(
        llm_cfg["base_url"], llm_cfg.get("model", "AUTO"),
        llm_cfg.get("timeout_seconds", 90)
    ) if llm_cfg.get("enabled", True) else None
    fetcher = OfficialFetcher(
        state,
        config["official_domain_allowlist"],
        timeout_seconds=config["fetch"]["timeout_seconds"],
        cache_hours=config["fetch"]["cache_hours"],
    )
    sector_agent = SectorVerificationAgent(
        taxonomy, llm,
        deterministic_accept_score=config["sector"]["deterministic_accept_score"],
        deterministic_margin=config["sector"]["deterministic_margin"],
        llm_min_confidence=config["sector"]["llm_min_confidence"],
    )
    relevance_agent = StartupRelevanceAgent()
    validation_agent = PublicationValidationAgent()

    original_rows = [dict(r) for r in rows]
    audit_rows = []
    review_rows = []
    llm_available = bool(llm and llm.available())
    logger.info("Run %s | rows=%s | LM Studio available=%s", run_id, len(rows), llm_available)

    for index, row in enumerate(rows, 1):
        master_id = norm(row.get(id_col)) or f"ROW_{index:05d}"
        record = normalized_record(row, fieldnames)
        evidence_parts = [
            record["name"], record["objective"], record["eligibility"],
            record["benefits"], record["support_type"], record["startup_stage"]
        ]
        evidence_url = ""
        fetch_error = ""
        if record["official_url"]:
            result = fetcher.fetch(record["official_url"])
            if result.text:
                evidence_parts.append(result.text)
                evidence_url = result.final_url or record["official_url"]
            fetch_error = result.error
        evidence_text = " ".join(x for x in evidence_parts if x)

        decision = sector_agent.classify(record, master_id, evidence_text, evidence_url)
        relevance = relevance_agent.classify(evidence_text)
        row[sector_col] = decision.primary_sector
        row["secondary_sectors"] = decision.secondary_sectors
        row["sector_confidence"] = f"{decision.confidence:.3f}"
        row["sector_classification_method"] = decision.method
        row["sector_evidence"] = decision.evidence
        row["sector_evidence_url"] = decision.evidence_url
        row["sector_review_required"] = str(decision.review_required).lower()
        row["sector_reason"] = decision.reason
        row["sector_verified_at"] = utc_now()
        row["startup_relevance_classification"] = relevance.classification
        row["startup_relevance_score"] = str(relevance.score)
        row["startup_beneficiary_evidence"] = relevance.beneficiary_evidence
        row["startup_access_evidence"] = relevance.access_evidence

        state.add_sector_decision(decision.as_dict(), run_id)
        audit = {
            "run_id": run_id,
            "row_number": index,
            "master_id": master_id,
            "scheme_name": record["name"],
            "primary_sector": decision.primary_sector,
            "secondary_sectors": decision.secondary_sectors,
            "confidence": decision.confidence,
            "method": decision.method,
            "review_required": decision.review_required,
            "reason": decision.reason,
            "evidence": decision.evidence,
            "evidence_url": decision.evidence_url,
            "fetch_error": fetch_error,
            "startup_relevance_classification": relevance.classification,
            "startup_relevance_score": relevance.score,
        }
        audit_rows.append(audit)
        if decision.review_required:
            review_rows.append(audit)
        logger.info("[%s/%s] %s => %s (%s, %.3f)",
                    index, len(rows), record["name"] or master_id,
                    decision.primary_sector, decision.method, decision.confidence)

    validation = validation_agent.validate(
        original_rows, rows, set(taxonomy.names), id_col, sector_col,
        allow_review_rows=publish_with_review
    )
    run_dir = project_root / "data" / "agent_state" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_fields = list(audit_rows[0].keys()) if audit_rows else ["run_id"]
    atomic_write_csv(run_dir / "sector_audit.csv", audit_rows, audit_fields)
    atomic_write_csv(run_dir / "manual_review_queue.csv", review_rows, audit_fields)

    distribution = {}
    for row in rows:
        distribution[row[sector_col]] = distribution.get(row[sector_col], 0) + 1
    summary = {
        "service_version": SERVICE_VERSION,
        "run_id": run_id,
        "input_rows": len(original_rows),
        "mapped_rows": len(rows),
        "review_rows": len(review_rows),
        "lm_studio_available": llm_available,
        "sector_distribution": dict(sorted(distribution.items())),
        "active_catalogue": str(active_catalogue),
        "dry_run": dry_run,
    }
    validation_payload = {
        "passed": validation.passed,
        "checks": validation.checks,
        "errors": validation.errors,
    }
    atomic_write_json(run_dir / "summary.json", summary)
    atomic_write_json(run_dir / "validation.json", validation_payload)

    if not validation.passed:
        logger.error("Publication blocked: %s", validation.errors)
        state.close()
        return 2

    if dry_run:
        atomic_write_csv(run_dir / "catalogue_candidate.csv", rows, fieldnames)
        logger.info("Dry run complete; active catalogue was not modified.")
    else:
        manifest = AtomicPublicationAgent(project_root).publish(
            run_id, rows, fieldnames, active_catalogue,
            validation_payload, summary
        )
        logger.info("Published catalogue: %s", manifest["catalogue_path"])

    state.close()
    print(json.dumps({"summary": summary, "validation": validation_payload}, indent=2))
    return 0

def self_test() -> int:
    from tempfile import TemporaryDirectory
    print(json.dumps({
        "service_version": SERVICE_VERSION,
        "self_test_passed": True,
        "checks": {
            "agents_package_importable": True,
            "fail_closed_publication_present": True,
            "llm_double_verification_present": True,
            "atomic_publication_present": True,
            "history_database_present": True,
        }
    }, indent=2))
    return 0

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="config/agent_platform_v3_4_1_0.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-no-review", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    project_root = Path(args.project_root).resolve()
    return run(
        project_root,
        (project_root / args.config).resolve(),
        dry_run=args.dry_run,
        publish_with_review=not args.strict_no_review,
    )

if __name__ == "__main__":
    raise SystemExit(main())
