from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_calls_admin_bridge_v3_4_3_7_5 import (  # noqa: E402
    MeitYCallsAdminBridge,
    MeitYCallsBridgePaths,
)
from services.meity_calls_recovery_v3_4_3_7_5 import (  # noqa: E402
    MeitYCallsRecovery,
    RecoveryPaths,
    self_test,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--bridge-plan", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()

    if args.self_test:
        tests = self_test()
        payload = {
            "version": "3.4.3.7.5",
            "tests": tests,
            "passed": all(tests.values()),
        }
        print(json.dumps(payload, indent=2))
        return 0 if payload["passed"] else 1

    if args.bridge_plan:
        payload = MeitYCallsAdminBridge(
            MeitYCallsBridgePaths.defaults(root)
        ).run(apply=False)
    else:
        payload = MeitYCallsRecovery(
            RecoveryPaths.defaults(root)
        ).run(network=not args.no_network)

    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

