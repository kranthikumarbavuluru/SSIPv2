from __future__ import annotations

import csv
import html
import logging
import re

from copy import copy
from dataclasses import is_dataclass, replace

from collections import Counter
from datetime import date
import sys
from pathlib import Path
from typing import Callable
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


from ssip_dashboard.meity_history import (
    MeitYHistoricalArchive,
    MeitYHistoricalRecord,
    load_meity_historical_archive,
)

from ssip_dashboard.meity_public_integrated_v3_4_3_8_1 import (
    is_public_record,
    public_safe_record,
    render_integrated_meity_public_page,
)
from ssip_dashboard.dpiit_preview import (
    DPIITPreviewBundle,
    DPIITPreviewRecord,
    filter_dpiit_preview,
    load_dpiit_preview,
)
from ssip_dashboard.dbt_birac_preview import (
    DBTBIRACPreviewBundle,
    DBTBIRACPreviewRecord,
    filter_dbt_birac_preview,
    load_dbt_birac_preview,
)
from ssip_dashboard.msme_public import (
    MSMEPublicBundle,
    build_msme_public_bundle,
    filter_msme_records,
)
from ssip_dashboard.dot_public import (
    DOTPublicBundle,
    build_dot_public_bundle,
    filter_dot_records,
)
from ssip_dashboard.idex_public import (
    IDEXPublicBundle,
    build_idex_public_bundle,
    filter_idex_records,
)
from ssip_dashboard.agri_startup_public import (
    AgriStartupPublicBundle,
    build_agri_startup_public_bundle,
    filter_agri_startup_records,
)
from ssip_dashboard.msde_public import (
    MSDEPublicBundle,
    build_msde_public_bundle,
    filter_msde_records,
)
from ssip_dashboard.moe_public import (
    MOEPublicBundle,
    build_moe_public_bundle,
    filter_moe_records,
)

APP_VERSION = "3.4.14.0-visual-foundation"
LOGGER = logging.getLogger(__name__)
PAGE_NAMES = [
    "Home",
    "Scheme Explorer",
    "Calls & Opportunities",
    "DST Schemes",
    "MeitY",
    "DPIIT",
    "DBT–BIRAC",
    "MSME",
    "DoT",
    "iDEX",
    "Agriculture",
    "MSDE",
    "MoE",
    "Incubators & Ecosystem",
    "Directory",
    "Official Sources",
    "Media Runs",
    "Scheme Details",
]
NAV_LABELS = {
    "Home": "Home",
    "Scheme Explorer": "Find Schemes",
    "Calls & Opportunities": "Live Calls",
    "DST Schemes": "DST",
    "MeitY": "MeitY",
    "DPIIT": "DPIIT",
    "DBT–BIRAC": "DBT–BIRAC",
    "MSME": "MSME",
    "DoT": "DoT",
    "iDEX": "iDEX",
    "Agriculture": "Agriculture",
    "MSDE": "MSDE",
    "MoE": "MoE",
    "Incubators & Ecosystem": "Ecosystem",
    "Directory": "Resources",
    "Official Sources": "Sources",
    "Media Runs": "Media runs",
    "Scheme Details": "Profiles",
}
PAGE_SLUGS = {
    "Home": "overview",
    "Scheme Explorer": "scheme-finder",
    "DST Schemes": "dst-programmes",
    "MeitY": "meity-programmes",
    "DPIIT": "dpiit-programmes",
    "DBT–BIRAC": "dbt-birac-programmes",
    "MSME": "msme-schemes",
    "DoT": "dot-programmes",
    "iDEX": "idex-programmes",
    "Agriculture": "agri-startups",
    "MSDE": "msde-programmes",
    "MoE": "moe-programmes",
    "Calls & Opportunities": "live-calls",
    "Incubators & Ecosystem": "ecosystem",
    "Official Sources": "official-sources",
    "Directory": "resources",
    "Media Runs": "media-runs",
    "Scheme Details": "scheme-profiles",
}

PAGE_SLUG_ALIASES = {"msme-programmes": "MSME"}


# Public organisation identity aliases.
#
# These aliases affect only the in-memory public view. The governed source
# catalogue remains untouched. Add new aliases here only after confirming that
# they represent the same legal/administrative organisation.
CANONICAL_ORGANISATION_BY_KEY = {
    "dst": "Department of Science and Technology (DST)",
    "department of science and technology": "Department of Science and Technology (DST)",
    "department science and technology": "Department of Science and Technology (DST)",
    "department of science technology": "Department of Science and Technology (DST)",
    "department of science ad technology": "Department of Science and Technology (DST)",
}


def organisation_identity_key(value: object) -> str:
    """Return a stable comparison key for department/agency aliases."""
    text = html.unescape(str(value or "")).strip().casefold()
    if not text:
        return ""

    # Remove a trailing/embedded abbreviation such as "(DST)" before comparing.
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def canonical_organisation_name(value: object) -> str:
    """Map a known alias to its governed public-facing organisation name."""
    original = str(value or "").strip()
    if not original:
        return ""
    return CANONICAL_ORGANISATION_BY_KEY.get(
        organisation_identity_key(original),
        original,
    )


def copy_with_updates(value: object, **updates: object) -> object:
    """Safely copy dataclass, Pydantic, namedtuple or mutable model objects."""
    if not updates:
        return value
    if is_dataclass(value):
        return replace(value, **updates)
    if hasattr(value, "model_copy"):
        return value.model_copy(update=updates)
    if hasattr(value, "_replace"):
        return value._replace(**updates)

    clone = copy(value)
    for field_name, field_value in updates.items():
        setattr(clone, field_name, field_value)
    return clone


def canonicalize_catalogue_organisations(bundle: CatalogueBundle) -> CatalogueBundle:
    """
    Consolidate known department/agency aliases before public calculations.

    This makes filters, department counts, analytics, cards and profiles use
    one canonical organisation identity while preserving the source files.
    """
    normalized_records: list[CatalogueRecord] = []

    for record in bundle.records:
        department_before = str(getattr(record, "department", "") or "").strip()
        agency_before = str(getattr(record, "implementing_agency", "") or "").strip()

        department_after = canonical_organisation_name(department_before)
        agency_after = canonical_organisation_name(agency_before)

        updates: dict[str, object] = {}
        if department_after != department_before:
            updates["department"] = department_after
        if agency_after != agency_before:
            updates["implementing_agency"] = agency_after

        normalized_records.append(
            copy_with_updates(record, **updates) if updates else record
        )

    return copy_with_updates(bundle, records=normalized_records)


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


def _msme_cache_token() -> str:
    manifests = (
        PROJECT_ROOT / "data/departments/msme/v3_4_6_0/active_publication_manifest_v3_4_6_0.json",
        PROJECT_ROOT / "data/departments/dot/v3_4_8_0/active_publication_manifest_v3_4_8_0.json",
        PROJECT_ROOT / "data/departments/idex/v3_4_9_0/active_publication_manifest_v3_4_9_0.json",
        PROJECT_ROOT / "data/departments/agri_startup/v3_4_10_0/active_publication_manifest_v3_4_10_0.json",
        PROJECT_ROOT / "data/departments/msde/v3_4_11_0/active_publication_manifest_v3_4_11_0.json",
        PROJECT_ROOT / "data/departments/moe/v3_4_12_0/active_publication_manifest_v3_4_12_0.json",
        PROJECT_ROOT / "data/media_publication/v3_4_7_3/active_publication_manifest_v3_4_7_3.json",
        PROJECT_ROOT / "data/media_publication/v3_4_7_0/active_publication_manifest_v3_4_7_0.json",
    )
    tokens: list[str] = []
    for manifest in manifests:
        try:
            tokens.append(str(manifest.stat().st_mtime_ns))
        except OSError:
            tokens.append("missing")
    return ":".join(tokens)


@st.cache_data(ttl=45, show_spinner=False)
def cached_catalogue(msme_cache_token: str = "") -> CatalogueBundle:
    del msme_cache_token
    loaded = load_catalogue(DashboardConfig.from_env(PROJECT_ROOT))
    return canonicalize_catalogue_organisations(loaded)


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
    "PROGRAMME_COMPONENT": "Programme component",
    "PROGRAM_COMPONENT": "Programme component",
    "SECTOR_AGNOSTIC_MULTI_SECTOR": "Multi-sector",
    "SECTOR_AGNOSTIC_/_MULTI_SECTOR": "Multi-sector",
    "CALL_FOR_APPLICATIONS": "Call for applications",
    "OPEN_FUNDING_CALL": "Open funding call",
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
    """Return a readable card summary that avoids cutting off mid-sentence."""
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned

    candidate = cleaned[:limit].rstrip()
    minimum = int(limit * 0.52)

    # Prefer a complete sentence when one is available within the card limit.
    sentence_end = max(candidate.rfind(mark) for mark in (".", "?", "!"))
    if sentence_end >= minimum:
        return candidate[: sentence_end + 1].strip()

    # Long official statements are often one sentence. A comma or semicolon can
    # still provide a complete, natural summary without a dangling fragment.
    clause_end = max(candidate.rfind(mark) for mark in (";", ",", ":"))
    if clause_end >= int(limit * 0.42):
        return candidate[:clause_end].rstrip(" ,;:") + "."

    # Final fallback: finish on a word boundary and make the continuation clear.
    word_end = candidate.rfind(" ")
    shortened = candidate[:word_end if word_end > 0 else limit].rstrip(" ,;:-")
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


def is_media_derived_record(record: CatalogueRecord) -> bool:
    """Identify records projected from the governed media publication bundle."""

    return (
        str(record.master_id or "").startswith("media_")
        or str(record.current_location or "").upper() == "MEDIA_ACTIVE_PUBLICATION"
        or str(record.source or "").casefold().startswith("media evidence")
    )


def public_status_text(record: CatalogueRecord) -> str:
    """Return a plain-language public status without exposing internal catalogue tokens."""
    bucket = status_bucket(record)
    labels = {
        "OPEN": "Open now",
        "CLOSING_SOON": "Closing soon",
        "UPCOMING": "Upcoming",
        "VERIFICATION_REQUIRED": "Check current status",
        "CLOSED": "Closed",
        "HISTORICAL": "Historical",
    }
    if bucket in labels:
        return labels[bucket]
    kind = str(record.record_kind or "").upper()
    if kind in {"APPLICATION_CALL", "CALL", "CHALLENGE"}:
        return "Call information"
    return "Scheme information"


