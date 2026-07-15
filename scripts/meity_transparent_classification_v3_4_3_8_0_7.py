from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_transparent_classification_v3_4_3_8_0_7 import (  # noqa: E402
    build_service,
    stable_json,
)


def write_inventory(project_root: Path) -> dict:
    service = build_service(project_root)
    rows = service.inventory()
    output_dir = service.paths.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = (
        output_dir
        / "meity_transparent_classification_inventory_v3_4_3_8_0_7.csv"
    )
    fields = sorted(
        {
            key
            for row in rows
            for key in row.keys()
            if key != "classification_reasons"
        }
    ) + ["classification_reasons_json"]

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            payload = {
                key: value
                for key, value in row.items()
                if key != "classification_reasons"
            }
            payload["classification_reasons_json"] = json.dumps(
                row.get("classification_reasons", []),
                ensure_ascii=False,
            )
            writer.writerow(payload)

    summary = {
        "version": "3.4.3.8.0.7",
        "record_count": len(rows),
        "suggested_counts": {},
        "database_write_performed": False,
        "publication_performed": False,
    }
    for row in rows:
        key = row.get("suggested_entity_type", "UNKNOWN")
        summary["suggested_counts"][key] = (
            summary["suggested_counts"].get(key, 0) + 1
        )
    summary["inventory_signature"] = __import__("hashlib").sha256(
        stable_json(rows).encode("utf-8")
    ).hexdigest()

    (
        output_dir
        / "meity_transparent_classification_manifest_v3_4_3_8_0_7.json"
    ).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = write_inventory(Path(args.project_root).resolve())
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
