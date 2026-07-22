from __future__ import annotations

"""Incremental daily orchestration for the SSIP media pipeline."""

from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any

from .entity_v3_4_7_2 import build_entity_candidates
from .extraction_v3_4_7_1 import extract_media_batch
from .intake_v3_4_7_0 import MediaIntakePaths, parse_ingest_date, scan_media_batch
from .review_v3_4_7_3 import build_review_workspace, project_validated_records, rollback_media_publication


MEDIA_AUTOMATION_SCHEMA_VERSION = "3.4.7.4"


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8", newline="")
    temporary.replace(path)


def _state_path(root: Path) -> Path:
    return root / "data" / "media_runs" / "pipeline_state.json"


def _read_state(root: Path) -> dict[str, Any]:
    try:
        return json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": MEDIA_AUTOMATION_SCHEMA_VERSION, "runs": []}


def run_incremental_media_pipeline(
    project_root: Path,
    ingest_date: str | date | None = None,
    *,
    publish_validated: bool = False,
) -> dict[str, Any]:
    """Run intake → extraction → entity → review, optionally projecting approvals."""

    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    paths = MediaIntakePaths(root)
    paths.ensure_batch_layout(parsed_date)
    batch_dir = paths.batch_run(parsed_date)
    run_started = datetime.now(timezone.utc)
    run_id = f"media-pipeline-{run_started.strftime('%Y%m%dT%H%M%SZ')}"
    report: dict[str, Any] = {
        "schema_version": MEDIA_AUTOMATION_SCHEMA_VERSION,
        "run_id": run_id,
        "ingest_date": parsed_date.isoformat(),
        "started_at": run_started.isoformat(),
        "status": "RUNNING",
        "stages": {},
        "alerts": [],
        "database_modified": False,
    }
    try:
        report["stages"]["intake"] = scan_media_batch(root, parsed_date)
        report["stages"]["extraction"] = extract_media_batch(root, parsed_date)
        report["stages"]["entity"] = build_entity_candidates(root, parsed_date)
        report["stages"]["review"] = {"workspace": asdict(build_review_workspace(root, parsed_date))}
        if publish_validated:
            report["stages"]["publication"] = project_validated_records(root, parsed_date, run_id)
        report["status"] = "SUCCEEDED"
    except Exception as exc:
        report["status"] = "FAILED"
        alert = {
            "schema_version": MEDIA_AUTOMATION_SCHEMA_VERSION,
            "run_id": run_id,
            "ingest_date": parsed_date.isoformat(),
            "severity": "ERROR",
            "message": str(exc),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        report["alerts"].append(alert)
        _atomic_write(batch_dir / "failure_alert.json", json.dumps(alert, indent=2, ensure_ascii=False) + "\n")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report_path = batch_dir / "pipeline_report.json"
    archived_report_path = batch_dir / f"pipeline_report_{run_id}.json"
    report_payload = json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n"
    _atomic_write(report_path, report_payload)
    _atomic_write(archived_report_path, report_payload)
    state = _read_state(root)
    state.setdefault("runs", []).append({"run_id": run_id, "ingest_date": parsed_date.isoformat(), "status": report["status"], "report_path": archived_report_path.relative_to(root).as_posix()})
    state["runs"] = state["runs"][-365:]
    state["last_run_id"] = run_id
    state["last_run_status"] = report["status"]
    _atomic_write(_state_path(root), json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return report


__all__ = [
    "MEDIA_AUTOMATION_SCHEMA_VERSION",
    "run_incremental_media_pipeline",
    "rollback_media_publication",
]
