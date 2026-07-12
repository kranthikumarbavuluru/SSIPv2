from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.common import atomic_write_json, canonical_key, dashboard_public_ids, first, load_json, read_csv, sha256_file
from scripts.validate_governed_agent_run_v1 import validate_run
from scripts.verify_dashboard_source_v1 import verify


def approval_is_valid(path: Path | None, run_id: str) -> bool:
    if not path or not path.exists():
        return False
    rows, _ = read_csv(path)
    return any(
        row.get("run_id", "").strip() == run_id
        and row.get("proposed_action", "").strip() == "APPROVE_PUBLICATION"
        and row.get("approved_by", "").strip()
        and row.get("approval_date", "").strip()
        for row in rows
    )


def _backup_current(root: Path, config: dict, stamp: str) -> Path:
    backup = root / "backups/governed_publication" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    active = root / config["active_catalogue"]
    shutil.copy2(active, backup / "active_catalogue_before_publication.csv")
    current = root / config["publication_root"] / "current"
    if current.exists() and any(current.iterdir()):
        shutil.copytree(current, backup / "current_publication_before_update")
    else:
        (backup / "current_was_absent.txt").write_text("true\n", encoding="ascii")
    atomic_write_json(backup / "publication_manifest.json", {
        "backup_created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "active_catalogue_sha256": sha256_file(active),
    })
    return backup


def _restore_current(root: Path, config: dict, backup: Path) -> None:
    current = root / config["publication_root"] / "current"
    previous = backup / "current_publication_before_update"
    current.mkdir(parents=True, exist_ok=True)
    if previous.exists():
        previous_names = {source.name for source in previous.iterdir() if source.is_file()}
        for name in ("public_catalogue.csv", "calls_and_opportunities.csv", "ecosystem_directory.csv", "publication_manifest.json"):
            path = current / name
            if path.exists() and name not in previous_names:
                path.unlink()
        for source in previous.iterdir():
            if source.is_file():
                temporary = current / (source.name + ".rollback.tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, current / source.name)
    elif (backup / "current_was_absent.txt").exists():
        for name in ("public_catalogue.csv", "calls_and_opportunities.csv", "ecosystem_directory.csv", "publication_manifest.json"):
            path = current / name
            if path.exists():
                path.unlink()


def publish(
    root: Path,
    run_id: str,
    approval_file: Path | None,
    deletion_approval: Path | None = None,
    allow_large_change: bool = False,
) -> dict:
    config = load_json(root / "config/governed_agents_v1.json")
    if not approval_is_valid(approval_file, run_id):
        raise PermissionError("Publication requires a completed APPROVE_PUBLICATION approval file.")
    run_dir = root / config["run_root"] / run_id
    validation = validate_run(root, run_id, deletion_approval, write_result=False)
    if not validation["passed"]:
        raise RuntimeError("Publication validation failed; the staged run remains unpublished.")
    candidate_rows, _ = read_csv(run_dir / "publication_candidate.csv")
    candidate_ids = {row.get("scheme_master_id", "") or row.get("master_id", "") for row in candidate_rows}
    active_path = root / config["active_catalogue"]
    active_ids = dashboard_public_ids(root, active_path)
    active_rows, _ = read_csv(active_path)
    active_names = {first(row, "master_id", "scheme_master_id"): first(row, "scheme_name", "canonical_name") for row in active_rows}
    candidate_names = {first(row, "scheme_master_id", "master_id"): first(row, "canonical_name", "scheme_name") for row in candidate_rows}
    renamed = [
        master_id for master_id in active_ids & candidate_ids
        if canonical_key(active_names.get(master_id, "")) != canonical_key(candidate_names.get(master_id, ""))
    ]
    if renamed:
        raise RuntimeError(f"Canonical renames are not automatic; review required for master IDs: {', '.join(sorted(renamed))}")
    change_percent = 100.0 * len(active_ids.symmetric_difference(candidate_ids)) / max(len(active_ids), 1)
    threshold = float(config["publication"]["maximum_change_percent_without_override"])
    if change_percent > threshold and not allow_large_change:
        raise RuntimeError(f"Change rate {change_percent:.2f}% exceeds {threshold:.2f}%; --allow-large-change is required.")
    if len(candidate_ids) < len(active_ids) and not deletion_approval:
        raise RuntimeError("Publication would reduce the public count and requires an explicit deletion-approval CSV.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = _backup_current(root, config, stamp)
    publication_root = root / config["publication_root"]
    approved = publication_root / "approved" / run_id
    if approved.exists():
        raise FileExistsError(f"Approved publication already exists: {approved}")
    approved.mkdir(parents=True)
    files = {
        "public_catalogue.csv": run_dir / "publication_candidate.csv",
        "calls_and_opportunities.csv": run_dir / "call_instances.csv",
        "ecosystem_directory.csv": run_dir / "ecosystem_entities.csv",
    }
    for name, source in files.items():
        shutil.copy2(source, approved / name)
    manifest = {
        "run_id": run_id,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation_passed": True,
        "public_catalogue_sha256": sha256_file(approved / "public_catalogue.csv"),
        "calls_sha256": sha256_file(approved / "calls_and_opportunities.csv"),
        "ecosystem_sha256": sha256_file(approved / "ecosystem_directory.csv"),
        "active_fallback_sha256": sha256_file(root / config["active_catalogue"]),
        "change_percent": round(change_percent, 3),
        "backup_location": str(backup),
    }
    atomic_write_json(approved / "publication_manifest.json", manifest)
    current = publication_root / "current"
    current.mkdir(parents=True, exist_ok=True)
    try:
        for name in (*files.keys(), "publication_manifest.json"):
            temporary = current / (name + ".publish.tmp")
            shutil.copy2(approved / name, temporary)
            os.replace(temporary, current / name)
        verification = verify(root)
        if not verification.get("valid") or verification.get("source_status") != "APPROVED_PUBLICATION_AVAILABLE":
            raise RuntimeError("Post-publication verification failed.")
        atomic_write_json(root / config["approved_manifest"], manifest)
    except Exception:
        _restore_current(root, config, backup)
        raise
    return {"published": True, "run_id": run_id, "approved_directory": str(approved), "current_directory": str(current), "backup_location": str(backup), "verification": verification}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an explicitly approved governed-agent run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-file", required=True, type=Path)
    parser.add_argument("--deletion-approval", type=Path)
    parser.add_argument("--allow-large-change", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    result = publish(
        args.project_root.resolve(), args.run_id, args.approval_file.resolve(),
        args.deletion_approval.resolve() if args.deletion_approval else None,
        args.allow_large_change,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
