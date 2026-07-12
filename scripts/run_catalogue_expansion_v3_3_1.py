from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.catalogue_expansion_planner_v3_3_1 import (  # noqa: E402
    planned_batch_report,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSIP v3.3.1 catalogue expansion preflight runner.")
    parser.add_argument(
        "--batch-id",
        default="batch_1_enterprise_startup_indexes",
        help="v3.3.1 batch ID to prepare. Default: Batch 1 only.",
    )
    parser.add_argument("--run-id", default="", help="Optional versioned run folder name.")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Reserved for a later approved phase. This runner refuses network execution.",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print generated report JSON after writing the versioned output files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.allow_network:
        raise SystemExit(
            "Network discovery is not enabled in SSIP v3.3.1 preflight. "
            "Start Batch 1 only after the controlled network-discovery pilot is explicitly approved."
        )
    report, report_path = planned_batch_report(
        project_root=PROJECT_ROOT,
        batch_id=args.batch_id,
        run_id=args.run_id or None,
    )
    print("SSIP v3.3.1 batch preflight generated")
    print(f"Batch: {report['batch_id']}")
    print(f"Run folder: {report['run_folder']}")
    print(f"Report: {report_path}")
    print(f"Sources processed: {len(report['sources_processed'])}")
    print(f"Seed URLs: {report['seed_url_count']}")
    print(f"Current eligible catalogue count: {report['current_catalogue_count_policy']['eligible_unique_master_records']}")
    print("Network requests performed: 0")
    print("Database writes performed: 0")
    if args.print_report:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
