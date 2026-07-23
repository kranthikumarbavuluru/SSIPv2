from __future__ import annotations

import csv
import json
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/departments/meity/v3_4_3_8_0"
)
MANIFEST_PATH = (
    OUTPUT_DIR
    / "meity_complete_intelligence_manifest_v3_4_3_8_0.json"
)
REVIEW_PATH = (
    OUTPUT_DIR
    / "meity_admin_review_preview_v3_4_3_8_0.csv"
)


def load_rows() -> list[dict[str, str]]:
    if not REVIEW_PATH.exists():
        return []
    with REVIEW_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8-sig"
        )
    )


def main() -> None:
    st.set_page_config(
        page_title=(
            "SSIP MeitY v3.4.3.8.0 Preview"
        ),
        page_icon="🧭",
        layout="wide",
    )

    manifest = load_manifest()
    rows = load_rows()

    st.title(
        "MeitY Complete Intelligence Preview"
    )
    st.caption(
        "Preview-only workspace. No database "
        "write and no publication action."
    )

    if not manifest:
        st.error(
            "Run the v3.4.3.8.0 live preview "
            "before opening this workspace."
        )
        return

    metric_columns = st.columns(6)
    metrics = (
        (
            "Programme candidates",
            manifest.get(
                "programme_candidate_count",
                0,
            ),
        ),
        (
            "Calls & challenges",
            manifest.get(
                "current_call_challenge_candidate_count",
                0,
            ),
        ),
        (
            "Historical/results",
            manifest.get(
                "historical_call_result_count",
                0,
            ),
        ),
        (
            "Relationship review",
            manifest.get(
                "relationship_review_count",
                0,
            ),
        ),
        (
            "Admin review",
            manifest.get(
                "admin_review_count",
                0,
            ),
        ),
        (
            "Verified open",
            manifest.get(
                "verified_open_count",
                0,
            ),
        ),
    )
    for column, (label, value) in zip(
        metric_columns,
        metrics,
    ):
        column.metric(label, value)

    st.info(
        "GENESIS and SASACT are reconciled "
        "against the existing database. "
        "New programmes, calls, challenges, "
        "results and relationship questions "
        "remain proposals until Admin action."
    )

    if not rows:
        st.warning(
            "The preview produced no Admin-review "
            "records. Inspect the fetch log and "
            "network diagnostics."
        )
        return

    queues = sorted(
        {
            row.get("admin_queue", "")
            for row in rows
            if row.get("admin_queue")
        }
    )
    types = sorted(
        {
            row.get("entity_type", "")
            for row in rows
            if row.get("entity_type")
        }
    )
    statuses = sorted(
        {
            row.get(
                "application_status",
                "",
            )
            for row in rows
            if row.get(
                "application_status"
            )
        }
    )

    f1, f2, f3, f4 = st.columns(
        [2, 1, 1, 1]
    )
    keyword = f1.text_input(
        "Search",
        placeholder=(
            "SAMRIDH, TIDE, challenge, cohort…"
        ),
    ).strip().casefold()
    selected_queue = f2.selectbox(
        "Queue",
        ["ALL", *queues],
    )
    selected_type = f3.selectbox(
        "Entity type",
        ["ALL", *types],
    )
    selected_status = f4.selectbox(
        "Status",
        ["ALL", *statuses],
    )

    visible: list[dict[str, str]] = []
    for row in rows:
        haystack = " ".join(
            str(value)
            for value in row.values()
        ).casefold()
        if keyword and keyword not in haystack:
            continue
        if (
            selected_queue != "ALL"
            and row.get("admin_queue")
            != selected_queue
        ):
            continue
        if (
            selected_type != "ALL"
            and row.get("entity_type")
            != selected_type
        ):
            continue
        if (
            selected_status != "ALL"
            and row.get(
                "application_status"
            )
            != selected_status
        ):
            continue
        visible.append(row)

    st.write(
        f"**{len(visible)} matching "
        "preview record(s)**"
    )

    names = [
        (
            row.get("canonical_name")
            or row.get("candidate_id")
            or "Unnamed record"
        )
        for row in visible
    ]
    if not visible:
        return

    left, centre, right = st.columns(
        [1.1, 1.45, 1.45]
    )

    with left:
        selected_index = st.radio(
            "Select record",
            range(len(visible)),
            format_func=lambda index: (
                names[index]
            ),
            label_visibility="collapsed",
        )
        selected = visible[selected_index]

    with centre:
        st.subheader(
            selected.get(
                "canonical_name",
                "Unnamed record",
            )
        )
        st.write(
            "**Entity:**",
            selected.get("entity_type"),
        )
        st.write(
            "**Queue:**",
            selected.get("admin_queue"),
        )
        st.write(
            "**Status:**",
            selected.get(
                "application_status"
            ),
        )
        st.write(
            "**Startup relevance:**",
            selected.get(
                "startup_relevance"
            ),
        )
        st.write(
            "**Parent resolution:**",
            selected.get(
                "parent_resolution"
            ),
        )
        st.write(
            "**Parent programme:**",
            selected.get(
                "parent_scheme_name"
            )
            or "Not resolved",
        )
        st.write(
            "**Existing master ID:**",
            selected.get(
                "existing_master_id"
            )
            or "New candidate",
        )
        official_url = selected.get(
            "official_page_url",
            "",
        )
        if official_url:
            st.link_button(
                "Open official source",
                official_url,
            )

    with right:
        st.subheader("Evidence and controls")
        st.write(
            selected.get(
                "entity_reason",
                "",
            )
        )
        st.text_area(
            "Evidence excerpt",
            selected.get(
                "evidence_excerpt",
                "",
            ),
            height=220,
            disabled=True,
        )
        st.write(
            "**Opening date:**",
            selected.get(
                "opening_date"
            )
            or "Not verified",
        )
        st.write(
            "**Closing date:**",
            selected.get(
                "closing_date"
            )
            or "Not verified",
        )
        st.write(
            "**Apply action allowed:**",
            selected.get(
                "apply_action_allowed"
            ),
        )
        st.write(
            "**Publication eligible:**",
            selected.get(
                "publication_eligible"
            ),
        )
        flags = [
            value
            for value in selected.get(
                "quality_flags",
                "",
            ).split(";")
            if value
        ]
        if flags:
            st.warning(
                "Quality flags: "
                + ", ".join(flags)
            )

    with st.expander(
        "Complete preview record",
        expanded=False,
    ):
        st.json(selected)

    st.divider()
    st.caption(
        "Manifest signature: "
        + str(
            manifest.get(
                "signature",
                "",
            )
        )
    )


if __name__ == "__main__":
    main()
