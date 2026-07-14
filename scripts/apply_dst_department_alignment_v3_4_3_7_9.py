from __future__ import annotations

import argparse
from pathlib import Path


DST_PAGE_BLOCK = r"""
def render_dst_schemes() -> None:
    bundle = cached_dst_pilot()
    archive = cached_dst_historical_archive()
    historical_records = archive.historical_records
    current_calls = [
        call
        for call in bundle.calls
        if (
            call.application_status.upper() in {"OPEN", "UPCOMING"}
            and not call.is_ecosystem
        )
    ]

    st.markdown(
        page_intro(
            "DST intelligence",
            "DST Schemes & Calls",
            (
                "Permanent DST programme identities, verified current "
                "calls and the governed historical archive are maintained "
                "as separate views."
            ),
            badge=(
                f"{len(bundle.programmes)} programmes · "
                f"{len(current_calls)} current calls · "
                f"{len(historical_records)} historical"
            ),
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card(
            "Permanent programmes",
            len(bundle.programmes),
            "Governed DST programme identities",
            "blue",
        )
        + metric_card(
            "Open calls",
            sum(
                call.application_status.upper() == "OPEN"
                for call in current_calls
            ),
            "Verified current application windows",
            "green",
        )
        + metric_card(
            "Upcoming",
            sum(
                call.application_status.upper() == "UPCOMING"
                for call in current_calls
            ),
            "Verified future application windows",
            "purple",
        )
        + metric_card(
            "Historical calls",
            len(historical_records),
            "Qualified official DST references",
            "orange",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    tab_schemes, tab_calls, tab_history = st.tabs(
        [
            "DST Schemes",
            "Current DST Calls",
            "DST Historical Archive",
        ]
    )

    with tab_schemes:
        if not bundle.programmes:
            st.error(
                "The DST programme database is unavailable. "
                "Run scripts/run_dst_pilot_v1.py to rebuild it."
            )
        else:
            st.markdown(
                '<div class="archive-governance">'
                '<strong>Permanent programme identities</strong>'
                '<span>Dated calls, archive pages and implementing '
                'centres remain separate from the DST programme count.'
                '</span></div>',
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns([2, 1, 1])
            keyword = c1.text_input(
                "Search DST schemes",
                key="dst_department_scheme_keyword",
                placeholder="PRAYAS, seed support, accelerator…",
            )
            entity_types = sorted(
                {
                    item.entity_type
                    for item in bundle.programmes
                    if item.entity_type
                }
            )
            entity_type = c2.selectbox(
                "Programme type",
                ["", *entity_types],
                format_func=lambda value: (
                    value.replace("_", " ").title()
                    if value
                    else "All types"
                ),
                key="dst_department_scheme_type",
            )
            scopes = sorted(
                {
                    item.sector_scope
                    for item in bundle.programmes
                    if item.sector_scope
                }
            )
            sector_scope = c3.selectbox(
                "Sector scope",
                ["", *scopes],
                format_func=lambda value: (
                    value.replace("_", " ").title()
                    if value
                    else "All scopes"
                ),
                key="dst_department_sector_scope",
            )
            visible_programmes = filter_dst_programmes(
                bundle.programmes,
                keyword=keyword,
                entity_type=entity_type,
                sector_scope=sector_scope,
            )
            st.markdown(
                f'<div class="filter-summary">'
                f'<strong>{len(visible_programmes)}</strong> '
                'permanent DST programme record(s)'
                '<span>Calls are maintained separately</span></div>',
                unsafe_allow_html=True,
            )
            cards = []
            for programme in visible_programmes:
                related = [
                    call
                    for call in bundle.calls
                    if call.parent_master_id == programme.master_id
                ]
                cards.append(
                    _dst_programme_card(programme, related)
                )
            st.markdown(
                '<div class="programme-grid">'
                + "".join(cards)
                + '</div>',
                unsafe_allow_html=True,
            )

    with tab_calls:
        if not current_calls:
            st.info(
                "No verified open or upcoming direct DST calls are "
                "currently available in the governed DST dataset."
            )
        else:
            st.markdown(
                '<div class="archive-governance">'
                '<strong>Current DST application windows</strong>'
                '<span>Only open and upcoming direct/review calls are '
                'shown here. Historical calls are maintained in the '
                'separate archive tab.</span></div>',
                unsafe_allow_html=True,
            )
            visible_calls = _render_dst_call_filters(
                current_calls,
                key_prefix="dst_department_current",
            )
            st.markdown(
                f'<div class="filter-summary">'
                f'<strong>{len(visible_calls)}</strong> '
                'current DST call(s) match'
                '<span>Verify the official deadline before applying'
                '</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="call-grid">'
                + "".join(
                    _dst_call_card(call)
                    for call in visible_calls
                )
                + '</div>',
                unsafe_allow_html=True,
            )

    with tab_history:
        render_dst_historical_archive()
"""

