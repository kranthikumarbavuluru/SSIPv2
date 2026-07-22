from __future__ import annotations

"""Classify extracted media into reviewable SSIP entity candidates."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.entity_v3_4_7_2 import build_entity_candidates  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Map extracted media records to entities and departments.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ingest-date", default=None, help="YYYY-MM-DD; defaults to today")
    args = parser.parse_args()
    print(json.dumps(build_entity_candidates(args.project_root, args.ingest_date), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
