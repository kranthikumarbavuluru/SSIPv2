from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

ACTIVE = ROOT / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv"
CURRENT_MANIFEST = ROOT / "data" / "publication" / "current_manifest.json"
LATEST_POINTER = ROOT / "data" / "publication" / "meity_v3_4_2_0_2_latest_publication.json"
AUDIT_ROOT = ROOT / "data" / "audit"
EXPECTED_IDS = {"147173e17ea741687247", "6af79cf6c8a213dddce8"}


def atomic_copy(source: Path, destination: Path) -> None:
    temp = destination.with_name(destination.name + ".tmp")
    shutil.copy2(source, temp)
    os.replace(temp, destination)


def row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def visible_count(path: Path) -> tuple[int, set[str]]:
    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    base = DashboardConfig.from_env(ROOT)
    config = replace(base, normalization_path=path.resolve(), preview_path_configured=True)
    bundle = load_catalogue(config)
    populations = split_catalogue_populations(bundle.records)
    ids = {record.master_id for record in populations.main_scheme_records if record.master_id}
    return len(ids), ids


def main() -> int:
    if not LATEST_POINTER.exists():
        raise RuntimeError(f"Publication pointer missing: {LATEST_POINTER}")
    pointer = json.loads(LATEST_POINTER.read_text(encoding="utf-8-sig"))
    rollback_dir = Path(pointer["rollback_directory"])
    backup_active = rollback_dir / "catalogue_preview_v3_3_2.csv"
    backup_manifest = rollback_dir / "current_manifest.json"
    if not backup_active.exists() or not backup_manifest.exists():
        raise RuntimeError("Rollback backup files are missing.")

    atomic_copy(backup_active, ACTIVE)
    atomic_copy(backup_manifest, CURRENT_MANIFEST)

    rows = row_count(ACTIVE)
    visible, visible_ids = visible_count(ACTIVE)
    if rows != 137 or visible != 51 or EXPECTED_IDS & visible_ids:
        raise RuntimeError(
            f"Rollback verification failed: rows={rows}, visible={visible}, "
            f"MeitY visible={sorted(EXPECTED_IDS & visible_ids)}"
        )

    audit = {
        "version": "3.4.2.0.2",
        "run_id": pointer.get("run_id"),
        "rolled_back_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "rollback_status": "PASS",
        "active_catalogue_rows": rows,
        "dashboard_visible_records": visible,
        "meity_records_visible": 0,
        "restored_from": str(rollback_dir),
    }
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    audit_path = AUDIT_ROOT / f"meity_v3_4_2_0_2_rollback_{pointer.get('run_id')}.json"
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print()
    print("SSIP MeitY v3.4.2.0.2 rollback")
    print("-----------------------------------")
    print("Rollback status:        PASS")
    print("Active catalogue rows: 137")
    print("Dashboard visible:      51")
    print("MeitY records visible:  0")
    print()
    print("Rollback audit:")
    print(audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
