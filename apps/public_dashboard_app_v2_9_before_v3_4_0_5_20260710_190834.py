from __future__ import annotations

from collections import Counter
from datetime import date
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_dashboard.catalogue import CatalogueBundle, CatalogueRecord, load_catalogue
from ssip_dashboard.components import (
    esc,
    horizontal_bars,
    metric_card,
    nav_header,
    scheme_card,
    warning_box,
)
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.filters import FilterState, apply_filters, unique_options
from ssip_dashboard.funding import (
    FUNDING_BUCKETS,
    format_inr,
    funding_bucket_counts,
    funding_bucket_label,
)
from ssip_dashboard.metrics import (
    compute_metrics,
    department_coverage,
    government_level,
    government_level_coverage,
    grant_support_distribution,
    latest_records,
    open_records,
    resource_counts,
    sector_coverage,
    source_scope_lookup,
    status_coverage,
)
from ssip_dashboard.source_directory import (
    OfficialSource,
    filter_sources,
    load_official_sources,
    source_counter,
    source_summary,
)
from ssip_dashboard.status import parse_date, status_bucket, status_css_class, status_label


APP_VERSION = "3.4.0.4"
PAGE_NAMES = [
    "Home",
    "Scheme Explorer",
    "Official Sources",
    "Directory",
    "Scheme Details",
]


def load_css() -> str:
    path = PROJECT_ROOT / "ssip_dashboard" / "assets" / "styles.css"
    return path.read_text(encoding="utf-8")


st.set_page_config(
    page_title="SSIP Public Dashboard",
    page_icon="SSIP",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=45, show_spinner=False)
def cached_catalogue() -> CatalogueBundle:
    return load_catalogue(DashboardConfig.from_env(PROJECT_ROOT))


@st.cache_data(ttl=300, show_spinner=False)
def cached_official_sources() -> list[OfficialSource]:
    return load_official_sources(PROJECT_ROOT)


def render_record_grid(records: list[CatalogueRecord], *, limit: int = 6) -> None:
    if not records:
        st.info("No records are available for this section.")
        return
    for record in records[:limit]:
        st.markdown(scheme_card(record, compact=True), unsafe_allow_html=True)


def render_source_card(source: OfficialSource) -> str:
    return (
        '<article class="source-card">'
        f'<div class="scheme-card-head"><span class="record-kind">{esc(source.scope)}</span>'
        f'<span class="status-badge status-reference">{esc(source.priority)} priority</span></div>'
        f'<h3>{esc(source.name)}</h3>'
        f'<div class="agency-line">{esc(source.department or source.ministry)}</div>'
        f'<p>{esc(source.coverage_note)}</p>'
        f'<div class="scheme-meta"><span>{esc(source.source_type.replace("_", " ").title())}</span>'
        f'<span>{len(source.seed_urls)} seed URL(s)</span></div>'
        f'<div class="link-row"><span class="link-pill"><a target="_blank" href="{esc(source.official_url)}">Official Source</a></span></div>'
        "</article>"
    )


def not_available(value: object) -> str:
    text = str(value or "").strip()
    return text or "Not available"


def display_token(value: object) -> str:
    text = not_available(value)
    if text != "Not available" and "_" in text:
        return text.replace("_", " ").title()
    return text


