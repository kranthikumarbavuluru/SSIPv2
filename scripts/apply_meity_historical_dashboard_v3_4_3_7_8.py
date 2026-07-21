from __future__ import annotations

import argparse
from pathlib import Path


IMPORT_BLOCK = '''
from ssip_dashboard.meity_history import (
    MeitYHistoricalArchive,
    MeitYHistoricalRecord,
    load_meity_historical_archive,
)
'''

RENDER_BLOCK = '''
@st.cache_data(ttl=300, show_spinner=False)
def cached_meity_historical_archive() -> MeitYHistoricalArchive:
    return load_meity_historical_archive(PROJECT_ROOT)


def _meity_history_chart(
    records: tuple[MeitYHistoricalRecord, ...],
) -> str:
    counts = Counter(
        record.historical_year or "Unknown"
        for record in records
    )
    if not counts:
        return (
            '<div class="empty-note">'
            'No qualified MeitY historical calls are available.'
            '</div>'
        )
    ordered = sorted(
        counts,
        key=lambda value: (
            value == "Unknown",
            value,
        ),
    )
    maximum = max(counts.values()) or 1
    rows = []
    for label in ordered:
        width = (counts[label] / maximum) * 100
        rows.append(
            '<div class="history-row">'
            f'<strong>{esc(label)}</strong>'
            '<div class="history-track">'
            '<span class="history-segment history-startup-relevant" '
            f'style="width:{width:.3f}%"></span>'
            '</div>'
            f'<b>{counts[label]}</b></div>'
        )
    return (
        '<div class="history-chart">'
        '<div class="history-legend">'
        '<span><i class="history-segment '
        'history-startup-relevant"></i>'
        'Qualified historical call</span>'
        '</div>'
        + "".join(rows)
        + '</div>'
    )


def _meity_historical_card(
    record: MeitYHistoricalRecord,
) -> str:
    year = record.historical_year or "Year not recorded"
    programme_type = record.programme_type.replace(
        "_",
        " ",
    ).title()
    official_link = (
        '<a target="_blank" rel="noopener noreferrer" '
        f'href="{html.escape(record.official_page_url, quote=True)}">'
        'Official historical source &#8599;</a>'
        if record.official_page_url
        else ""
    )
    return (
        '<article class="historical-call-card">'
        '<div class="scheme-card-head">'
        '<span class="status-badge status-history">Historical</span>'
        f'<span class="record-kind">{esc(programme_type)}</span>'
        f'<span class="record-kind">{esc(year)}</span>'
        '</div>'
        f'<h3>{esc(record.canonical_title)}</h3>'
        '<div class="archive-note">'
        'Historical reference only — no active Apply action is shown.'
        '</div>'
        f'<p><b>Startup relevance:</b> '
        f'{esc(record.startup_relevance.replace("_", " ").title())}</p>'
        f'<p><b>Sector:</b> {esc(record.sector or "Not assessed")}</p>'
        f'<p><b>Historical basis:</b> '
        f'{esc(record.historical_basis)}</p>'
        '<div class="resource-actions">'
        f'{official_link}</div>'
        '</article>'
    )


def render_meity_historical_archive() -> None:
    archive = cached_meity_historical_archive()
    records = archive.records
    manifest = archive.manifest

    st.markdown(
        '<div class="archive-governance">'
        '<strong>Governed MeitY historical reconstruction</strong>'
        f'<span>{len(records)} official-source call identities passed '
        'historical page-role and past-activity evidence gates. '
        f'{manifest.get("historical_review_queue_count", 0)} additional '
        'identities remain under reconstruction and are not displayed '
        'as public calls.</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="metric-grid archive-metrics">'
        + metric_card(
            "Historical Calls",
            len(records),
            "Qualified official MeitY references",
            "blue",
        )
        + metric_card(
            "Startup Direct",
            manifest.get("startup_direct_count", 0),
            "Explicit startup participation",
            "green",
        )
        + metric_card(
            "Year Evidenced",
            manifest.get("year_evidenced_count", 0),
            "Year explicitly recorded",
            "purple",
        )
        + metric_card(
            "Under Review",
            manifest.get(
                "historical_review_queue_count",
                0,
            ),
            "Not exposed as public calls",
            "orange",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-band">'
        '<h2 class="section-title">'
        'MeitY Historical Calls by Year</h2>'
        + _meity_history_chart(records)
        + '</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    keyword = c1.text_input(
        "Search MeitY historical calls",
        placeholder="DRISHTI, Appscale, tolling…",
        key="meity_history_keyword",
    ).strip().casefold()
    years = sorted(
        {
            record.historical_year
            for record in records
            if record.historical_year
        },
        reverse=True,
    )
    selected_year = c2.selectbox(
        "Historical year",
        ["ALL", *years, "UNKNOWN"],
        format_func=lambda value: {
            "ALL": "All years",
            "UNKNOWN": "Year not recorded",
        }.get(value, value),
        key="meity_history_year",
    )
    types = sorted(
        {record.programme_type for record in records}
    )
    selected_type = c3.selectbox(
        "Programme type",
        ["ALL", *types],
        format_func=lambda value: (
            "All types"
            if value == "ALL"
            else value.replace("_", " ").title()
        ),
        key="meity_history_type",
    )

    visible = []
    for record in records:
        haystack = " ".join(
            (
                record.canonical_title,
                record.programme_type,
                record.sector,
                record.historical_basis,
                record.evidence_excerpt,
            )
        ).casefold()
        if keyword and keyword not in haystack:
            continue
        if (
            selected_year not in {"ALL", "UNKNOWN"}
            and record.historical_year != selected_year
        ):
            continue
        if (
            selected_year == "UNKNOWN"
            and record.historical_year
        ):
            continue
        if (
            selected_type != "ALL"
            and record.programme_type != selected_type
        ):
            continue
        visible.append(record)

    st.markdown(
        f'<div class="filter-summary"><strong>{len(visible)}</strong> '
        'qualified MeitY historical call(s) match'
        '<span>No application action is displayed</span></div>',
        unsafe_allow_html=True,
    )

    if visible:
        st.markdown(
            '<div class="historical-call-grid">'
            + "".join(
                _meity_historical_card(record)
                for record in visible
            )
            + '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info(
            "No qualified MeitY historical calls match the filters."
        )

    st.caption(
        "Archive manifest: "
        + str(manifest.get("signature", ""))[:16]
        + "… · Excluded non-call pages: "
        + str(manifest.get("excluded_non_call_count", 0))
        + " · Apply actions: 0"
    )


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
    current_calls = [
        record
        for record in verified_calls
        if record.application_status.upper()
        in {"OPEN", "UPCOMING"}
    ]
    history = cached_meity_historical_archive()

    st.markdown(
        page_intro(
            "MeitY intelligence",
            "MeitY Schemes & Calls",
            (
                "Permanent MeitY schemes, verified current calls and "
                "qualified historical call references are maintained "
                "as separate governed views."
            ),
            badge=(
                f"{len(schemes)} schemes · "
                f"{len(current_calls)} current calls · "
                f"{len(history.records)} historical"
            ),
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
                for record in current_calls
            ),
            "Verified current application windows",
            "green",
        )
        + metric_card(
            "Upcoming",
            sum(
                record.application_status.upper() == "UPCOMING"
                for record in current_calls
            ),
            "Verified future windows",
            "purple",
        )
        + metric_card(
            "Historical calls",
            len(history.records),
            "Qualified official-source references",
            "orange",
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    tab_schemes, tab_calls, tab_history = st.tabs(
        [
            "MeitY Schemes",
            "Current MeitY Calls",
            "MeitY Historical Archive",
        ]
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
        if not current_calls:
            st.info(
                "No verified open or upcoming MeitY calls are currently "
                "published. Unverified calls remain hidden."
            )
        else:
            parent_names = {
                record.master_id: record.scheme_name
                for record in bundle.records
            }
            visible = _render_published_call_filters(
                current_calls,
                key_prefix="meity_calls",
                parent_names=parent_names,
            )
            if not visible:
                st.info(
                    "No MeitY calls match the selected filters."
                )
            else:
                st.markdown(
                    '<div class="call-grid">'
                    + "".join(
                        _published_call_card(
                            record,
                            parent_names=parent_names,
                        )
                        for record in visible
                    )
                    + '</div>',
                    unsafe_allow_html=True,
                )

    with tab_history:
        render_meity_historical_archive()
'''


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    if "from ssip_dashboard.meity_history import (" not in text:
        marker = "\n\nAPP_VERSION = "
        if marker not in text:
            marker = "\nAPP_VERSION = "
        if marker not in text:
            raise RuntimeError(
                "Dashboard import insertion marker was not found."
            )
        text = text.replace(
            marker,
            "\n\n" + IMPORT_BLOCK.strip() + marker,
            1,
        )

    start = text.find("\ndef render_meity_page(")
    end = text.find("\ndef main() -> None:", start)
    if start < 0 or end < 0:
        raise RuntimeError(
            "Current MeitY renderer block was not found."
        )
    text = (
        text[:start]
        + "\n\n"
        + RENDER_BLOCK.strip()
        + "\n\n"
        + text[end + 1 :]
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        "from ssip_dashboard.meity_history import (",
        "def cached_meity_historical_archive(",
        "def render_meity_historical_archive(",
        '"MeitY Historical Archive"',
        "Historical reference only — no active Apply action is shown.",
        "No application action is displayed",
        "render_meity_historical_archive()",
        "Apply actions: 0",
    )
    missing = [
        marker for marker in required if marker not in text
    ]
    if missing:
        raise RuntimeError(
            "MeitY historical dashboard validation failed: "
            + repr(missing)
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
            "MeitY historical dashboard patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print(
        "SSIP v3.4.3.7.8 MeitY historical dashboard: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
