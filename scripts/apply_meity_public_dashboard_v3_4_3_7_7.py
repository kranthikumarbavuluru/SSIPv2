from __future__ import annotations

import argparse
from pathlib import Path


MEITY_RENDERER = r"""
def render_meity_page(bundle: CatalogueBundle) -> None:
    meity_records = [
        record
        for record in bundle.records
        if (
            "meity" in (
                " ".join(
                    (
                        record.source,
                        record.ministry,
                        record.department,
                        record.implementing_agency,
                    )
                ).casefold()
            )
            and record.publication_status.upper() == "PUBLISHED"
            and int(record.is_public or 0) == 1
        )
    ]
    schemes = [
        record
        for record in meity_records
        if record.record_kind.upper()
        not in {"APPLICATION_CALL", "CHALLENGE"}
    ]
    calls = [
        record
        for record in meity_records
        if record.record_kind.upper()
        in {"APPLICATION_CALL", "CHALLENGE"}
    ]
    verified_calls = [
        record
        for record in calls
        if record.application_status.upper()
        in {"OPEN", "UPCOMING", "CLOSED"}
    ]

    st.markdown(
        page_intro(
            "MeitY intelligence",
            "MeitY Schemes & Calls",
            (
                "Permanent MeitY schemes and governed time-bound calls "
                "are shown separately. Unverified or withdrawn calls are "
                "not exposed to the public catalogue."
            ),
            badge=f"{len(schemes)} schemes · {len(verified_calls)} verified calls",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card(
            "Published schemes",
            len(schemes),
            "Permanent MeitY scheme identities",
            "blue",
        )
        + metric_card(
            "Open calls",
            sum(
                record.application_status.upper() == "OPEN"
                for record in verified_calls
            ),
            "Verified current application windows",
            "green",
        )
        + metric_card(
            "Upcoming",
            sum(
                record.application_status.upper() == "UPCOMING"
                for record in verified_calls
            ),
            "Verified future windows",
            "purple",
        )
        + metric_card(
            "Closed calls",
            sum(
                record.application_status.upper() == "CLOSED"
                for record in verified_calls
            ),
            "Published historical references",
            "orange",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    tab_schemes, tab_calls = st.tabs(
        ["MeitY Schemes", "MeitY Calls"]
    )

    with tab_schemes:
        if schemes:
            st.markdown(
                '<div class="scheme-results-grid">'
                + "".join(
                    public_record_card(record)
                    for record in sorted(
                        schemes,
                        key=lambda item: item.scheme_name.casefold(),
                    )
                )
                + '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "No published permanent MeitY schemes are available "
                "in the current public catalogue."
            )

    with tab_calls:
        if not verified_calls:
            st.info(
                "No verified MeitY calls are currently published. "
                "Calls under revalidation remain hidden until the "
                "governed publication checks are completed."
            )
            return

        status_counts = Counter(
            record.application_status.upper()
            for record in verified_calls
        )
        chart_data = pd.DataFrame(
            {
                "Status": ["OPEN", "UPCOMING", "CLOSED"],
                "Calls": [
                    status_counts.get("OPEN", 0),
                    status_counts.get("UPCOMING", 0),
                    status_counts.get("CLOSED", 0),
                ],
            }
        ).set_index("Status")
        st.bar_chart(chart_data)

        parent_names = {
            record.master_id: record.scheme_name
            for record in bundle.records
        }
        visible = _render_published_call_filters(
            verified_calls,
            key_prefix="meity_calls",
            parent_names=parent_names,
        )
        if not visible:
            st.info("No MeitY calls match the selected filters.")
        else:
            st.markdown(
                '<div class="scheme-results-grid home-call-grid">'
                + "".join(
                    _call_card(record, parent_names)
                    for record in visible
                )
                + '</div>',
                unsafe_allow_html=True,
            )
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Dashboard patch marker not found: {label}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    text = replace_once(
        text,
        '    "DST Schemes",\n',
        '    "DST Schemes",\n    "MeitY",\n',
        "page names",
    )
    text = replace_once(
        text,
        '    "DST Schemes": "DST",\n',
        '    "DST Schemes": "DST",\n    "MeitY": "MeitY",\n',
        "nav labels",
    )
    text = replace_once(
        text,
        '    "DST Schemes": "dst-programmes",\n',
        '    "DST Schemes": "dst-programmes",\n'
        '    "MeitY": "meity-programmes",\n',
        "page slugs",
    )
    text = replace_once(
        text,
        '        "DST Schemes",\n        "Directory",\n',
        '        "DST Schemes",\n        "MeitY",\n        "Directory",\n',
        "primary navigation",
    )

    status_old = (
        '    status_options = ["OPEN", "UPCOMING", "CLOSED", '
        '"STATUS_UNVERIFIED", "ALL"]\n'
    )
    status_new = (
        '    status_options = ["OPEN", "UPCOMING", "CLOSED", '
        '"VERIFICATION_REQUIRED", "STATUS_UNVERIFIED", "ALL"]\n'
    )
    text = replace_once(
        text,
        status_old,
        status_new,
        "call status options",
    )

    renderer_marker = "\ndef main() -> None:\n"
    if "def render_meity_page(" not in text:
        if renderer_marker not in text:
            raise RuntimeError("MeitY renderer insertion marker not found")
        text = text.replace(
            renderer_marker,
            "\n" + MEITY_RENDERER.rstrip() + "\n\n\ndef main() -> None:\n",
            1,
        )

    dispatch_old = (
        '    elif page == "DST Schemes":\n'
        '        render_dst_schemes()\n'
        '    elif page == "Official Sources":\n'
    )
    dispatch_new = (
        '    elif page == "DST Schemes":\n'
        '        render_dst_schemes()\n'
        '    elif page == "MeitY":\n'
        '        render_meity_page(bundle)\n'
        '    elif page == "Official Sources":\n'
    )
    text = replace_once(
        text,
        dispatch_old,
        dispatch_new,
        "MeitY dispatch",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        '"MeitY": "MeitY"',
        '"MeitY": "meity-programmes"',
        'def render_meity_page(',
        'MeitY Schemes & Calls',
        'Unverified or withdrawn calls are ',
        'not exposed to the public catalogue.',
        'elif page == "MeitY":',
        'render_meity_page(bundle)',
        '"VERIFICATION_REQUIRED"',
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError(
            f"MeitY public dashboard validation failed: {missing}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = (
        Path(args.project_root).resolve()
        / "apps/public_dashboard_app_v2_9.py"
    )
    if not args.check:
        changed = patch(path)
        print(
            "MeitY public dashboard patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print("SSIP v3.4.3.7.7 MeitY dashboard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
