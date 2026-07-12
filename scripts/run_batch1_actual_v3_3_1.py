from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.batch1_actual_runner_v3_3_1 import run_batch1_actual  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SSIP v3.3.1 Batch 1 actual controlled expansion.")
    parser.add_argument("--allow-network", action="store_true", help="Required to perform the approved controlled network discovery.")
    parser.add_argument("--run-id", default="", help="Optional timestamped run folder ID.")
    parser.add_argument("--max-total-pages", type=int, default=250, help="Maximum fetched pages across all Batch 1 sources.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.allow_network:
        raise SystemExit("Refusing to run network discovery without --allow-network.")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("batch_1_actual_v3_3_1_%Y%m%dT%H%M%SZ")
    output_dir = run_batch1_actual(PROJECT_ROOT, run_id, max_total_pages=args.max_total_pages)
    summary_path = output_dir / "source_summary.json"
    validation_path = output_dir / "validation_summary_v3_3_1.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    print("SSIP v3.3.1 Batch 1 actual controlled run complete")
    print(f"Run ID: {run_id}")
    print(f"Run folder: {output_dir}")
    print(f"Sources processed: {len(summary['sources_processed'])}")
    print(f"Network requests: {summary['requested_pages']}")
    print(f"Successful fetches: {summary['successful_fetches']}")
    print(f"Failed fetches: {summary['failed_fetches']}")
    print(f"Robots denied: {summary['robots_denied']}")
    print(f"Unique discovered URLs: {summary['unique_discovered_urls']}")
    print(f"Relevant classified pages: {summary['scheme_related_candidates']}")
    print(f"Validated new scheme/programme records: {validation['validated_new_scheme_programme_records']}")
    print(f"Review-required records: {validation['review_required_records']}")
    print(f"Rejected records: {validation['rejected_records']}")
    print(f"Cumulative preview scheme count: {validation['cumulative_preview_scheme_count']}")
    print("Database writes performed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
