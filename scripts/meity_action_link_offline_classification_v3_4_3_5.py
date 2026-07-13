from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.action_link_offline_classifier_v3_4_3_5 import (
    run_offline_classification,
)


def validate_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "OFFLINE_CLASSIFICATION_ONLY"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["input_inventory_row_count"] > 0
    assert summary["classified_row_count"] == summary["input_inventory_row_count"]
    assert summary["review_queue_row_count"] == (
        summary["input_inventory_row_count"]
        + summary["input_quarantine_row_count"]
    )
    assert summary["action_counts"].get("SCHEME_DETAILS", 0) >= 4
    assert summary["verification_status_counts"]["UNVERIFIED"] == (
        summary["classified_row_count"]
    )
    assert summary["public_button_eligible_count"] == 0
    assert summary["apply_now_button_count"] == 0
    assert summary["network_requests"] == 0
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert all(summary["safety"].values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 preview-only offline action-link classifier."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run offline classification and enforce all safety checks.",
    )
    parser.add_argument(
        "--offline-classify",
        action="store_true",
        help="Classify clean inventory records without network verification.",
    )
    args = parser.parse_args()

    if not args.self_test and not args.offline_classify:
        args.offline_classify = True

    summary = run_offline_classification(PROJECT_ROOT)
    validate_summary(summary)

    if args.self_test:
        print("MeitY v3.4.3.5 offline action-link classification self-test: PASS")
        return 0

    print("SSIP MeitY v3.4.3.5 offline action-link classification")
    print("----------------------------------------------------")
    print(f"Clean inventory rows:         {summary['input_inventory_row_count']}")
    print(f"Quarantined input rows:       {summary['input_quarantine_row_count']}")
    print(f"Classified rows:              {summary['classified_row_count']}")
    print(f"Review queue rows:            {summary['review_queue_row_count']}")
    print(f"Public-button eligible:       {summary['public_button_eligible_count']}")
    print(f"Apply Now buttons:            {summary['apply_now_button_count']}")
    print(f"Network requests:             {summary['network_requests']}")
    print(f"Database modified:            {not summary['safety']['database_files_unchanged']}")
    print(
        "Dashboard code modified:      "
        f"{not summary['safety']['dashboard_python_files_unchanged']}"
    )
    print(f"Publication performed:        {summary['publication_performed']}")
    print()
    print("Proposed action counts:")
    for action_type, count in sorted(summary["action_counts"].items()):
        print(f"  {action_type}: {count}")
    print()
    print(f"Classification: {PROJECT_ROOT / summary['classification_path']}")
    print(f"Review queue:   {PROJECT_ROOT / summary['review_queue_path']}")
    print(
        "Summary:        "
        + str(
            PROJECT_ROOT
            / "data"
            / "departments"
            / "meity"
            / "v3_4_3_5"
            / "meity_action_link_offline_classification_summary_v3_4_3_5.json"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
