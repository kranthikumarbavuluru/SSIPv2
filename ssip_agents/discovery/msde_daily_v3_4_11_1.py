from __future__ import annotations

"""Read-only daily discovery planner for the MSDE publication surface.

The planner is intentionally separate from publication.  It reads the governed
source registry, produces an incremental run report, and never changes the
catalogue database or promotes a record.  A later approved crawler can consume
the same batch without changing the public contract.
"""

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .source_registry_loader_v3_3 import build_dry_run_report, load_registry_sources


VERSION = "3.4.11.1"
BATCH_ID = "msde_scheme_sources"
STATE_RELATIVE_PATH = Path("outputs/msde_discovery_v3_4_11_1/state.json")
REPORT_ROOT = Path("outputs/msde_discovery_v3_4_11_1")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise_run_date(value: str | date | None) -> str:
    if value is None:
        return datetime.now().astimezone().date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()[:10]).isoformat()


def _read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _batch_from_report(report: dict[str, Any]) -> dict[str, Any]:
    return next(
        (batch for batch in report.get("planned_discovery_batches", []) if batch.get("batch_id") == BATCH_ID),
        {"batch_id": BATCH_ID, "source_count": 0, "seed_url_count": 0, "sources": []},
    )


def build_msde_daily_report(project_root: Path, run_date: str | date | None = None) -> dict[str, Any]:
    root = project_root.resolve()
    run_day = _normalise_run_date(run_date)
    registry_sources, _registry = load_registry_sources(root)
    registry_report = build_dry_run_report(root)
    batch = _batch_from_report(registry_report)
    msde_sources = [source for source in registry_sources if source.source_id in {
        item.get("source_id") for item in batch.get("sources", [])
    }]
    source_payload = [
        {
            "source_id": source.source_id,
            "official_url": source.official_url,
            "seed_urls": list(source.seed_urls),
            "max_depth": source.max_depth,
            "max_pages_per_seed": source.max_pages_per_seed,
        }
        for source in sorted(msde_sources, key=lambda item: item.source_id)
    ]
    fingerprint = sha256(json.dumps(source_payload, sort_keys=True).encode("utf-8")).hexdigest()
    state_path = root / STATE_RELATIVE_PATH
    previous = _read_state(state_path)
    changed = previous.get("fingerprint") != fingerprint
    manifest_path = root / "data/departments/msde/v3_4_11_0/active_publication_manifest_v3_4_11_0.json"
    manifest = _read_state(manifest_path)
    return {
        "version": VERSION,
        "run_id": f"msde_daily_{run_day.replace('-', '')}",
        "run_date": run_day,
        "generated_at": _utc_now(),
        "mode": "DRY_RUN_REGISTRY_REFRESH",
        "network_requests_performed": 0,
        "database_writes_performed": 0,
        "publication_performed": False,
        "batch_id": BATCH_ID,
        "source_count": len(msde_sources),
        "seed_url_count": sum(len(source.seed_urls) for source in msde_sources),
        "sources": source_payload,
        "incremental": {
            "changed_since_last_run": changed,
            "previous_run_id": previous.get("run_id", ""),
            "skipped_unchanged_source_count": 0 if changed else len(msde_sources),
            "fingerprint": fingerprint,
        },
        "publication_snapshot": {
            "manifest_path": str(manifest_path),
            "run_id": manifest.get("run_id", ""),
            "record_count": manifest.get("record_count", 0),
            "source_last_verified": manifest.get("source_last_verified", ""),
        },
        "registry_audit": {
            "total_enabled_sources": registry_report.get("total_enabled_sources", 0),
            "missing_authority_mappings": registry_report.get("missing_authority_mappings", []),
            "missing_trusted_domain_mappings": registry_report.get("missing_trusted_domain_mappings", []),
        },
        "next_action": "Run approved network extraction and field-level validation; do not promote records from this planner alone.",
    }


def write_msde_daily_report(project_root: Path, run_date: str | date | None = None) -> Path:
    root = project_root.resolve()
    report = build_msde_daily_report(root, run_date)
    report_path = root / REPORT_ROOT / report["run_date"] / "run_report.json"
    _write_json(report_path, report)
    state_path = root / STATE_RELATIVE_PATH
    _write_json(
        state_path,
        {
            "version": VERSION,
            "run_id": report["run_id"],
            "run_date": report["run_date"],
            "generated_at": report["generated_at"],
            "fingerprint": report["incremental"]["fingerprint"],
        },
    )
    return report_path
