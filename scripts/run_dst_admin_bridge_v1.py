from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.dst_pilot.admin_bridge import BridgePaths, DSTAdminBridge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or apply the DST pilot import into the existing SSIP admin-review queue.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write only planned new/pending records. Omit for the mandatory dry-run.")
    args = parser.parse_args()
    report = DSTAdminBridge(BridgePaths.defaults(args.project_root)).run(apply=args.apply)
    summary = {key: value for key, value in report.items() if key not in {"actions"}}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