def verified_scheme_details_action(
    record: CatalogueRecord,
) -> dict[str, str] | None:
    # Return the first governed Scheme Details action, if present.
    for action in getattr(record, "verified_public_actions", []) or []:
        if not isinstance(action, dict):
            continue
        if str(action.get("action_type", "")).upper() != "SCHEME_DETAILS":
            continue
        if str(action.get("link_role", "")).upper() != "SCHEME_MASTER":
            continue
        if str(action.get("verification_status", "")).upper() != (
            "VERIFIED_INFORMATION_PAGE"
        ):
            continue
        if action.get("is_active") is not True:
            continue
        if action.get("is_time_bound") is not False:
            continue
        resolved_url = str(action.get("resolved_url", "") or "").strip()
        if not resolved_url.startswith(("https://", "http://")):
            continue
        return {
            "label": "Scheme Details",
            "resolved_url": resolved_url,
        }
    return None


def public_record_card(
    record: CatalogueRecord,
    *,
    compact: bool = True,
    include_details_link: bool = True,
) -> str:
    """Render a public-first scheme/call card without exposing internal tokens."""
    if is_media_derived_record(record) and record.record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"}:
        include_details_link = False
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
    status = public_status_text(record)

    tag_values = [*record.sectors[:1], *record.scheme_types[:1]]
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
    governed_details = verified_scheme_details_action(record)
    if record.application_url:
        actions.append(
            f'<a class="public-action public-action-primary" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.application_url)}">Apply now</a>'
        )
    if include_details_link and record.master_id:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_top" '
            f'href="{html.escape(record_details_href(record), quote=True)}">View details</a>'
        )
    if governed_details:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{html.escape(governed_details["resolved_url"], quote=True)}">Scheme Details <span aria-hidden="true">&#8599;</span></a>'
        )
    elif record.official_page_url:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">&#8599;</span></a>'
        )
    if record.guideline_urls:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener noreferrer" '
            f'href="{esc(record.guideline_urls[0])}">Guideline <span aria-hidden="true">↗</span></a>'
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