DST_HISTORY_BLOCK = r"""
def render_dst_historical_archive() -> None:
    archive = cached_dst_historical_archive()
    records = archive.historical_records
    manifest = archive.manifest
    relevance_counts = manifest["relevance_counts"]
    startup_count = relevance_counts["STARTUP_RELEVANT"]
    ecosystem_count = relevance_counts["STARTUP_ECOSYSTEM_CALL"]
    review_count = relevance_counts["REVIEW_REQUIRED"]
    general_count = relevance_counts["GENERAL_DST"]
    reconciled_total = (
        startup_count
        + ecosystem_count
        + review_count
        + general_count
    )

    st.markdown(
        '<div class="archive-governance">'
        '<strong>Governed DST historical qualification</strong>'
        f'<span>{len(records)} closed calls passed official-source, '
        'date, identity and page-role gates. Category reconciliation: '
        f'{startup_count} startup relevant + {ecosystem_count} ecosystem '
        f'+ {review_count} relevance review + {general_count} general DST '
        f'= {reconciled_total}. '
        f'{manifest["current_calls_excluded"]} current calls are excluded.'
        '</span></div>',
        unsafe_allow_html=True,
    )

    if reconciled_total != len(records):
        st.error(
            "DST historical relevance categories do not reconcile "
            "to the qualified archive total."
        )

    st.markdown(
        '<div class="metric-grid archive-metrics">'
        + metric_card(
            "Historical Calls",
            len(records),
            "Closed official DST call instances",
            "blue",
        )
        + metric_card(
            "Startup Relevant",
            startup_count,
            "Explicit startup evidence",
            "green",
        )
        + metric_card(
            "Ecosystem",
            ecosystem_count,
            "Institutional implementation calls",
            "purple",
        )
        + metric_card(
            "Relevance Review",
            review_count,
            "Startup relevance needs evidence",
            "orange",
        )
        + metric_card(
            "General DST",
            general_count,
            "Not classified as startup opportunities",
            "blue",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-band">'
        '<h2 class="section-title">'
        'DST Historical Calls by Closing Year</h2>'
        + _historical_chart(records)
        + '</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    keyword = c1.text_input(
        "Search DST historical calls",
        placeholder="Title, applicant, sector or programme",
        key="dst_department_history_keyword",
    ).strip().casefold()
    years = sorted(
        {
            item.closing_year
            for item in records
            if item.closing_year is not None
        },
        reverse=True,
    )
    selected_year = c2.selectbox(
        "Closing year",
        [0, *years],
        format_func=lambda value: (
            "All years" if value == 0 else str(value)
        ),
        key="dst_department_history_year",
    )
    relevance = c3.selectbox(
        "Relevance",
        ["ALL", *RELEVANCE_ORDER],
        format_func=lambda value: (
            "All relevance"
            if value == "ALL"
            else _historical_relevance_label(value)
        ),
        key="dst_department_history_relevance",
    )
    sectors = sorted(
        {
            item.call.primary_sector
            for item in records
            if item.call.primary_sector
        }
    )
    sector = c4.selectbox(
        "Sector",
        ["", *sectors],
        format_func=lambda value: value or "All sectors",
        key="dst_department_history_sector",
    )

    visible = []
    for item in records:
        call = item.call
        haystack = " ".join(
            (
                call.call_title,
                call.parent_name,
                call.eligible_applicants,
                call.primary_sector,
                call.secondary_sectors,
            )
        ).casefold()
        if keyword and keyword not in haystack:
            continue
        if selected_year and item.closing_year != selected_year:
            continue
        if (
            relevance != "ALL"
            and item.relevance_group != relevance
        ):
            continue
        secondary_sectors = {
            value.strip()
            for value in call.secondary_sectors.split(";")
            if value.strip()
        }
        if (
            sector
            and sector != call.primary_sector
            and sector not in secondary_sectors
        ):
            continue
        visible.append(item)

    visible.sort(
        key=lambda item: (
            item.closing_date or date.min,
            item.call.call_title.casefold(),
        ),
        reverse=True,
    )

    page_size = 30
    total_pages = max(
        1,
        (len(visible) + page_size - 1) // page_size,
    )
    page_number = st.selectbox(
        "Archive page",
        range(1, total_pages + 1),
        format_func=lambda value: (
            f"Page {value} of {total_pages}"
        ),
        key="dst_department_history_page",
    )
    page_start = (page_number - 1) * page_size
    displayed = visible[
        page_start : page_start + page_size
    ]
    first_record = page_start + 1 if displayed else 0
    last_record = page_start + len(displayed)

    st.markdown(
        f'<div class="filter-summary">'
        f'<strong>{len(visible)}</strong> historical call(s) match'
        f'<span>Showing {first_record}–{last_record} · '
        '30 per page · no active Apply action is displayed'
        '</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="historical-call-grid">'
        + "".join(
            _historical_call_card(item)
            for item in displayed
        )
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Archive manifest: "
        + manifest["signature"][:16]
        + "… · Reconciled categories: "
        + str(reconciled_total)
        + " · Human stratified sample: "
        + str(len(manifest["sample_ids"]))
        + " records · Exceptions: "
        + str(manifest["exception_count"])
        + " · Apply actions: 0"
    )
"""

