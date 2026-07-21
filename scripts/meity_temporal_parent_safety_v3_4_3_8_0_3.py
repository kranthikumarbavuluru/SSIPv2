from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_temporal_parent_safety_v3_4_3_8_0_3 import (  # noqa: E402
    run_safety_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--today", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else None
    result = run_safety_gate(
        Path(args.project_root).resolve(),
        today=today,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=args.json,
            indent=None if args.json else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