def site_header(active_page: str) -> str:
    """Render a two-tier header: portal tools above, department destinations below."""
    primary_pages = [
        "Home",
        "Scheme Explorer",
        "Calls & Opportunities",
        "DST Schemes",
        "MeitY",
        "DPIIT",
        "DBT–BIRAC",
        "MSME",
        "DoT",
        "iDEX",
        "Agriculture",
        "MSDE",
        "MoE",
    ]
    core_pages = primary_pages[:3]
    department_pages = primary_pages[3:]
    links = []
    for page_name in core_pages:
        active = " is-active" if active_page == page_name else ""
        links.append(
            f'<a class="ssip-nav-link{active}" target="_top" href="?page={PAGE_SLUGS[page_name]}">'
            f'{esc(NAV_LABELS[page_name])}</a>'
        )
    more_active = active_page in {"Directory", "Official Sources", "Media Runs", "Incubators & Ecosystem", "Scheme Details"}
    more_class = " is-active" if more_active else ""
    more_links = (
        f'<a target="_top" href="?page={PAGE_SLUGS["Directory"]}">Resources</a>'
        f'<a target="_top" href="?page={PAGE_SLUGS["Official Sources"]}">Sources</a>'
        f'<a target="_top" href="?page={PAGE_SLUGS["Incubators & Ecosystem"]}">Ecosystem</a>'
        f'<a target="_top" href="?page={PAGE_SLUGS["Media Runs"]}">Media runs</a>'
        f'<a target="_top" href="?page={PAGE_SLUGS["Scheme Details"]}">Scheme profiles</a>'
    )
    department_links = []
    department_classes = {
        "DST Schemes": "dst",
        "MeitY": "meity",
        "DPIIT": "dpiit",
        "DBTâ€“BIRAC": "dbt-birac",
        "MSME": "msme",
        "DoT": "dot",
        "iDEX": "idex",
        "Agriculture": "agri",
        "MSDE": "msde",
        "MoE": "moe",
    }
    for page_name in department_pages:
        active = " is-active" if active_page == page_name else ""
        department_class = department_classes.get(page_name, "department")
        department_links.append(
            f'<a class="ssip-nav-link ssip-nav-department ssip-nav-department-{department_class}{active}" '
            f'target="_top" href="?page={PAGE_SLUGS[page_name]}">'
            f'{esc(NAV_LABELS[page_name])}</a>'
        )
    return (
        '<header class="ssip-site-header">'
        '<div class="ssip-header-main">'
        '<a class="ssip-brand-lockup" target="_top" href="?page=overview" aria-label="SSIP home">'
        '<span class="ssip-brand-mark">SSIP</span>'
        '<span class="ssip-brand-copy"><strong>SSIP</strong>'
        '<small>Startup Scheme Intelligence Platform</small></span></a>'
        '<div class="ssip-header-nav-stack">'
        f'<nav class="ssip-primary-nav ssip-primary-nav-core" aria-label="Portal navigation">{" ".join(links)}'
        f'<details class="ssip-nav-more{more_class}"><summary>More</summary>'
        f'<div class="ssip-nav-more-menu">{more_links}</div></details></nav>'
        f'<nav class="ssip-primary-nav ssip-primary-nav-departments" aria-label="Department navigation">{" ".join(department_links)}</nav>'
        '</div>'
        '<div class="ssip-header-trust"><i></i><span>Official-source catalogue</span></div>'
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
    if "focus" in st.query_params:
        del st.query_params["focus"]
    st.query_params["page"] = PAGE_SLUGS[page_name]


def public_department_verification_dates() -> tuple[str, ...]:
    """Return governed record dates from public packages outside the main catalogue."""
    dates: list[str] = []
    for loader in (cached_dpiit_preview, cached_dbt_birac_preview):
        try:
            package = loader()
        except (OSError, ValueError) as exc:
            LOGGER.warning("Public department package unavailable for Home verification: %s", exc)
            continue
        dates.extend(record.last_verified_date for record in package.records)
    return tuple(dates)


def render_home(bundle: CatalogueBundle, official_sources: list[OfficialSource]) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = populations.main_scheme_records
    calls = populations.application_call_records
    metrics = compute_metrics(bundle.records)
    source_stats = source_summary(official_sources)
    lookup = source_scope_lookup(official_sources)
    analytics = build_public_analytics(
        bundle.records,
        government_lookup=lookup,
        additional_verification_dates=public_department_verification_dates(),
    )
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
        st.markdown(
            '<a class="home-advanced-search-link" target="_top" '
            'href="?page=scheme-finder&amp;focus=filters#scheme-filters">'
            'Advanced search</a>',
            unsafe_allow_html=True,
        )

    if keyword:
        needle = keyword.casefold()
        featured = [record for record in records if needle in record.search_blob.casefold()]
        match_count = len(featured)
        featured = sort_records(featured, "Recently Updated")[:3]
        section_title = f"Matching schemes ({match_count})"
        section_note = "Results are drawn from governed scheme and programme identities."
    else:
        featured = latest_records(records, limit=3)
        section_title = "Recently verified schemes"
        section_note = "A quick starting point from the latest governed catalogue signals."

    st.markdown(
        f'<div class="home-section-heading"><div><span class="page-eyebrow">Explore support</span>'
        f'<h2>{esc(section_title)}</h2><p>{esc(section_note)}</p></div>'
        f'<a class="home-section-action" target="_top" href="?page={PAGE_SLUGS["Scheme Explorer"]}">View all schemes →</a></div>',
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
    )
    media_calls = [item for item in current_calls if is_media_derived_record(item)]
    other_calls = [item for item in current_calls if not is_media_derived_record(item)]
    current_calls = (media_calls + other_calls)[:6]
    st.markdown(
        '<div class="home-section-heading home-section-heading-spaced"><div>'
        '<span class="page-eyebrow">Time-bound opportunities</span>'
        '<h2>Open and upcoming calls</h2>'
        '<p>Calls, cohorts and challenges remain separate from their permanent parent schemes. Media-derived calls are included when currently actionable.</p>'
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
        f'<a class="public-action public-action-secondary" target="_top" href="?page={PAGE_SLUGS["Official Sources"]}">Browse official sources</a>'
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
        departments = c2.multiselect(
            "Department",
            unique_options(records, "department"),
            key="explorer_department_filter_v2",
        )
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
        page_intro(
            "Scheme finder",
            "Find the right government support",
            "Search schemes and programmes by agency, sector, eligibility, benefit, startup stage or support type.",
            badge=f"{len(records)} schemes",
        ),
        unsafe_allow_html=True,
    )
    keyword = st.text_input(
        "Search schemes and programmes",
        placeholder="Search by scheme, department, sector, eligibility or support type…",
        key="explorer_search",
        label_visibility="collapsed",
    )
    focus_filters = str(st.query_params.get("focus", "") or "").strip().casefold() == "filters"
    st.markdown(
        '<span id="scheme-filters" class="scheme-filter-anchor" '
        'aria-hidden="true"></span>',
        unsafe_allow_html=True,
    )
    with st.container(key="explorer_filters_panel"):
        with st.expander("Filters", expanded=focus_filters):
            state = render_filters(records, keyword=keyword)

    toolbar_left, toolbar_sort, toolbar_show = st.columns([4.2, 1.3, 1.05])
    sort_by = toolbar_sort.selectbox(
        "Sort by",
        ["Recently Updated", "Scheme Name", "Status", "Department"],
        key="explorer_sort",
    )
    display_limit = toolbar_show.selectbox(
        "Show",
        [24, 48, 0],
        format_func=lambda value: "All" if value == 0 else str(value),
        key="explorer_display_limit",
    )

    filtered = apply_filters(records, state)
    if sort_by == "Scheme Name":
        filtered = sorted(filtered, key=lambda record: record.scheme_name.casefold())
    elif sort_by == "Status":
        filtered = sorted(filtered, key=lambda record: (status_bucket(record), record.scheme_name.casefold()))
    elif sort_by == "Department":
        filtered = sorted(filtered, key=lambda record: ((record.department or "").casefold(), record.scheme_name.casefold()))
    else:
        filtered = sorted(filtered, key=lambda record: record.last_updated, reverse=True)

    displayed = filtered if display_limit == 0 else filtered[:display_limit]
    with toolbar_left:
        st.markdown(
            f'<div class="explorer-result-count"><strong>{len(filtered)}</strong>'
            f'<span>scheme and programme result(s)</span><small>Showing {len(displayed)}</small></div>',
            unsafe_allow_html=True,
        )

    filter_tokens: list[str] = []
    if keyword.strip():
        filter_tokens.append(f'Search: {keyword.strip()}')
    for values in (state.ministries, state.departments, state.agencies, state.sectors, state.statuses, state.applicant_types, state.startup_stages, state.scheme_types):
        filter_tokens.extend(str(value) for value in values[:3])
    if filter_tokens:
        st.markdown(
            '<div class="active-filter-chips"><span>Active filters</span>'
            + ''.join(f'<b>{esc(public_label(value))}</b>' for value in filter_tokens[:8])
            + '</div>',
            unsafe_allow_html=True,
        )

    result_cards = []
    for record in displayed:
        warnings = []
        if record.current_decision == "REJECTED":
            warnings.append("This record is retained only for historical or revalidation context.")
        if status_bucket(record) == "VERIFICATION_REQUIRED":
            warnings.append("Confirm the current status on the official source before acting.")
        result_cards.append(
            '<div class="scheme-result-item">'
            + public_record_card(record, compact=False)
            + warning_box("Evidence note", warnings)
            + "</div>"
        )
    if result_cards:
        st.markdown('<div class="scheme-results-grid">' + "".join(result_cards) + "</div>", unsafe_allow_html=True)
    else:
        st.info("No schemes match the selected filters. Try removing one or more filters.")


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
    msme_bundle = build_msme_public_bundle(bundle.records)
    dot_bundle = build_dot_public_bundle(bundle.records)
    idex_bundle = build_idex_public_bundle(bundle.records)
    agri_bundle = build_agri_startup_public_bundle(bundle.records)
    moe_bundle = build_moe_public_bundle(bundle.records)
    department_documents = [
        {**document, "department_label": "Department of Biotechnology / BIRAC"}
        for document in cached_dbt_birac_preview().documents
    ]
    department_documents.extend(
        {**document, "department_label": "Department for Promotion of Industry and Internal Trade (DPIIT)"}
        for document in cached_dpiit_preview().documents
    )
    department_documents.extend(
        {
            "title": document.scheme_name,
            "document_type": document.record_kind or "DOCUMENT",
            "official_url": document.official_page_url,
            "department_label": "Ministry of Micro, Small and Medium Enterprises",
        }
        for document in msme_bundle.documents
    )
    department_documents.extend(
        {**document, "department_label": "Department of Telecommunications (DoT)"}
        for document in dot_bundle.documents
    )
    department_documents.extend(
        {**document, "department_label": "Department of Defence Production / iDEX"}
        for document in idex_bundle.documents
    )
    department_documents.extend(
        {**document, "department_label": "Agriculture & Farmers Welfare startup ecosystem"}
        for document in agri_bundle.documents
    )
    department_documents.extend(
        {**document, "department_label": "Ministry of Education / AICTE"}
        for document in moe_bundle.documents
    )
    msme_document_ids = {document.master_id for document in msme_bundle.documents}
    dot_document_ids = {record.master_id for record in (*dot_bundle.permanent_records, *dot_bundle.current_calls, *dot_bundle.historical_records)}
    idex_document_ids = {record.master_id for record in (*idex_bundle.permanent_records, *idex_bundle.current_calls, *idex_bundle.historical_records)}
    agri_document_ids = {record.master_id for record in (*agri_bundle.permanent_records, *agri_bundle.current_calls, *agri_bundle.historical_records)}
    moe_document_ids = {record.master_id for record in (*moe_bundle.permanent_records, *moe_bundle.current_calls, *moe_bundle.historical_records)}
    resource_records = [
        item for item in records
        if item.master_id not in msme_document_ids
        and item.master_id not in dot_document_ids
        and item.master_id not in idex_document_ids
        and item.master_id not in agri_document_ids
        and item.master_id not in moe_document_ids
        and (item.official_page_url or item.application_url or item.guideline_urls or item.reference_urls)
    ]
    resource_total = len(resource_records) + len(department_documents)
    st.markdown(
        page_intro(
            "Application resources",
            "Official Links & Documents",
            "Open verified scheme pages, application portals, manuals and reference documents without searching across multiple government websites.",
            badge=f"{resource_total} records",
        ),
        unsafe_allow_html=True,
    )
    application_count = sum(bool(item.application_url) for item in resource_records)
    document_count = sum(bool(item.guideline_urls) for item in resource_records) + len(department_documents)
    st.markdown(
        '<div class="metric-grid resource-metrics">'
        + metric_card("Resource Records", resource_total, "Schemes, calls and official documents", "blue")
        + metric_card("Application Portals", application_count, "Direct official application routes", "green")
        + metric_card("Manuals & Documents", document_count, "Structured official resources", "orange")
        + metric_card("Source Registry", len(official_sources), "Discovery portals maintained", "purple")
        + '</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns([2, 1, 1, .75])
    keyword = c1.text_input("Search resources", placeholder="Scheme, call, department or document", key="resource_keyword").strip().casefold()
    population = c2.selectbox("Record population", ["ALL", "SCHEME", "CALL", "DOCUMENT"], format_func=lambda value: {"ALL":"All records","SCHEME":"Schemes & programmes","CALL":"Application calls","DOCUMENT":"Documents"}[value])
    resource_type = c3.selectbox("Resource type", ["ALL", "APPLICATION", "GUIDELINE", "OFFICIAL"], format_func=lambda value: {"ALL":"All resources","APPLICATION":"Application portals","GUIDELINE":"Manuals & documents","OFFICIAL":"Official pages"}[value])
    display_limit = c4.selectbox("Show", [24, 48, 0], format_func=lambda value: "All" if value == 0 else str(value), key="resource_display_limit")
    visible = []
    for item in resource_records:
        is_call = item.record_kind.upper() in {"APPLICATION_CALL", "CHALLENGE"}
        if population == "DOCUMENT":
            continue
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
    visible_documents = []
    if population in {"ALL", "DOCUMENT"} and resource_type in {"ALL", "GUIDELINE", "OFFICIAL"}:
        for document in department_documents:
            searchable = " ".join((
                document.get("title", ""),
                document.get("document_type", ""),
                document.get("department_label", ""),
            )).casefold()
            if keyword and keyword not in searchable:
                continue
            visible_documents.append(document)
    cards = []
    for item in visible:
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
    for document in visible_documents:
        cards.append(
            '<article class="resource-card">'
            '<div class="scheme-card-head">'
            f'<span class="record-kind">{esc(display_token(document.get("document_type", "DOCUMENT")))}</span>'
            '<span class="status-badge status-reference">Official source</span></div>'
            f'<h3>{esc(document.get("title", "DBT–BIRAC document"))}</h3>'
            f'<div class="agency-line">{esc(document.get("department_label", "Government department"))}</div>'
            '<div class="resource-actions">'
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(document.get("official_url", ""))}">Open document</a>'
            '</div></article>'
        )
    displayed_cards = cards if display_limit == 0 else cards[:display_limit]
    visible_total = len(visible) + len(visible_documents)
    st.markdown(f'<div class="filter-summary"><strong>{visible_total}</strong> resource record(s)<span>Showing {len(displayed_cards)} · official links open in a new tab</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="resource-grid">' + "".join(displayed_cards) + '</div>', unsafe_allow_html=True)
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




def render_media_runs_page(bundle: CatalogueBundle) -> None:
    """Expose governed media-derived records from the More menu."""

    media_records = sorted(
        [record for record in bundle.records if is_media_derived_record(record)],
        key=lambda record: (record.scheme_name.casefold(), record.master_id),
    )
    st.markdown(
        page_intro(
            "Media intake",
            "Media-derived schemes, programmes & calls",
            "Records extracted from dated media runs are shown here after the governed publication gate. Source assets and official links remain available for verification.",
            badge=f"{len(media_records)} records",
        ),
        unsafe_allow_html=True,
    )
    if not media_records:
        st.info("No governed media-run records are currently published.")
        return
    current_count = sum(status_bucket(record) in {"OPEN", "CLOSING_SOON", "UPCOMING"} for record in media_records)
    st.markdown(
        '<div class="metric-grid resource-metrics">'
        + metric_card("Media records", len(media_records), "Published from reviewed media runs", "blue")
        + metric_card("Current calls", current_count, "Open, closing soon or upcoming", "green")
        + metric_card("Departments mapped", len({record.department for record in media_records if record.department}), "Explicit department mappings", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="scheme-results-grid">'
        + "".join(public_record_card(record, compact=False, include_details_link=False) for record in media_records)
        + '</div>',
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
                'DST scheme(s) and programme(s)'
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
    status_options = ["OPEN", "UPCOMING", "CLOSED", "VERIFICATION_REQUIRED", "STATUS_UNVERIFIED", "ALL"]
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


def _calls_for_separate_verification_page(
    bundle: CatalogueBundle,
) -> list[CatalogueRecord]:
    """Return curated calls without changing the Home catalogue projection."""
    calls = split_catalogue_populations(
        bundle.records
    ).application_call_records
    return [
        public_safe_record(item)
        if is_public_record(item)
        else replace(item, application_url="")
        for item in calls
    ]


def _published_call_card(
    item: CatalogueRecord,
    *,
    parent_names: dict[str, str],
    ecosystem: bool = False,
) -> str:
    """Render a governed published call using the standard scheme card."""
    parent = (
        item.parent_scheme_name
        or parent_names.get(
            item.parent_master_id,
            "",
        )
        or "Parent scheme requires curation"
    )

    card_html = scheme_card(
        item,
        compact=False,
    )

    if (
        not isinstance(card_html, str)
        or not card_html.strip()
    ):
        identifier = (
            item.master_id
            or item.scheme_name
            or "unknown call"
        )

        raise TypeError(
            "scheme_card returned no HTML for "
            + str(identifier)
        )

    audience = (
        "Institutional or ecosystem opportunity"
        if ecosystem
        else "Startup application opportunity"
    )

    call_context = (
        '<div class="agency-line">'
        '<b>Parent programme:</b> '
        + esc(parent)
        + " - "
        + esc(audience)
        + "</div>"
    )

    closing_tag = "</article>"

    if closing_tag in card_html:
        return card_html.replace(
            closing_tag,
            call_context + closing_tag,
            1,
        )

    return card_html + call_context



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
    bundle = cached_catalogue(_msme_cache_token())
    all_calls = _calls_for_separate_verification_page(bundle)
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
                "Curated open, upcoming and closed startup calls are shown "
                "here across departments for independent verification. "
                "Unpublished records remain non-actionable. Detailed historical "
                "archives are maintained in the DST and MeitY pages."
            ),
            badge=f"{len(calls)} curated startup-scope calls",
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
            "No curated direct or applicant-layer-unverified "
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


def render_startup_ecosystem() -> None:
    bundle = cached_catalogue(_msme_cache_token())
    calls = [item for item in _published_calls(bundle) if item.applicant_layer.upper() == "INTERMEDIARY_IMPLEMENTER"]
    parent_names = {item.master_id: item.scheme_name for item in bundle.records}
    st.markdown(page_intro("Institutional opportunities", "Published Incubator & Ecosystem Calls", "Published calls for TBIs, incubators, programme centres and implementation partners. These are never shown as direct founder applications.", badge=f"{len(calls)} intermediary calls"), unsafe_allow_html=True)
    if not calls:
        st.info("No published intermediary calls are available.")
        return
    visible = _render_published_call_filters(calls, key_prefix="published_ecosystem", parent_names=parent_names)
    st.markdown(f"**{len(visible)} matching published intermediary call(s)**")
    raw_ecosystem_call_cards = [
        _published_call_card(
            item,
            parent_names=parent_names,
            ecosystem=True,
        )
        for item in visible
    ]

    valid_ecosystem_call_cards = [
        card
        for card in raw_ecosystem_call_cards
        if isinstance(card, str)
        and card.strip()
    ]

    st.markdown(
        '<div class="call-grid">'
        + "".join(valid_ecosystem_call_cards)
        + "</div>",
        unsafe_allow_html=True,
    )

    if len(valid_ecosystem_call_cards) != len(
        raw_ecosystem_call_cards
    ):
        st.warning(
            "One or more published call records could not "
            "be displayed because the card renderer returned "
            "no HTML. The underlying records remain available."
        )


def _detail_panel(title: str, items: list[str], *, empty_message: str = "Not yet available in structured catalogue data.") -> str:
    if items:
        body = ''.join(f'<li>{esc(item)}</li>' for item in items)
        content = f'<ul>{body}</ul>'
    else:
        content = f'<p class="profile-empty">{esc(empty_message)}</p>'
    return f'<section class="profile-detail-panel"><h2>{esc(title)}</h2>{content}</section>'


def render_scheme_details(bundle: CatalogueBundle) -> None:
    populations = split_catalogue_populations(bundle.records)
    records = sorted(
        populations.main_scheme_records,
        key=lambda record: (
            0 if record.publication_status.upper() == "PUBLISHED" else 1,
            1 if status_bucket(record) == "VERIFICATION_REQUIRED" else 0,
            record.scheme_name.casefold(),
        ),
    )
    if not records:
        st.info("No eligible scheme or programme records are available.")
        return

    records_by_id = {record.master_id: record for record in records}
    record_labels = {
        item.master_id: f'{item.scheme_name} — {item.department or item.implementing_agency or item.source or "Agency not recorded"}'
        for item in records
    }
    record_ids = [record.master_id for record in records]
    requested_scheme = str(st.query_params.get("scheme", "") or "").strip()
    selected_index = record_ids.index(requested_scheme) if requested_scheme in record_ids else 0

    st.markdown(
        '<nav class="profile-breadcrumb" aria-label="Breadcrumb">'
        f'<a target="_top" href="?page={PAGE_SLUGS["Scheme Explorer"]}">Find schemes</a><span>/</span><b>Scheme profile</b></nav>',
        unsafe_allow_html=True,
    )
    with st.expander("Choose another scheme or programme", expanded=not bool(requested_scheme)):
        selected_id = st.selectbox(
            "Scheme or programme",
            options=record_ids,
            index=selected_index,
            format_func=lambda item_id: record_labels[item_id],
            key="scheme_profile_selector",
            label_visibility="collapsed",
        )
    if str(st.query_params.get("scheme", "") or "") != selected_id:
        st.query_params["scheme"] = selected_id
    record = records_by_id[selected_id]

    agency = record.department or record.implementing_agency or record.source or "Government department / agency"
    summary = concise_text(" ".join((record.objectives or record.benefits or ["Official scheme information is available."])[:1]), limit=330)
    actions: list[str] = []
    governed_details = verified_scheme_details_action(record)
    if record.application_url:
        actions.append(
            f'<a class="public-action public-action-primary" target="_blank" rel="noopener" '
            f'href="{esc(record.application_url)}">Apply now</a>'
        )
    if governed_details:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_blank" rel="noopener" '
            f'href="{html.escape(governed_details["resolved_url"], quote=True)}">Scheme Details &#8599;</a>'
        )
    elif record.official_page_url:
        actions.append(
            f'<a class="public-action public-action-secondary" target="_blank" rel="noopener" '
            f'href="{esc(record.official_page_url)}">Official page &#8599;</a>'
        )
    if record.guideline_urls:
        actions.append(
            f'<a class="public-action public-action-quiet" target="_blank" rel="noopener" '
            f'href="{esc(record.guideline_urls[0])}">Guideline &#8599;</a>'
        )

    verified_on = optional_text(record.last_updated[:10] if record.last_updated else "") or "Date not recorded"
    st.markdown(
        '<section class="scheme-profile-hero">'
        '<div class="scheme-profile-copy">'
        f'<div class="public-record-card-top"><span class="status-badge {status_css_class(record)}">{esc(public_status_text(record))}</span>'
        f'<span class="public-kind">{esc(public_record_kind(record))}</span></div>'
        f'<h1>{esc(record.scheme_name)}</h1><p class="scheme-profile-agency">{esc(agency)}</p>'
        f'<p class="scheme-profile-summary">{esc(summary)}</p>'
        f'<div class="scheme-profile-actions">{"".join(actions)}</div></div>'
        '<aside class="scheme-profile-trust">'
        '<span>Catalogue verification</span>'
        f'<strong>{esc(verified_on)}</strong>'
        '<small>Confirm current terms on the linked official source.</small>'
        '</aside></section>',
        unsafe_allow_html=True,
    )

    funding_text = "Not structured"
    if record.funding_maximum not in (None, "", 0, 0.0):
        funding_text = f'Up to {format_inr(record.funding_maximum)}'
    elif record.funding_minimum not in (None, "", 0, 0.0):
        funding_text = f'From {format_inr(record.funding_minimum)}'
    meta_items = [
        ("Ministry", record.ministry or "Not recorded"),
        ("Department / agency", agency),
        ("Support", funding_text),
        ("Record type", public_record_kind(record)),
    ]
    st.markdown(
        '<div class="profile-meta-grid">'
        + ''.join(f'<div><span>{esc(label)}</span><strong>{esc(value)}</strong></div>' for label, value in meta_items)
        + '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="profile-detail-grid profile-detail-grid-two">'
        + _detail_panel("Overview", record.objectives)
        + _detail_panel("Benefits", record.benefits)
        + '</div>'
        + '<div class="profile-detail-grid">'
        + _detail_panel("Eligibility", record.eligibility)
        + '</div>'
        + '<div class="profile-detail-grid profile-detail-grid-two">'
        + _detail_panel("How to apply", record.application_process, empty_message="Use the official page for current application instructions.")
        + _detail_panel("Required documents", record.required_documents)
        + '</div>',
        unsafe_allow_html=True,
    )

    profile_tags = [*record.target_beneficiaries[:3], *record.startup_stage[:3], *record.sectors[:3], *record.scheme_types[:2]]
    if profile_tags:
        st.markdown(
            '<section class="profile-tag-panel"><h2>Who and what it supports</h2><div class="public-chip-row">'
            + ''.join(f'<span class="public-chip">{esc(public_label(value))}</span>' for value in profile_tags if optional_text(value))
            + '</div></section>',
            unsafe_allow_html=True,
        )

    related_calls = []
    scheme_name_key = record.scheme_name.casefold().strip()
    for call in populations.application_call_records:
        parent_id = str(getattr(call, "parent_master_id", "") or "").strip()
        parent_name = str(getattr(call, "parent_scheme_name", "") or getattr(call, "parent_name", "") or "").casefold().strip()
        if parent_id == record.master_id or (parent_name and parent_name == scheme_name_key):
            related_calls.append(call)
    if related_calls:
        related_calls = sorted(related_calls, key=lambda item: parse_date(item.closing_date) or date.max)[:4]
        st.markdown(
            '<div class="profile-section-heading"><span class="page-eyebrow">Application opportunities</span>'
            '<h2>Current and related calls</h2><p>Time-bound calls remain separate from this permanent scheme identity.</p></div>'
            '<div class="scheme-results-grid home-call-grid">'
            + ''.join(public_record_card(item, compact=True) for item in related_calls)
            + '</div>',
            unsafe_allow_html=True,
        )

    detail_links: list[tuple[str, str]] = []
    governed_details = verified_scheme_details_action(record)
    governed_url = (
        governed_details["resolved_url"]
        if governed_details
        else ""
    )
    if governed_url:
        detail_links.append(("Scheme Details", governed_url))
    if record.official_page_url and (
        record.official_page_url.casefold().rstrip("/")
        != governed_url.casefold().rstrip("/")
    ):
        detail_links.append(
            ("Official scheme page", record.official_page_url)
        )
    if record.application_url:
        detail_links.append(
            ("Application portal", record.application_url)
        )
    detail_links.extend(
        (f"Guideline or manual {index}", url)
        for index, url in enumerate(
            record.guideline_urls or [],
            start=1,
        )
    )
    detail_links.extend(
        (f"Official reference {index}", url)
        for index, url in enumerate(
            record.reference_urls or [],
            start=1,
        )
    )

    deduped_detail_links: list[tuple[str, str]] = []
    seen_detail_urls: set[str] = set()
    for label, url in detail_links:
        normalized_url = str(url or "").strip().casefold().rstrip("/")
        if not normalized_url or normalized_url in seen_detail_urls:
            continue
        seen_detail_urls.add(normalized_url)
        deduped_detail_links.append((label, url))
    detail_links = deduped_detail_links
    if detail_links:
        st.markdown(
            '<section class="profile-resource-panel"><div><span class="page-eyebrow">Official evidence</span>'
            '<h2>Official links and documents</h2><p>Open the authoritative source before making an application decision.</p></div>'
            '<div class="resource-actions">'
            + ''.join(f'<a target="_blank" rel="noopener" href="{html.escape(url, quote=True)}">{esc(label)} ↗</a>' for label, url in detail_links)
            + '</div></section>',
            unsafe_allow_html=True,
        )




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


def _historical_year_label(value: object) -> str:
    match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
    return match.group(0) if match else "Date not recorded"


def _department_history_chart(
    records: list[object] | tuple[object, ...],
    *,
    date_getter: Callable[[object], object],
    legend_label: str,
) -> str:
    """Render an accessible year-count chart from explicitly evidenced dates."""
    counts = Counter(
        _historical_year_label(date_getter(record))
        for record in records
    )
    if not counts:
        return '<div class="empty-note">No historical date data is available.</div>'

    def sort_key(value: str) -> tuple[int, int | str]:
        if value == "Date not recorded":
            return (1, value)
        return (0, int(value))

    ordered = sorted(counts, key=sort_key)
    maximum = max(counts.values()) or 1
    rows = []
    for label in ordered:
        count = counts[label]
        width = (count / maximum) * 100
        rows.append(
            '<div class="history-row">'
            f'<strong>{esc(label)}</strong>'
            '<div class="history-track">'
            '<span class="history-segment history-startup-relevant" '
            f'style="width:{width:.3f}%" title="{esc(label)}: {count}"></span>'
            '</div>'
            f'<b>{count}</b></div>'
        )
    return (
        '<div class="history-chart" role="img" '
        f'aria-label="{esc(legend_label)} by evidenced year">'
        '<div class="history-legend">'
        '<span><i class="history-segment history-startup-relevant"></i>'
        f'{esc(legend_label)}</span>'
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
        f'<span>{len(records)} official-source call identities are published '
        'as historical references. Optional metadata may be shown as not specified. '
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
    return render_integrated_meity_public_page(
        st=st,
        bundle=bundle,
        historical_archive=cached_meity_historical_archive(),
        page_intro=page_intro,
        metric_card=metric_card,
        public_record_card=public_record_card,
        published_call_filters=_render_published_call_filters,
        published_call_card=_published_call_card,
        render_historical_archive=render_meity_historical_archive,
    )

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


@st.cache_data(ttl=300, show_spinner=False)
def cached_dpiit_preview() -> DPIITPreviewBundle:
    return load_dpiit_preview(PROJECT_ROOT)


def _dpiit_preview_card(record: DPIITPreviewRecord, parent_names: dict[str, str]) -> str:
    parent = parent_names.get(record.parent_record_id, "")
    facts = []
    if parent:
        facts.append(f'<div><span>Parent programme</span><strong>{esc(parent)}</strong></div>')
    facts.extend((
        f'<div><span>Direct applicant</span><strong>{esc(display_token(record.direct_applicant_layer))}</strong></div>',
        f'<div><span>Application status</span><strong>{esc(display_token(record.application_status))}</strong></div>',
        f'<div><span>Closing date</span><strong>{esc(record.closing_date or "Not specified")}</strong></div>',
    ))
    links = []
    if record.official_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_url)}">Official evidence ↗</a>'
        )
    if record.guideline_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.guideline_url)}">Guidelines ↗</a>'
        )
    note = (
        '<div class="public-record-note">Historical reference · Application window closed · No Apply action</div>'
        if record.application_status == "CLOSED"
        else '<div class="public-record-note">Official-source department record · Apply is shown only for a verified open call</div>'
    )
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge">{esc(display_token(record.application_status))}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_type))}</span></div>'
        f'<h3>{esc(record.canonical_name)}</h3>'
        '<div class="public-record-agency">Department for Promotion of Industry and Internal Trade (DPIIT)</div>'
        f'<p>{esc(record.summary or "Details are preserved in the governed official evidence record.")}</p>'
        f'<div class="public-record-facts">{"".join(facts)}</div>'
        f'<div class="public-chip-row"><span>{esc(record.sector)}</span><span>{esc(record.startup_relevance)}</span></div>'
        f'{note}<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_dpiit_page() -> None:
    bundle = cached_dpiit_preview()
    permanent = [
        row for row in bundle.records
        if row.application_status == "NOT_APPLICABLE_TO_PROGRAMME_IDENTITY"
    ]
    current = [row for row in bundle.records if row.application_status in {"OPEN", "UPCOMING"}]
    historical = [row for row in bundle.records if row.application_status == "CLOSED"]
    st.markdown(
        page_intro(
            "DPIIT intelligence",
            "DPIIT Schemes, Services & Calls",
            "Permanent DPIIT schemes, services and programmes, verified current opportunities and the governed historical archive are maintained as separate views.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed DPIIT schemes, services and programmes", "blue")
        + metric_card("Open calls", sum(row.application_status == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical calls", len(historical), "Qualified official DPIIT references", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f'Last verified: {bundle.manifest.get("generated_at", "")[:10]} · '
        'Published on this department page from governed official-source records.'
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>Verified DPIIT ownership</strong>'
        '<span>Permanent schemes, government services and ecosystem platforms retain their explicit record type. '
        'Dated calls and challenges remain separate identities, while unresolved review work stays in the internal workflow.</span></div>',
        unsafe_allow_html=True,
    )

    keyword_column, type_column, status_column, applicant_column = st.columns([2.2, 1.3, 1.3, 1.5])
    with keyword_column:
        keyword = st.text_input("Search DPIIT schemes", placeholder="Recognition, Seed Fund, MAARG, challenge…")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_type for row in bundle.records})])
    with status_column:
        status = st.selectbox("Status", ["All", *sorted({row.application_status for row in bundle.records})])
    with applicant_column:
        applicant_options = sorted({item for row in bundle.records for item in row.direct_applicant_layer.split(";") if item})
        applicant = st.selectbox("Direct applicant", ["All", *applicant_options])

    visible = filter_dpiit_preview(
        bundle.records, keyword=keyword, record_type=record_type,
        status=status, applicant_layer=applicant,
    )
    parent_names = {row.record_id: row.canonical_name for row in bundle.records}
    groups = (
        (
            "Schemes & Programmes",
            {"SCHEME", "PROGRAMME", "GOVERNMENT_SERVICE", "ECOSYSTEM_OPPORTUNITY"},
            None,
        ),
        (
            "Current Calls & Challenges",
            {"APPLICATION_CALL", "FUNDING_ROUND", "COHORT", "CHALLENGE", "COMPETITION", "HISTORICAL_CALL"},
            {"OPEN", "UPCOMING"},
        ),
        (
            "Historical Archive",
            {"APPLICATION_CALL", "FUNDING_ROUND", "COHORT", "CHALLENGE", "COMPETITION", "HISTORICAL_CALL"},
            {"CLOSED"},
        ),
    )
    tabs = st.tabs([label for label, _, _ in groups])
    for tab, (label, types, allowed_statuses) in zip(tabs, groups):
        with tab:
            records = [
                row for row in visible
                if row.record_type in types
                and (allowed_statuses is None or row.application_status in allowed_statuses)
            ]
            if label == "Historical Archive" and records:
                st.markdown(
                    '<div class="section-band">'
                    '<h2 class="section-title">DPIIT Historical Calls by Closing Year</h2>'
                    + _department_history_chart(
                        records,
                        date_getter=lambda item: item.closing_date,
                        legend_label="Qualified DPIIT historical calls",
                    )
                    + '</div>',
                    unsafe_allow_html=True,
                )
            if not records:
                st.info(f"No {label.lower()} match the selected filters.")
            else:
                st.markdown(
                    '<div class="public-record-grid">'
                    + "".join(_dpiit_preview_card(row, parent_names) for row in records)
                    + "</div>",
                    unsafe_allow_html=True,
                )


