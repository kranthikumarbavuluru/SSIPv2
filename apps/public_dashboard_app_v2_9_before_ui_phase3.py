from __future__ import annotations

import csv
import html

from collections import Counter
from datetime import date
import sys
from pathlib import Path
from urllib.parse import quote

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_dashboard.catalogue import CatalogueBundle, CatalogueRecord, load_catalogue
from ssip_dashboard.analytics import ReadinessMeasure, build_public_analytics
from ssip_dashboard.components import (
    esc,
    horizontal_bars,
    metric_card,
    scheme_card,
    warning_box,
)
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.filters import FilterState, apply_filters, unique_options
from ssip_dashboard.funding import format_inr
from ssip_dashboard.metrics import (
    compute_metrics,
    department_coverage,
    government_level,
    grant_support_distribution,
    latest_records,
    open_records,
    resource_counts,
    sector_coverage,
    source_scope_lookup,
)
from ssip_dashboard.source_directory import (
    OfficialSource,
    filter_sources,
    load_official_sources,
    source_counter,
    source_summary,
)
from ssip_dashboard.status import parse_date, status_bucket, status_css_class, status_label
from ssip_dashboard.dst_pilot import (
    CONTROLLED_STATUSES,
    DSTCall,
    DSTPilotBundle,
    DSTProgramme,
    default_dst_pilot_path,
    filter_dst_calls,
    filter_dst_programmes,
    load_dst_pilot,
)
from ssip_dashboard.dst_history import (
    DSTHistoricalArchive,
    HistoricalCallAssessment,
    RELEVANCE_ORDER,
    load_dst_historical_archive,
    year_relevance_counts,
)


APP_VERSION = "3.4.0.15-ui-phase2"
PAGE_NAMES = [
    "Home",
    "Scheme Explorer",
    "Calls & Opportunities",
    "DST Schemes",
    "Incubators & Ecosystem",
    "Directory",
    "Official Sources",
    "Scheme Details",
]
NAV_LABELS = {
    "Home": "Home",
    "Scheme Explorer": "Find Schemes",
    "Calls & Opportunities": "Live Calls",
    "DST Schemes": "DST",
    "Incubators & Ecosystem": "Ecosystem",
    "Directory": "Resources",
    "Official Sources": "Sources",
    "Scheme Details": "Profiles",
}
PAGE_SLUGS = {
    "Home": "overview",
    "Scheme Explorer": "scheme-finder",
    "DST Schemes": "dst-programmes",
    "Calls & Opportunities": "live-calls",
    "Incubators & Ecosystem": "ecosystem",
    "Official Sources": "official-sources",
    "Directory": "resources",
    "Scheme Details": "scheme-profiles",
}


