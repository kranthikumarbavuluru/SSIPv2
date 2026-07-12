from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.common import load_json, sha256_file
from scripts.publish_approved_agent_run_v1 import _restore_current
from scripts.verify_dashboard_source_v1 import verify


def rollback(root: Path, backup_name: str | None = None) -> dict:
    config = load_json(root / "config/governed_agents_v1.json")
    backup_root = root / "backups/governed_publication"
    if backup_name:
        backup = backup_root / backup_name
    else:
        candidates = sorted(path for path in backup_root.iterdir() if path.is_dir()) if backup_root.exists() else []
        if not candidates:
            raise FileNotFoundError("No governed-publication backup is available.")
        backup = candidates[-1]
    expected_active_hash = load_json(backup / "publication_manifest.json")["active_catalogue_sha256"]
    active = root / config["active_catalogue"]
    if sha256_file(active) != expected_active_hash:
        raise RuntimeError("Protected active fallback differs from the publication backup; rollback aborted.")
    _restore_current(root, config, backup)
    return {"rolled_back": True, "backup_location": str(backup), "dashboard_source": verify(root)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Rollback the last approved publication snapshot.")
    parser.add_argument("--backup-name")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    print(json.dumps(rollback(args.project_root.resolve(), args.backup_name), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