@st.cache_data(ttl=300, show_spinner=False)
def cached_dbt_birac_preview() -> DBTBIRACPreviewBundle:
    return load_dbt_birac_preview(PROJECT_ROOT)


def _dbt_birac_preview_card(record: DBTBIRACPreviewRecord, parent_names: dict[str, str]) -> str:
    parent = parent_names.get(record.parent_record_id, "")
    facts = []
    if parent:
        facts.append(f'<div><span>Parent programme</span><strong>{esc(parent)}</strong></div>')
    facts.extend((
        f'<div><span>Direct applicant</span><strong>{esc(display_token(record.direct_applicant_layer))}</strong></div>',
        f'<div><span>Status</span><strong>{esc(display_token(record.application_status))}</strong></div>',
        f'<div><span>Closing date</span><strong>{esc(record.closing_date or "Not specified")}</strong></div>',
    ))
    links = []
    if record.official_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_url)}">Official evidence <span aria-hidden="true">↗</span></a>')
    if record.guideline_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.guideline_url)}">Guidelines <span aria-hidden="true">↗</span></a>')
    note = (
        "Historical reference · Application window closed · No Apply action"
        if record.application_status == "CLOSED"
        else "Official-source programme record · Apply is shown only for a verified open call"
    )
    chips = [item for item in (record.sector.split(";") + record.support_type.split(";")) if item][:4]
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge">{esc(display_token(record.application_status))}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_type))}</span></div>'
        f'<h3>{esc(record.canonical_name)}</h3>'
        f'<div class="public-record-agency">{esc(record.implementing_agency or "Department of Biotechnology")}</div>'
        f'<p>{esc(record.summary or "Details are preserved in the official evidence package.")}</p>'
        f'<div class="public-record-facts">{"".join(facts)}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(display_token(item))}</span>" for item in chips)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_dbt_birac_page() -> None:
    bundle = cached_dbt_birac_preview()
    permanent = [row for row in bundle.records if row.record_type in {"SCHEME", "PROGRAMME"}]
    current = [row for row in bundle.records if row.application_status in {"OPEN", "UPCOMING"}]
    historical = [row for row in bundle.records if row.application_status == "CLOSED"]
    st.markdown(
        page_intro(
            "DBT–BIRAC intelligence",
            "DBT–BIRAC Schemes, Calls & Archive",
            "Permanent DBT and BIRAC programme identities, verified current calls and the governed historical archive are maintained as separate views.",
            badge=f"{len(permanent)} programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Permanent programmes", len(permanent), "Governed DBT–BIRAC programme identities", "blue")
        + metric_card("Open calls", sum(row.application_status == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical calls", len(historical), "Qualified official DBT–BIRAC references", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f'Last verified: {bundle.manifest.get("generated_at", "")[:10]} · '
        'Published on this department page from governed official-source records.'
    )

    st.markdown(
        '<div class="archive-governance">'
        '<strong>Verified ownership</strong>'
        '<span>Ministry of Science and Technology → Department of Biotechnology → '
        'BIRAC where the official record identifies BIRAC as implementing agency. '
        'Unresolved review items remain in the separate internal review workflow.</span></div>',
        unsafe_allow_html=True,
    )

    keyword_column, type_column, status_column = st.columns([2.2, 1.25, 1.25])
    with keyword_column:
        keyword = st.text_input("Search DBT–BIRAC schemes", placeholder="BIG, PACE, biotechnology, grant…")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_type for row in bundle.records})])
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in bundle.records})])
    applicant_column, sector_column = st.columns(2)
    with applicant_column:
        applicants = sorted({item for row in bundle.records for item in row.direct_applicant_layer.split(";") if item})
        applicant = st.selectbox("Direct applicant", ["All", *applicants])
    with sector_column:
        sectors = sorted({item for row in bundle.records for item in row.sector.split(";") if item})
        sector = st.selectbox("Sector", ["All", *sectors])
    visible = filter_dbt_birac_preview(bundle.records, keyword=keyword, record_type=record_type, status=status, applicant_layer=applicant, sector=sector)
    parent_names = {row.record_id: row.canonical_name for row in bundle.records}
    groups = (
        ("Schemes & Programmes", {"SCHEME", "PROGRAMME"}, None),
        (
            "Current Calls & Challenges",
            {
                "APPLICATION_CALL", "FUNDING_ROUND", "COHORT", "CHALLENGE", "COMPETITION",
                "INCUBATOR_OPPORTUNITY", "ACCELERATOR_OPPORTUNITY", "ECOSYSTEM_OPPORTUNITY",
                "IMPLEMENTATION_PARTNER_OPPORTUNITY",
            },
            {"OPEN", "UPCOMING"},
        ),
        (
            "Historical Archive",
            {
                "HISTORICAL_CALL", "APPLICATION_CALL", "FUNDING_ROUND", "COHORT", "CHALLENGE", "COMPETITION",
                "INCUBATOR_OPPORTUNITY", "ACCELERATOR_OPPORTUNITY", "ECOSYSTEM_OPPORTUNITY",
                "IMPLEMENTATION_PARTNER_OPPORTUNITY",
            },
            {"CLOSED"},
        ),
    )
    tabs = st.tabs([label for label, _, _ in groups])
    for tab, (label, types, allowed_statuses) in zip(tabs, groups):
        with tab:
            records = [row for row in visible if row.record_type in types and (allowed_statuses is None or row.application_status in allowed_statuses)]
            if label == "Historical Archive" and records:
                st.markdown(
                    '<div class="section-band">'
                    '<h2 class="section-title">DBT–BIRAC Historical Calls by Closing Year</h2>'
                    + _department_history_chart(
                        records,
                        date_getter=lambda item: item.closing_date,
                        legend_label="Qualified DBT–BIRAC historical calls",
                    )
                    + '</div>',
                    unsafe_allow_html=True,
                )
            if not records:
                st.info(f"No {label.lower()} match the selected filters.")
            else:
                st.markdown('<div class="public-record-grid">' + "".join(_dbt_birac_preview_card(row, parent_names) for row in records) + '</div>', unsafe_allow_html=True)


