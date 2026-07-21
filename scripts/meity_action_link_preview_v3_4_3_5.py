from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.action_link_agent_v3_4_3_5 import run_inventory


def validate_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "HYGIENE_INVENTORY_ONLY"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["source_row_count"] >= 141
    assert summary["detected_meity_row_count"] >= 4
    assert summary["inventory_row_count"] > 0
    assert summary["excluded_non_scheme_utility_row_count"] >= 10
    assert summary["required_entities_visible"]["SASACT"] is True
    assert summary["required_entities_visible"]["GENESIS"] is True
    assert summary["classification_performed"] is False
    assert summary["network_requests"] == 0
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert all(summary["safety"].values())

    forbidden_reasons = summary["quarantine_counts"]
    assert forbidden_reasons.get("LOCAL_OR_PRIVATE_ENDPOINT", 0) == 0 or (
        summary["quarantined_inventory_row_count"] > 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 preview-only hygienic action-link inventory builder."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Build the hygienic inventory and enforce all safety checks.",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Build the hygienic URL inventory without network access or classification.",
    )
    args = parser.parse_args()

    if not args.self_test and not args.inventory_only:
        args.inventory_only = True

    summary = run_inventory(PROJECT_ROOT)
    validate_summary(summary)

    if args.self_test:
        print("MeitY v3.4.3.5 hygienic action-link inventory self-test: PASS")
        return 0

    print("SSIP MeitY v3.4.3.5 hygienic action-link inventory")
    print("----------------------------------------------------")
    print(f"Source candidate rows:        {summary['source_row_count']}")
    print(f"Detected MeitY scheme rows:   {summary['detected_meity_row_count']}")
    print(
        "Excluded utility rows:        "
        f"{summary['excluded_non_scheme_utility_row_count']}"
    )
    print(
        "Raw URL records:              "
        f"{summary['raw_url_record_count_before_hygiene']}"
    )
    print(f"Clean inventory rows:         {summary['inventory_row_count']}")
    print(
        "Quarantined URL rows:         "
        f"{summary['quarantined_inventory_row_count']}"
    )
    print(f"Unique clean URLs:            {summary['unique_normalized_url_count']}")
    print(f"SASACT visible:               {summary['required_entities_visible']['SASACT']}")
    print(f"GENESIS visible:              {summary['required_entities_visible']['GENESIS']}")
    print(f"Network requests:             {summary['network_requests']}")
    print(f"Classification performed:     {summary['classification_performed']}")
    print(f"Database modified:            {not summary['safety']['database_files_unchanged']}")
    print(
        "Dashboard code modified:      "
        f"{not summary['safety']['dashboard_python_files_unchanged']}"
    )
    print(f"Publication performed:        {summary['publication_performed']}")
    print()
    print("Quarantine reasons:")
    if summary["quarantine_counts"]:
        for reason, count in sorted(summary["quarantine_counts"].items()):
            print(f"  {reason}: {count}")
    else:
        print("  None")
    print()
    print(f"Inventory:  {PROJECT_ROOT / summary['inventory_path']}")
    print(f"Quarantine: {PROJECT_ROOT / summary['quarantine_path']}")
    print(
        "Summary:    "
        + str(
            PROJECT_ROOT
            / "data"
            / "departments"
            / "meity"
            / "v3_4_3_5"
            / "meity_action_link_inventory_summary_v3_4_3_5.json"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
