from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.common import (
    atomic_write_json, dashboard_public_ids, load_json, read_csv, sha256_file,
)
from agents.governed_v1.publication_guard_agent import PublicationGuardAgent


def validate_run(
    root: Path,
    run_id: str,
    deletion_approval: Path | None = None,
    write_result: bool = True,
) -> dict:
    config = load_json(root / "config/governed_agents_v1.json")
    run_dir = root / config["run_root"] / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run not found: {run_dir}")
    public_rows, _ = read_csv(run_dir / "publication_candidate.csv")
    call_rows, _ = read_csv(run_dir / "call_instances.csv")
    active = root / config["active_catalogue"]
    summary = load_json(run_dir / "summary.json")
    active_hash = sha256_file(active)
    taxonomy = {item["name"] for item in load_json(root / config["sector_taxonomy"])["sectors"]}
    result = PublicationGuardAgent().validate(
        public_rows,
        call_rows,
        dashboard_public_ids(root, active),
        (run_dir / "input_snapshot.csv").exists(),
        summary["active_catalogue_sha256_before"] == active_hash,
        taxonomy,
        deletion_approval,
    )
    payload = {"passed": result.passed, "checks": result.checks, "details": result.details}
    if write_result:
        atomic_write_json(run_dir / "validation.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a staged SSIP governed-agent run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--deletion-approval", type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    approval = args.deletion_approval.resolve() if args.deletion_approval else None
    result = validate_run(root, args.run_id, approval)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