def _msme_display_title(value: str) -> str:
    """Use the canonical first title segment while retaining the governed source record."""
    return str(value or "").split("|", 1)[0].strip() or "MSME support record"


def _msme_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text = "Historical"
        status_class = "status-history"
        note = "Historical reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current opportunity · Confirm the official deadline before applying"
    else:
        status_label_text = "Status unverified"
        status_class = "status-unverified"
        note = "Permanent support record · Current application status is not verified"

    agency = record.implementing_agency or record.department or record.source or "MSME agency not recorded"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Support type</span><strong>{esc(display_token(record.record_kind or "SCHEME_OR_PROGRAMME"))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>'
    )
    chips = [*record.sectors[:2], *record.scheme_types[:2]]
    links = []
    if record.official_page_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">'
            'Official page <span aria-hidden="true">↗</span></a>'
        )
    if record.application_url and status in {"OPEN", "UPCOMING"}:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.application_url)}">'
            'Application portal <span aria-hidden="true">↗</span></a>'
        )
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_kind or "SCHEME_OR_PROGRAMME"))}</span></div>'
        f'<h3>{esc(_msme_display_title(record.scheme_name))}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        '<p>Official MSME or NSIC support information retained from the governed catalogue.</p>'
        f'<div class="public-record-facts">{facts}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def _render_msme_record_group(
    records: list[CatalogueRecord],
    *,
    label: str,
    historical: bool = False,
) -> None:
    st.markdown(
        f'<div class="filter-summary"><strong>{len(records)}</strong> {esc(label.lower())}'
        '<span>Official links open in a new tab</span></div>',
        unsafe_allow_html=True,
    )
    if not records:
        st.info(f"No {label.lower()} match the selected filters.")
        return
    st.markdown(
        '<div class="public-record-grid">'
        + "".join(_msme_record_card(record, historical=historical) for record in records)
        + '</div>',
        unsafe_allow_html=True,
    )


