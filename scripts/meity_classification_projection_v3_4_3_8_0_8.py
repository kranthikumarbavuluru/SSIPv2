from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_classification_projection_v3_4_3_8_0_8 import (  # noqa: E402
    build_service,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-signature", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--actor", default="Admin")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    service = build_service(Path(args.project_root).resolve())
    if args.apply:
        result = service.apply_projection(
            expected_signature=args.expected_signature,
            confirmation=args.confirmation,
            actor=args.actor,
        )
    else:
        result = service.build_preview()

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
