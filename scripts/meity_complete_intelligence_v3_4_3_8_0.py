from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_complete_intelligence_v3_4_3_8_0 import (  # noqa: E402
    run_pipeline,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        default=".",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "live-preview",
            "repository-evidence-only",
        ),
        default="live-preview",
    )
    parser.add_argument(
        "--json",
        action="store_true",
    )
    args = parser.parse_args()

    result = run_pipeline(
        Path(
            args.project_root
        ).resolve(),
        live_network=(
            args.mode
            == "live-preview"
        ),
    )
    print(
        json.dumps(
            result,
            ensure_ascii=(
                True
                if args.json
                else False
            ),
            indent=(
                None
                if args.json
                else 2
            ),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
