from __future__ import annotations

"""Run the date-based incremental media pipeline."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.automation_v3_4_7_4 import run_incremental_media_pipeline  # noqa: E402
from ssip_agents.media.review_v3_4_7_3 import rollback_media_publication  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SSIP media intake, extraction, mapping and review automation.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ingest-date", default=None, help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--publish-validated", action="store_true")
    parser.add_argument("--rollback", metavar="PUBLICATION_RUN_ID")
    args = parser.parse_args()
    if args.rollback:
        result = rollback_media_publication(args.project_root, args.rollback)
    else:
        result = run_incremental_media_pipeline(args.project_root, args.ingest_date, publish_validated=args.publish_validated)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("status", "SUCCEEDED") != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
