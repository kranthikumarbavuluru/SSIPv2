from __future__ import annotations

import csv
import json
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/departments/meity/v3_4_3_8_0_1"
)
MANIFEST_PATH = (
    OUTPUT_DIR
    / "meity_candidate_purification_manifest_v3_4_3_8_0_1.json"
)
REVIEW_PATH = (
    OUTPUT_DIR
    / "meity_purified_admin_review_v3_4_3_8_0_1.csv"
)
DOCUMENT_PATH = (
    OUTPUT_DIR
    / "meity_supporting_documents_v3_4_3_8_0_1.csv"
)
EXCLUDED_PATH = (
    OUTPUT_DIR
    / "meity_excluded_error_pages_v3_4_3_8_0_1.csv"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8-sig")
    )


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY v3.4.3.8.0.1 Purified Review",
        page_icon="🧹",
        layout="wide",
    )

    manifest = load_manifest()
    review_rows = read_csv(REVIEW_PATH)
    document_rows = read_csv(DOCUMENT_PATH)
    excluded_rows = read_csv(EXCLUDED_PATH)

    st.title("MeitY Purified Intelligence Review")
    st.caption(
        "Candidate purification, identity consolidation and date-role repair. "
        "Preview only: no database write and no publication."
    )

    if not manifest:
        st.error(
            "Run the v3.4.3.8.0.1 purification before opening this workspace."
        )
        return

    metrics = (
        ("Source candidates", manifest.get("source_candidate_count", 0)),
        ("Programme families", manifest.get("purified_programme_family_count", 0)),
        ("Calls & challenges", manifest.get("purified_call_challenge_count", 0)),
        ("Historical events", manifest.get("purified_historical_event_count", 0)),
        ("Supporting documents", manifest.get("supporting_document_count", 0)),
        ("Excluded/error", manifest.get("excluded_error_page_count", 0)),
        ("Identity review", manifest.get("identity_role_review_count", 0)),
    )
    columns = st.columns(len(metrics))
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)

    st.success(
        "Every source candidate is partitioned exactly once. Generic portal "
        "pages, Page Not Found, Access Denied, raw filenames and footer dates "
        "cannot become public programme identities."
    )

    tab_review, tab_documents, tab_excluded = st.tabs(
        [
            "Purified Admin Review",
            "Supporting Documents",
            "Excluded & Error Pages",
        ]
    )

    with tab_review:
        if not review_rows:
            st.warning("No purified Admin-review records were generated.")
            return

        dispositions = sorted(
            {
                row.get("disposition", "")
                for row in review_rows
                if row.get("disposition")
            }
        )
        types = sorted(
            {
                row.get("entity_type", "")
                for row in review_rows
                if row.get("entity_type")
            }
        )

        f1, f2, f3 = st.columns([2, 1, 1])
        keyword = f1.text_input(
            "Search",
            placeholder="GENESIS, SAMRIDH, challenge, accelerator…",
            key="purified_search",
        ).strip().casefold()
        disposition = f2.selectbox(
            "Disposition",
            ["ALL", *dispositions],
            key="purified_disposition",
        )
        entity_type = f3.selectbox(
            "Entity type",
            ["ALL", *types],
            key="purified_entity_type",
        )

        visible = []
        for row in review_rows:
            haystack = " ".join(str(value) for value in row.values()).casefold()
            if keyword and keyword not in haystack:
                continue
            if disposition != "ALL" and row.get("disposition") != disposition:
                continue
            if entity_type != "ALL" and row.get("entity_type") != entity_type:
                continue
            visible.append(row)

        st.write(f"**{len(visible)} matching purified record(s)**")
        if not visible:
            return

        left, centre, right = st.columns([1.1, 1.45, 1.45])

        with left:
            selected_index = st.radio(
                "Select purified record",
                range(len(visible)),
                format_func=lambda index: (
                    visible[index].get("canonical_name")
                    or visible[index].get("original_canonical_name")
                    or visible[index].get("source_candidate_id")
                ),
                label_visibility="collapsed",
                key="purified_selected_index",
            )
            selected = visible[selected_index]

        with centre:
            st.subheader(
                selected.get("canonical_name")
                or selected.get("original_canonical_name")
                or "Unnamed record"
            )
            st.write("**Disposition:**", selected.get("disposition"))
            st.write("**Entity type:**", selected.get("entity_type"))
            st.write(
                "**Source candidates merged:**",
                selected.get("source_candidate_count") or "1",
            )
            st.write("**Source titles:**", selected.get("source_titles") or selected.get("original_canonical_name"))
            st.write("**Existing master:**", selected.get("existing_master_id") or "New / unresolved")
            st.write("**Parent resolution:**", selected.get("parent_resolution") or "Not applicable")
            url = selected.get("official_page_url", "")
            if url:
                st.link_button("Open official source", url)

        with right:
            st.subheader("Evidence and controls")
            st.write(selected.get("decision_reason", ""))
            st.text_area(
                "Evidence excerpt",
                selected.get("evidence_excerpt", ""),
                height=220,
                disabled=True,
                key="purified_evidence_excerpt",
            )
            st.write("**Opening date:**", selected.get("opening_date") or "Not proven")
            st.write("**Closing date:**", selected.get("closing_date") or "Not proven")
            st.write("**Publication eligible:**", selected.get("publication_eligible"))
            st.write("**Apply action allowed:**", selected.get("apply_action_allowed"))
            flags = [
                value
                for value in selected.get("quality_flags", "").split(";")
                if value
            ]
            if flags:
                st.warning("Quality flags: " + ", ".join(flags))

        with st.expander("Complete purified record", expanded=False):
            st.json(selected)

    with tab_documents:
        st.write(
            f"**{len(document_rows)} supporting document record(s)** — "
            "these are evidence, not programme titles."
        )
        if document_rows:
            role_filter = st.selectbox(
                "Document role",
                [
                    "ALL",
                    *sorted(
                        {
                            row.get("document_role", "")
                            for row in document_rows
                            if row.get("document_role")
                        }
                    ),
                ],
                key="document_role_filter",
            )
            visible_documents = [
                row
                for row in document_rows
                if role_filter == "ALL"
                or row.get("document_role") == role_filter
            ]
            st.dataframe(
                visible_documents,
                use_container_width=True,
                hide_index=True,
            )

    with tab_excluded:
        st.write(
            f"**{len(excluded_rows)} rejected page record(s)** — "
            "retained for audit, never treated as schemes or calls."
        )
        if excluded_rows:
            st.dataframe(
                excluded_rows,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.caption(
        "Manifest signature: "
        + str(manifest.get("signature", ""))
        + " · Source signature: "
        + str(manifest.get("source_manifest_signature", ""))
    )


if __name__ == "__main__":
    main()
