from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_emergency_withdrawal_v3_4_3_7_7 import (  # noqa: E402
    MeitYEmergencyWithdrawal,
    WithdrawalPaths,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-signature", default="")
    parser.add_argument("--actor", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.plan == args.apply:
        parser.error("Choose exactly one of --plan or --apply.")

    root = Path(args.project_root).resolve()
    service = MeitYEmergencyWithdrawal(
        WithdrawalPaths.defaults(root)
    )

    if args.plan:
        payload = service.plan()
        payload["output_files"] = service.write_plan(payload)
    else:
        payload = service.apply(
            expected_signature=args.expected_signature,
            actor=args.actor,
            reason=args.reason,
        )

    print(
        json.dumps(
            payload,
            indent=None if args.json else 2,
            ensure_ascii=True if args.json else False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
