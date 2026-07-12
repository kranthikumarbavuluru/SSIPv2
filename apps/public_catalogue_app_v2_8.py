from __future__ import annotations

import ast
import html
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


APP_VERSION = "2.8.2-dashboard-mvp"


def find_project_root(start: Path) -> Path:
    candidates = [start.parent, *start.parents]
    for candidate in candidates:
        if (candidate / "database" / "ssip_staging_v1.db").exists():
            return candidate
    return start.parent.parent


PROJECT_ROOT = find_project_root(Path(__file__).resolve())
DATABASE_PATH = PROJECT_ROOT / "database" / "ssip_staging_v1.db"
NORMALIZATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "audit"
    / "v2_8_1_catalogue_normalization"
    / "catalogue_normalization_plan_v2_8_1.csv"
)

st.set_page_config(
    page_title="SSIP — Startup Scheme Intelligence Platform",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
        :root {
            --ssip-purple: #5b3cc4;
            --ssip-purple-dark: #3e268f;
            --ssip-soft: #f5f3ff;
            --ssip-border: #e4def8;
            --ssip-text: #202033;
            --ssip-muted: #6b6b7c;
        }

        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 3rem;
            max-width: 1450px;
        }

        .ssip-hero {
            padding: 1.5rem 1.6rem;
            border-radius: 20px;
            background:
                radial-gradient(circle at 100% 0%, rgba(255,255,255,.28), transparent 34%),
                linear-gradient(135deg, var(--ssip-purple-dark), var(--ssip-purple));
            color: white;
            box-shadow: 0 14px 34px rgba(62, 38, 143, .18);
            margin-bottom: 1rem;
        }

        .ssip-hero h1 {
            margin: 0;
            font-size: clamp(1.8rem, 3vw, 3rem);
            line-height: 1.08;
        }

        .ssip-hero p {
            margin: .65rem 0 0;
            max-width: 900px;
            font-size: 1.02rem;
            opacity: .94;
        }

        .ssip-note {
            background: var(--ssip-soft);
            border: 1px solid var(--ssip-border);
            border-radius: 14px;
            padding: .8rem 1rem;
            color: var(--ssip-text);
            margin: .5rem 0 1rem;
        }

        .scheme-card {
            border: 1px solid var(--ssip-border);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            margin: .75rem 0 .35rem;
            background: white;
            box-shadow: 0 7px 22px rgba(38, 26, 83, .07);
        }

        .scheme-card h3 {
            margin: 0 0 .35rem;
            color: var(--ssip-text);
            font-size: 1.18rem;
        }

        .scheme-card p {
            color: var(--ssip-muted);
            margin: .35rem 0;
            line-height: 1.45;
        }

        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: .22rem .62rem;
            margin: .12rem .22rem .12rem 0;
            font-size: .78rem;
            font-weight: 700;
            background: var(--ssip-soft);
            color: var(--ssip-purple-dark);
            border: 1px solid var(--ssip-border);
        }

        .badge-open {
            background: #eaf9ef;
            color: #166534;
            border-color: #bce8c9;
        }

        .badge-closed {
            background: #fff1f1;
            color: #991b1b;
            border-color: #f3c2c2;
        }

        .badge-pending {
            background: #fff8e6;
            color: #8a5200;
            border-color: #f1d894;
        }

        .small-muted {
            color: var(--ssip-muted);
            font-size: .84rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid var(--ssip-border);
            border-radius: 16px;
            padding: .7rem .85rem;
            background: white;
        }

        section[data-testid="stSidebar"] {
            border-right: 1px solid var(--ssip-border);
        }

        @media (max-width: 700px) {
            .block-container {
                padding-left: .8rem;
                padding-right: .8rem;
            }

            .ssip-hero {
                padding: 1.2rem;
                border-radius: 16px;
            }

            .scheme-card {
                padding: .9rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip()
    return text == "" or text.casefold() in {"none", "null", "nan", "nat"}


def first_value(*values: Any) -> Any:
    for value in values:
        if not is_blank(value):
            return value
    return None


def safe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if is_blank(value):
        return {}
    text = str(value).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return {}


def merge_dicts(base: dict[str, Any], incoming: Any) -> dict[str, Any]:
    if not isinstance(incoming, dict):
        return base
    for key, value in incoming.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            base[key] = merge_dicts(dict(base[key]), value)
        elif key not in base or is_blank(base[key]):
            base[key] = value
    return base


def deep_find(value: Any, keys: list[str]) -> Any:
    wanted = {key.casefold() for key in keys}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in wanted and not is_blank(item):
                return item
        for item in value.values():
            found = deep_find(item, keys)
            if not is_blank(found):
                return found
    elif isinstance(value, list):
        for item in value:
            found = deep_find(item, keys)
            if not is_blank(found):
                return found
    return None


def text_item(value: Any) -> str:
    if isinstance(value, dict):
        preferred = first_value(
            value.get("value"),
            value.get("name"),
            value.get("title"),
            value.get("label"),
            value.get("description"),
            value.get("text"),
            value.get("email"),
            value.get("phone"),
        )
        if not is_blank(preferred):
            return str(preferred).strip()
        parts = []
        for key, item in value.items():
            if not is_blank(item) and not isinstance(item, (dict, list)):
                parts.append(f"{str(key).replace('_', ' ').title()}: {item}")
        return "; ".join(parts)
    return str(value).strip()


def to_list(value: Any) -> list[str]:
    if is_blank(value):
        return []
    parsed = safe_json(value)
    if parsed not in ({}, []):
        value = parsed
    if isinstance(value, list):
        output = []
        for item in value:
            cleaned = text_item(item)
            if cleaned:
                output.append(cleaned)
        return dedupe(output)
    if isinstance(value, dict):
        cleaned = text_item(value)
        return [cleaned] if cleaned else []
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        parsed = safe_json(text)
        if isinstance(parsed, list):
            return to_list(parsed)
    pieces = re.split(r"\s*[|;\n]\s*", text)
    return dedupe([piece.strip(" •-\t") for piece in pieces if piece.strip(" •-\t")])


def dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            output.append(item.strip())
    return output


URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+", re.IGNORECASE)


def collect_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            urls.extend(collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(collect_urls(item))
    elif not is_blank(value):
        urls.extend(URL_RE.findall(str(value)))
    return dedupe([url.rstrip(".,;") for url in urls])


def safe_url(value: Any) -> str | None:
    if is_blank(value):
        return None
    match = URL_RE.search(str(value))
    return match.group(0).rstrip(".,;") if match else None


def label(value: Any) -> str:
    if is_blank(value):
        return "Not specified"
    return str(value).replace("_", " ").strip().title()


def format_date(value: Any) -> str:
    if is_blank(value):
        return "Not specified"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d %b %Y")


def format_money(value: Any, currency: Any = "INR") -> str:
    if is_blank(value):
        return "Not specified"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    if amount >= 10_000_000:
        return f"₹{amount / 10_000_000:,.2f} crore"
    if amount >= 100_000:
        return f"₹{amount / 100_000:,.2f} lakh"
    return f"{str(currency or 'INR').upper()} {amount:,.0f}"


def read_sql_table(connection: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    if not exists:
        return pd.DataFrame()
    return pd.read_sql_query(f'SELECT * FROM "{table_name}"', connection)


def dataframe_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "master_id" not in frame.columns:
        return {}
    output: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict(orient="records"):
        master_id = str(row.get("master_id") or "").strip()
        if master_id:
            output[master_id] = row
    return output


def table_url_map(frame: pd.DataFrame) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output
    for row in frame.to_dict(orient="records"):
        master_id = str(row.get("master_id") or "").strip()
        if not master_id:
            continue
        output.setdefault(master_id, []).extend(collect_urls(row))
    return {key: dedupe(value) for key, value in output.items()}


def attribute_map(frame: pd.DataFrame) -> dict[str, dict[str, list[str]]]:
    output: dict[str, dict[str, list[str]]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output

    key_candidates = [
        "attribute_name",
        "field_name",
        "attribute_key",
        "key",
        "name",
    ]
    value_candidates = [
        "attribute_value",
        "field_value",
        "value_json",
        "json_value",
        "value",
    ]
    key_column = next((column for column in key_candidates if column in frame.columns), None)
    value_column = next(
        (column for column in value_candidates if column in frame.columns), None
    )
    if not key_column or not value_column:
        return output

    for row in frame.to_dict(orient="records"):
        master_id = str(row.get("master_id") or "").strip()
        key = str(row.get(key_column) or "").strip()
        if not master_id or not key:
            continue
        values = to_list(row.get(value_column))
        output.setdefault(master_id, {}).setdefault(key.casefold(), []).extend(values)

    for master_id in output:
        for key in output[master_id]:
            output[master_id][key] = dedupe(output[master_id][key])
    return output


def attribute_values(
    attributes: dict[str, dict[str, list[str]]],
    master_id: str,
    keys: list[str],
) -> list[str]:
    current = attributes.get(master_id, {})
    values: list[str] = []
    wanted = {key.casefold() for key in keys}
    for key, items in current.items():
        if key.casefold() in wanted:
            values.extend(items)
    return dedupe(values)


def contact_map(frame: pd.DataFrame) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    if frame.empty or "master_id" not in frame.columns:
        return output
    ignored = {
        "master_id",
        "id",
        "created_at",
        "updated_at",
        "record_hash",
        "source_run_id",
    }
    for row in frame.to_dict(orient="records"):
        master_id = str(row.get("master_id") or "").strip()
        if not master_id:
            continue
        parts = []
        for key, value in row.items():
            if key in ignored or is_blank(value):
                continue
            parts.append(f"{label(key)}: {text_item(value)}")
        if parts:
            output.setdefault(master_id, []).append(" | ".join(parts))
    return {key: dedupe(value) for key, value in output.items()}


@st.cache_data(ttl=60, show_spinner=False)
def load_catalogue() -> tuple[pd.DataFrame, dict[str, Any]]:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DATABASE_PATH}")

    connection = sqlite3.connect(DATABASE_PATH)
    staging = read_sql_table(connection, "scheme_staging")
    review = read_sql_table(connection, "admin_review_queue")
    attributes_frame = read_sql_table(connection, "scheme_attributes")
    contacts_frame = read_sql_table(connection, "scheme_contacts")
    sources_frame = read_sql_table(connection, "scheme_sources")
    connection.close()

    staging_by_id = dataframe_map(staging)
    review_by_id = dataframe_map(review)
    attrs = attribute_map(attributes_frame)
    contacts = contact_map(contacts_frame)
    source_urls = table_url_map(sources_frame)

    if NORMALIZATION_PATH.exists():
        plan = pd.read_csv(NORMALIZATION_PATH, dtype=str, keep_default_na=False)
    else:
        plan = staging.copy()
        if "catalogue_inclusion" not in plan.columns:
            plan["catalogue_inclusion"] = "INCLUDED"
        if "catalogue_section" not in plan.columns:
            plan["catalogue_section"] = plan.get(
                "record_kind", pd.Series(["SCHEMES_AND_PROGRAMMES"] * len(plan))
            )
        if "normalized_record_kind" not in plan.columns:
            plan["normalized_record_kind"] = plan.get(
                "record_kind", pd.Series(["SCHEME_OR_PROGRAMME"] * len(plan))
            )

    records: list[dict[str, Any]] = []

    for plan_row in plan.to_dict(orient="records"):
        master_id = str(plan_row.get("master_id") or "").strip()
        if not master_id:
            continue

        staged = staging_by_id.get(master_id, {})
        reviewed = review_by_id.get(master_id, {})

        payload: dict[str, Any] = {}
        for candidate in [
            safe_json(reviewed.get("validated_record_json")),
            safe_json(staged.get("raw_record_json")),
        ]:
            if isinstance(candidate, dict):
                payload = merge_dicts(payload, candidate)

        nested_record = deep_find(
            payload,
            ["validated_record", "record", "scheme_record", "data"],
        )
        if isinstance(nested_record, dict):
            payload = merge_dicts(payload, nested_record)

        def direct(*names: str) -> Any:
            values: list[Any] = []
            for name in names:
                values.extend(
                    [
                        plan_row.get(name),
                        staged.get(name),
                        reviewed.get(name),
                    ]
                )
            values.append(deep_find(payload, list(names)))
            return first_value(*values)

        def detail_list(names: list[str]) -> list[str]:
            values = to_list(deep_find(payload, names))
            if values:
                return values
            return attribute_values(attrs, master_id, names)

        scheme_name = str(
            first_value(
                direct("scheme_name", "canonical_name", "title"),
                f"Unnamed record {master_id}",
            )
        )
        application_status = direct("application_status", "scheme_status")
        if is_blank(application_status):
            reason_text = " ".join(
                to_list(
                    first_value(
                        plan_row.get("decision_reasons"),
                        reviewed.get("decision_reasons_json"),
                    )
                )
            ).casefold()
            if "closed" in reason_text or "old scheme" in reason_text:
                application_status = "CLOSED"
            else:
                application_status = "STATUS_UNVERIFIED"

        funding_container = deep_find(
            payload,
            ["funding_amount", "funding", "financial_support"],
        )
        if not isinstance(funding_container, dict):
            funding_container = {}

        funding_minimum = first_value(
            direct("funding_minimum"),
            funding_container.get("minimum"),
            attribute_values(attrs, master_id, ["funding_minimum", "minimum_funding"]),
        )
        funding_maximum = first_value(
            direct("funding_maximum"),
            funding_container.get("maximum"),
            attribute_values(attrs, master_id, ["funding_maximum", "maximum_funding"]),
        )

        guideline_urls = collect_urls(
            deep_find(
                payload,
                [
                    "guideline_urls",
                    "guidelines",
                    "manual_urls",
                    "scheme_guidelines",
                    "documents_urls",
                ],
            )
        )

        all_urls = dedupe(
            [
                url
                for url in [
                    safe_url(direct("official_page_url", "final_url", "best_available_url")),
                    safe_url(direct("application_url", "apply_url")),
                ]
                if url
            ]
            + guideline_urls
            + source_urls.get(master_id, [])
            + collect_urls(deep_find(payload, ["source_evidence", "sources", "references"]))
        )
        pdf_urls = [url for url in all_urls if ".pdf" in url.casefold()]
        guideline_urls = dedupe(guideline_urls + pdf_urls)

        objectives = detail_list(
            ["objectives", "objective", "purpose", "description", "overview"]
        )
        eligibility = detail_list(
            ["eligibility", "eligibility_criteria", "who_can_apply"]
        )
        benefits = detail_list(
            ["benefits", "support", "assistance", "financial_assistance"]
        )
        application_process = detail_list(
            ["application_process", "how_to_apply", "application_steps"]
        )
        required_documents = detail_list(
            ["required_documents", "documents_required", "documents"]
        )
        beneficiaries = detail_list(
            ["target_beneficiaries", "beneficiaries", "target_group"]
        )
        startup_stage = detail_list(["startup_stage", "startup_stages"])
        sectors = detail_list(["sector", "sectors"])
        contacts_list = detail_list(["contact_details", "contacts", "contact"])
        contacts_list = dedupe(contacts_list + contacts.get(master_id, []))

        short_description = first_value(
            objectives[0] if objectives else None,
            benefits[0] if benefits else None,
            f"{label(direct('programme_status'))}.",
        )

        record = {
            "master_id": master_id,
            "scheme_name": scheme_name,
            "short_name": direct("short_name"),
            "source": direct("source"),
            "ministry": direct("ministry"),
            "department": direct("department"),
            "implementing_agency": direct("implementing_agency"),
            "catalogue_inclusion": first_value(
                plan_row.get("catalogue_inclusion"), "INCLUDED"
            ),
            "catalogue_section": first_value(
                plan_row.get("catalogue_section"), "SCHEMES_AND_PROGRAMMES"
            ),
            "record_kind": first_value(
                plan_row.get("normalized_record_kind"),
                direct("record_kind"),
                "SCHEME_OR_PROGRAMME",
            ),
            "programme_status": direct("programme_status"),
            "application_status": application_status,
            "opening_date": direct("opening_date"),
            "closing_date": direct("closing_date"),
            "official_page_url": safe_url(
                direct("official_page_url", "final_url", "best_available_url")
            ),
            "application_url": safe_url(direct("application_url", "apply_url")),
            "currency": first_value(direct("currency"), funding_container.get("currency"), "INR"),
            "funding_minimum": funding_minimum,
            "funding_maximum": funding_maximum,
            "geographic_scope": direct("geographic_scope"),
            "objectives": objectives,
            "eligibility": eligibility,
            "benefits": benefits,
            "application_process": application_process,
            "required_documents": required_documents,
            "beneficiaries": beneficiaries,
            "startup_stage": startup_stage,
            "sectors": sectors,
            "contacts": contacts_list,
            "guideline_urls": guideline_urls,
            "reference_urls": all_urls,
            "short_description": str(short_description),
            "normalization_disposition": plan_row.get("normalization_disposition"),
            "publication_recommendation": plan_row.get("publication_recommendation"),
            "review_status": direct("review_status"),
            "validation_score": direct("validation_score"),
        }

        searchable_values = [
            record["scheme_name"],
            record["source"],
            record["ministry"],
            record["department"],
            record["implementing_agency"],
            record["catalogue_section"],
            record["application_status"],
            record["programme_status"],
            record["short_description"],
            *record["beneficiaries"],
            *record["startup_stage"],
            *record["sectors"],
            *record["eligibility"],
            *record["benefits"],
        ]
        record["search_blob"] = " ".join(
            str(value) for value in searchable_values if not is_blank(value)
        ).casefold()
        records.append(record)

    frame = pd.DataFrame(records)
    if not frame.empty:
        frame = frame.sort_values(
            by=["catalogue_section", "scheme_name"],
            kind="stable",
        ).reset_index(drop=True)

    metadata = {
        "database_path": str(DATABASE_PATH),
        "normalization_path": str(NORMALIZATION_PATH),
        "normalization_used": NORMALIZATION_PATH.exists(),
        "staging_count": len(staging),
        "review_count": len(review),
        "version": APP_VERSION,
    }
    return frame, metadata


def status_badge_class(status: Any) -> str:
    text = str(status or "").upper()
    if text == "OPEN" or "OPEN_FOR_APPLICATIONS" in text:
        return "badge badge-open"
    if "CLOSED" in text or "ARCHIVED" in text or "OLD" in text:
        return "badge badge-closed"
    return "badge badge-pending"


def render_list_section(title: str, items: list[str]) -> None:
    if not items:
        st.caption(f"{title}: Information not yet available.")
        return
    st.markdown(f"**{title}**")
    for item in items[:12]:
        st.markdown(f"- {item}")
    if len(items) > 12:
        st.caption(f"{len(items) - 12} additional item(s) are available in the source data.")


def markdown_link(label_text: str, url: str) -> str:
    return f"[{label_text}]({url})"


try:
    catalogue, metadata = load_catalogue()
except Exception as exc:
    st.error("The public catalogue could not be loaded.")
    st.exception(exc)
    st.stop()


st.markdown(
    """
    <div class="ssip-hero">
        <h1>Startup Scheme Intelligence Platform</h1>
        <p>
            Discover government schemes, grants, programmes, challenges and
            support opportunities for startups, innovators, researchers and institutions.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

if catalogue.empty:
    st.warning("No catalogue records are currently available.")
    st.stop()

all_records = catalogue.copy()
scheme_count = int(
    all_records["record_kind"].astype(str).str.upper().eq("SCHEME_OR_PROGRAMME").sum()
)
open_count = int(
    all_records["application_status"]
    .astype(str)
    .str.upper()
    .str.contains(r"(^OPEN$|OPEN_FOR_APPLICATIONS)", regex=True)
    .sum()
)
agency_series = all_records["department"].where(
    all_records["department"].astype(str).str.strip() != "",
    all_records["source"],
)
agency_count = int(
    agency_series.replace({"None": "", "nan": ""}).astype(str).str.strip().replace("", pd.NA).dropna().nunique()
)

metric_columns = st.columns(4)
metric_columns[0].metric("Catalogue records", len(all_records))
metric_columns[1].metric("Schemes & programmes", scheme_count)
metric_columns[2].metric("Open opportunities", open_count)
metric_columns[3].metric("Departments / sources", agency_count)

st.markdown(
    """
    <div class="ssip-note">
        <strong>Catalogue view:</strong> closed and historical records remain visible for
        reference. The application-status badge tells users whether an opportunity is
        currently open, closed or requires verification.
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Find schemes")

    search_text = st.text_input(
        "Search",
        placeholder="Scheme, department, sector, benefit…",
    ).strip().casefold()

    section_options = sorted(
        [
            value
            for value in all_records["catalogue_section"].dropna().astype(str).unique()
            if value.strip()
        ]
    )
    selected_sections = st.multiselect(
        "Catalogue section",
        options=section_options,
        format_func=label,
    )

    source_options = sorted(
        [
            value
            for value in all_records["source"].dropna().astype(str).unique()
            if value.strip()
        ]
    )
    selected_sources = st.multiselect("Source / agency", options=source_options)

    status_options = sorted(
        [
            value
            for value in all_records["application_status"].dropna().astype(str).unique()
            if value.strip()
        ]
    )
    selected_statuses = st.multiselect(
        "Application status",
        options=status_options,
        format_func=label,
    )

    include_archived = st.checkbox(
        "Include archived / historical records",
        value=True,
    )
    include_pending = st.checkbox(
        "Include records requiring verification",
        value=True,
    )

    st.divider()
    st.caption(f"SSIP public catalogue {APP_VERSION}")
    st.caption(f"Database records in staging: {metadata['staging_count']}")
    if st.button("Refresh catalogue data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


filtered = all_records.copy()

if search_text:
    filtered = filtered[
        filtered["search_blob"].astype(str).str.contains(
            re.escape(search_text),
            regex=True,
            na=False,
        )
    ]

if selected_sections:
    filtered = filtered[filtered["catalogue_section"].isin(selected_sections)]

if selected_sources:
    filtered = filtered[filtered["source"].isin(selected_sources)]

if selected_statuses:
    filtered = filtered[filtered["application_status"].isin(selected_statuses)]

if not include_archived:
    filtered = filtered[
        filtered["catalogue_inclusion"].astype(str).str.upper() != "ARCHIVED"
    ]

if not include_pending:
    filtered = filtered[
        filtered["catalogue_inclusion"].astype(str).str.upper()
        != "PENDING_REVALIDATION"
    ]

result_header, result_sort = st.columns([3, 1])
with result_header:
    st.subheader(f"{len(filtered)} matching record(s)")
with result_sort:
    sort_choice = st.selectbox(
        "Sort",
        [
            "Scheme name",
            "Application status",
            "Department / source",
            "Closing date",
        ],
        label_visibility="collapsed",
    )

if sort_choice == "Scheme name":
    filtered = filtered.sort_values("scheme_name", kind="stable")
elif sort_choice == "Application status":
    filtered = filtered.sort_values(
        ["application_status", "scheme_name"], kind="stable"
    )
elif sort_choice == "Department / source":
    filtered = filtered.assign(
        _sort_agency=filtered["department"].where(
            filtered["department"].astype(str).str.strip() != "",
            filtered["source"],
        )
    ).sort_values(["_sort_agency", "scheme_name"], kind="stable")
else:
    filtered = filtered.assign(
        _sort_date=pd.to_datetime(filtered["closing_date"], errors="coerce")
    ).sort_values(["_sort_date", "scheme_name"], na_position="last", kind="stable")

if filtered.empty:
    st.info("No records match the selected filters.")
    st.stop()

page_size = st.selectbox(
    "Records per page",
    [10, 20, 50],
    index=0,
    key="records_per_page",
)
page_count = max(1, math.ceil(len(filtered) / page_size))
page_number = st.selectbox(
    "Page",
    list(range(1, page_count + 1)),
    format_func=lambda value: f"Page {value} of {page_count}",
    key=f"catalogue_page_{page_count}_{page_size}",
)
start = (page_number - 1) * page_size
page_records = filtered.iloc[start : start + page_size].to_dict(orient="records")

for record in page_records:
    title = html.escape(str(record["scheme_name"]))
    source = html.escape(str(first_value(record["department"], record["source"], "Government source")))
    description = html.escape(str(record["short_description"])[:420])
    status = label(record["application_status"])
    section = label(record["catalogue_section"])
    kind = label(record["record_kind"])
    status_class = status_badge_class(record["application_status"])

    st.markdown(
        f"""
        <div class="scheme-card">
            <h3>{title}</h3>
            <div>
                <span class="{status_class}">{html.escape(status)}</span>
                <span class="badge">{html.escape(section)}</span>
                <span class="badge">{html.escape(kind)}</span>
            </div>
            <p>{description}</p>
            <div class="small-muted">{source}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("View scheme details"):
        summary_columns = st.columns(3)
        summary_columns[0].markdown(
            f"**Ministry**  \n{first_value(record['ministry'], 'Not specified')}"
        )
        summary_columns[1].markdown(
            f"**Department / Agency**  \n"
            f"{first_value(record['department'], record['implementing_agency'], record['source'], 'Not specified')}"
        )
        summary_columns[2].markdown(
            f"**Geographic scope**  \n{first_value(record['geographic_scope'], 'Not specified')}"
        )

        date_columns = st.columns(3)
        date_columns[0].markdown(
            f"**Application status**  \n{label(record['application_status'])}"
        )
        date_columns[1].markdown(
            f"**Opening date**  \n{format_date(record['opening_date'])}"
        )
        date_columns[2].markdown(
            f"**Closing date**  \n{format_date(record['closing_date'])}"
        )

        funding_columns = st.columns(2)
        funding_columns[0].markdown(
            f"**Minimum support**  \n"
            f"{format_money(record['funding_minimum'], record['currency'])}"
        )
        funding_columns[1].markdown(
            f"**Maximum support**  \n"
            f"{format_money(record['funding_maximum'], record['currency'])}"
        )

        if record["objectives"]:
            render_list_section("Purpose / objectives", record["objectives"])
        render_list_section("Who can apply / eligibility", record["eligibility"])
        render_list_section("Benefits / support", record["benefits"])
        render_list_section("Application process", record["application_process"])
        render_list_section("Documents required", record["required_documents"])

        if record["beneficiaries"] or record["startup_stage"] or record["sectors"]:
            tag_columns = st.columns(3)
            with tag_columns[0]:
                render_list_section("Beneficiaries", record["beneficiaries"])
            with tag_columns[1]:
                render_list_section("Startup stage", record["startup_stage"])
            with tag_columns[2]:
                render_list_section("Sectors", record["sectors"])

        if record["contacts"]:
            render_list_section("Contact information", record["contacts"])

        st.markdown("**Official links**")
        link_items: list[str] = []

        if record["official_page_url"]:
            link_items.append(
                markdown_link("Official scheme / programme page ↗", record["official_page_url"])
            )

        if record["application_url"]:
            link_items.append(
                markdown_link("Apply / application portal ↗", record["application_url"])
            )

        for index, url in enumerate(record["guideline_urls"][:5], start=1):
            link_items.append(markdown_link(f"Guideline / manual {index} ↗", url))

        additional_references = [
            url
            for url in record["reference_urls"]
            if url not in {
                record["official_page_url"],
                record["application_url"],
                *record["guideline_urls"],
            }
        ]
        for index, url in enumerate(additional_references[:5], start=1):
            link_items.append(markdown_link(f"Official reference {index} ↗", url))

        if link_items:
            for item in dedupe(link_items):
                st.markdown(f"- {item}")
        else:
            st.caption("Official link information is not yet available.")

        if str(record["catalogue_inclusion"]).upper() == "PENDING_REVALIDATION":
            st.warning(
                "This record requires status or evidence verification. "
                "Use the official source before making an application decision."
            )
        elif str(record["catalogue_inclusion"]).upper() == "ARCHIVED":
            st.info(
                "This is an archived or historical record retained for reference."
            )

st.caption(
    "Information is compiled from official government sources. "
    "Applicants should confirm current eligibility, deadlines and application instructions on the official page."
)
