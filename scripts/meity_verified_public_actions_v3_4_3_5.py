from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.action_link_public_action_builder_v3_4_3_5 import (
    run_public_action_builder,
)


def validate_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "VERIFIED_PUBLIC_ACTIONS_PREVIEW"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["release_readiness_status"] == "PASS"
    assert summary["verified_public_action_count"] == 4
    assert summary["scheme_details_button_count"] == 4
    assert summary["apply_now_button_count"] == 0
    assert summary["open_call_button_count"] == 0
    assert summary["guidelines_button_count"] == 0
    assert summary["manual_button_count"] == 0
    assert summary["notification_button_count"] == 0
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert summary["validation"]["passed"] is True
    assert all(summary["safety"].values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 verified public action preview builder."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Build and validate four preview-only Scheme Details actions.",
    )
    parser.add_argument(
        "--build-actions",
        action="store_true",
        help="Generate the verified public action CSV and summary.",
    )
    args = parser.parse_args()

    if not args.self_test and not args.build_actions:
        args.build_actions = True

    summary = run_public_action_builder(PROJECT_ROOT)
    validate_summary(summary)

    if args.self_test:
        print(
            "MeitY v3.4.3.5 verified public actions self-test: PASS"
        )
        return 0

    print("SSIP MeitY v3.4.3.5 verified public actions preview")
    print("----------------------------------------------------")
    print(
        f"Release readiness status:       "
        f"{summary['release_readiness_status']}"
    )
    print(
        f"Verified public actions:        "
        f"{summary['verified_public_action_count']}"
    )
    print(
        f"Scheme Details buttons:         "
        f"{summary['scheme_details_button_count']}"
    )
    print(
        f"Apply Now buttons:              "
        f"{summary['apply_now_button_count']}"
    )
    print(
        f"Open-call buttons:              "
        f"{summary['open_call_button_count']}"
    )
    print(
        f"Database modified:              "
        f"{not summary['safety']['database_files_unchanged']}"
    )
    print(
        f"Dashboard code modified:        "
        f"{not summary['safety']['dashboard_python_files_unchanged']}"
    )
    print(
        f"Publication performed:          "
        f"{summary['publication_performed']}"
    )
    print()
    print("Verified schemes:")
    for name in summary["verified_scheme_names"]:
        print(f"  {name}")
    print()
    print(f"Actions: {PROJECT_ROOT / summary['actions_path']}")
    print(
        "Summary: "
        + str(
            PROJECT_ROOT
            / "data"
            / "departments"
            / "meity"
            / "v3_4_3_5"
            / "meity_verified_public_actions_summary_v3_4_3_5.json"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
