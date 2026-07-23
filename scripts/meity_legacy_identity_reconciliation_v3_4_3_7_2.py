from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_identity_reconciliation_v3_4_3_7_2 import (
    MeitYLegacyIdentityReconciliationBridge,
    MeitYReconciliationPaths,
)


def print_report(report: dict) -> None:
    print()
    print(
        "SSIP v3.4.3.7.2 - Legacy Rejected Identity Reconciliation"
    )
    print("-" * 68)
    print(f"Dry run:                         {report['dry_run']}")
    print(
        f"Source records:                  "
        f"{report['source_queue_count']}"
    )
    print(
        f"Canonical replacements:          "
        f"{report['reconciliation_count']}"
    )
    print(
        f"New pending:                     "
        f"{report['proposed_insert_count']}"
    )
    print(
        f"Pending updates:                 "
        f"{report['proposed_update_count']}"
    )
    print(
        f"Duplicates skipped:              "
        f"{report['skipped_semantic_duplicate_count']}"
    )
    print(
        f"Legacy decisions protected:      "
        f"{report['legacy_rejection_history_protected_count']}"
    )
    print(
        f"Application calls:               "
        f"{report['application_call_count']}"
    )
    print(
        f"Verified current MeitY calls:    "
        f"{report['verified_current_call_count']}"
    )
    print(
        f"Database modified:               "
        f"{report['database_modified']}"
    )
    print(
        f"Publication performed:           "
        f"{report['publication_performed']}"
    )
    print(
        f"Plan signature:                  "
        f"{report['plan_signature']}"
    )
    print()
    for action in report["actions"]:
        reconciliation = action.get("reconciliation") or {}
        suffix = (
            " <- legacy "
            + reconciliation["legacy_master_id"]
            if reconciliation
            else ""
        )
        print(
            f"- {action['scheme_name']}: "
            f"{action['action']}{suffix}"
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
        else None
    )
    bridge = MeitYLegacyIdentityReconciliationBridge(
        MeitYReconciliationPaths.defaults(
            root,
            database,
        )
    )
    report = bridge.run(
        apply=args.apply,
        expected_signature=args.signature,
    )
    if args.json:
        print(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

