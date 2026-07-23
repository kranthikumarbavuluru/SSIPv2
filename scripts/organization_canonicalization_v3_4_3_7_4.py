from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.organization_canonicalization_v3_4_3_7_4 import (  # noqa: E402
    OrganizationCanonicalizationService,
)


def print_report(report: dict) -> None:
    print()
    print("SSIP v3.4.3.7.4 - Ministry and Department Canonicalization")
    print("-" * 72)
    print(f"Dry run:                       {report['dry_run']}")
    print(f"Change count:                  {report['change_count']}")
    print(f"Admin queue changes:           {report['table_counts'].get('admin_review_queue', 0)}")
    print(f"Staging changes:               {report['table_counts'].get('scheme_staging', 0)}")
    print(f"Master IDs preserved:          {report['master_ids_preserved']}")
    print(f"Application fields modified:   {report['application_fields_modified']}")
    print(f"Publication fields modified:   {report['publication_fields_modified']}")
    print(f"Audit history modified:        {report['audit_history_modified']}")
    print(f"Database modified:             {report['database_modified']}")
    print(f"Plan signature:                {report['plan_signature']}")
    print()
    for change in report.get("changes", []):
        print(
            f"- {change['table_name']} | {change['scheme_name']} | "
            f"{change['old_ministry']!r} / {change['old_department']!r} -> "
            f"{change['new_ministry']!r} / {change['new_department']!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--database")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--signature")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    database = (
        Path(args.database).resolve()
        if args.database
        else root / "database/ssip_staging_v1.db"
    )
    service = OrganizationCanonicalizationService(database)
    report = (
        service.apply(args.signature or "")
        if args.apply
        else service.plan()
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
