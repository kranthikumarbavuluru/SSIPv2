from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_admin_bridge_v3_4_3_7_1 import (  # noqa: E402
    MeitYAdminBridge,
    MeitYBridgePaths,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="SSIP v3.4.3.7.1 MeitY Admin Workspace bridge")
    parser.add_argument("--apply", action="store_true", help="Import the reviewed plan into admin_review_queue")
    parser.add_argument("--expected-signature", default="", help="Exact dry-run signature required for --apply")
    parser.add_argument("--json", action="store_true", help="Print the complete report as JSON")
    args = parser.parse_args()

    bridge = MeitYAdminBridge(MeitYBridgePaths.defaults(PROJECT_ROOT))
    report = bridge.run(apply=args.apply, expected_signature=args.expected_signature or None)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print()
    print("SSIP v3.4.3.7.1 - MeitY Admin Workspace Integration")
    print("----------------------------------------------------------")
    print(f"Dry run:                         {report['dry_run']}")
    print(f"Source records:                  {report['source_queue_count']}")
    print(f"Permanent schemes:               {report['permanent_scheme_count']}")
    print(f"Application calls:               {report['application_call_count']}")
    print(f"Verified current MeitY calls:    {report['verified_current_call_count']}")
    print(f"New pending:                     {report['proposed_insert_count']}")
    print(f"Pending updates:                 {report['proposed_update_count']}")
    print(f"Duplicates skipped:              {report['skipped_semantic_duplicate_count']}")
    print(f"Decisions protected:             {report['skipped_existing_decision_count']}")
    print(f"Database modified:               {report['database_modified']}")
    print(f"Publication performed:           {report['publication_performed']}")
    print(f"Plan signature:                  {report['plan_signature']}")
    print()
    for action in report["actions"]:
        print(f"- {action['scheme_name']}: {action['action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