def read_stylesheet(path: Path, *, required: bool = False) -> str:
    """Read a CSS file without allowing an optional theme file to stop the app."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        if required:
            raise
        return ""


def load_stylesheets() -> list[str]:
    """Load SSIP styles from general rules to final public-dashboard overrides."""
    stylesheet_paths = [
        (PROJECT_ROOT / "ssip_dashboard" / "assets" / "styles.css", True),
        (PROJECT_ROOT / "assets" / "dashboard_theme.css", False),
        (PROJECT_ROOT / "assets" / "styles" / "ssip_public_dashboard.css", False),
    ]
    return [
        css
        for path, required in stylesheet_paths
        if (css := read_stylesheet(path, required=required))
    ]


st.set_page_config(
    page_title="SSIP Public Dashboard",
    page_icon="SSIP",
    layout="wide",
    initial_sidebar_state="collapsed",
)
for stylesheet in load_stylesheets():
    st.markdown(f"<style>{stylesheet}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=45, show_spinner=False)
def cached_catalogue() -> CatalogueBundle:
    return load_catalogue(DashboardConfig.from_env(PROJECT_ROOT))


@st.cache_data(ttl=300, show_spinner=False)
def cached_official_sources() -> list[OfficialSource]:
    return load_official_sources(PROJECT_ROOT)


@st.cache_data(ttl=45, show_spinner=False)
def cached_dst_pilot() -> DSTPilotBundle:
    return load_dst_pilot(default_dst_pilot_path(PROJECT_ROOT))


@st.cache_data(ttl=300, show_spinner=False)
def cached_dst_historical_archive() -> DSTHistoricalArchive:
    return load_dst_historical_archive(PROJECT_ROOT)


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
        f'<div class="link-row"><span class="link-pill"><a target="_blank" rel="noopener noreferrer" href="{esc(source.official_url)}">Official Source</a></span></div>'
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


PUBLIC_LABELS = {
    "SCHEME_OR_PROGRAMME": "Scheme / Programme",
    "SCHEME": "Scheme",
    "PROGRAMME": "Programme",
    "PROGRAM": "Programme",
    "APPLICATION_CALL": "Application Call",
    "CALL": "Application Call",
    "CHALLENGE": "Challenge",
    "PROGRAMME_COMPONENT": "Programme Component",
    "PROGRAM_COMPONENT": "Programme Component",
    "REFERENCE": "Reference",
    "FUND": "Fund",
}


def public_label(value: object, *, fallback: str = "") -> str:
    """Convert governed/internal tokens into concise public-facing language."""
    raw = str(value or "").strip()
    if not raw:
        return fallback
    token = raw.upper().replace("-", "_").replace(" ", "_")
    if token in PUBLIC_LABELS:
        return PUBLIC_LABELS[token]
    return raw.replace("_", " ").strip().title()


def optional_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.casefold() in {
        "none", "null", "nan", "not available", "not recorded",
        "closing date not recorded", "date not recorded",
    }:
        return ""
    return text


def concise_text(value: str, *, limit: int = 190) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{shortened}…"


def public_record_kind(record: CatalogueRecord) -> str:
    kind = public_label(record.record_kind, fallback="Scheme / Programme")
    if kind == "Reference" and str(record.record_kind or "").upper() not in {"REFERENCE"}:
        return "Scheme / Programme"
    return kind


def record_details_href(record: CatalogueRecord) -> str:
    return (
        f"?page={PAGE_SLUGS['Scheme Details']}"
        f"&scheme={quote(str(record.master_id or ''))}"
    )


def public_record_card(
    record: CatalogueRecord,
    *,
    compact: bool = True,
    include_details_link: bool = True,
) -> str:
    """Render a public-first scheme/call card without exposing internal tokens."""
    agency = (
        record.department
        or record.implementing_agency
        or record.source
        or "Government department / agency"
    )
    description_source = " ".join(
        (record.objectives or record.benefits or ["Information is available on the official source."])[:1]
    )
    description = concise_text(description_source, limit=175 if compact else 240)
    kind = public_record_kind(record)
    status = status_label(record)

    tag_values = [*record.sectors[:2], *record.scheme_types[:1]]
    tags = "".join(
        f'<span class="public-chip">{esc(public_label(value))}</span>'
        for value in tag_values
        if optional_text(value)
    )

    facts: list[str] = []
    closing = optional_text(record.closing_date)
    if closing:
        facts.append(f'<span><b>Closes</b> {esc(closing)}</span>')
    if record.funding_maximum not in (None, "", 0, 0.0):
        facts.append(f'<span><b>Support up to</b> {esc(format_inr(record.funding_maximum))}</span>')
    elif record.funding_minimum not in (None, "", 0, 0.0):
        facts.append(f'<span><b>Support from</b> {esc(format_inr(record.funding_minimum))}</span>')
    fact_html = f'<div class="public-record-facts">{"".join(facts)}</div>' if facts else ""

    actions: list[str] = []
    if record.application_url:
        actions.append(
            f'<a class="public-action public-action-primary" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.application_url)}">Apply now</a>'
        )
    if include_details_link and record.master_id:
        actions.append(
            f'<a class="public-action public-action-secondary" '
            f'href="{html.escape(record_details_href(record), quote=True)}">View details</a>'
        )
    if record.official_page_url:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.official_page_url)}">Official page</a>'
        )
    if record.guideline_urls:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.guideline_urls[0])}">Guideline</a>'
        )

    empty_note = ""
    if not facts:
        empty_note = '<div class="public-record-note">More details are available on the official page.</div>'

    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_css_class(record)}">{esc(status)}</span>'
        f'<span class="public-kind">{esc(kind)}</span>'
        '</div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        f'<p>{esc(description)}</p>'
        f'{fact_html}{empty_note}'
        f'<div class="public-chip-row">{tags}</div>'
        f'<div class="public-record-actions">{"".join(actions)}</div>'
        '</article>'
    )


def site_header() -> str:
    """Compact public-service header independent of internal admin navigation."""
    return (
        '<header class="ssip-site-header">'
        '<div class="ssip-gov-bar"><span>Government startup-support intelligence</span>'
        '<span>Central Government · Andhra Pradesh</span></div>'
        '<div class="ssip-brand-bar">'
        '<div class="ssip-brand-lockup"><span class="ssip-brand-mark">SSIP</span>'
        '<div><strong>SSIP</strong><small>Startup Scheme Intelligence Platform</small></div></div>'
        '<div class="ssip-header-trust"><i></i><span>Curated from official government sources</span></div>'
        '</div></header>'
    )


def page_intro(eyebrow: str, title: str, description: str, *, badge: str = "") -> str:
    badge_html = f'<span class="finder-badge">{esc(badge)}</span>' if badge else ""
    return (
        '<section class="page-intro">'
        f'<div><div class="page-eyebrow">{esc(eyebrow)}</div>'
        f'<h1>{esc(title)}</h1><p>{esc(description)}</p></div>{badge_html}'
        '</section>'
    )


def render_scheme_row(record: CatalogueRecord, lookup: dict[str, str] | None = None) -> str:
    agency = record.department or record.implementing_agency or record.source or "Agency / Source not recorded"
    description = " ".join((record.objectives or record.benefits or ["Information available in official sources."])[:1])
    tags = "".join(
        f'<span class="tag">{esc(public_label(tag))}</span>'
        for tag in [*record.sectors[:2], *record.scheme_types[:1]]
    )
    level = government_level(record, lookup or {})
    links = []
    if record.official_page_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official Page</a>')
    if record.application_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.application_url)}">Application Portal</a>')
    if record.application_process:
        links.append("<span>How to Apply</span>")
    if record.guideline_urls:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.guideline_urls[0])}">Manual</a>')
    if record.reference_urls:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.reference_urls[0])}">Reference</a>')
    link_html = "".join(f'<span class="link-pill">{link}</span>' for link in links)
    eligibility = "; ".join(record.target_beneficiaries[:2] or record.eligibility[:1])
    return (
        '<article class="opportunity-row">'
        f'<div class="opportunity-icon">{esc((record.scheme_name or "S")[:2].upper())}</div>'
        '<div class="opportunity-main">'
        f'<div class="scheme-card-head"><span class="status-badge {status_css_class(record)}">{esc(status_label(record))}</span>'
        f'<span class="record-kind">{esc(public_record_kind(record))}</span>'
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
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(source.official_url)}"><strong>{esc(source.name)}</strong></a>'
            '<span>Priority source seed</span>'
            "</div>"
        )
    return rows


def pct(value: int, total: int) -> str:
    return "0%" if total <= 0 else f"{(value / total) * 100:.0f}%"


STATUS_ORDER = (
    "OPEN",
    "CLOSING_SOON",
    "UPCOMING",
    "VERIFICATION_REQUIRED",
    "CLOSED",
    "HISTORICAL",
    "REFERENCE",
)
STATUS_TONES = {
    "OPEN": "green",
    "CLOSING_SOON": "amber",
    "UPCOMING": "blue",
    "VERIFICATION_REQUIRED": "orange",
    "CLOSED": "slate",
    "HISTORICAL": "purple",
    "REFERENCE": "navy",
    "Central Government": "blue",
    "State Government": "green",
    "Unspecified": "slate",
}


def ordered_counter_rows(counter: Counter[str], order: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    positioned = [(label, counter.get(label, 0)) for label in order if counter.get(label, 0)]
    positioned_labels = {label for label, _value in positioned}
    remaining = sorted(
        ((label, value) for label, value in counter.items() if value and label not in positioned_labels),
        key=lambda item: (-item[1], item[0].casefold()),
    )
    return [*positioned, *remaining]


def render_composition_chart(
    title: str,
    counter: Counter[str],
    *,
    note: str = "",
    order: tuple[str, ...] = (),
) -> str:
    total = sum(counter.values())
    if total <= 0:
        return f'<section class="chart-card analytics-card"><h2 class="section-title">{esc(title)}</h2><div class="empty-note">No structured data recorded.</div></section>'
    segments: list[str] = []
    legend_rows: list[str] = []
    rows = ordered_counter_rows(counter, order)
    accessible_summary = ", ".join(f"{display_token(label)} {value}" for label, value in rows)
    for index, (label, value) in enumerate(rows):
        tone = STATUS_TONES.get(label, ("blue", "green", "amber", "purple", "navy", "slate")[index % 6])
        width = (value / total) * 100
        segments.append(
            f'<span class="composition-segment composition-{tone}" style="width:{width:.2f}%" aria-hidden="true"></span>'
        )
        legend_rows.append(
            '<div class="analytics-legend-row">'
            f'<span class="analytics-legend-key composition-{tone}" aria-hidden="true"></span>'
            f'<strong>{esc(display_token(label))}</strong><span>{value} · {pct(value, total)}</span>'
            "</div>"
        )
    return (
        '<section class="chart-card analytics-card">'
        f'<h2 class="section-title">{esc(title)}</h2>'
        f'<div class="composition-total"><strong>{total}</strong><span>governed record(s)</span></div>'
        f'<div class="composition-track" role="img" aria-label="{esc(title)}: {esc(accessible_summary)}">{"".join(segments)}</div>'
        f'<div class="analytics-legend">{"".join(legend_rows)}</div>'
        f'<div class="chart-note">{esc(note)}</div>'
        "</section>"
    )


def render_ranked_bars(
    title: str,
    counter: Counter[str],
    *,
    note: str = "",
    limit: int = 6,
) -> str:
    rows = counter.most_common(limit)
    if not rows:
        return f'<section class="chart-card analytics-card"><h2 class="section-title">{esc(title)}</h2><div class="empty-note">No structured data recorded.</div></section>'
    maximum = max(value for _label, value in rows) or 1
    total = sum(counter.values())
    body: list[str] = []
    for label, value in rows:
        width = max(3, (value / maximum) * 100)
        body.append(
            '<div class="analytics-bar-row">'
            f'<div class="analytics-bar-heading"><strong>{esc(display_token(label))}</strong><span>{value} · {pct(value, total)}</span></div>'
            f'<div class="analytics-bar-track" role="progressbar" aria-label="{esc(display_token(label))}" aria-valuemin="0" aria-valuemax="{maximum}" aria-valuenow="{value}">'
            f'<span style="width:{width:.2f}%"></span></div>'
            "</div>"
        )
    return (
        '<section class="chart-card analytics-card">'
        f'<h2 class="section-title">{esc(title)}</h2>'
        f'<div class="analytics-bars">{"".join(body)}</div>'
        f'<div class="chart-note">{esc(note)}</div>'
        "</section>"
    )


def render_readiness_chart(
    measures: tuple[ReadinessMeasure, ...],
    *,
    note: str = "",
) -> str:
    rows = []
    for measure in measures:
        rows.append(
            '<div class="readiness-row">'
            f'<div class="readiness-heading"><strong>{esc(measure.label)}</strong>'
            f'<span>{measure.complete}/{measure.total} · {measure.percentage}%</span></div>'
            f'<div class="readiness-track" role="progressbar" aria-label="{esc(measure.label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{measure.percentage}">'
            f'<span style="width:{measure.percentage}%"></span></div>'
            "</div>"
        )
    return (
        '<section class="chart-card analytics-card readiness-card">'
        '<h2 class="section-title">Catalogue Data Readiness</h2>'
        f'<div class="readiness-list">{"".join(rows)}</div>'
        f'<div class="chart-note">{esc(note)}</div>'
        "</section>"
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


def navigate_to(page_name: str) -> None:
    """Move between public pages without mutating a rendered widget mid-run."""
    st.session_state["ssip_primary_navigation"] = page_name
    st.query_params["page"] = PAGE_SLUGS[page_name]


def render_home(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = populations.main_scheme_records
    calls = populations.application_call_records
    metrics = compute_metrics(bundle.records)
    source_stats = source_summary(official_sources)
    lookup = source_scope_lookup(official_sources)
    analytics = build_public_analytics(bundle.records, government_lookup=lookup)
    sector_ready = next((item.complete for item in analytics.readiness if item.label == "Sector evidenced"), 0)

    st.markdown(
        '<section class="public-hero public-hero-compact" aria-labelledby="public-hero-title">'
        '<div class="public-hero-copy">'
        '<span class="public-hero-kicker">Official government startup support</span>'
        '<h1 id="public-hero-title">Find government support for your startup</h1>'
        '<p>Search verified schemes, grants, programmes and live calls from official government sources.</p>'
        '<div class="public-hero-scope" aria-label="Catalogue scope">'
        '<span>Central Government</span><span>Andhra Pradesh</span><span>Startups &amp; Innovators</span>'
        '</div></div>'
        '<aside class="public-hero-summary" aria-label="Current catalogue summary">'
        '<div class="public-hero-summary-label">Catalogue at a glance</div>'
        '<div class="public-hero-summary-grid">'
        f'<div><strong>{analytics.scheme_count}</strong><span>Schemes &amp;<br>programmes</span></div>'
        f'<div><strong>{analytics.open_call_windows}</strong><span>Open call<br>windows</span></div>'
        f'<div><strong>{metrics.total_explicit_departments}</strong><span>Departments<br>mapped</span></div>'
        '</div>'
        f'<div class="public-hero-verified"><span>Latest verification</span><strong>{esc(analytics.latest_verification_signal)}</strong></div>'
        '</aside></section>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<section class="home-search-heading">'
        '<div><span class="page-eyebrow">Start here</span><h2>Search verified startup support</h2>'
        '<p>Search by scheme, department, sector, benefit, eligibility or support type.</p></div>'
        '</section>',
        unsafe_allow_html=True,
    )
    search_col, action_col = st.columns([5.2, 1])
    keyword = search_col.text_input(
        "Search the SSIP catalogue",
        placeholder="Try: seed funding, women entrepreneurs, biotechnology, DST…",
        key="home_primary_search",
        label_visibility="collapsed",
    ).strip()
    with action_col:
        st.button(
            "Advanced search",
            use_container_width=True,
            key="home_open_finder",
            on_click=navigate_to,
            args=("Scheme Explorer",),
        )

    if keyword:
        needle = keyword.casefold()
        featured = [record for record in records if needle in record.search_blob.casefold()]
        featured = sort_records(featured, "Recently Updated")[:6]
        section_title = f"Matching schemes ({len(featured)})"
        section_note = "Results are drawn from governed scheme and programme identities."
    else:
        featured = latest_records(records, limit=6)
        section_title = "Recently verified schemes"
        section_note = "A quick starting point from the latest governed catalogue signals."

    st.markdown(
        f'<div class="home-section-heading"><div><span class="page-eyebrow">Explore support</span>'
        f'<h2>{esc(section_title)}</h2><p>{esc(section_note)}</p></div>'
        '<span class="home-section-action">Official links open in a new tab</span></div>',
        unsafe_allow_html=True,
    )
    if featured:
        st.markdown(
            '<div class="scheme-results-grid home-featured-grid">'
            + "".join(public_record_card(record, compact=True) for record in featured)
            + '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No schemes match this search. Try a broader keyword or use Advanced search.")

    current_calls = [
        item for item in calls
        if status_bucket(item) in {"OPEN", "CLOSING_SOON", "UPCOMING"}
    ]
    current_calls = sorted(
        current_calls,
        key=lambda item: (parse_date(item.closing_date) or date.max, item.scheme_name.casefold()),
    )[:4]
    st.markdown(
        '<div class="home-section-heading home-section-heading-spaced"><div>'
        '<span class="page-eyebrow">Time-bound opportunities</span>'
        '<h2>Open and upcoming calls</h2>'
        '<p>Calls, cohorts and challenges remain separate from their permanent parent schemes.</p>'
        '</div><span class="home-section-action">Check the official deadline before applying</span></div>',
        unsafe_allow_html=True,
    )
    if current_calls:
        st.markdown(
            '<div class="scheme-results-grid home-call-grid">'
            + "".join(public_record_card(record, compact=True) for record in current_calls)
            + '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="home-empty-state"><strong>No verified open call is currently highlighted.</strong>'
            '<span>Use Live Calls to review all published and verification-required opportunities.</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="home-pair-grid home-pair-grid-balanced home-support-grid">'
        '<section class="section-band home-journey-card"><span class="page-eyebrow">Simple journey</span>'
        '<h2 class="section-title">From discovery to application</h2>'
        '<div class="how-grid how-grid-compact">'
        '<div class="how-step"><strong>1. Search</strong><br>Find support by need, sector or agency.</div>'
        '<div class="how-step"><strong>2. Compare</strong><br>Review eligibility, benefit and status.</div>'
        '<div class="how-step"><strong>3. Verify</strong><br>Open official pages and guidelines.</div>'
        '<div class="how-step"><strong>4. Apply</strong><br>Use the verified application route.</div>'
        '</div></section>'
        '<section class="section-band home-trust-card"><span class="page-eyebrow">Trust &amp; transparency</span>'
        '<h2 class="section-title">Evidence before assumptions</h2>'
        '<div class="trust-list">'
        '<span>Permanent schemes and temporary calls are stored separately.</span>'
        '<span>Missing eligibility or funding is shown as missing—not inferred.</span>'
        '<span>Every application decision should be confirmed on the official source.</span>'
        '</div></section></div>',
        unsafe_allow_html=True,
    )

    analytics_grid_html = (
        '<div class="analytics-dashboard compact-analytics-dashboard">'
        '<div class="analytics-primary-grid">'
        + render_composition_chart(
            "Application Call Status",
            analytics.call_statuses,
            note=f"Calls are separate from parent programmes. {analytics.verification_required_calls} call(s) need stronger status evidence.",
            order=STATUS_ORDER,
        )
        + render_readiness_chart(
            analytics.readiness,
            note="Completeness is measured across schemes and programmes; missing values are not inferred.",
        )
        + "</div>"
        '<div class="analytics-comparison-grid">'
        + render_ranked_bars(
            "Schemes by Department or Agency",
            analytics.departments,
            note="Calls are excluded from this scheme comparison.",
            limit=6,
        )
        + render_ranked_bars(
            "Verified Sector Coverage",
            analytics.structured_sectors,
            note=f"{sector_ready} of {analytics.scheme_count} schemes currently have structured sector evidence.",
            limit=6,
        )
        + "</div>"
        '<div class="analytics-secondary-grid">'
        + render_composition_chart(
            "Government Level Coverage",
            analytics.government_levels,
            note="Mapped from explicit fields or the official-source registry.",
            order=("Central Government", "State Government", "Unspecified"),
        )
        + render_ranked_bars(
            "Verified Support Types",
            analytics.structured_support_types,
            note="Unspecified support types are excluded from the bars.",
            limit=6,
        )
        + "</div>"
        + '<div class="data-quality-callout"><strong>Coverage context</strong>'
        + f'<span>{metrics.records_missing_sector} scheme(s) still need sector evidence and {metrics.records_missing_funding_information} need structured funding. '
        + f'The official-source registry tracks {source_stats["central_sources"]} Central and {source_stats["state_sources"]} State/UT source entries.</span></div>'
        + "</div>"
    )
    with st.expander("Catalogue insights and data readiness", expanded=False):
        st.markdown(analytics_grid_html, unsafe_allow_html=True)

    source_names = "".join(
        f'<span>{esc(source.name)}</span>' for source in official_sources[:3]
    )
    st.markdown(
        '<section class="official-source-summary">'
        '<div><span class="page-eyebrow">Official evidence</span>'
        f'<h2>Verified across {len(official_sources)} government portals</h2>'
        '<p>SSIP uses authoritative government sources for discovery and verification.</p>'
        f'<div class="official-source-chips">{source_names}</div></div>'
        f'<a class="public-action public-action-secondary" href="?page={PAGE_SLUGS["Official Sources"]}">Browse official sources</a>'
        '</section>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="notice-panel home-final-notice"><strong>Before you apply</strong>'
        '<span>Confirm current eligibility, deadlines and application instructions on the linked official government website.</span></div>',
        unsafe_allow_html=True,
    )
    latest_signal = latest_records(records, limit=1)[0].last_updated[:10] if records else "Not available"
    st.markdown(
        '<footer class="public-footer">'
        f'<span>Last catalogue update: {esc(latest_signal)}</span>'
        '<span>Official-source catalogue · Read-only public access</span>'
        '</footer>',
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
        '<div><h1 class="finder-title">Find Schemes, Grants, Challenges &amp; Startup Programmes</h1>'
        '<p>Search the complete catalogue by scheme name, ministry, department, sector, eligibility, benefit, application portal or support type.</p></div>'
        '<span class="finder-badge">Scheme Explorer</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    search_col, action_col = st.columns([5, 1])
    keyword = search_col.text_input(
        "Search schemes, grants, challenges and programmes",
        placeholder="Search schemes, grants, challenges, departments, sectors, eligibility…",
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
    display_limit = st.selectbox(
        "Results displayed",
        [24, 48, 0],
        format_func=lambda value: "All results" if value == 0 else f"First {value} results",
        key="explorer_display_limit",
    )
    displayed = filtered if display_limit == 0 else filtered[:display_limit]
    st.markdown(
        f'<div class="filter-summary"><strong>{len(filtered)}</strong> matching record(s)<span>Showing {len(displayed)} below</span></div>',
        unsafe_allow_html=True,
    )
    result_cards = []
    for record in displayed:
        warnings = []
        if record.current_decision == "REJECTED":
            warnings.append("This record is retained only because the normalization plan classifies it as closed, historical, archived or pending revalidation.")
        if status_bucket(record) == "VERIFICATION_REQUIRED":
            warnings.append("Status or deadline requires verification before use.")
        result_cards.append(
            '<div class="scheme-result-item">'
            + public_record_card(record, compact=False)
            + warning_box("Evidence warning", warnings)
            + "</div>"
        )
    st.markdown('<div class="scheme-results-grid">' + "".join(result_cards) + "</div>", unsafe_allow_html=True)


def render_departments(bundle: CatalogueBundle) -> None:
    records = split_catalogue_populations(bundle.records).main_scheme_records
    st.markdown('<div class="section-band"><h2 class="section-title">Departments &amp; Agencies</h2>' + horizontal_bars(department_coverage(records), limit=20) + "</div>", unsafe_allow_html=True)
    rows = []
    for label, count in department_coverage(records).most_common():
        rows.append({"Department / Agency / Source": label, "Records": count})
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_official_sources(official_sources: list[OfficialSource], bundle: CatalogueBundle) -> None:
    stats = source_summary(official_sources)
    st.markdown(
        page_intro(
            "Source governance",
            "Official Source Registry",
            "Search the authoritative government portals used for discovery. Registry entries are source seeds, not scheme records.",
            badge=f"{stats['total_sources']} portals",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="section-band"><h2 class="section-title">Official Source Registry</h2>'
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
    c1, c2, c3, c4 = st.columns([2, 1, 1, .75])
    keyword = c1.text_input("Search official sources", placeholder="Department, scheme type, state, agency")
    scopes = sorted({source.scope for source in official_sources if source.scope})
    priorities = sorted({source.priority for source in official_sources if source.priority})
    scope = c2.selectbox("Scope", ["", *scopes], format_func=lambda value: value or "All scopes")
    priority = c3.selectbox("Priority", ["", *priorities], format_func=lambda value: value or "All priorities")
    display_limit = c4.selectbox("Show", [12, 24, 0], format_func=lambda value: "All" if value == 0 else str(value), key="source_display_limit")
    filtered = filter_sources(official_sources, keyword=keyword, scope=scope, priority=priority)
    displayed = filtered if display_limit == 0 else filtered[:display_limit]
    st.subheader(f"{len(filtered)} official source(s) · showing {len(displayed)}")
    st.markdown(
        '<div class="source-grid">'
        + "".join(render_source_card(source) for source in displayed)
        + "</div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    left.markdown(
        '<div class="section-band"><h2 class="section-title">By Ministry / Government</h2>'
        + horizontal_bars(source_counter(official_sources, "ministry"), limit=12)
        + "</div>",
        unsafe_allow_html=True,
    )
    right.markdown(
        '<div class="section-band"><h2 class="section-title">By Source Type</h2>'
        + horizontal_bars(source_counter(official_sources, "source_type"), limit=12)
        + "</div>",
        unsafe_allow_html=True,
    )
    render_departments(bundle)


def render_sectors(bundle: CatalogueBundle) -> None:
    records = split_catalogue_populations(bundle.records).main_scheme_records
    st.markdown('<div class="section-band"><h2 class="section-title">Sector Coverage</h2>' + horizontal_bars(sector_coverage(records), limit=20) + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="section-band"><h2 class="section-title">Grant / Support Types</h2>' + horizontal_bars(grant_support_distribution(records), limit=20) + "</div>", unsafe_allow_html=True)


def render_resources(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = [*populations.main_scheme_records, *populations.application_call_records]
    resource_records = [
        item for item in records
        if item.official_page_url or item.application_url or item.guideline_urls or item.reference_urls
    ]
    st.markdown(
        page_intro(
            "Application resources",
            "Official Links & Documents",
            "Open verified scheme pages, application portals, manuals and reference documents without searching across multiple government websites.",
            badge=f"{len(resource_records)} records",
        ),
        unsafe_allow_html=True,
    )
    application_count = sum(bool(item.application_url) for item in resource_records)
    guideline_count = sum(bool(item.guideline_urls) for item in resource_records)
    st.markdown(
        '<div class="metric-grid resource-metrics">'
        + metric_card("Resource Records", len(resource_records), "Schemes and calls with official links", "blue")
        + metric_card("Application Portals", application_count, "Direct official application routes", "green")
        + metric_card("Manuals & Guidelines", guideline_count, "Structured official documents", "orange")
        + metric_card("Source Registry", len(official_sources), "Discovery portals maintained", "purple")
        + '</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns([2, 1, 1, .75])
    keyword = c1.text_input("Search resources", placeholder="Scheme, call, department or document", key="resource_keyword").strip().casefold()
    population = c2.selectbox("Record population", ["ALL", "SCHEME", "CALL"], format_func=lambda value: {"ALL":"All records","SCHEME":"Schemes & programmes","CALL":"Application calls"}[value])
    resource_type = c3.selectbox("Resource type", ["ALL", "APPLICATION", "GUIDELINE", "OFFICIAL"], format_func=lambda value: {"ALL":"All resources","APPLICATION":"Application portals","GUIDELINE":"Manuals & guidelines","OFFICIAL":"Official pages"}[value])
    display_limit = c4.selectbox("Show", [24, 48, 0], format_func=lambda value: "All" if value == 0 else str(value), key="resource_display_limit")
    visible = []
    for item in resource_records:
        is_call = item.record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"}
        if population == "CALL" and not is_call:
            continue
        if population == "SCHEME" and is_call:
            continue
        if resource_type == "APPLICATION" and not item.application_url:
            continue
        if resource_type == "GUIDELINE" and not item.guideline_urls:
            continue
        if resource_type == "OFFICIAL" and not item.official_page_url:
            continue
        if keyword and keyword not in " ".join([item.scheme_name, item.department, item.implementing_agency, item.source, item.search_blob]).casefold():
            continue
        visible.append(item)
    displayed = visible if display_limit == 0 else visible[:display_limit]
    cards = []
    for item in displayed:
        kind = "Application call" if item.record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"} else "Scheme / programme"
        agency = item.department or item.implementing_agency or item.source or "Agency not recorded"
        links = _dst_links(
            ("Official page", item.official_page_url),
            ("Apply", item.application_url),
            ("Guideline", item.guideline_urls[0] if item.guideline_urls else ""),
            ("Reference", item.reference_urls[0] if item.reference_urls else ""),
        )
        cards.append(
            '<article class="resource-card">'
            f'<div class="scheme-card-head"><span class="record-kind">{esc(kind)}</span>'
            f'<span class="status-badge {status_css_class(item)}">{esc(status_label(item))}</span></div>'
            f'<h3>{esc(item.scheme_name)}</h3><div class="agency-line">{esc(agency)}</div>'
            f'<div class="resource-actions">{links}</div></article>'
        )
    st.markdown(f'<div class="filter-summary"><strong>{len(visible)}</strong> resource record(s)<span>Showing {len(displayed)} · official links open in a new tab</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="resource-grid">' + "".join(cards) + '</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-band resource-source-band"><h2 class="section-title">Priority Government Portals</h2>'
        + '<div class="source-link-grid">'
        + "".join(
            f'<a target="_blank" rel="noopener" href="{esc(source.official_url)}"><strong>{esc(source.name)}</strong><span>{esc(source.scope)} · {esc(source.source_type.replace("_", " ").title())}</span></a>'
            for source in official_sources[:12]
        )
        + '</div></div>',
        unsafe_allow_html=True,
    )




def _dst_preview_notice(bundle: DSTPilotBundle) -> None:
    st.markdown(
        '<div class="notice-box"><b>DST relationship intelligence</b><br>'
        'This department view explains permanent programme identities and their call relationships. '
        'Publication is governed separately; published records appear in Scheme Explorer and the Calls pages.</div>',
        unsafe_allow_html=True,
    )
    if not bundle.programmes:
        st.error("The DST pilot database is unavailable. Run scripts/run_dst_pilot_v1.py to rebuild it.")


def _dst_status_badge(status: str) -> str:
    classes = {
        "OPEN": "status-open",
        "UPCOMING": "status-upcoming",
        "CLOSED": "status-closed",
        "STATUS_UNVERIFIED": "status-unverified",
    }
    label = status.replace("_", " ").title()
    return f'<span class="status-badge {classes.get(status, "status-reference")}">{esc(label)}</span>'


def _dst_links(*links: tuple[str, str]) -> str:
    parts = [
        f'<a target="_blank" rel="noopener" href="{html.escape(url, quote=True)}">{esc(label)}</a>'
        for label, url in links if url
    ]
    return " &nbsp; ".join(parts)


def _dst_programme_card(item: DSTProgramme, related_calls: list[DSTCall]) -> str:
    direct = sum(call.startup_relevance == "STARTUP_RELEVANT" for call in related_calls)
    ecosystem = sum(call.is_ecosystem for call in related_calls)
    open_calls = sum(call.application_status == "OPEN" and not call.is_ecosystem for call in related_calls)
    parent = item.parent_name or "Department of Science and Technology"
    sector = item.primary_sector or "Sector evidence pending"
    return (
        '<article class="scheme-card">'
        '<div class="scheme-card-head">'
        f'<span class="record-kind">{esc(item.entity_type.replace("_", " ").title())}</span>'
        f'<span class="status-badge status-reference">{esc(item.sector_scope.replace("_", " ").title())}</span></div>'
        f'<h3>{esc(item.canonical_name)}</h3><div class="agency-line">Parent: {esc(parent)}</div>'
        f'<p>{esc(item.evidence_text)}</p>'
        f'<div class="scheme-meta"><span>{esc(sector)}</span><span>{direct} direct call(s)</span>'
        f'<span>{ecosystem} intermediary call(s)</span><span>{open_calls} open</span></div>'
        f'<div class="scheme-links">{_dst_links(("Official programme page", item.official_master_url))}</div>'
        '</article>'
    )


def render_dst_schemes() -> None:
    bundle = cached_dst_pilot()
    st.markdown(page_intro("Department view", "DST Schemes & Programmes", "Permanent programme identities only. Dated calls, archive pages and implementing centres are excluded from the scheme count.", badge="DST intelligence"), unsafe_allow_html=True)
    _dst_preview_notice(bundle)
    if not bundle.programmes:
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    keyword = c1.text_input("Search DST schemes", key="dst_scheme_keyword", placeholder="PRAYAS, seed support, accelerator…")
    entity_types = sorted({item.entity_type for item in bundle.programmes})
    entity_type = c2.selectbox("Programme type", ["", *entity_types], format_func=lambda value: value.replace("_", " ").title() if value else "All types")
    scopes = sorted({item.sector_scope for item in bundle.programmes})
    sector_scope = c3.selectbox("Sector scope", ["", *scopes], format_func=lambda value: value.replace("_", " ").title() if value else "All scopes")
    visible = filter_dst_programmes(bundle.programmes, keyword=keyword, entity_type=entity_type, sector_scope=sector_scope)
    st.markdown(f"**{len(visible)} permanent DST programme record(s)**")
    cards = []
    for programme in visible:
        related = [call for call in bundle.calls if call.parent_master_id == programme.master_id]
        cards.append(_dst_programme_card(programme, related))
    st.markdown('<div class="programme-grid">' + "".join(cards) + '</div>', unsafe_allow_html=True)


def _dst_call_card(item: DSTCall, *, ecosystem: bool = False) -> str:
    parent = item.parent_name or "Parent programme requires curation"
    implementing = item.implementing_entity or "Implementing entity requires curation"
    applicants = item.eligible_applicants or item.applicant_layer.replace("_", " ").title() or "Applicant layer unverified"
    sector = item.primary_sector or "Sector evidence pending"
    secondary = f"; {item.secondary_sectors}" if item.secondary_sectors else ""
    funding = item.funding_summary or "Funding details require verification"
    stage = item.startup_stage.replace("_", " ").title() if item.startup_stage else "Stage requires verification"
    verified = item.last_verified_at or "Not recorded"
    warning = ""
    if item.startup_relevance == "REVIEW_REQUIRED":
        warning = '<div class="warning-box">Startup applicability requires curator approval.</div>'
    if ecosystem:
        warning = '<div class="warning-box">For incubators/institutions — not a direct startup application.</div>'
    return (
        '<article class="scheme-card">'
        '<div class="scheme-card-head">'
        f'<span class="record-kind">{esc(item.call_type.replace("_", " ").title())}</span>{_dst_status_badge(item.application_status)}</div>'
        f'<h3>{esc(item.call_title)}</h3><div class="agency-line">Parent scheme: {esc(parent)} · Implemented by: {esc(implementing)}</div>'
        f'{warning}<div class="scheme-meta"><span>Opens: {esc(item.opening_date or "Not recorded")}</span>'
        f'<span>Closes: {esc(item.closing_date or "Not published")}</span><span>{esc(sector + secondary)}</span>'
        f'<span>Last verified: {esc(verified)}</span></div>'
        f'<p><b>Eligible applicants:</b> {esc(applicants)}</p><p><b>Startup/technology stage:</b> {esc(stage)}</p>'
        f'<p><b>Funding:</b> {esc(funding)}</p>'
        f'<p><b>Status evidence:</b> {esc(item.status_evidence or item.application_status.replace("_", " ").title())}</p>'
        f'<p class="muted"><b>Evidence decision:</b> {esc(item.startup_relevance_reason or item.applicant_layer_reason)}</p>'
        f'<div class="scheme-links">{_dst_links(("Official announcement", item.detail_url), ("Apply", item.application_url), ("Guidelines", item.guideline_url), ("Attachment", item.attachment_url))}</div>'
        '</article>'
    )


def _render_dst_call_filters(calls: list[DSTCall], *, key_prefix: str) -> list[DSTCall]:
    counts = Counter(item.application_status for item in calls)
    status_options = ["OPEN", "UPCOMING", "CLOSED", "STATUS_UNVERIFIED", "ALL"]
    default_status = next((value for value in status_options[:-1] if counts.get(value, 0)), "ALL")
    selected = st.radio(
        "Call status",
        status_options,
        index=status_options.index(default_status),
        horizontal=True,
        key=f"{key_prefix}_status",
        format_func=lambda value: f"{value.replace('_', ' ').title()} ({len(calls) if value == 'ALL' else counts.get(value, 0)})",
    )
    c1, c2, c3 = st.columns([2, 1, 1])
    keyword = c1.text_input("Search calls", key=f"{key_prefix}_keyword", placeholder="startup, quantum, PRAYAS…")
    sectors = sorted({item.primary_sector for item in calls if item.primary_sector})
    sector = c2.selectbox("Sector", ["", *sectors], key=f"{key_prefix}_sector", format_func=lambda value: value or "All sectors")
    parent_ids = sorted({item.parent_master_id for item in calls if item.parent_master_id})
    names = {item.parent_master_id: item.parent_name for item in calls if item.parent_master_id}
    parent_id = c3.selectbox("Parent programme", ["", *parent_ids], key=f"{key_prefix}_parent", format_func=lambda value: names.get(value, "All parents") if value else "All parents")
    return filter_dst_calls(calls, status="" if selected == "ALL" else selected, keyword=keyword, sector=sector, parent_id=parent_id)


def _published_calls(bundle: CatalogueBundle) -> list[CatalogueRecord]:
    """Return only calls that passed both review and publication governance."""
    calls = split_catalogue_populations(bundle.records).application_call_records
    return [
        item for item in calls
        if item.publication_status.upper() == "PUBLISHED" and int(item.is_public or 0) == 1
    ]


def _published_call_card(
    item: CatalogueRecord,
    *,
    parent_names: dict[str, str],
    ecosystem: bool = False,
) -> str:
    parent = (
        item.parent_scheme_name
        or parent_names.get(item.parent_master_id, "")
        or "Parent scheme requires curation"
    )


def _historical_relevance_label(value: str) -> str:
    return {
        "STARTUP_RELEVANT": "Startup relevant",
        "STARTUP_ECOSYSTEM_CALL": "Ecosystem call",
        "REVIEW_REQUIRED": "Relevance review",
        "GENERAL_DST": "General DST call",
    }.get(value, value.replace("_", " ").title())


def _historical_chart(records: list[HistoricalCallAssessment]) -> str:
    counts = year_relevance_counts(records)
    if not counts:
        return '<div class="empty-note">No historical year data is available.</div>'
    totals = {year: sum(groups.values()) for year, groups in counts.items()}
    maximum = max(totals.values()) or 1
    legend = "".join(
        f'<span><i class="history-segment history-{group.casefold().replace("_", "-")}"></i>{esc(_historical_relevance_label(group))}</span>'
        for group in RELEVANCE_ORDER
    )
    rows = []
    for year, groups in counts.items():
        segments = "".join(
            f'<span class="history-segment history-{group.casefold().replace("_", "-")}" '
            f'style="width:{(groups[group] / maximum) * 100:.3f}%" '
            f'title="{esc(_historical_relevance_label(group))}: {groups[group]}"></span>'
            for group in RELEVANCE_ORDER if groups[group]
        )
        rows.append(
            '<div class="history-row">'
            f'<strong>{year}</strong><div class="history-track">{segments}</div>'
            f'<b>{totals[year]}</b></div>'
        )
    return (
        '<div class="history-chart"><div class="history-legend">' + legend + '</div>'
        + "".join(rows) + '</div>'
    )


def _historical_call_card(item: HistoricalCallAssessment) -> str:
    call = item.call
    sectors = "; ".join(value for value in [call.primary_sector, call.secondary_sectors] if value) or "Sector not assessed"
    applicants = call.eligible_applicants or call.applicant_layer.replace("_", " ").title() or "Applicant classification not assessed"
    warning = ""
    if item.relevance_group == "GENERAL_DST":
        warning = '<div class="archive-note">Official DST archive record — not classified as a startup opportunity.</div>'
    elif item.relevance_group == "REVIEW_REQUIRED":
        warning = '<div class="archive-note">Startup relevance requires further evidence review.</div>'
    link = (
        f'<a target="_blank" rel="noopener" href="{html.escape(call.detail_url, quote=True)}">Official historical call</a>'
        if call.detail_url else ""
    )
    return (
        '<article class="historical-call-card">'
        '<div class="scheme-card-head">'
        '<span class="status-badge status-history">Historical</span>'
        f'<span class="record-kind">{esc(_historical_relevance_label(item.relevance_group))}</span>'
        f'<span class="record-kind">{esc(str(item.closing_year or "Year unknown"))}</span></div>'
        f'<h3>{esc(call.call_title)}</h3>{warning}'
        '<div class="scheme-meta">'
        f'<span>Opened: {esc(call.opening_date or "Not recorded")}</span>'
        f'<span>Closed: {esc(call.closing_date or "Not recorded")}</span>'
        f'<span>Last verified: {esc(call.last_verified_at or "Not recorded")}</span></div>'
        f'<p><b>Applicant evidence:</b> {esc(applicants)}</p>'
        f'<p><b>Sector evidence:</b> {esc(sectors)}</p>'
        f'<p><b>Status basis:</b> {esc(call.status_evidence or call.status_basis or "Official historical deadline")}</p>'
        f'<div class="resource-actions">{link}</div>'
        '</article>'
    )


def render_dst_historical_archive() -> None:
    archive = cached_dst_historical_archive()
    records = archive.historical_records
    manifest = archive.manifest
    st.markdown(
        '<div class="archive-governance"><strong>Automated historical qualification</strong>'
        f'<span>{manifest["qualified_historical_calls"]} closed calls passed official-source, date, identity and page-role gates. '
        f'{manifest["current_calls_excluded"]} current calls are excluded. This archive does not imply startup eligibility.</span></div>',
        unsafe_allow_html=True,
    )
    metrics = '<div class="metric-grid archive-metrics">' + (
        metric_card("Historical Calls", len(records), "Closed official DST call instances", "blue")
        + metric_card("Startup Relevant", manifest["relevance_counts"]["STARTUP_RELEVANT"], "Explicit startup evidence", "green")
        + metric_card("Ecosystem", manifest["relevance_counts"]["STARTUP_ECOSYSTEM_CALL"], "Institutional implementation calls", "purple")
        + metric_card("General DST", manifest["relevance_counts"]["GENERAL_DST"], "Not shown as startup opportunities", "orange")
    ) + '</div>'
    st.markdown(metrics, unsafe_allow_html=True)
    st.markdown('<div class="section-band"><h2 class="section-title">DST Historical Calls by Closing Year</h2>' + _historical_chart(records) + '</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    keyword = c1.text_input("Search historical calls", placeholder="Title, applicant, sector or programme", key="dst_history_keyword").strip().casefold()
    years = sorted({item.closing_year for item in records if item.closing_year is not None}, reverse=True)
    selected_year = c2.selectbox("Closing year", [0, *years], format_func=lambda value: "All years" if value == 0 else str(value), key="dst_history_year")
    relevance = c3.selectbox("Relevance", ["ALL", *RELEVANCE_ORDER], format_func=lambda value: "All relevance" if value == "ALL" else _historical_relevance_label(value), key="dst_history_relevance")
    sectors = sorted({item.call.primary_sector for item in records if item.call.primary_sector})
    sector = c4.selectbox("Sector", ["", *sectors], format_func=lambda value: value or "All sectors", key="dst_history_sector")

    visible = []
    for item in records:
        call = item.call
        haystack = " ".join((call.call_title, call.parent_name, call.eligible_applicants, call.primary_sector, call.secondary_sectors)).casefold()
        if keyword and keyword not in haystack:
            continue
        if selected_year and item.closing_year != selected_year:
            continue
        if relevance != "ALL" and item.relevance_group != relevance:
            continue
        if sector and sector not in {call.primary_sector, *call.secondary_sectors.split("; ")}:
            continue
        visible.append(item)
    visible.sort(key=lambda item: (item.closing_date or date.min, item.call.call_title.casefold()), reverse=True)
    page_size = 30
    total_pages = max(1, (len(visible) + page_size - 1) // page_size)
    page_number = st.selectbox(
        "Archive page",
        range(1, total_pages + 1),
        format_func=lambda value: f"Page {value} of {total_pages}",
        key="dst_history_page",
    )
    page_start = (page_number - 1) * page_size
    displayed = visible[page_start:page_start + page_size]
    first_record = page_start + 1 if displayed else 0
    last_record = page_start + len(displayed)
    st.markdown(
        f'<div class="filter-summary"><strong>{len(visible)}</strong> historical call(s) match'
        f'<span>Showing {first_record}–{last_record} · 30 per page · no active Apply action is displayed</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="historical-call-grid">' + "".join(_historical_call_card(item) for item in displayed) + '</div>', unsafe_allow_html=True)
    st.caption(f"Archive manifest: {manifest['signature'][:16]}… · Human stratified sample: {len(manifest['sample_ids'])} records · Exceptions: {manifest['exception_count']}")


def _render_published_call_filters(
    calls: list[CatalogueRecord],
    *,
    key_prefix: str,
    parent_names: dict[str, str],
) -> list[CatalogueRecord]:
    counts = Counter((item.application_status or "STATUS_UNVERIFIED").upper() for item in calls)
    status_options = ["OPEN", "UPCOMING", "CLOSED", "STATUS_UNVERIFIED", "ALL"]
    default_status = next((value for value in status_options[:-1] if counts.get(value, 0)), "ALL")
    selected = st.radio(
        "Call status",
        status_options,
        index=status_options.index(default_status),
        horizontal=True,
        key=f"{key_prefix}_status",
        format_func=lambda value: f"{value.replace('_', ' ').title()} ({len(calls) if value == 'ALL' else counts.get(value, 0)})",
    )
    c1, c2, c3 = st.columns([2, 1, 1])
    keyword = c1.text_input("Search calls", key=f"{key_prefix}_keyword", placeholder="startup, quantum, PRAYAS…").strip().casefold()
    sectors = sorted({sector for item in calls for sector in item.sectors if sector})
    sector = c2.selectbox("Sector", ["", *sectors], key=f"{key_prefix}_sector", format_func=lambda value: value or "All sectors")
    parent_ids = sorted({item.parent_master_id for item in calls if item.parent_master_id})
    parent_id = c3.selectbox(
        "Parent programme",
        ["", *parent_ids],
        key=f"{key_prefix}_parent",
        format_func=lambda value: parent_names.get(value, value) if value else "All parents",
    )
    visible = []
    for item in calls:
        status = (item.application_status or "STATUS_UNVERIFIED").upper()
        haystack = " ".join([
            item.scheme_name,
            item.parent_scheme_name,
            parent_names.get(item.parent_master_id, ""),
            item.implementing_agency,
            item.search_blob,
        ]).casefold()
        if selected != "ALL" and status != selected:
            continue
        if keyword and keyword not in haystack:
            continue
        if sector and sector not in item.sectors:
            continue
        if parent_id and item.parent_master_id != parent_id:
            continue
        visible.append(item)
    return visible


def render_calls_and_opportunities() -> None:
    bundle = cached_catalogue()
    all_calls = _published_calls(bundle)
    calls = [item for item in all_calls if item.applicant_layer.upper() != "INTERMEDIARY_IMPLEMENTER"]
    parent_names = {item.master_id: item.scheme_name for item in bundle.records}
    st.markdown(page_intro("Calls intelligence", "Calls & Opportunities", "Current opportunities, published closed startup calls and the governed DST historical archive are maintained as separate views.", badge=f"{len(calls)} published startup-scope calls"), unsafe_allow_html=True)
    call_view = st.radio(
        "Call catalogue view",
        ["OPEN_CURRENT", "CLOSED_STARTUP", "HISTORICAL_ARCHIVE"],
        horizontal=True,
        key="call_catalogue_view",
        format_func=lambda value: {
            "OPEN_CURRENT": "Open & Current",
            "CLOSED_STARTUP": "Closed Startup Calls",
            "HISTORICAL_ARCHIVE": "DST Historical Archive",
        }[value],
    )
    if call_view == "HISTORICAL_ARCHIVE":
        render_dst_historical_archive()
        return
    calls = [
        item for item in calls
        if (
            item.application_status.upper() != "CLOSED"
            if call_view == "OPEN_CURRENT"
            else item.application_status.upper() == "CLOSED"
        )
    ]
    if not calls:
        st.info("No published direct or applicant-layer-unverified calls are available.")
        return
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Open", sum(item.application_status == "OPEN" for item in calls), "Accepting applications", "green")
        + metric_card("Upcoming", sum(item.application_status == "UPCOMING" for item in calls), "Future application windows", "blue")
        + metric_card("Closed", sum(item.application_status == "CLOSED" for item in calls), "Retained for reference", "purple")
        + metric_card("Layer Review", sum(item.applicant_layer.upper() in {"", "UNKNOWN", "UNVERIFIED"} for item in calls), "Applicant classification pending", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    visible = _render_published_call_filters(calls, key_prefix=f"published_direct_{call_view.casefold()}", parent_names=parent_names)
    st.markdown(f"**{len(visible)} matching published direct/review call(s)**")
    st.markdown('<div class="call-grid">' + "".join(_published_call_card(item, parent_names=parent_names) for item in visible) + '</div>', unsafe_allow_html=True)


def render_startup_ecosystem() -> None:
    bundle = cached_catalogue()
    calls = [item for item in _published_calls(bundle) if item.applicant_layer.upper() == "INTERMEDIARY_IMPLEMENTER"]
    parent_names = {item.master_id: item.scheme_name for item in bundle.records}
    st.markdown(page_intro("Institutional opportunities", "Published Incubator & Ecosystem Calls", "Published calls for TBIs, incubators, programme centres and implementation partners. These are never shown as direct founder applications.", badge=f"{len(calls)} intermediary calls"), unsafe_allow_html=True)
    if not calls:
        st.info("No published intermediary calls are available.")
        return
    visible = _render_published_call_filters(calls, key_prefix="published_ecosystem", parent_names=parent_names)
    st.markdown(f"**{len(visible)} matching published intermediary call(s)**")
    st.markdown('<div class="call-grid">' + "".join(_published_call_card(item, parent_names=parent_names, ecosystem=True) for item in visible) + '</div>', unsafe_allow_html=True)


def render_scheme_details(bundle: CatalogueBundle) -> None:
    records = sorted(
        split_catalogue_populations(
            bundle.records
        ).main_scheme_records,
        key=lambda record: (
            0 if record.publication_status.upper() == "PUBLISHED" else 1,
            1 if status_bucket(record) == "VERIFICATION_REQUIRED" else 0,
            1 if record.scheme_name.casefold().endswith((".html", ".aspx")) else 0,
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

    st.markdown(page_intro("Scheme profile", "Scheme Details", "Review structured eligibility, benefits, application steps, documents and official links for one scheme or programme.", badge=f"{len(records)} profiles"), unsafe_allow_html=True)

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

    record_ids = [record.master_id for record in records]
    requested_scheme = str(st.query_params.get("scheme", "") or "").strip()
    selected_index = record_ids.index(requested_scheme) if requested_scheme in record_ids else 0
    selected_id = st.selectbox(
        "Select scheme",
        options=record_ids,
        index=selected_index,
        format_func=lambda item_id: record_labels[item_id],
        key="scheme_profile_selector",
    )
    if str(st.query_params.get("scheme", "") or "") != selected_id:
        st.query_params["scheme"] = selected_id
    record = records_by_id[selected_id]

    st.markdown(
        public_record_card(record, compact=False, include_details_link=False),
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.write(f"**Ministry**  \n{record.ministry or 'Not recorded'}")
    c2.write(
        f"**Department / Agency**  \n"
        f"{record.department or record.implementing_agency or record.source or 'Not recorded'}"
    )
    c3.write(
        f"**Record Type**  \n"
        f"{public_record_kind(record)}"
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

    detail_links: list[tuple[str, str]] = []
    if record.official_page_url:
        detail_links.append(("Official scheme/programme page", record.official_page_url))
    if record.application_url:
        detail_links.append(("Application portal", record.application_url))
    detail_links.extend(
        (f"Guideline / manual {index}", url)
        for index, url in enumerate(record.guideline_urls or [], start=1)
    )
    detail_links.extend(
        (f"Official reference {index}", url)
        for index, url in enumerate(record.reference_urls or [], start=1)
    )
    if detail_links:
        st.markdown(
            '<div class="section-band"><h2 class="section-title">All Official Resources</h2>'
            '<div class="resource-actions">'
            + "".join(
                f'<a target="_blank" rel="noopener" href="{html.escape(url, quote=True)}">{esc(label)}</a>'
                for label, url in detail_links
            )
            + '</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("No official resource links are recorded.")


def main() -> None:
    requested_slug = str(st.query_params.get("page", "") or "").strip().lower()
    requested_page = next(
        (page_name for page_name, slug in PAGE_SLUGS.items() if slug == requested_slug),
        None,
    )
    if "ssip_primary_navigation" not in st.session_state and requested_page:
        st.session_state["ssip_primary_navigation"] = requested_page

    dark_mode = st.session_state.get("ssip_dark_mode", False)
    if dark_mode:
        st.markdown('<span id="ssip-dark-mode" aria-hidden="true"></span>', unsafe_allow_html=True)

    st.markdown(
        '<a class="skip-link" href="#ssip-main-content">Skip to main content</a>',
        unsafe_allow_html=True,
    )
    st.markdown(site_header(), unsafe_allow_html=True)

    navigation_column, appearance_column = st.columns([8.6, 1.15])
    with navigation_column:
        page = st.radio(
            "Navigation",
            PAGE_NAMES,
            horizontal=True,
            label_visibility="collapsed",
            format_func=lambda value: NAV_LABELS[value],
            key="ssip_primary_navigation",
        )
    with appearance_column:
        st.toggle(
            "Dark mode",
            key="ssip_dark_mode",
            help="Switch between the light and dark dashboard appearance.",
        )

    active_slug = PAGE_SLUGS[page]
    if str(st.query_params.get("page", "") or "") != active_slug:
        st.query_params["page"] = active_slug

    st.markdown(
        '<div class="compact-trust-strip"><span>Official-source evidence</span>'
        '<span>Schemes and time-bound calls are maintained separately</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<span id="ssip-main-content" class="main-content-anchor" tabindex="-1"></span>',
        unsafe_allow_html=True,
    )
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
    elif page == "DST Schemes":
        render_dst_schemes()
    elif page == "Official Sources":
        render_official_sources(official_sources, bundle)
    elif page == "Calls & Opportunities":
        render_calls_and_opportunities()
    elif page == "Incubators & Ecosystem":
        render_startup_ecosystem()
    elif page == "Directory":
        render_resources(bundle, official_sources)
    elif page == "Scheme Details":
        render_scheme_details(bundle)

    st.caption("SSIP · Information sourced from official government portals.")


if __name__ == "__main__":
    main()


