from __future__ import annotations

"""Build media review workspaces and project approved records."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.review_v3_4_7_3 import (  # noqa: E402
    build_review_workspace,
    project_validated_records,
    rollback_media_publication,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the append-only SSIP media review/publication stage.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ingest-date", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--publish-validated", action="store_true", help="Project only APPROVE decisions")
    parser.add_argument("--rollback", metavar="RUN_ID", help="Activate a prior immutable publication run")
    args = parser.parse_args()
    if args.rollback:
        result = rollback_media_publication(args.project_root, args.rollback)
    elif args.publish_validated:
        result = project_validated_records(args.project_root, args.ingest_date)
    else:
        result = asdict(build_review_workspace(args.project_root, args.ingest_date))
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
