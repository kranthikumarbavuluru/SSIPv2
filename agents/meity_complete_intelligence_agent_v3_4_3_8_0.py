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
    parser = argparse.ArgumentParser(
        description=(
            "Nightly-ready governed MeitY "
            "complete intelligence agent. "
            "It creates preview inventories only."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
    )
    args = parser.parse_args()

    result = run_pipeline(
        Path(
            args.project_root
        ).resolve(),
        live_network=(
            not args.no_network
        ),
    )
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )
    if result.get(
        "database_write_performed"
    ):
        raise RuntimeError(
            "Governance violation: "
            "database write reported."
        )
    if result.get(
        "publication_performed"
    ):
        raise RuntimeError(
            "Governance violation: "
            "publication reported."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
