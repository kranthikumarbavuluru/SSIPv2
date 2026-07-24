from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.msde_daily_v3_4_11_1 import (  # noqa: E402
    build_msde_daily_report,
    write_msde_daily_report,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the read-only MSDE daily discovery planner.")
    parser.add_argument("--date", default="", help="Run date in YYYY-MM-DD format; defaults to local today.")
    parser.add_argument("--print-only", action="store_true", help="Print the report without writing state or a run folder.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_only:
        print(json.dumps(build_msde_daily_report(PROJECT_ROOT, args.date or None), ensure_ascii=False, indent=2))
        return 0
    report_path = write_msde_daily_report(PROJECT_ROOT, args.date or None)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("MSDE daily discovery planner completed")
    print(f"Run report: {report_path}")
    print(f"Sources: {report['source_count']} · Seed URLs: {report['seed_url_count']}")
    print(f"Changed since last run: {report['incremental']['changed_since_last_run']}")
    print("Network requests: 0 · Database writes: 0 · Publication: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
