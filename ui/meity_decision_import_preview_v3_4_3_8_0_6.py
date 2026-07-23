from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import streamlit as st

from services.meity_guided_decision_import_v3_4_3_8_0_6 import (
    run_decision_import,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_6"

SUMMARY_PATH = (
    OUTPUT_DIR / "meity_decision_import_summary_v3_4_3_8_0_6.json"
)
ACCEPTED_PATH = (
    OUTPUT_DIR / "meity_validated_admin_decisions_v3_4_3_8_0_6.csv"
)
REJECTED_PATH = (
    OUTPUT_DIR / "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
)
BRIDGE_PATH = (
    OUTPUT_DIR / "meity_admin_bridge_preview_v3_4_3_8_0_6.csv"
)
PLAN_PATH = (
    OUTPUT_DIR / "meity_signed_admin_bridge_plan_v3_4_3_8_0_6.json"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY Decision Import Preview",
        page_icon="📥",
        layout="wide",
    )

    st.title("MeitY Guided Decision Import")
    st.caption(
        "Upload the CSV downloaded from the guided review page. "
        "The system validates it and creates a read-only Admin-bridge preview."
    )

    st.info(
        "**This page does not update the database.** It checks signatures, "
        "allowed actions, selected children and required notes."
    )

    st.markdown("### Step 1 — Upload the decision worksheet")
    uploaded = st.file_uploader(
        "Choose the CSV downloaded from port 8511",
        type=["csv"],
        accept_multiple_files=False,
    )

    strict_mode = st.checkbox(
        "Block the whole plan when any row is invalid",
        value=True,
        help=(
            "Recommended. Invalid or stale decisions must be corrected in "
            "the guided review page before proceeding."
        ),
    )

    if uploaded is None:
        st.warning(
            "Complete at least one decision in the guided review page, "
            "download the worksheet, and upload it here."
        )
        return

    st.markdown("### Step 2 — Validate the worksheet")
    if st.button(
        "Validate decisions and create preview",
        type="primary",
        use_container_width=True,
    ):
        suffix = Path(uploaded.name).suffix or ".csv"
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temporary:
            temporary.write(uploaded.getvalue())
            temporary_path = Path(temporary.name)

        try:
            result = run_decision_import(
                PROJECT_ROOT,
                temporary_path,
                strict=strict_mode,
            )
            st.session_state["meity_import_result"] = result
        finally:
            temporary_path.unlink(missing_ok=True)

    result = st.session_state.get("meity_import_result")
    if not result:
        return

    accepted = read_csv(ACCEPTED_PATH)
    rejected = read_csv(REJECTED_PATH)
    bridge = read_csv(BRIDGE_PATH)

    st.markdown("### Step 3 — Review the validation result")
    metrics = st.columns(4)
    metrics[0].metric(
        "Worksheet rows",
        result.get("worksheet_row_count", 0),
    )
    metrics[1].metric(
        "Accepted decisions",
        result.get("accepted_decision_count", 0),
    )
    metrics[2].metric(
        "Rejected rows",
        result.get("rejected_decision_count", 0),
    )
    metrics[3].metric(
        "Plan status",
        result.get("plan_status", "UNKNOWN"),
    )

    if result.get("plan_status") == "READY_FOR_REVIEW":
        st.success(
            "The signed decisions passed validation. The Admin-bridge plan "
            "is ready for review, but it has not been applied."
        )
    elif result.get("plan_status") == "BLOCKED":
        st.error(
            "The plan is blocked. Correct every rejected row in the guided "
            "review page, download a new worksheet, and validate it again."
        )
    else:
        st.warning("No completed decisions were available for a plan.")

    tab_accepted, tab_rejected, tab_bridge = st.tabs(
        [
            "Accepted Decisions",
            "Rejected Rows",
            "Admin-Bridge Preview",
        ]
    )

    with tab_accepted:
        if accepted:
            st.dataframe(
                accepted,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No decisions were accepted.")

    with tab_rejected:
        if rejected:
            st.dataframe(
                rejected,
                use_container_width=True,
                hide_index=True,
            )
            st.warning(
                "Rejected rows never enter the Admin bridge."
            )
        else:
            st.success("No worksheet rows were rejected.")

    with tab_bridge:
        if bridge:
            simple_rows = [
                {
                    "Record": row.get("bundle_title", ""),
                    "Decision": row.get("admin_decision_label")
                    or row.get("admin_decision", ""),
                    "Proposed next action": (
                        row.get("bridge_action", "")
                        .replace("_", " ")
                        .title()
                    ),
                    "Selected records": row.get(
                        "selected_child_count",
                        "0",
                    ),
                    "Database action": row.get("database_action", ""),
                    "Publication action": row.get(
                        "publication_action",
                        "",
                    ),
                }
                for row in bridge
            ]
            st.dataframe(
                simple_rows,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No Admin-bridge actions were proposed.")

    st.markdown("### Plan controls")
    st.write(
        "**Decision plan signature:**",
        result.get("decision_plan_signature", ""),
    )
    st.write(
        "**Database write performed:**",
        result.get("database_write_performed", False),
    )
    st.write(
        "**Publication performed:**",
        result.get("publication_performed", False),
    )
    st.write(
        "**Admin bridge applied:**",
        result.get("admin_bridge_applied", False),
    )

    if PLAN_PATH.exists():
        st.download_button(
            "Download the signed Admin-bridge plan",
            data=PLAN_PATH.read_bytes(),
            file_name=PLAN_PATH.name,
            mime="application/json",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
