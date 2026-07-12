from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.common import atomic_write_csv, dashboard_public_ids, first, load_json, read_csv


def compare(root: Path, run_id: str) -> dict:
    config = load_json(root / "config/governed_agents_v1.json")
    run_dir = root / config["run_root"] / run_id
    active = root / config["active_catalogue"]
    active_ids = dashboard_public_ids(root, active)
    active_rows, _ = read_csv(active)
    active_names = {first(row, "master_id", "scheme_master_id"): first(row, "scheme_name", "canonical_name") for row in active_rows}
    candidates, _ = read_csv(run_dir / "publication_candidate.csv")
    candidate_names = {first(row, "scheme_master_id", "master_id"): first(row, "canonical_name", "scheme_name") for row in candidates}
    candidate_ids = set(candidate_names)
    rows = []
    for master_id in sorted(active_ids | candidate_ids):
        in_active = master_id in active_ids
        in_candidate = master_id in candidate_ids
        rows.append({
            "master_id": master_id,
            "canonical_name": candidate_names.get(master_id, active_names.get(master_id, "")),
            "in_active_catalogue": str(in_active).lower(),
            "in_publication_candidate": str(in_candidate).lower(),
            "change_type": "UNCHANGED" if in_active and in_candidate else ("ADD" if in_candidate else "PROPOSED_REMOVAL_REQUIRES_APPROVAL"),
        })
    output = run_dir / "comparison_with_active.csv"
    atomic_write_csv(output, rows, ["master_id", "canonical_name", "in_active_catalogue", "in_publication_candidate", "change_type"])
    return {
        "run_id": run_id,
        "active_count": len(active_ids),
        "candidate_count": len(candidate_ids),
        "addition_count": len(candidate_ids - active_ids),
        "proposed_removal_count": len(active_ids - candidate_ids),
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a governed run with the active dashboard population.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    print(json.dumps(compare(args.project_root.resolve(), args.run_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
