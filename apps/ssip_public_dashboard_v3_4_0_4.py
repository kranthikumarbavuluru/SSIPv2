#!/usr/bin/env python3
"""SSIP public dashboard preview for the DST v3.4.0.4 publication catalogue."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

VERSION = "3.4.0.4"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "departments" / "dst" / "v3_4_0_4" / "ssip_public_preview_v3_4_0_4.db"

LIGHT_THEME_CSS = """
  :root {
    --ssip-purple: #5b2a86;
    --ssip-soft: #f4effa;
    --ssip-border: #e2d8ee;
    --ssip-surface: #ffffff;
    --ssip-surface-raised: #ffffff;
    --ssip-text: #21172b;
    --ssip-muted: #665d6e;
  }
  .stApp {
    background: #fbfafc;
    color: var(--ssip-text);
  }
  header[data-testid="stHeader"],
  div[data-testid="stToolbar"] {
    background: #ffffff;
    color: var(--ssip-text);
  }
  section[data-testid="stSidebar"] {
    background: #ffffff;
    border-right: 1px solid var(--ssip-border);
  }
  section[data-testid="stSidebar"] * { color: var(--ssip-text); }
  .entity-card,
  div[data-testid="stMetric"] {
    background: var(--ssip-surface-raised);
    border-color: var(--ssip-border);
  }
  .entity-title,
  .stApp h1,
  .stApp h2,
  .stApp h3,
  .stApp h4,
  .stApp p,
  .stApp label,
  .stApp [data-testid="stMetricLabel"] {
    color: var(--ssip-text) !important;
    -webkit-text-fill-color: var(--ssip-text) !important;
  }
  .ssip-hero h1,
  .ssip-hero p { color: #ffffff !important; -webkit-text-fill-color: #ffffff !important; }
  .entity-meta,
  .footer-note,
  .stApp [data-testid="stCaptionContainer"],
  .stApp [data-testid="stMetricDelta"] {
    color: var(--ssip-muted) !important;
    -webkit-text-fill-color: var(--ssip-muted) !important;
  }
  .status-pill,
  .notice {
    background: var(--ssip-soft);
    color: var(--ssip-purple);
  }
  div[data-baseweb="input"],
  div[data-baseweb="select"] > div,
  div[data-testid="stTextInputRootElement"] {
    background: var(--ssip-surface) !important;
    border-color: var(--ssip-border) !important;
  }
  div[data-baseweb="input"] input,
  div[data-baseweb="select"] input,
  input[type="text"] {
    background: var(--ssip-surface) !important;
    color: var(--ssip-text) !important;
    -webkit-text-fill-color: var(--ssip-text) !important;
  }
  div[role="listbox"] {
    background: var(--ssip-surface-raised) !important;
    color: var(--ssip-text) !important;
  }
  div[data-testid="stButton"] > button,
  div[data-testid="stLinkButton"] > a {
    background: #ffffff;
    border-color: #bda9d1;
    color: var(--ssip-purple) !important;
  }
  div[data-testid="stButton"] > button:hover,
  div[data-testid="stLinkButton"] > a:hover {
    background: #f4effa;
    border-color: var(--ssip-purple);
  }
  label[data-rac] > div:first-of-type {
    background: #ded4ea !important;
    border: 1px solid #bda9d1 !important;
  }
  label[data-rac][data-selected="true"] > div:first-of-type {
    background: var(--ssip-purple) !important;
    border-color: var(--ssip-purple) !important;
  }
  hr { border-color: var(--ssip-border) !important; }
"""

DARK_THEME_CSS = """
  :root {
    --ssip-purple: #c7a8f6;
    --ssip-soft: #251d35;
    --ssip-border: #4b3c63;
    --ssip-surface: #171321;
    --ssip-surface-raised: #201a2d;
    --ssip-text: #f4effb;
    --ssip-muted: #c4b9d0;
  }
  .stApp {
    background: linear-gradient(180deg, #0f0c16 0%, #171321 48%, #100d17 100%);
    color: var(--ssip-text);
  }
  section[data-testid="stSidebar"] {
    background: #15111f;
    border-right: 1px solid var(--ssip-border);
  }
  section[data-testid="stSidebar"] * { color: var(--ssip-text); }
  .ssip-hero {
    background: linear-gradient(135deg, #251443, #4d2677);
    box-shadow: 0 12px 30px rgba(0, 0, 0, .34);
  }
  .entity-card,
  div[data-testid="stMetric"] {
    background: var(--ssip-surface-raised);
    border-color: var(--ssip-border);
    box-shadow: 0 8px 20px rgba(0, 0, 0, .24);
  }
  .entity-title,
  .stApp h1,
  .stApp h2,
  .stApp h3,
  .stApp h4,
  .stApp p,
  .stApp label,
  .stApp [data-testid="stMetricLabel"] {
    color: var(--ssip-text) !important;
    -webkit-text-fill-color: var(--ssip-text) !important;
  }
  .entity-meta,
  .footer-note,
  .stApp [data-testid="stCaptionContainer"],
  .stApp [data-testid="stMetricDelta"] {
    color: var(--ssip-muted) !important;
    -webkit-text-fill-color: var(--ssip-muted) !important;
  }
  .status-pill,
  .notice {
    background: var(--ssip-soft);
    border-color: var(--ssip-purple);
    color: #eadcff;
  }
  .notice { border-left-color: var(--ssip-purple); }
  div[data-baseweb="input"],
  div[data-baseweb="select"] > div,
  div[data-testid="stTextInputRootElement"] {
    background: var(--ssip-surface) !important;
    border-color: var(--ssip-border) !important;
  }
  div[data-baseweb="input"] input,
  div[data-baseweb="select"] input,
  input[type="text"] {
    background: var(--ssip-surface) !important;
    color: var(--ssip-text) !important;
    -webkit-text-fill-color: var(--ssip-text) !important;
  }
  div[role="listbox"] {
    background: var(--ssip-surface-raised) !important;
    color: var(--ssip-text) !important;
  }
  div[data-testid="stButton"] > button,
  div[data-testid="stLinkButton"] > a {
    background: #302046;
    border-color: #76549a;
    color: #f4effb !important;
  }
  div[data-testid="stButton"] > button:hover,
  div[data-testid="stLinkButton"] > a:hover {
    background: #432860;
    border-color: #b98ced;
  }
  label[data-rac] > div:first-of-type {
    background: #3f3350 !important;
    border: 1px solid #70578d !important;
  }
  label[data-rac][data-selected="true"] > div:first-of-type {
    background: #b98ced !important;
    border-color: #d8bcff !important;
  }
  hr { border-color: var(--ssip-border) !important; }
"""

st.set_page_config(
    page_title="SSIP — Government Schemes",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "ssip_dark_mode" not in st.session_state:
    st.session_state["ssip_dark_mode"] = False
dark_mode = bool(st.session_state["ssip_dark_mode"])

st.markdown(
    """
    <style>
      :root { --ssip-purple:#5b2a86; --ssip-soft:#f4effa; --ssip-border:#e2d8ee; }
      .stApp { background: #fbfafc; }
      .ssip-hero {
        padding: 1.35rem 1.55rem; border-radius: 18px;
        background: linear-gradient(135deg, #3f1f67, #7142a2);
        color: white; margin-bottom: 1rem;
        box-shadow: 0 10px 30px rgba(63,31,103,.16);
      }
      .ssip-hero h1 { margin:0; font-size:2rem; }
      .ssip-hero p { margin:.4rem 0 0; opacity:.94; }
      .entity-card {
        background:white; border:1px solid var(--ssip-border); border-radius:14px;
        padding:1rem 1.05rem; margin:.5rem 0; box-shadow:0 3px 12px rgba(60,40,80,.05);
      }
      .entity-type { font-size:.78rem; font-weight:700; color:var(--ssip-purple); letter-spacing:.05em; }
      .entity-title { font-size:1.05rem; font-weight:750; color:#21172b; margin:.2rem 0 .35rem; }
      .entity-meta { color:#665d6e; font-size:.88rem; }
      .status-pill {
        display:inline-block; padding:.25rem .55rem; border-radius:999px;
        background:var(--ssip-soft); color:var(--ssip-purple); font-size:.78rem; font-weight:650;
      }
      .notice {
        border-left:4px solid var(--ssip-purple); background:var(--ssip-soft);
        padding:.8rem 1rem; border-radius:8px; margin:.6rem 0 1rem;
      }
      div[data-testid="stMetric"] { background:white; border:1px solid var(--ssip-border); padding:.7rem; border-radius:12px; }
      .footer-note { color:#776d80; font-size:.8rem; margin-top:1.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(f"<style>{LIGHT_THEME_CSS}</style>", unsafe_allow_html=True)

if dark_mode:
    st.markdown(f"<style>{DARK_THEME_CSS}</style>", unsafe_allow_html=True)


def valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


@st.cache_data(show_spinner=False)
def load_data(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame(), pd.DataFrame()
    con = sqlite3.connect(path)
    try:
        catalogue = pd.read_sql_query(
            "SELECT * FROM publication_catalogue ORDER BY entity_type, scheme_name", con
        )
        department = pd.read_sql_query("SELECT * FROM departments", con)
    finally:
        con.close()
    return catalogue, department


st.markdown(
    """
    <div class="ssip-hero">
      <h1>Startup Scheme Intelligence Platform</h1>
      <p>Verified government scheme and programme identities with direct official references.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Appearance")
    st.toggle(
        "Dark mode",
        key="ssip_dark_mode",
        help="Switch between light and dark appearance.",
    )
    st.divider()
    st.header("Browse schemes")
    configured_db = st.text_input("Publication database", value=str(DEFAULT_DB), help="Generated by the v3.4.0.4 builder.")

catalogue, department_df = load_data(configured_db)
if catalogue.empty:
    st.error("The DST publication database is not available yet.")
    st.code(
        "python .\\scripts\\dst_canonical_publication_builder_v3_4_0_4.py "
        "--project-root \"D:\\WebSite\\DASHBOARD\\Code\\SSIP\" --strict"
    )
    st.stop()

for column in catalogue.columns:
    catalogue[column] = catalogue[column].fillna("").astype(str)

with st.sidebar:
    search = st.text_input("Search", placeholder="Scheme, programme, fellowship…")
    entity_options = ["All"] + sorted(catalogue["entity_type"].dropna().unique().tolist())
    entity_filter = st.selectbox("Type", entity_options)
    status_options = ["All"] + sorted(catalogue["public_status"].dropna().unique().tolist())
    status_filter = st.selectbox("Status", status_options)
    st.caption(f"Dataset version: SSIP {VERSION}")

filtered = catalogue.copy()
if search.strip():
    needle = search.strip().casefold()
    searchable = (
        filtered["scheme_name"] + " " + filtered["official_abbreviation"] + " " +
        filtered["objective"] + " " + filtered["department"]
    ).str.casefold()
    filtered = filtered[searchable.str.contains(needle, regex=False)]
if entity_filter != "All":
    filtered = filtered[filtered["entity_type"] == entity_filter]
if status_filter != "All":
    filtered = filtered[filtered["public_status"] == status_filter]

scheme_count = int((catalogue["entity_type"] == "SCHEME").sum())
programme_count = int((catalogue["entity_type"] == "PROGRAMME").sum())
open_count = int(catalogue["application_status"].str.contains("OPEN", case=False, na=False).sum())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Verified identities", len(catalogue))
col2.metric("Schemes", scheme_count)
col3.metric("Programmes", programme_count)
col4.metric("Applications open", open_count)

st.markdown(
    """
    <div class="notice">
      This DST preview shows <b>verified permanent identities</b>. Eligibility, benefits,
      documents and active application windows are displayed only when verified; missing
      details are intentionally marked as pending rather than inferred.
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns([1.35, 1], gap="large")
with left:
    st.subheader(f"Department of Science and Technology ({len(filtered)} records)")
    if filtered.empty:
        st.info("No records match the selected filters.")
    else:
        selected_default = filtered.iloc[0]["master_id"]
        for _, row in filtered.iterrows():
            abbreviation = f" ({row['official_abbreviation']})" if row["official_abbreviation"] else ""
            st.markdown(
                f"""
                <div class="entity-card">
                  <div class="entity-type">{row['entity_type']}</div>
                  <div class="entity-title">{row['scheme_name']}{abbreviation}</div>
                  <div class="entity-meta">{row['department']}</div>
                  <div style="margin-top:.55rem"><span class="status-pill">{row['public_status']}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("View details", key=f"view_{row['master_id']}", use_container_width=True):
                    st.session_state["selected_master_id"] = row["master_id"]
            with c2:
                if valid_http_url(row["official_page_url"]):
                    st.link_button("Official page", row["official_page_url"], use_container_width=True)
        if "selected_master_id" not in st.session_state:
            st.session_state["selected_master_id"] = selected_default

with right:
    st.subheader("Scheme details")
    selected_id = st.session_state.get("selected_master_id")
    selected = catalogue[catalogue["master_id"] == selected_id]
    if selected.empty:
        selected = filtered.head(1)
    if not selected.empty:
        row = selected.iloc[0]
        st.markdown(f"### {row['scheme_name']}")
        st.caption(f"{row['entity_type'].title()} · {row['ministry']}")
        st.markdown(f"**Status:** {row['public_status']}")
        st.markdown(f"**Application status:** {row['application_status'].replace('_', ' ').title()}")

        detail_fields = [
            ("Objective", "objective"),
            ("Eligibility", "eligibility"),
            ("Benefits", "benefits"),
            ("Funding", "funding_summary"),
            ("Application process", "application_process"),
            ("Required documents", "required_documents"),
            ("Contact", "contact_information"),
        ]
        for label, field in detail_fields:
            st.markdown(f"**{label}**")
            value = row[field].strip()
            st.write(value if value else "Not yet verified")

        st.markdown("**Official references**")
        if valid_http_url(row["official_page_url"]):
            st.link_button("Open official scheme page", row["official_page_url"], use_container_width=True)
        if valid_http_url(row["application_url"]):
            st.link_button("Open application portal", row["application_url"], use_container_width=True)
        if valid_http_url(row["guideline_url"]):
            st.link_button("Open guidelines", row["guideline_url"], use_container_width=True)
        st.caption(
            f"Identity verification: {row['verification_status'].replace('_', ' ').title()} · "
            f"Last verified: {row['last_verified_date']}"
        )

st.markdown(
    "<div class='footer-note'>SSIP public preview · No user registration · Official-source links only.</div>",
    unsafe_allow_html=True,
)
