from __future__ import annotations

"""Run the non-destructive SSIP v3.4.7.0 media foundation scan."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.intake_v3_4_7_0 import parse_ingest_date, scan_media_batch  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register dated SSIP media inbox files without modifying them."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="SSIP project root (defaults to the repository root).",
    )
    parser.add_argument(
        "--ingest-date",
        default=None,
        help="Inbox date in YYYY-MM-DD format (defaults to today).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    ingest_date = parse_ingest_date(args.ingest_date)
    report = scan_media_batch(args.project_root, ingest_date)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