def render_scheme_row(record: CatalogueRecord, lookup: dict[str, str] | None = None) -> str:
    agency = record.department or record.implementing_agency or record.source or "Agency / Source not recorded"
    description = " ".join((record.objectives or record.benefits or ["Information available in official sources."])[:1])
    tags = "".join(f'<span class="tag">{esc(tag)}</span>' for tag in [*record.sectors[:2], *record.scheme_types[:1]])
    level = government_level(record, lookup or {})
    links = []
    if record.official_page_url:
        links.append(f'<a target="_blank" href="{esc(record.official_page_url)}">Official Page</a>')
    if record.application_url:
        links.append(f'<a target="_blank" href="{esc(record.application_url)}">Application Portal</a>')
    if record.application_process:
        links.append("<span>How to Apply</span>")
    if record.guideline_urls:
        links.append(f'<a target="_blank" href="{esc(record.guideline_urls[0])}">Manual</a>')
    if record.reference_urls:
        links.append(f'<a target="_blank" href="{esc(record.reference_urls[0])}">Reference</a>')
    link_html = "".join(f'<span class="link-pill">{link}</span>' for link in links)
    eligibility = "; ".join(record.target_beneficiaries[:2] or record.eligibility[:1])
    return (
        '<article class="opportunity-row">'
        f'<div class="opportunity-icon">{esc((record.scheme_name or "S")[:2].upper())}</div>'
        '<div class="opportunity-main">'
        f'<div class="scheme-card-head"><span class="status-badge {status_css_class(record)}">{esc(status_label(record))}</span>'
        f'<span class="record-kind">{esc(record.record_kind or "Catalogue Record")}</span>'
        f'<span class="record-kind">{esc(level)}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="agency-line">Ministry: {esc(not_available(record.ministry))}</div>'
        f'<div class="agency-line">Department / Agency: {esc(agency)}</div>'
        f'<p>{esc(description[:260])}</p>'
        f'<div class="tag-row">{tags}</div>'
        "</div>"
        '<div class="opportunity-meta">'
        f'<strong>{esc(display_token(record.programme_status))}</strong><span>Programme status</span>'
        f'<strong>{esc(display_token(record.application_status))}</strong><span>Application status</span>'
        f'<strong>{esc(not_available(record.opening_date))}</strong><span>Opening date</span>'
        f'<strong>{esc(not_available(record.closing_date))}</strong><span>Closing date</span>'
        "</div>"
        '<div class="opportunity-meta">'
        f'<strong>{esc(format_inr(record.funding_minimum))}</strong><span>Minimum funding</span>'
        f'<strong>{esc(format_inr(record.funding_maximum))}</strong><span>Maximum funding</span>'
        f'<strong>{esc(not_available(eligibility))}</strong><span>Eligibility summary</span>'
        f'<span>Updated: {esc(not_available(record.last_updated[:10]))}</span>'
        f'<div class="link-row">{link_html}</div>'
        "</div>"
        "</article>"
    )


def render_latest_list(records: list[CatalogueRecord]) -> str:
    rows = []
    for record in latest_records(records, limit=5):
        rows.append(
            '<div class="latest-row">'
            f'<span class="status-badge {status_css_class(record)}">{esc(status_label(record))}</span>'
            f'<strong>{esc(record.scheme_name)}</strong>'
            f'<span>{esc(record.last_updated[:10] or "Date not recorded")}</span>'
            "</div>"
        )
    return "".join(rows) or '<div class="empty-note">No catalogue records available.</div>'


def render_quick_links(official_sources: list[OfficialSource]) -> str:
    links = [
        ("Official Source Directory", "View government portals"),
        ("Scheme Explorer", "Search current catalogue"),
        ("Manuals / Guidelines", "Official documents"),
    ]
    rows = "".join(
        '<div class="quick-link">'
        f'<strong>{esc(title)}</strong><span>{esc(subtitle)}</span>'
        "</div>"
        for title, subtitle in links
    )
    if official_sources:
        source = official_sources[0]
        rows += (
            '<div class="quick-link">'
            f'<a target="_blank" href="{esc(source.official_url)}"><strong>{esc(source.name)}</strong></a>'
            '<span>Priority source seed</span>'
            "</div>"
        )
    return rows


CHART_COLORS = ("#1357d9", "#10a365", "#ff8a1c", "#7b4ee6", "#5aa6ff", "#d25a8d", "#8da2c0")


def pct(value: int, total: int) -> str:
    return "0%" if total <= 0 else f"{(value / total) * 100:.0f}%"


def top_counter_with_others(counter: Counter[str], *, limit: int = 5) -> Counter[str]:
    output: Counter[str] = Counter()
    for label, value in counter.most_common(limit):
        output[label] = value
    other_total = sum(value for label, value in counter.items() if label not in output)
    if other_total:
        output["Others"] += other_total
    return output


def render_donut(title: str, counter: Counter[str], *, note: str = "") -> str:
    total = sum(counter.values())
    if total <= 0:
        return f'<div class="chart-card"><div class="section-title">{esc(title)}</div><div class="empty-note">No structured data recorded.</div></div>'
    start = 0.0
    segments = []
    legend_rows = []
    for index, (label, value) in enumerate(counter.items()):
        end = start + (value / total) * 100
        color = CHART_COLORS[index % len(CHART_COLORS)]
        segments.append(f"{color} {start:.2f}% {end:.2f}%")
        legend_rows.append(
            '<div class="legend-row">'
            f'<span class="legend-dot" style="background:{color}"></span>'
            f'<strong>{esc(label)}</strong><span>{value} ({pct(value, total)})</span>'
            "</div>"
        )
        start = end
    return (
        '<div class="chart-card">'
        f'<div class="section-title">{esc(title)}</div>'
        '<div class="donut-wrap">'
        f'<div class="donut" style="background:conic-gradient({", ".join(segments)});"><span>{total}</span></div>'
        f'<div class="legend-list">{"".join(legend_rows)}</div>'
        "</div>"
        f'<div class="chart-note">{esc(note)}</div>'
        "</div>"
    )


