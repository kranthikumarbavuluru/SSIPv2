from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.source_registry_loader_v3_3 import (  # noqa: E402
    build_dry_run_report,
    write_dry_run_report,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SSIP v3.3.0 official-source registry discovery planner."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Plan discovery and write a dry-run report without network requests. This is the only supported mode in v3.3.0.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional versioned run folder name under outputs/catalogue_discovery_v3_3.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the dry-run report without writing a run folder.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Reserved for a later approved phase. v3.3.0 refuses network execution.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.allow_network:
        raise SystemExit(
            "Network crawl is intentionally disabled for SSIP v3.3.0. Run dry-run only and seek approval first."
        )

    if args.print_only:
        report = build_dry_run_report(PROJECT_ROOT)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    report_path = write_dry_run_report(PROJECT_ROOT, run_id=args.run_id or None)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    print("SSIP v3.3.0 dry-run report generated")
    print(f"Run folder: {report['run_folder']}")
    print(f"Report: {report_path}")
    print(f"Enabled sources: {report['total_enabled_sources']}")
    print(f"Central sources: {report['central_sources']}")
    print(f"State/UT sources: {report['state_ut_sources']}")
    print(f"Seed URLs: {report['seed_url_count']}")
    print(f"Duplicate seed URLs: {len(report['duplicate_seed_urls'])}")
    print(f"Missing authority mappings: {len(report['missing_authority_mappings'])}")
    print(f"Missing trusted-domain mappings: {len(report['missing_trusted_domain_mappings'])}")
    print(f"Planned batches: {len(report['planned_discovery_batches'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
