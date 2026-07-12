from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_dashboard.dst_history import load_dst_historical_archive  # noqa: E402


def build(output_dir: Path) -> dict:
    archive = load_dst_historical_archive(PROJECT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "dst_historical_archive_manifest_v1.json"
    records_path = output_dir / "dst_historical_archive_qualified_v1.csv"
    sample_path = output_dir / "dst_historical_archive_sample_v1.csv"
    exceptions_path = output_dir / "dst_historical_archive_exceptions_v1.csv"

    manifest_path.write_text(
        json.dumps(archive.manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    fields = [
        "call_id", "call_title", "closing_date", "closing_year", "archive_state",
        "relevance_group", "applicant_layer", "parent_master_id", "primary_sector",
        "secondary_sectors", "detail_url", "last_verified_at", "warnings", "blockers",
    ]

    def write_rows(path: Path, rows: list) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in rows:
                writer.writerow({
                    "call_id": item.call.call_id,
                    "call_title": item.call.call_title,
                    "closing_date": item.call.closing_date,
                    "closing_year": item.closing_year or "",
                    "archive_state": item.archive_state,
                    "relevance_group": item.relevance_group,
                    "applicant_layer": item.call.applicant_layer,
                    "parent_master_id": item.call.parent_master_id,
                    "primary_sector": item.call.primary_sector,
                    "secondary_sectors": item.call.secondary_sectors,
                    "detail_url": item.call.detail_url,
                    "last_verified_at": item.call.last_verified_at,
                    "warnings": " | ".join(item.warnings),
                    "blockers": " | ".join(item.blocking_gaps),
                })

    qualified = archive.historical_records
    by_id = {item.call.call_id: item for item in qualified}
    write_rows(records_path, qualified)
    write_rows(sample_path, [by_id[item_id] for item_id in archive.manifest["sample_ids"] if item_id in by_id])
    write_rows(exceptions_path, archive.exceptions)
    return {
        "manifest": str(manifest_path),
        "qualified_records": str(records_path),
        "sample": str(sample_path),
        "exceptions": str(exceptions_path),
        "signature": archive.manifest["signature"],
        "qualified_count": len(qualified),
        "sample_count": len(archive.manifest["sample_ids"]),
        "exception_count": len(archive.exceptions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the governed DST historical-call archive preview.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data/departments/dst/pilot_v1/archive_v1",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()

