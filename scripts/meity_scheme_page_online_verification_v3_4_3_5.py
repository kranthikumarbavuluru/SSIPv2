from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.action_link_online_verifier_v3_4_3_5 import (
    DEFAULT_TIMEOUT_SECONDS,
    run_content_evidence_policy_self_test,
    run_online_verification,
    run_preflight,
)


def validate_online_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "ONLINE_SCHEME_PAGE_VERIFICATION"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["selected_candidate_count"] == 4
    assert summary["network_verification_attempts"] == 4
    assert summary["result_row_count"] == 4
    assert summary["apply_now_button_count"] == 0
    assert summary["open_call_button_count"] == 0
    assert summary["pdf_requests"] == 0
    assert summary["quarantined_link_requests"] == 0
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert summary["release_readiness_status"] in {
        "PASS",
        "PASS_WITH_REVIEW",
    }
    assert all(summary["safety"].values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 controlled online scheme-page verifier."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run a zero-network preflight proving that exactly four official "
            "HTML scheme pages—and no documents—are selected."
        ),
    )
    parser.add_argument(
        "--verify-online",
        action="store_true",
        help="Fetch and verify the four selected official MeitY scheme pages.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-page network timeout in seconds; default is 25.",
    )
    args = parser.parse_args()

    if args.timeout < 5 or args.timeout > 90:
        parser.error("--timeout must be between 5 and 90 seconds.")

    if args.self_test:
        preflight = run_preflight(PROJECT_ROOT)
        policy_test = run_content_evidence_policy_self_test()
        assert preflight["preflight_passed"] is True
        assert preflight["selected_candidate_count"] == 4
        assert preflight["network_requests"] == 0
        assert policy_test["passed"] is True
        print(
            "MeitY v3.4.3.5 online scheme-page verification "
            "preflight self-test: PASS"
        )
        print(
            "Content-evidence-only verification policy self-test: PASS"
        )
        print("Selected candidates:")
        for name, url in zip(
            preflight["selected_names"],
            preflight["selected_urls"],
        ):
            print(f"  {name}: {url}")
        print("Network requests: 0")
        return 0

    if not args.verify_online:
        parser.error("Choose --self-test or --verify-online.")

    summary = run_online_verification(
        PROJECT_ROOT,
        timeout_seconds=args.timeout,
    )
    validate_online_summary(summary)

    print("SSIP MeitY v3.4.3.5 online scheme-page verification")
    print("----------------------------------------------------")
    print(
        "Release readiness status:       "
        f"{summary['release_readiness_status']}"
    )
    print(
        "Selected scheme pages:          "
        f"{summary['selected_candidate_count']}"
    )
    print(
        "Network verification attempts:  "
        f"{summary['network_verification_attempts']}"
    )
    print(
        "Verified information pages:     "
        f"{summary['verified_information_page_count']}"
    )
    print(
        "Scheme Details candidates:      "
        f"{summary['scheme_details_button_candidate_count']}"
    )
    print(
        "Pages requiring review:         "
        f"{summary['review_required_count']}"
    )
    print(f"Apply Now buttons:              {summary['apply_now_button_count']}")
    print(f"Open-call buttons:              {summary['open_call_button_count']}")
    print(f"PDF requests:                   {summary['pdf_requests']}")
    print(
        "Quarantined-link requests:      "
        f"{summary['quarantined_link_requests']}"
    )
    print(
        "Database modified:              "
        f"{not summary['safety']['database_files_unchanged']}"
    )
    print(
        "Dashboard code modified:        "
        f"{not summary['safety']['dashboard_python_files_unchanged']}"
    )
    print(
        "Publication performed:          "
        f"{summary['publication_performed']}"
    )
    print()
    print("Verification status counts:")
    for status, count in sorted(
        summary["verification_status_counts"].items()
    ):
        print(f"  {status}: {count}")
    print()
    print(f"Verification: {PROJECT_ROOT / summary['verification_path']}")
    print(
        "Summary:      "
        + str(
            PROJECT_ROOT
            / "data"
            / "departments"
            / "meity"
            / "v3_4_3_5"
            / "meity_scheme_page_online_verification_summary_v3_4_3_5.json"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