def render_distribution_bars(title: str, rows: list[tuple[str, int]], *, note: str = "") -> str:
    max_value = max([value for _label, value in rows], default=0) or 1
    body = []
    for label, value in rows:
        height = max(8, int((value / max_value) * 78))
        body.append(
            '<div class="dist-bar-item">'
            f'<div class="dist-bar-value">{value}</div>'
            f'<div class="dist-bar-track"><span style="height:{height}px"></span></div>'
            f'<div class="dist-bar-label">{esc(label)}</div>'
            "</div>"
        )
    return (
        '<div class="chart-card">'
        f'<div class="section-title">{esc(title)}</div>'
        f'<div class="dist-bars">{"".join(body)}</div>'
        f'<div class="chart-note">{esc(note)}</div>'
        "</div>"
    )


def government_filter(records: list[CatalogueRecord], level: str, lookup: dict[str, str]) -> list[CatalogueRecord]:
    if level == "All Levels":
        return records
    return [record for record in records if government_level(record, lookup) == level]


def sort_records(records: list[CatalogueRecord], sort_by: str) -> list[CatalogueRecord]:
    if sort_by == "Closing Soon":
        return sorted(records, key=lambda record: parse_date(record.closing_date) or date.max)
    if sort_by == "Scheme Name":
        return sorted(records, key=lambda record: record.scheme_name.casefold())
    if sort_by == "Highest Funding":
        return sorted(records, key=lambda record: record.funding_maximum or 0, reverse=True)
    if sort_by == "Lowest Funding":
        return sorted(records, key=lambda record: record.funding_maximum or 0)
    if sort_by == "Department":
        return sorted(records, key=lambda record: (record.department or "").casefold())
    if sort_by == "Ministry":
        return sorted(records, key=lambda record: (record.ministry or "").casefold())
    return latest_records(records, limit=len(records))


def active_filter_count(state: FilterState, government_level_value: str, sort_by: str) -> int:
    count = 0
    count += bool(state.keyword)
    count += len(state.ministries)
    count += len(state.departments)
    count += len(state.agencies)
    count += len(state.sectors)
    count += len(state.scheme_types)
    count += len(state.statuses)
    count += len(state.applicant_types)
    count += len(state.startup_stages)
    count += government_level_value != "All Levels"
    count += sort_by != "Recently Updated"
    count += state.min_funding is not None or state.max_funding is not None
    return int(count)


def clear_home_filter_state() -> None:
    defaults = {
        "home_search": "",
        "home_government_level": "All Levels",
        "home_ministry": [],
        "home_department": [],
        "home_agency": [],
        "home_sector": [],
        "home_scheme_type": [],
        "home_status": [],
        "home_applicant_type": [],
        "home_stage": [],
        "home_min_funding": 0,
        "home_max_funding": 0,
        "home_sort": "Recently Updated",
    }
    for key, value in defaults.items():
        st.session_state[key] = value


