from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.action_link_browser_verifier_v3_4_3_5 import (
    DEFAULT_TIMEOUT_MS,
    run_browser_verification,
    run_self_test,
)


def validate_summary(summary: dict) -> None:
    assert summary["version"] == "3.4.3.5"
    assert summary["stage"] == "BROWSER_RENDERED_SCHEME_PAGE_VERIFICATION"
    assert summary["execution_mode"] == "PREVIEW_ONLY"
    assert summary["selected_candidate_count"] == 4
    assert summary["browser_render_attempts"] == 4
    assert summary["result_row_count"] == 4
    assert summary["apply_now_button_count"] == 0
    assert summary["open_call_button_count"] == 0
    assert summary["pdf_requests"] == 0
    assert summary["quarantined_link_requests"] == 0
    assert summary["database_writes"] == 0
    assert summary["dashboard_code_changes"] == 0
    assert summary["publication_performed"] is False
    assert summary["release_readiness_status"] in {"PASS", "PASS_WITH_REVIEW"}
    assert all(summary["safety"].values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SSIP MeitY v3.4.3.5 Playwright rendered-DOM scheme-page verifier."
        )
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the candidate checks and launch a local about:blank browser "
            "page without internet access."
        ),
    )
    parser.add_argument(
        "--verify-rendered",
        action="store_true",
        help="Render and verify the four official MeitY scheme pages.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="Per-page Playwright timeout in milliseconds.",
    )
    args = parser.parse_args()

    if args.timeout_ms < 10_000 or args.timeout_ms > 120_000:
        parser.error("--timeout-ms must be between 10000 and 120000.")

    if args.self_test:
        result = run_self_test(PROJECT_ROOT)
        assert result["passed"] is True
        print("MeitY v3.4.3.5 browser-renderer preflight self-test: PASS")
        print(f"Browser:            {result['browser_name']}")
        print(f"Browser executable: {result['browser_executable'] or 'Playwright managed'}")
        print(f"Playwright version: {result['playwright_version']}")
        print("Selected candidates:")
        for name, url in zip(
            result["candidate_test"]["selected_names"],
            result["candidate_test"]["selected_urls"],
        ):
            print(f"  {name}: {url}")
        print("Network requests: 0")
        return 0

    if not args.verify_rendered:
        parser.error("Choose --self-test or --verify-rendered.")

    summary = run_browser_verification(
        PROJECT_ROOT,
        timeout_ms=args.timeout_ms,
    )
    validate_summary(summary)

    print("SSIP MeitY v3.4.3.5 browser-rendered scheme-page verification")
    print("----------------------------------------------------")
    print(
        f"Release readiness status:       "
        f"{summary['release_readiness_status']}"
    )
    print(f"Browser:                        {summary['browser_name']}")
    print(
        f"Selected scheme pages:          "
        f"{summary['selected_candidate_count']}"
    )
    print(
        f"Browser render attempts:        "
        f"{summary['browser_render_attempts']}"
    )
    print(
        f"Verified information pages:     "
        f"{summary['verified_information_page_count']}"
    )
    print(
        f"Scheme Details candidates:      "
        f"{summary['scheme_details_button_candidate_count']}"
    )
    print(
        f"Pages requiring review:         "
        f"{summary['review_required_count']}"
    )
    print(f"Apply Now buttons:              {summary['apply_now_button_count']}")
    print(f"Open-call buttons:              {summary['open_call_button_count']}")
    print(f"PDF requests:                   {summary['pdf_requests']}")
    print(
        f"Quarantined-link requests:      "
        f"{summary['quarantined_link_requests']}"
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
    print("Verification status counts:")
    for status, count in sorted(
        summary["verification_status_counts"].items()
    ):
        print(f"  {status}: {count}")
    print()
    print(f"Verification: {PROJECT_ROOT / summary['result_path']}")
    print(
        "Summary:      "
        + str(
            PROJECT_ROOT
            / "data"
            / "departments"
            / "meity"
            / "v3_4_3_5"
            / "meity_scheme_page_browser_verification_summary_v3_4_3_5.json"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