CALLS_PAGE_BLOCK = r"""
def render_calls_and_opportunities() -> None:
    bundle = cached_catalogue()
    all_calls = _published_calls(bundle)
    calls = [
        item
        for item in all_calls
        if item.applicant_layer.upper()
        != "INTERMEDIARY_IMPLEMENTER"
    ]
    parent_names = {
        item.master_id: item.scheme_name
        for item in bundle.records
    }

    st.markdown(
        page_intro(
            "Calls intelligence",
            "Calls & Opportunities",
            (
                "Open, upcoming and published closed startup calls are "
                "shown here across departments. Detailed historical "
                "archives are maintained in the DST and MeitY pages."
            ),
            badge=f"{len(calls)} published startup-scope calls",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="archive-governance">'
        '<strong>Department historical archives</strong>'
        '<span>Open the '
        '<a target="_top" href="?page=dst-programmes">'
        'DST Historical Archive</a> or '
        '<a target="_top" href="?page=meity-programmes">'
        'MeitY Historical Archive</a> for department-level charts, '
        'filters and historical records.</span></div>',
        unsafe_allow_html=True,
    )

    call_view = st.radio(
        "Call catalogue view",
        ["OPEN_CURRENT", "CLOSED_STARTUP"],
        horizontal=True,
        key="call_catalogue_view",
        format_func=lambda value: {
            "OPEN_CURRENT": "Open & Current",
            "CLOSED_STARTUP": "Closed Startup Calls",
        }[value],
    )

    calls = [
        item
        for item in calls
        if (
            item.application_status.upper() != "CLOSED"
            if call_view == "OPEN_CURRENT"
            else item.application_status.upper() == "CLOSED"
        )
    ]
    if not calls:
        st.info(
            "No published direct or applicant-layer-unverified "
            "calls are available."
        )
        return

    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card(
            "Open",
            sum(
                item.application_status == "OPEN"
                for item in calls
            ),
            "Accepting applications",
            "green",
        )
        + metric_card(
            "Upcoming",
            sum(
                item.application_status == "UPCOMING"
                for item in calls
            ),
            "Future application windows",
            "blue",
        )
        + metric_card(
            "Closed",
            sum(
                item.application_status == "CLOSED"
                for item in calls
            ),
            "Retained for reference",
            "purple",
        )
        + metric_card(
            "Layer Review",
            sum(
                item.applicant_layer.upper()
                in {"", "UNKNOWN", "UNVERIFIED"}
                for item in calls
            ),
            "Applicant classification pending",
            "orange",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    visible = _render_published_call_filters(
        calls,
        key_prefix=(
            f"published_direct_{call_view.casefold()}"
        ),
        parent_names=parent_names,
    )
    st.markdown(
        f"**{len(visible)} matching published "
        "direct/review call(s)**"
    )
    raw_published_call_cards = [
        _published_call_card(
            item,
            parent_names=parent_names,
        )
        for item in visible
    ]
    valid_published_call_cards = [
        card
        for card in raw_published_call_cards
        if isinstance(card, str) and card.strip()
    ]

    st.markdown(
        '<div class="call-grid">'
        + "".join(valid_published_call_cards)
        + "</div>",
        unsafe_allow_html=True,
    )

    if len(valid_published_call_cards) != len(
        raw_published_call_cards
    ):
        st.warning(
            "One or more published call records could not "
            "be displayed because the card renderer returned "
            "no HTML. The underlying records remain available."
        )
"""


