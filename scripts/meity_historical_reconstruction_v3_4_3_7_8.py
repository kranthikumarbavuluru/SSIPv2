from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_historical_reconstruction_v3_4_3_7_8 import (  # noqa: E402
    MeitYHistoricalReconstruction,
    ReconstructionPaths,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.build:
        parser.error("--build is required")

    root = Path(args.project_root).resolve()
    result = MeitYHistoricalReconstruction(
        ReconstructionPaths.defaults(root)
    ).build()
    print(
        json.dumps(
            result,
            indent=None if args.json else 2,
            ensure_ascii=True if args.json else False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
