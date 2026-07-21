from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.catalogue_action_reference_builder_v3_4_3_5 import (
    run_catalogue_action_merge,
)


def validate_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "CATALOGUE_ACTION_REFERENCE_PREVIEW"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["release_readiness_status"] == "PASS"
    assert summary["source_catalogue_rows"] == 141
    assert summary["output_catalogue_rows"] == 141
    assert summary["verified_public_action_count"] == 4
    assert summary["action_enriched_row_count"] == 4
    assert summary["scheme_details_reference_count"] == 4
    assert summary["apply_now_reference_count"] == 0
    assert summary["open_call_reference_count"] == 0
    assert summary["sasact_action_reference_present"] is True
    assert summary["genesis_action_reference_present"] is True
    assert summary["active_catalogue_modified"] is False
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert all(summary["safety"].values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 preview catalogue action-reference merger."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Build the preview catalogue and enforce all merge validations.",
    )
    parser.add_argument(
        "--build-preview",
        action="store_true",
        help="Build the v3.4.3.5 preview catalogue with governed action references.",
    )
    args = parser.parse_args()

    if not args.self_test and not args.build_preview:
        args.build_preview = True

    summary = run_catalogue_action_merge(PROJECT_ROOT)
    validate_summary(summary)

    if args.self_test:
        print(
            "MeitY v3.4.3.5 catalogue action-reference merge "
            "self-test: PASS"
        )
        return 0

    print("SSIP MeitY v3.4.3.5 catalogue action-reference preview")
    print("----------------------------------------------------")
    print(
        f"Release readiness status:       "
        f"{summary['release_readiness_status']}"
    )
    print(
        f"Source catalogue rows:          "
        f"{summary['source_catalogue_rows']}"
    )
    print(
        f"Output catalogue rows:          "
        f"{summary['output_catalogue_rows']}"
    )
    print(
        f"Verified public actions:        "
        f"{summary['verified_public_action_count']}"
    )
    print(
        f"Action-enriched rows:           "
        f"{summary['action_enriched_row_count']}"
    )
    print(
        f"Scheme Details references:      "
        f"{summary['scheme_details_reference_count']}"
    )
    print(
        f"Apply Now references:           "
        f"{summary['apply_now_reference_count']}"
    )
    print(
        f"Open-call references:           "
        f"{summary['open_call_reference_count']}"
    )
    print(
        f"SASACT action reference:        "
        f"{summary['sasact_action_reference_present']}"
    )
    print(
        f"GENESIS action reference:       "
        f"{summary['genesis_action_reference_present']}"
    )
    print(
        f"Active catalogue modified:      "
        f"{summary['active_catalogue_modified']}"
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
    print(f"Preview catalogue: {PROJECT_ROOT / summary['output_path']}")
    print(f"Validation:        {PROJECT_ROOT / summary['validation_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