def render_msme_page(bundle: CatalogueBundle) -> None:
    msme: MSMEPublicBundle = build_msme_public_bundle(bundle.records)
    permanent = list(msme.permanent_records)
    current = list(msme.current_calls)
    historical = list(msme.historical_records)
    public_records = [*permanent, *current, *historical]
    ap_msme_count = sum(row.source == "AP MSME ONE" for row in public_records)
    mymsme_count = sum(row.source == "MyMSME Portal" for row in public_records)

    st.markdown(
        page_intro(
            "MSME intelligence",
            "MSME Schemes, Calls & Archive",
            "Official Ministry of MSME, AP MSME ONE and implementing-agency records are kept separate from current calls and historical references.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed MSME and NSIC support identities", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical references", len(historical), "Closed or historical official support records", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Latest scheme verification: {msme.latest_verification_date} · "
        "Counts are calculated from the governed catalogue projection."
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>Governed MSME ownership & page roles</strong>'
        '<span>Central and Andhra Pradesh ownership are retained separately; AP MSME ONE records are sourced from dedicated official detail pages. '
        f'{ap_msme_count} AP MSME ONE records and {mymsme_count} MyMSME Portal records are included. {len(msme.documents)} supporting documents are available under Resources; {msme.excluded_count} generic index or unverified call-like records are excluded from public counts.</span></div>',
        unsafe_allow_html=True,
    )

    keyword_column, agency_column, type_column = st.columns([2.2, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input(
            "Search MSME schemes",
            placeholder="Credit, marketing, registration, incubation…",
            key="msme_keyword",
        )
    agencies = sorted({row.implementing_agency or row.department or row.source for row in public_records})
    with agency_column:
        agency = st.selectbox("Implementing agency", ["All", *agencies], key="msme_agency")
    support_types = sorted({row.record_kind for row in public_records if row.record_kind})
    with type_column:
        support_type = st.selectbox(
            "Support type",
            ["All", *support_types],
            format_func=lambda value: "All support types" if value == "All" else display_token(value),
            key="msme_support_type",
        )

    visible = filter_msme_records(
        public_records,
        keyword=keyword,
        agency=agency,
        support_type=support_type,
    )
    visible_ids = {row.master_id for row in visible}
    tab_schemes, tab_calls, tab_history = st.tabs(
        ["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"]
    )
    with tab_schemes:
        _render_msme_record_group(
            [row for row in permanent if row.master_id in visible_ids],
            label="MSME scheme(s) and programme(s)",
        )
    with tab_calls:
        _render_msme_record_group(
            [row for row in current if row.master_id in visible_ids],
            label="verified current MSME call(s)",
        )
        if not current:
            st.caption(
                "Unverified challenge and service-centre pages remain excluded until official open-window evidence is recorded."
            )
    with tab_history:
        visible_history = [row for row in historical if row.master_id in visible_ids]
        if visible_history:
            st.markdown(
                '<div class="section-band">'
                '<h2 class="section-title">MSME Historical References by Evidenced Year</h2>'
                + _department_history_chart(
                    visible_history,
                    date_getter=lambda item: item.closing_date,
                    legend_label="Qualified MSME historical references",
                )
                + '</div>',
                unsafe_allow_html=True,
            )
        _render_msme_record_group(
            visible_history,
            label="historical MSME reference(s)",
            historical=True,
        )


def _dot_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text, status_class = "Historical", "status-history"
        note = "Historical reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current opportunity · Confirm the official deadline before applying"
    else:
        status_label_text, status_class = "Status unverified", "status-unverified"
        note = "Permanent DoT support record · Current application status is not verified"
    agency = record.implementing_agency or record.department or "Department of Telecommunications"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    funding = ""
    if record.funding_maximum is not None:
        funding = f'<div><span>Maximum support</span><strong>{esc(format_inr(record.funding_maximum))}</strong></div>'
    date_fact = ""
    if record.closing_date:
        date_fact = f'<div><span>Closing date</span><strong>{esc(record.closing_date)}</strong></div>'
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Scheme / programme type</span><strong>{esc(display_token(record.record_kind))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>'
        f'{date_fact}'
        f'{funding}'
    )
    chips = [*record.sectors[:3], *record.scheme_types[:2]]
    links = []
    if record.official_page_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">↗</span></a>'
        )
    for url in record.guideline_urls[:1]:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(url)}">Guideline <span aria-hidden="true">↗</span></a>'
        )
    summary = record.benefits[0] if record.benefits else (record.objectives[0] if record.objectives else "Details are preserved in the governed official evidence record.")
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_kind))}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        f'<p>{esc(summary)}</p>'
        f'<div class="public-record-facts">{facts}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_dot_page(bundle: CatalogueBundle) -> None:
    dot: DOTPublicBundle = build_dot_public_bundle(bundle.records)
    permanent = list(dot.permanent_records)
    current = list(dot.current_calls)
    historical = list(dot.historical_records)
    all_records = [*permanent, *current, *historical]
    st.markdown(
        page_intro(
            "DoT intelligence",
            "DoT Schemes, Calls & Archive",
            "Department of Telecommunications support identities, verified application windows and historical TTDF/DCIS calls are maintained as separate public views.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed DoT schemes and programmes", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical calls", len(historical), "Qualified TTDF and DCIS references", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Latest scheme verification: {dot.latest_verification_date} · "
        "Counts are calculated from the governed DoT publication snapshot."
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>DoT ownership and status governance</strong>'
        '<span>Permanent DoT, TTDF and DCIS identities are separate from dated calls. '
        f'No current DoT call is published in this snapshot because no dated official application window was verified; {dot.excluded_count} call-like records remain excluded from active counts.</span></div>',
        unsafe_allow_html=True,
    )
    keyword_column, type_column, status_column = st.columns([2.3, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input("Search DoT schemes", placeholder="TTDF, 5G, testing, rural connectivity…", key="dot_keyword")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_kind for row in all_records})], key="dot_record_type")
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in all_records})], key="dot_status")
    visible = filter_dot_records(all_records, keyword=keyword, record_type=record_type, status=status)
    visible_ids = {row.master_id for row in visible}
    tab_schemes, tab_calls, tab_history = st.tabs(["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"])
    with tab_schemes:
        rows = [row for row in permanent if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> DoT scheme(s) and programme(s)<span>Official links open in a new tab</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_dot_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No DoT schemes or programmes match the selected filters.")
    with tab_calls:
        rows = [row for row in current if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> verified current DoT call(s)<span>Unverified windows remain hidden</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_dot_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No verified open or upcoming DoT calls are currently published.")
    with tab_history:
        rows = [row for row in historical if row.master_id in visible_ids]
        if rows:
            st.markdown(
                '<div class="section-band"><h2 class="section-title">DoT Historical Calls by Evidenced Closing Year</h2>'
                + _department_history_chart(rows, date_getter=lambda item: item.closing_date, legend_label="Qualified DoT historical calls")
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="public-record-grid">' + "".join(_dot_record_card(row, historical=True) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No historical DoT records match the selected filters.")


def _idex_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text, status_class = "Historical", "status-history"
        note = "Historical challenge reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current challenge · Confirm the official deadline before applying"
    else:
        status_label_text, status_class = "Status unverified", "status-unverified"
        note = "Permanent iDEX support identity · Current application status is not verified"
    agency = record.implementing_agency or "Defence Innovation Organisation (DIO)"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    funding = ""
    if record.funding_maximum is not None:
        funding = f'<div><span>Maximum support</span><strong>{esc(format_inr(record.funding_maximum))}</strong></div>'
    date_fact = ""
    if record.closing_date:
        date_fact = f'<div><span>Closing date</span><strong>{esc(record.closing_date)}</strong></div>'
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Scheme / programme type</span><strong>{esc(display_token(record.record_kind))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>'
        f'{date_fact}'
        f'{funding}'
    )
    chips = [*record.sectors[:3], *record.scheme_types[:2]]
    links = []
    if record.official_page_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">↗</span></a>'
        )
    for url in record.guideline_urls[:1]:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(url)}">Guideline <span aria-hidden="true">↗</span></a>'
        )
    summary = record.benefits[0] if record.benefits else (record.objectives[0] if record.objectives else "Details are preserved in the governed official evidence record.")
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_kind))}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        f'<p>{esc(summary)}</p>'
        f'<div class="public-record-facts">{facts}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_idex_page(bundle: CatalogueBundle) -> None:
    idex: IDEXPublicBundle = build_idex_public_bundle(bundle.records)
    permanent = list(idex.permanent_records)
    current = list(idex.current_calls)
    historical = list(idex.historical_records)
    all_records = [*permanent, *current, *historical]
    st.markdown(
        page_intro(
            "iDEX intelligence",
            "iDEX Schemes, Programmes, Calls & Archive",
            "Department of Defence Production and Defence Innovation Organisation schemes, programmes, verified calls and historical references are maintained as separate public views.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed iDEX schemes and programmes", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current iDEX application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future challenge windows", "purple")
        + metric_card("Historical calls", len(historical), "Qualified DISC, ADITI and iDEX references", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Latest scheme verification: {idex.latest_verification_date} · "
        "Counts are calculated from the governed iDEX publication snapshot."
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>iDEX ownership and status governance</strong>'
        '<span>Permanent iDEX, ADITI and SPARK identities are separate from dated DISC, Open, Thematic and partner challenges. '
        f'{len(current)} current iDEX challenge window(s) are published only where an official deadline was evidenced; {idex.excluded_count} call-like entries remain excluded from active counts.</span></div>',
        unsafe_allow_html=True,
    )
    keyword_column, type_column, status_column = st.columns([2.3, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input("Search iDEX schemes and challenges", placeholder="DISC, ADITI, Open Challenge, aerospace…", key="idex_keyword")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_kind for row in all_records})], key="idex_record_type")
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in all_records})], key="idex_status")
    visible = filter_idex_records(all_records, keyword=keyword, record_type=record_type, status=status)
    visible_ids = {row.master_id for row in visible}
    tab_schemes, tab_calls, tab_history = st.tabs(["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"])
    with tab_schemes:
        rows = [row for row in permanent if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> iDEX scheme(s) and programme(s)<span>Official links open in a new tab</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_idex_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No iDEX schemes or programmes match the selected filters.")
    with tab_calls:
        rows = [row for row in current if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> verified current iDEX challenge(s)<span>Unverified windows remain hidden</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_idex_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No verified open or upcoming iDEX challenges match the selected filters.")
    with tab_history:
        rows = [row for row in historical if row.master_id in visible_ids]
        if rows:
            st.markdown(
                '<div class="section-band"><h2 class="section-title">iDEX Historical Challenges by Evidenced Closing Year</h2>'
                + _department_history_chart(rows, date_getter=lambda item: item.closing_date, legend_label="Qualified iDEX historical challenges")
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="public-record-grid">' + "".join(_idex_record_card(row, historical=True) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No historical iDEX calls match the selected filters.")


def _agri_startup_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text, status_class = "Historical", "status-history"
        note = "Historical startup/innovation reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current startup opportunity · Confirm the official deadline before applying"
    else:
        status_label_text, status_class = "Status unverified", "status-unverified"
        note = "Permanent agri-startup support identity · Current application status is not verified"
    agency = record.implementing_agency or record.department or "Department of Agriculture & Farmers Welfare"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    date_fact = f'<div><span>Closing date</span><strong>{esc(record.closing_date)}</strong></div>' if record.closing_date else ""
    funding = f'<div><span>Maximum support</span><strong>{esc(format_inr(record.funding_maximum))}</strong></div>' if record.funding_maximum is not None else ""
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Scheme type</span><strong>{esc(display_token(record.record_kind))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>{date_fact}{funding}'
    )
    chips = [*record.sectors[:3], *record.scheme_types[:2]]
    links = []
    if record.application_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.application_url)}">Register / Apply <span aria-hidden="true">↗</span></a>')
    if record.official_page_url:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">↗</span></a>')
    for url in record.guideline_urls[:1]:
        links.append(f'<a target="_blank" rel="noopener noreferrer" href="{esc(url)}">Guideline <span aria-hidden="true">↗</span></a>')
    summary = record.benefits[0] if record.benefits else (record.objectives[0] if record.objectives else "Details are preserved in the governed official evidence record.")
    return (
        '<article class="public-record-card"><div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span><span class="public-kind">{esc(display_token(record.record_kind))}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3><div class="public-record-agency">{esc(agency)}</div><p>{esc(summary)}</p>'
        f'<div class="public-record-facts">{facts}</div><div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div><div class="public-record-actions">{"".join(links)}</div></article>'
    )


def render_agri_startup_page(bundle: CatalogueBundle) -> None:
    agri: AgriStartupPublicBundle = build_agri_startup_public_bundle(bundle.records)
    permanent, current, historical = list(agri.permanent_records), list(agri.current_calls), list(agri.historical_records)
    all_records = [*permanent, *current, *historical]
    st.markdown(page_intro(
        "Agri-startup intelligence", "Agri-Startup & Innovation",
        "Startup schemes, incubators, venture funds and innovation calls in the agriculture and allied ecosystem are maintained as separate public views.",
        badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
    ), unsafe_allow_html=True)
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed agri-startup schemes and programmes", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical innovation calls", len(historical), "Qualified historical references", "orange") + '</div>', unsafe_allow_html=True)
    st.caption(f"Latest scheme verification: {agri.latest_verification_date} · Counts are calculated from the governed agriculture-startup publication snapshot.")
    st.markdown(
        '<div class="archive-governance"><strong>Agri-startup scope and status governance</strong>'
        f'<span>General farmer-benefit schemes are excluded. Incubator directories are discovery sources only; training calendars are also discovery evidence and neither is counted as schemes. Current startup and allied-sector opportunities are shown only where an official deadline and registration evidence are available; undated programme identities remain visible without being promoted to open calls. {agri.excluded_count} call-like records remain excluded from active counts.</span></div>',
        unsafe_allow_html=True,
    )
    keyword_column, type_column, status_column = st.columns([2.3, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input("Search agri-startup schemes", placeholder="RKVY, AgriSURE, incubator, agritech…", key="agri_startup_keyword")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_kind for row in all_records})], key="agri_startup_record_type")
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in all_records})], key="agri_startup_status")
    visible_ids = {row.master_id for row in filter_agri_startup_records(all_records, keyword=keyword, record_type=record_type, status=status)}
    tab_schemes, tab_calls, tab_history = st.tabs(["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"])
    with tab_schemes:
        rows = [row for row in permanent if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> agriculture startup scheme(s) and programme(s)<span>Official links open in a new tab</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_agri_startup_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No agriculture startup schemes or programmes match the selected filters.")
    with tab_calls:
        rows = [row for row in current if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> verified current agri-startup call(s)<span>Unverified windows remain hidden</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_agri_startup_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No verified open or upcoming agriculture startup calls are currently published.")
    with tab_history:
        rows = [row for row in historical if row.master_id in visible_ids]
        if rows:
            st.markdown('<div class="section-band"><h2 class="section-title">Agri-Startup Historical Innovation Calls by Evidenced Closing Year</h2>' + _department_history_chart(rows, date_getter=lambda item: item.closing_date, legend_label="Qualified agri-startup historical calls") + '</div>', unsafe_allow_html=True)
            st.markdown('<div class="public-record-grid">' + "".join(_agri_startup_record_card(row, historical=True) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No historical agri-startup schemes or calls match the selected filters.")


def _msde_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text, status_class = "Historical", "status-history"
        note = "Historical MSDE reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current opportunity · Confirm the official deadline before applying"
    else:
        status_label_text, status_class = "Status unverified", "status-unverified"
        note = "Permanent MSDE support identity · Current application status is not verified"
    agency = record.implementing_agency or record.department or "MSDE"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    date_fact = ""
    if record.opening_date:
        date_fact += f'<div><span>Opening date</span><strong>{esc(record.opening_date)}</strong></div>'
    if record.closing_date:
        date_fact += f'<div><span>Closing date</span><strong>{esc(record.closing_date)}</strong></div>'
    funding = ""
    if record.funding_maximum is not None:
        funding = f'<div><span>Maximum support</span><strong>{esc(format_inr(record.funding_maximum))}</strong></div>'
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Scheme / programme type</span><strong>{esc(display_token(record.record_kind))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>'
        f'{date_fact}{funding}'
    )
    chips = [*record.sectors[:3], *record.scheme_types[:2]]
    links = []
    if record.official_page_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">↗</span></a>'
        )
    for url in record.guideline_urls[:1]:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(url)}">Guideline <span aria-hidden="true">↗</span></a>'
        )
    summary = record.benefits[0] if record.benefits else (record.objectives[0] if record.objectives else "Details are preserved in the governed official evidence record.")
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_kind))}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        f'<p>{esc(summary)}</p>'
        f'<div class="public-record-facts">{facts}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_msde_page(bundle: CatalogueBundle) -> None:
    msde: MSDEPublicBundle = build_msde_public_bundle(bundle.records)
    permanent = list(msde.permanent_records)
    current = list(msde.current_calls)
    historical = list(msde.historical_records)
    all_records = [*permanent, *current, *historical]
    st.markdown(
        page_intro(
            "MSDE intelligence",
            "MSDE Schemes, Programmes & Calls",
            "Ministry of Skill Development & Entrepreneurship schemes, entrepreneurship pathways, verified calls and historical references are maintained as separate public views.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed MSDE support identities", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical references", len(historical), "Qualified MSDE cycles and notices", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Latest scheme verification: {msde.latest_verification_date} · "
        "Counts are calculated from the governed MSDE publication snapshot."
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>MSDE ownership and status governance</strong>'
        '<span>Permanent Skill India and entrepreneurship identities are separate from dated calls and public-comment windows. '
        f'Only official dated application evidence is promoted to current calls; {msde.excluded_count} call-like record(s) remain excluded from active counts.</span></div>',
        unsafe_allow_html=True,
    )
    keyword_column, type_column, status_column = st.columns([2.3, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input("Search MSDE schemes", placeholder="PMKVY, apprenticeship, entrepreneurship…", key="msde_keyword")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_kind for row in all_records})], key="msde_record_type")
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in all_records})], key="msde_status")
    visible = filter_msde_records(all_records, keyword=keyword, record_type=record_type, status=status)
    visible_ids = {row.master_id for row in visible}
    tab_schemes, tab_calls, tab_history = st.tabs(["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"])
    with tab_schemes:
        rows = [row for row in permanent if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> MSDE scheme(s) and programme(s)<span>Official links open in a new tab</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_msde_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No MSDE schemes or programmes match the selected filters.")
    with tab_calls:
        rows = [row for row in current if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> verified current MSDE call(s)<span>Undated windows remain hidden</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_msde_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No verified open or upcoming MSDE calls are currently published.")
    with tab_history:
        rows = [row for row in historical if row.master_id in visible_ids]
        if rows:
            st.markdown(
                '<div class="section-band"><h2 class="section-title">MSDE Historical Calls & Cycles by Evidenced Closing Year</h2>'
                + _department_history_chart(rows, date_getter=lambda item: item.closing_date, legend_label="Qualified MSDE historical references")
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="public-record-grid">' + "".join(_msde_record_card(row, historical=True) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No historical MSDE records match the selected filters.")


def _moe_record_card(record: CatalogueRecord, *, historical: bool = False) -> str:
    status = record.application_status.upper()
    if historical:
        status_label_text, status_class = "Historical", "status-history"
        note = "Historical MoE / AICTE reference · No active application action"
    elif status in {"OPEN", "UPCOMING"}:
        status_label_text = display_token(status)
        status_class = "status-open" if status == "OPEN" else "status-upcoming"
        note = "Verified current opportunity · Confirm the official deadline before applying"
    else:
        status_label_text, status_class = "Status unverified", "status-unverified"
        note = "Permanent MoE / AICTE identity · Current application status is not verified"
    agency = record.implementing_agency or record.department or "Ministry of Education / AICTE"
    verified = record.last_verified_at or record.last_updated or "Not recorded"
    date_fact = ""
    if record.opening_date:
        date_fact += f'<div><span>Opening date</span><strong>{esc(record.opening_date)}</strong></div>'
    if record.closing_date:
        date_fact += f'<div><span>Closing date</span><strong>{esc(record.closing_date)}</strong></div>'
    funding = ""
    if record.funding_maximum is not None:
        funding = f'<div><span>Maximum support</span><strong>{esc(format_inr(record.funding_maximum))}</strong></div>'
    facts = (
        f'<div><span>Implementing agency</span><strong>{esc(agency)}</strong></div>'
        f'<div><span>Scheme / programme type</span><strong>{esc(display_token(record.record_kind))}</strong></div>'
        f'<div><span>Last verified</span><strong>{esc(verified)}</strong></div>'
        f'{date_fact}{funding}'
    )
    chips = [*record.sectors[:3], *record.scheme_types[:2]]
    links = []
    if record.official_page_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.official_page_url)}">Official page <span aria-hidden="true">↗</span></a>'
        )
    if record.application_url:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(record.application_url)}">Apply / portal <span aria-hidden="true">↗</span></a>'
        )
    for url in record.guideline_urls[:1]:
        links.append(
            f'<a target="_blank" rel="noopener noreferrer" href="{esc(url)}">Guideline <span aria-hidden="true">↗</span></a>'
        )
    summary = record.benefits[0] if record.benefits else (record.objectives[0] if record.objectives else "Details are preserved in the governed official evidence record.")
    return (
        '<article class="public-record-card">'
        '<div class="public-record-card-top">'
        f'<span class="status-badge {status_class}">{esc(status_label_text)}</span>'
        f'<span class="public-kind">{esc(display_token(record.record_kind))}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="public-record-agency">{esc(agency)}</div>'
        f'<p>{esc(summary)}</p>'
        f'<div class="public-record-facts">{facts}</div>'
        f'<div class="public-chip-row">{"".join(f"<span>{esc(item)}</span>" for item in chips if item)}</div>'
        f'<div class="public-record-note">{esc(note)}</div>'
        f'<div class="public-record-actions">{"".join(links)}</div>'
        '</article>'
    )