def replace_function_block(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError(
            f"DST alignment marker not found: {label}"
        )
    return (
        text[:start]
        + replacement.strip()
        + "\n\n"
        + text[end:]
    )


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    text = replace_function_block(
        text,
        "\ndef render_dst_schemes() -> None:",
        "\ndef _dst_call_card(",
        "\n" + DST_PAGE_BLOCK,
        "DST department page",
    )
    text = replace_function_block(
        text,
        "\ndef render_dst_historical_archive() -> None:",
        "\ndef _render_published_call_filters(",
        "\n" + DST_HISTORY_BLOCK,
        "DST historical archive",
    )
    text = replace_function_block(
        text,
        "\ndef render_calls_and_opportunities() -> None:",
        "\ndef render_startup_ecosystem() -> None:",
        "\n" + CALLS_PAGE_BLOCK,
        "general Calls page",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        '"DST Schemes & Calls"',
        '"DST Schemes"',
        '"Current DST Calls"',
        '"DST Historical Archive"',
        "Category reconciliation:",
        '"Relevance Review"',
        "reconciled_total != len(records)",
        "Detailed historical ",
        "archives are maintained in the DST and MeitY pages.",
        'href="?page=dst-programmes"',
        'href="?page=meity-programmes"',
        '["OPEN_CURRENT", "CLOSED_STARTUP"]',
        "Apply actions: 0",
    )
    missing = [
        marker
        for marker in required
        if marker not in text
    ]
    if missing:
        raise RuntimeError(
            "DST page alignment validation failed: "
            + repr(missing)
        )

    calls_start = text.index(
        "def render_calls_and_opportunities() -> None:"
    )
    calls_end = text.index(
        "def render_startup_ecosystem() -> None:",
        calls_start,
    )
    calls_block = text[calls_start:calls_end]
    forbidden = (
        '"HISTORICAL_ARCHIVE"',
        'render_dst_historical_archive()\n        return',
    )
    found = [
        marker
        for marker in forbidden
        if marker in calls_block
    ]
    if found:
        raise RuntimeError(
            "General Calls page still embeds the DST archive: "
            + repr(found)
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
            "DST department alignment patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print(
        "SSIP v3.4.3.7.9 DST department alignment: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
