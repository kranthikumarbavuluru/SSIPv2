from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_guided_decision_import_v3_4_3_8_0_6 import (  # noqa: E402
    run_decision_import,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--worksheet", required=True)
    parser.add_argument("--allow-valid-subset", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_decision_import(
        Path(args.project_root).resolve(),
        Path(args.worksheet).resolve(),
        strict=not args.allow_valid_subset,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=args.json,
            indent=None if args.json else 2,
        )
    )
    return 2 if result["plan_status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
