from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ssip_agents.discovery.source_registry_loader_v3_3 import (
    RegistrySource,
    load_registry_sources,
)


VERSION = "3.3.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean(value: Any) -> str:
    return str(value or "").strip()


def normal_kind(value: Any) -> str:
    return clean(value).upper()


def load_policy(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or project_root_from_file()
    return load_json(root / "config" / "catalogue_expansion_policy_v3_3_1.json")


@dataclass(frozen=True)
class CountSummary:
    eligible_unique_master_records: int
    application_calls: int
    excluded_unique_master_records: int
    duplicate_master_ids: int
    open_schemes: int
    closing_soon: int
    upcoming: int
    closed_historical: int
    verification_required: int
    record_kind_distribution: dict[str, int]


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def existing_catalogue_rows(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = project_root or project_root_from_file()
    candidate_paths = [
        root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_inclusion_candidates_v2_8_1.csv",
        root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "legacy_staged_records_v2_8_1.csv",
        root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_revalidation_backlog_v2_8_1.csv",
    ]
    rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        for row in read_csv_records(path):
            row["_source_path"] = str(path)
            rows.append(row)
    return rows


def summarize_catalogue_count(rows: list[dict[str, Any]], policy: dict[str, Any]) -> CountSummary:
    eligible_kinds = {normal_kind(kind) for kind in policy["counting_policy"]["main_scheme_total_record_kinds"]}
    excluded_kinds = {normal_kind(kind) for kind in policy["counting_policy"]["excluded_from_main_scheme_total"]}
    seen_all: Counter[str] = Counter()
    eligible_ids: set[str] = set()
    excluded_ids: set[str] = set()
    application_call_ids: set[str] = set()
    open_ids: set[str] = set()
    closing_soon_ids: set[str] = set()
    upcoming_ids: set[str] = set()
    closed_ids: set[str] = set()
    verify_ids: set[str] = set()
    kind_counts: Counter[str] = Counter()

    for row in rows:
        master_id = clean(row.get("master_id"))
        if not master_id:
            continue
        seen_all[master_id] += 1
        kind = normal_kind(row.get("normalized_record_kind") or row.get("record_kind") or row.get("current_record_kind"))
        kind_counts[kind or "UNSPECIFIED"] += 1
        status_text = " ".join(
            clean(row.get(key)).upper()
            for key in (
                "programme_status",
                "application_status",
                "catalogue_section",
                "catalogue_inclusion",
                "normalization_disposition",
                "publication_recommendation",
            )
        )
        if kind in eligible_kinds:
            eligible_ids.add(master_id)
        if kind in excluded_kinds:
            excluded_ids.add(master_id)
        if kind == "APPLICATION_CALL":
            application_call_ids.add(master_id)
        if "OPEN" in status_text or "ACTIVE" in status_text:
            open_ids.add(master_id)
        if "CLOSING_SOON" in status_text or "CLOSING SOON" in status_text:
            closing_soon_ids.add(master_id)
        if "UPCOMING" in status_text:
            upcoming_ids.add(master_id)
        if "CLOSED" in status_text or "HISTORICAL" in status_text or "ARCHIVED" in status_text:
            closed_ids.add(master_id)
        if "VERIFY" in status_text or "REVALIDATION" in status_text or "REQUIRES_REVIEW" in status_text:
            verify_ids.add(master_id)

    return CountSummary(
        eligible_unique_master_records=len(eligible_ids),
        application_calls=len(application_call_ids),
        excluded_unique_master_records=len(excluded_ids),
        duplicate_master_ids=sum(1 for count in seen_all.values() if count > 1),
        open_schemes=len(open_ids & eligible_ids),
        closing_soon=len(closing_soon_ids & eligible_ids),
        upcoming=len(upcoming_ids & eligible_ids),
        closed_historical=len(closed_ids & (eligible_ids | application_call_ids | excluded_ids)),
        verification_required=len(verify_ids),
        record_kind_distribution=dict(sorted(kind_counts.items())),
    )


def validate_batches(policy: dict[str, Any], sources: list[RegistrySource]) -> list[str]:
    known_source_ids = {source.source_id for source in sources}
    errors: list[str] = []
    used: Counter[str] = Counter()
    for batch in policy.get("batches", []):
        batch_id = clean(batch.get("batch_id"))
        for source_id in batch.get("source_ids", []):
            used[source_id] += 1
            if source_id not in known_source_ids:
                errors.append(f"{batch_id}: unknown source_id {source_id}")
    duplicates = sorted(source_id for source_id, count in used.items() if count > 1)
    if duplicates:
        errors.append("source IDs assigned to multiple v3.3.1 batches: " + ", ".join(duplicates))
    return errors


def batch_sources(batch: dict[str, Any], sources: list[RegistrySource]) -> list[RegistrySource]:
    by_id = {source.source_id: source for source in sources}
    return [by_id[source_id] for source_id in batch.get("source_ids", []) if source_id in by_id]


def planned_batch_report(
    *,
    project_root: Path | None = None,
    batch_id: str,
    run_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
    root = project_root or project_root_from_file()
    policy = load_policy(root)
    sources, _registry = load_registry_sources(root)
    errors = validate_batches(policy, sources)
    if errors:
        raise ValueError("; ".join(errors))

    batch = next((item for item in policy["batches"] if item["batch_id"] == batch_id), None)
    if batch is None:
        raise ValueError(f"Unknown v3.3.1 batch_id: {batch_id}")

    selected_sources = batch_sources(batch, sources)
    rows = existing_catalogue_rows(root)
    counts = summarize_catalogue_count(rows, policy)
    safe_run_id = run_id or datetime.now(timezone.utc).strftime(f"{batch_id}_%Y%m%dT%H%M%SZ")
    output_root = root / policy["output_contract"]["root"] / safe_run_id
    output_root.mkdir(parents=True, exist_ok=True)

    report = {
        "version": VERSION,
        "generated_at": utc_now(),
        "run_id": safe_run_id,
        "run_folder": str(output_root),
        "batch_id": batch_id,
        "batch_title": batch["title"],
        "dry_run": True,
        "network_requests_performed": 0,
        "database_writes_performed": 0,
        "stop_after_batch": bool(batch.get("stop_after_batch", True)),
        "network_discovery_status": "NOT_STARTED_APPROVAL_REQUIRED",
        "pipeline_steps": policy["pipeline_steps"],
        "sources_processed": [source.source_id for source in selected_sources],
        "registry_batch_ids": batch.get("registry_batch_ids", []),
        "seed_url_count": sum(len(source.seed_urls) for source in selected_sources),
        "planned_seed_urls": [
            {"source_id": source.source_id, "seed_urls": list(source.seed_urls)}
            for source in selected_sources
        ],
        "batch_target_unique_master_records": batch["target_unique_master_records"],
        "current_catalogue_count_policy": asdict(counts),
        "batch_metrics": {
            "pages_requested": 0,
            "successful_fetches": 0,
            "failed_fetches": 0,
            "discovered_urls": 0,
            "relevant_classified_pages": 0,
            "master_candidates": 0,
            "unique_master_records": 0,
            "duplicates_merged": 0,
            "core_pages_resolved": 0,
            "records_ready_for_extraction": 0,
            "records_requiring_browser_fallback": 0,
            "validation_results": {},
            "cumulative_catalogue_count": counts.eligible_unique_master_records,
        },
        "safety": {
            "dashboard_source_code_modified": False,
            "production_database_modified": False,
            "publication_tables_modified": False,
            "admin_review_decisions_modified": False,
            "automatic_publication": False,
        },
    }

    report_path = output_root / policy["output_contract"]["batch_report_file"]
    checkpoint_path = output_root / policy["output_contract"]["checkpoint_file"]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    checkpoint = {
        "version": VERSION,
        "run_id": safe_run_id,
        "batch_id": batch_id,
        "status": "PREFLIGHT_COMPLETE_WAITING_FOR_APPROVAL",
        "completed_steps": ["batch_planning", "count_policy_audit", "checkpoint_created"],
        "next_step": "controlled_network_discovery_pilot",
        "network_requests_performed": 0,
        "database_writes_performed": 0,
        "report_path": str(report_path),
    }
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, report_path