def render_moe_page(bundle: CatalogueBundle) -> None:
    moe: MOEPublicBundle = build_moe_public_bundle(bundle.records)
    permanent = list(moe.permanent_records)
    current = list(moe.current_calls)
    historical = list(moe.historical_records)
    all_records = [*permanent, *current, *historical]
    st.markdown(
        page_intro(
            "MoE / AICTE intelligence",
            "MoE / AICTE Schemes, Programmes & Calls",
            "Higher-education innovation, entrepreneurship, research pathways and dated application windows are maintained as separate public views.",
            badge=f"{len(permanent)} schemes & programmes · {len(current)} current calls · {len(historical)} historical",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid call-metrics">'
        + metric_card("Schemes & programmes", len(permanent), "Governed MoE / AICTE support identities", "blue")
        + metric_card("Open calls", sum(row.application_status.upper() == "OPEN" for row in current), "Verified current application windows", "green")
        + metric_card("Upcoming", sum(row.application_status.upper() == "UPCOMING" for row in current), "Verified future application windows", "purple")
        + metric_card("Historical references", len(historical), "Qualified MoE / AICTE cycles", "orange")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Latest scheme verification: {moe.latest_verification_date} · "
        "Counts are calculated from the governed MoE / AICTE publication snapshot."
    )
    st.markdown(
        '<div class="archive-governance">'
        '<strong>MoE / AICTE ownership and status governance</strong>'
        '<span>Permanent innovation identities are separate from dated challenge and research-application windows. '
        f'Only official dated application evidence is promoted to current calls; {moe.excluded_count} call-like record(s) remain excluded from active counts.</span></div>',
        unsafe_allow_html=True,
    )
    keyword_column, type_column, status_column = st.columns([2.3, 1.35, 1.35])
    with keyword_column:
        keyword = st.text_input("Search MoE / AICTE schemes", placeholder="IIC, IDEA Lab, YUKTI, PMRC…", key="moe_keyword")
    with type_column:
        record_type = st.selectbox("Scheme / programme type", ["All", *sorted({row.record_kind for row in all_records})], key="moe_record_type")
    with status_column:
        status = st.selectbox("Application status", ["All", *sorted({row.application_status for row in all_records})], key="moe_status")
    visible = filter_moe_records(all_records, keyword=keyword, record_type=record_type, status=status)
    visible_ids = {row.master_id for row in visible}
    tab_schemes, tab_calls, tab_history = st.tabs(["Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"])
    with tab_schemes:
        rows = [row for row in permanent if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> MoE / AICTE scheme(s) and programme(s)<span>Official links open in a new tab</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_moe_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No MoE / AICTE schemes or programmes match the selected filters.")
    with tab_calls:
        rows = [row for row in current if row.master_id in visible_ids]
        st.markdown(f'<div class="filter-summary"><strong>{len(rows)}</strong> verified current MoE / AICTE call(s)<span>Undated windows remain hidden</span></div>', unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="public-record-grid">' + "".join(_moe_record_card(row) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No verified open or upcoming MoE / AICTE calls are currently published.")
    with tab_history:
        rows = [row for row in historical if row.master_id in visible_ids]
        if rows:
            st.markdown(
                '<div class="section-band"><h2 class="section-title">MoE / AICTE Historical Calls by Evidenced Closing Year</h2>'
                + _department_history_chart(rows, date_getter=lambda item: item.closing_date, legend_label="Qualified MoE / AICTE historical references")
                + '</div>',
                unsafe_allow_html=True,
            )
            st.markdown('<div class="public-record-grid">' + "".join(_moe_record_card(row, historical=True) for row in rows) + '</div>', unsafe_allow_html=True)
        else:
            st.info("No historical MoE / AICTE records match the selected filters.")


def main() -> None:
    requested_slug = str(st.query_params.get("page", "") or "").strip().lower()
    requested_page = PAGE_SLUG_ALIASES.get(requested_slug) or next(
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
    page = requested_page or st.session_state.get("ssip_primary_navigation", "Home")
    if page not in PAGE_NAMES:
        page = "Home"
    st.session_state["ssip_primary_navigation"] = page
    active_slug = PAGE_SLUGS[page]
    if str(st.query_params.get("page", "") or "") != active_slug:
        st.query_params["page"] = active_slug

    header_column, appearance_column = st.columns([8.75, 1.25])
    with header_column:
        st.markdown(site_header(page), unsafe_allow_html=True)
    with appearance_column:
        st.toggle(
            "Dark mode",
            key="ssip_dark_mode",
            help="Switch between light and dark appearance.",
        )
    st.markdown(
        '<span id="ssip-main-content" class="main-content-anchor" tabindex="-1"></span>',
        unsafe_allow_html=True,
    )
    try:
        bundle = cached_catalogue(_msme_cache_token())
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
    elif page == "MeitY":
        render_meity_page(bundle)
    elif page == "DPIIT":
        render_dpiit_page()
    elif page == "DBT–BIRAC":
        render_dbt_birac_page()
    elif page == "MSME":
        render_msme_page(bundle)
    elif page == "DoT":
        render_dot_page(bundle)
    elif page == "iDEX":
        render_idex_page(bundle)
    elif page == "Agriculture":
        render_agri_startup_page(bundle)
    elif page == "MSDE":
        render_msde_page(bundle)
    elif page == "MoE":
        render_moe_page(bundle)
    elif page == "Official Sources":
        render_official_sources(official_sources, bundle)
    elif page == "Calls & Opportunities":
        render_calls_and_opportunities()
    elif page == "Incubators & Ecosystem":
        render_startup_ecosystem()
    elif page == "Directory":
        render_resources(bundle, official_sources)
    elif page == "Media Runs":
        render_media_runs_page(bundle)
    elif page == "Scheme Details":
        render_scheme_details(bundle)

    st.caption("SSIP · Information sourced from official government portals.")


if __name__ == "__main__":
    main()