def render_home(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = populations.main_scheme_records
    metrics = compute_metrics(records)
    source_stats = source_summary(official_sources)
    lookup = source_scope_lookup(official_sources)
    gov_counts = government_level_coverage(records, lookup)
    all_department_counts = department_coverage(records)
    all_sector_counts = sector_coverage(records)
    all_grant_counts = grant_support_distribution(records)
    all_status_counts = Counter(
        {bucket.replace("_", " ").title(): value for bucket, value in status_coverage(records).items()}
    )
    all_funding_counts = funding_bucket_counts(records)
    all_ministry_counter = Counter(record.ministry or "Missing Ministry" for record in records)
    latest_update_count = sum(1 for record in records if record.last_updated)

    st.markdown(
        '<div class="finder-heading finder-heading-main">'
        '<div><div class="finder-title">SSIP Catalogue Analytics</div>'
        '<p>Public intelligence view of schemes, grants, challenges, source coverage, application links and data readiness from the current SSIP catalogue.</p></div>'
        '<span class="finder-badge">Analytics view</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    catalogue_snapshot_html = (
        '<div class="section-band intelligence-snapshot"><div class="section-title">Catalogue Intelligence Snapshot</div>'
        '<div class="snapshot-lead">A quick public view of what is currently discoverable in the SSIP catalogue, what can be applied for, and where the data is most complete.</div>'
        '<div class="kpi-strip">'
        + metric_card("Total Records", metrics.total_catalogue_records, "Catalogue records in current mode", "blue")
        + metric_card("Closing Soon", metrics.closing_soon_records, "Within 30 days", "orange")
        + metric_card("Upcoming", metrics.upcoming_records, "Future or reopening signals", "purple")
        + metric_card("Ministries", metrics.total_explicit_ministries, "Explicit ministry values", "blue")
        + metric_card("Departments", metrics.total_explicit_departments, f"{metrics.total_implementing_agencies} agencies tagged", "purple")
        + metric_card("Latest Updates", latest_update_count, "Records with update dates", "green")
        + "</div>"
        + '<div class="snapshot-note">Closed and historical programmes remain searchable. Counts are calculated from the current SSIP catalogue only.</div>'
        + "</div>"
    )

    government_coverage_html = (
        '<div class="section-band"><div class="section-title">Government Level Coverage</div>'
        + '<div class="metric-grid">'
        + metric_card("Central Government", gov_counts["Central Government"], "Mapped from registry/fields", "blue")
        + metric_card("State Government", gov_counts["State Government"], "Mapped from registry/fields", "green")
        + metric_card("Unspecified", gov_counts["Unspecified"], "Needs explicit level", "orange")
        + "</div></div>"
    )

    source_expansion_html = (
        '<div class="section-band"><div class="section-title">Official Source Expansion</div>'
        + '<div class="metric-grid">'
        + metric_card("Central Sources", source_stats["central_sources"], "Registry entries", "blue")
        + metric_card("State / UT Sources", source_stats["state_sources"], "Registry entries", "purple")
        + metric_card("High Priority", source_stats["high_priority_sources"], "Discovery first", "orange")
        + "</div>"
        + "</div>"
    )

    analytics_grid_html = (
        '<div class="donut-grid">'
        + render_donut(
            "Ministry & Department Coverage",
            top_counter_with_others(all_department_counts, limit=5),
            note=f"Missing department: {metrics.records_missing_department}",
        )
        + render_donut(
            "Schemes by Ministry",
            top_counter_with_others(all_ministry_counter, limit=5),
            note=f"Missing ministry: {metrics.records_missing_ministry}",
        )
        + render_donut(
            "Schemes by Sector",
            top_counter_with_others(all_sector_counts, limit=5),
            note=f"Missing sector: {metrics.records_missing_sector}",
        )
        + render_donut(
            "Funding Distribution",
            top_counter_with_others(
                Counter({funding_bucket_label(bucket): all_funding_counts[bucket] for bucket, _label in FUNDING_BUCKETS}),
                limit=5,
            ),
            note="Structured funding values only.",
        )
        + render_donut(
            "Application Status",
            top_counter_with_others(all_status_counts, limit=5),
            note="Closing Soon means deadline within 30 days.",
        )
        + render_donut(
            "Grant & Support Types",
            top_counter_with_others(all_grant_counts, limit=5),
            note="Unknown support type remains visible when data is missing.",
        )
        + "</div>"
    )

    quick_links_html = (
        '<div class="section-band"><div class="section-title">Quick Links</div>'
        + render_quick_links(official_sources)
        + "</div>"
    )

    latest_schemes_html = (
        '<div class="section-band"><div class="section-title">Latest Schemes</div>'
        + render_latest_list(records)
        + "</div>"
    )

    st.markdown(catalogue_snapshot_html, unsafe_allow_html=True)
    st.markdown(
        '<div class="home-pair-grid">'
        + government_coverage_html
        + source_expansion_html
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(analytics_grid_html, unsafe_allow_html=True)
    st.markdown(
        '<div class="home-pair-grid home-pair-grid-balanced">'
        + quick_links_html
        + latest_schemes_html
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="section-band"><div class="section-title">Priority Official Sources To Expand</div>'
        + '<div class="source-grid">'
        + "".join(render_source_card(source) for source in official_sources[:4])
        + "</div>"
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="section-band">
          <div class="section-title">How It Works</div>
          <div class="how-grid">
            <div class="how-step"><strong>1. Search</strong><br>Find schemes by keyword, agency, sector or eligibility.</div>
            <div class="how-step"><strong>2. Explore</strong><br>Review eligibility, benefits, funding, dates and official documents.</div>
            <div class="how-step"><strong>3. Apply</strong><br>Follow verified application processes and official portals.</div>
            <div class="how-step"><strong>4. Track</strong><br>Check updates, opening dates, closing dates and new calls.</div>
          </div>
        </div>
        <div class="notice-panel"><strong>Important Notice</strong><span>SSIP compiles information from official government websites and documents. Applicants must confirm current eligibility, deadlines and application instructions on the linked official website before applying.</span></div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="footer-note">'
        f'Catalogue refresh signal: {esc(latest_records(records, limit=1)[0].last_updated[:10] if records else "Not available")}. '
        f'{metrics.verification_required_records} record(s) require verification. '
        f'{metrics.records_missing_funding_information} record(s) are missing structured funding information. '
        f'{metrics.records_missing_ministry} record(s) are missing ministry, {metrics.records_missing_department} missing department and {metrics.records_missing_sector} missing sector. '
        'Official-source entries are discovery targets for the later backend crawler and are not counted as published schemes until extraction, validation, admin review and publication are complete.'
        "</div>",
        unsafe_allow_html=True,
    )


def render_filters(records: list[CatalogueRecord], *, keyword: str) -> FilterState:
    with st.container():
        c1, c2, c3, c4 = st.columns(4)
        ministries = c1.multiselect("Ministry", unique_options(records, "ministry"))
        departments = c2.multiselect("Department", unique_options(records, "department"))
        agencies = c3.multiselect("Implementing Agency", unique_options(records, "implementing_agency"))
        sectors = c4.multiselect("Sector", unique_options(records, "sectors"))
        c5, c6, c7, c8 = st.columns(4)
        statuses = c5.multiselect(
            "Status",
            ["OPEN", "CLOSING_SOON", "UPCOMING", "VERIFICATION_REQUIRED", "CLOSED", "HISTORICAL", "REFERENCE"],
            format_func=lambda value: value.replace("_", " ").title(),
        )
        applicant_types = c6.multiselect("Applicant Type", unique_options(records, "target_beneficiaries"))
        scheme_types = c7.multiselect("Scheme / Support Type", unique_options(records, "scheme_types"))
        stages = c8.multiselect("Startup Stage", unique_options(records, "startup_stage"))
        c9, c10, c11, c12 = st.columns(4)
        min_funding = c9.number_input("Minimum Funding", min_value=0, value=0, step=100000)
        max_funding = c10.number_input("Maximum Funding", min_value=0, value=0, step=100000)
        include_verify = c11.checkbox("Include verification-required records", value=True)
        include_archived = c12.checkbox("Include closed / historical", value=True)
    return FilterState(
        keyword=keyword,
        ministries=ministries,
        departments=departments,
        agencies=agencies,
        sectors=sectors,
        applicant_types=applicant_types,
        startup_stages=stages,
        scheme_types=scheme_types,
        statuses=statuses,
        min_funding=min_funding or None,
        max_funding=max_funding or None,
        include_archived=include_archived,
        include_verification_required=include_verify,
    )


def render_explorer(bundle: CatalogueBundle) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = populations.main_scheme_records
    st.markdown(
        '<div class="finder-heading finder-heading-main explorer-search-panel">'
        '<div><div class="finder-title">Find Schemes, Grants, Challenges & Startup Programmes</div>'
        '<p>Search the complete catalogue by scheme name, ministry, department, sector, eligibility, benefit, application portal or support type.</p></div>'
        '<span class="finder-badge">Scheme Explorer</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    search_col, action_col = st.columns([5, 1])
    keyword = search_col.text_input(
        "Search schemes, grants, challenges and programmes",
        placeholder="Search schemes, grants, challenges, departments, sectors, eligibility...",
        key="explorer_search",
        label_visibility="collapsed",
    )
    action_col.markdown('<div class="finder-button-visual">Search</div>', unsafe_allow_html=True)
    with st.expander("Advanced Search", expanded=False):
        state = render_filters(records, keyword=keyword)
        sort_by = st.selectbox("Sort by", ["Recently Updated", "Scheme Name", "Status", "Department"])
    filtered = apply_filters(records, state)
    if sort_by == "Scheme Name":
        filtered = sorted(filtered, key=lambda record: record.scheme_name.casefold())
    elif sort_by == "Status":
        filtered = sorted(filtered, key=lambda record: (status_bucket(record), record.scheme_name.casefold()))
    elif sort_by == "Department":
        filtered = sorted(filtered, key=lambda record: (record.department.casefold(), record.scheme_name.casefold()))
    else:
        filtered = sorted(filtered, key=lambda record: record.last_updated, reverse=True)
    st.markdown(
        f'<div class="filter-summary"><strong>{len(filtered)}</strong> matching record(s)<span>All matching records are shown below</span></div>',
        unsafe_allow_html=True,
    )
    result_cards = []
    for record in filtered:
        warnings = []
        if record.current_decision == "REJECTED":
            warnings.append("This record is retained only because the normalization plan classifies it as closed, historical, archived or pending revalidation.")
        if status_bucket(record) == "VERIFICATION_REQUIRED":
            warnings.append("Status or deadline requires verification before use.")
        result_cards.append(
            '<div class="scheme-result-item">'
            + scheme_card(record)
            + warning_box("Evidence warning", warnings)
            + "</div>"
        )
    st.markdown('<div class="scheme-results-grid">' + "".join(result_cards) + "</div>", unsafe_allow_html=True)


def render_departments(bundle: CatalogueBundle) -> None:
    records = split_catalogue_populations(bundle.records).main_scheme_records
    st.markdown('<div class="section-band"><div class="section-title">Departments & Agencies</div>' + horizontal_bars(department_coverage(records), limit=20) + "</div>", unsafe_allow_html=True)
    rows = []
    for label, count in department_coverage(records).most_common():
        rows.append({"Department / Agency / Source": label, "Records": count})
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_official_sources(official_sources: list[OfficialSource], bundle: CatalogueBundle) -> None:
    stats = source_summary(official_sources)
    st.markdown(
        '<div class="section-band"><div class="section-title">Official Source Registry</div>'
        + '<div class="metric-grid">'
        + metric_card("Source Portals", stats["total_sources"], "Not counted as schemes", "blue")
        + metric_card("Central", stats["central_sources"], "National sources", "green")
        + metric_card("State / UT", stats["state_sources"], "State coverage seeds", "purple")
        + metric_card("Departments", stats["departments"], "From registry fields", "orange")
        + "</div>"
        + "</div>",
        unsafe_allow_html=True,
    )
    warning = [
        "These are discovery seeds only. A source becomes a scheme record only after extraction, validation, admin review and publication.",
        "Do not treat registry counts as scheme counts.",
    ]
    st.markdown(warning_box("Data integrity guardrail", warning), unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    keyword = c1.text_input("Search official sources", placeholder="Department, scheme type, state, agency")
    scopes = sorted({source.scope for source in official_sources if source.scope})
    priorities = sorted({source.priority for source in official_sources if source.priority})
    scope = c2.selectbox("Scope", ["", *scopes], format_func=lambda value: value or "All scopes")
    priority = c3.selectbox("Priority", ["", *priorities], format_func=lambda value: value or "All priorities")
    filtered = filter_sources(official_sources, keyword=keyword, scope=scope, priority=priority)
    st.subheader(f"{len(filtered)} official source(s)")
    st.markdown(
        '<div class="source-grid">'
        + "".join(render_source_card(source) for source in filtered)
        + "</div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    left.markdown(
        '<div class="section-band"><div class="section-title">By Ministry / Government</div>'
        + horizontal_bars(source_counter(official_sources, "ministry"), limit=12)
        + "</div>",
        unsafe_allow_html=True,
    )
    right.markdown(
        '<div class="section-band"><div class="section-title">By Source Type</div>'
        + horizontal_bars(source_counter(official_sources, "source_type"), limit=12)
        + "</div>",
        unsafe_allow_html=True,
    )
    render_departments(bundle)


def render_sectors(bundle: CatalogueBundle) -> None:
    records = split_catalogue_populations(bundle.records).main_scheme_records
    st.markdown('<div class="section-band"><div class="section-title">Sector Coverage</div>' + horizontal_bars(sector_coverage(records), limit=20) + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="section-band"><div class="section-title">Grant / Support Types</div>' + horizontal_bars(grant_support_distribution(records), limit=20) + "</div>", unsafe_allow_html=True)


def render_resources(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:
    rows = []
    for record in bundle.records:
        if record.official_page_url:
            rows.append({"Scheme": record.scheme_name, "Resource Type": "Official Page", "URL": record.official_page_url})
        if record.application_url:
            rows.append({"Scheme": record.scheme_name, "Resource Type": "Application Portal", "URL": record.application_url})
        for url in record.guideline_urls:
            rows.append({"Scheme": record.scheme_name, "Resource Type": "Manual / Guideline", "URL": url})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    for row in rows[:30]:
        st.markdown(f'- <a target="_blank" href="{esc(row["URL"])}">{esc(row["Resource Type"])}: {esc(row["Scheme"])}</a>', unsafe_allow_html=True)
    st.markdown('<div class="section-band"><div class="section-title">Official Source Directory</div>', unsafe_allow_html=True)
    for source in official_sources[:12]:
        st.markdown(f'- <a target="_blank" href="{esc(source.official_url)}">{esc(source.name)}</a>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    render_sectors(bundle)


def render_scheme_details(bundle: CatalogueBundle) -> None:
    records = sorted(
        split_catalogue_populations(
            bundle.records
        ).main_scheme_records,
        key=lambda record: (
            record.scheme_name.casefold(),
            (
                record.department
                or record.implementing_agency
                or record.source
                or ""
            ).casefold(),
        ),
    )

    if not records:
        st.info("No eligible scheme or programme records are available.")
        return

    records_by_id = {record.master_id: record for record in records}
    record_labels = {}
    for item in records:
        agency = (
            item.department
            or item.implementing_agency
            or item.source
            or "Agency not recorded"
        )
        record_labels[item.master_id] = f"{item.scheme_name} — {agency}"

    selected_id = st.selectbox(
        "Select scheme",
        options=[record.master_id for record in records],
        format_func=lambda item_id: record_labels[item_id],
    )
    record = records_by_id[selected_id]

    st.markdown(scheme_card(record), unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.write(f"**Ministry**  \n{record.ministry or 'Not recorded'}")
    c2.write(
        f"**Department / Agency**  \n"
        f"{record.department or record.implementing_agency or record.source or 'Not recorded'}"
    )
    c3.write(
        f"**Record Type**  \n"
        f"{record.record_kind.replace('_', ' ').title()}"
    )

    detail_sections = [
        ("Objectives", record.objectives),
        ("Eligibility", record.eligibility),
        ("Benefits", record.benefits),
        ("Application Process", record.application_process),
        ("Required Documents", record.required_documents),
        ("Contacts", record.contacts),
    ]

    for title, items in detail_sections:
        with st.expander(title, expanded=title in {"Objectives", "Eligibility"}):
            if items:
                for item in items:
                    st.markdown(f"- {item}")
            else:
                st.caption("Not recorded in structured catalogue data.")

    st.markdown("### Official links")

    if record.official_page_url:
        st.markdown(
            f"- [Official scheme/programme page]({record.official_page_url})"
        )
    if record.application_url:
        st.markdown(
            f"- [Application portal]({record.application_url})"
        )

    for index, url in enumerate(record.guideline_urls or [], start=1):
        st.markdown(f"- [Guideline / manual {index}]({url})")

    if not (
        record.official_page_url
        or record.application_url
        or record.guideline_urls
    ):
        st.caption("No official resource links are recorded.")


def main() -> None:
    st.markdown(nav_header(), unsafe_allow_html=True)
    page = st.radio("Navigation", PAGE_NAMES, horizontal=True, label_visibility="collapsed")
    try:
        bundle = cached_catalogue()
        official_sources = cached_official_sources()
    except Exception as exc:
        st.error("The SSIP public dashboard could not load the catalogue.")
        st.exception(exc)
        st.stop()

    if not bundle.records:
        st.warning("No records are available for the selected catalogue mode.")

    if page == "Home":
        render_home(bundle, official_sources)
    elif page == "Scheme Explorer":
        render_explorer(bundle)
    elif page == "Official Sources":
        render_official_sources(official_sources, bundle)
    elif page == "Directory":
        render_resources(bundle, official_sources)
    elif page == "Scheme Details":
        render_scheme_details(bundle)

    st.caption(f"SSIP Public Dashboard v{APP_VERSION}. SQLite access is read-only. Current mode: {bundle.mode.value}.")


if __name__ == "__main__":
    main()

