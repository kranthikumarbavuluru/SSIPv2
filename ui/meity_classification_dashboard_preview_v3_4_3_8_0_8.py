from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from services.meity_classification_projection_v3_4_3_8_0_8 import (
    build_service,
    clean,
    truthy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def label_type(value: str) -> str:
    return clean(value).replace("_", " ").title()


def render_card(row: dict) -> None:
    with st.container(border=True):
        st.subheader(clean(row.get("canonical_name")) or "Unnamed record")
        st.caption(label_type(row.get("effective_entity_type")))
        if truthy(row.get("override_applied")):
            st.success("Admin classification override applied")
        if row.get("effective_parent_scheme_name"):
            st.write(
                "**Parent programme:**",
                row.get("effective_parent_scheme_name"),
            )
        st.write(
            "**Status:**",
            label_type(
                row.get("safe_application_status")
                or row.get("application_status")
            ),
        )
        information_url = clean(row.get("verified_information_url"))
        if information_url:
            st.link_button(
                "Open verified official source",
                information_url,
                use_container_width=True,
            )
        application_url = clean(row.get("verified_application_url"))
        if application_url and row.get("dashboard_section") == "CALLS_CHALLENGES":
            st.info(
                "Application route is retained in the projection evidence, "
                "but no public Apply action is enabled."
            )
        if row.get("projection_status") == "BLOCKED":
            st.warning(
                "Staging projection blocked: "
                + clean(row.get("projection_errors")).replace("_", " ")
            )


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY Classification Dashboard Preview",
        page_icon="📊",
        layout="wide",
    )

    service = build_service(PROJECT_ROOT)
    summary = service.build_preview()
    rows = service.effective_inventory()

    st.title("MeitY Classification Dashboard Preview")
    st.caption(
        "Public-dashboard-style preview using the written classification "
        "overrides. This view is not published."
    )
    st.warning(
        "This preview does not change the live public dashboard. "
        "Staging projection writes only to the dedicated projection layer."
    )

    metrics = st.columns(6)
    metrics[0].metric("Overrides applied", summary["override_count"])
    metrics[1].metric("Type corrections", summary["type_correction_count"])
    metrics[2].metric("Programmes", summary["programme_count"])
    metrics[3].metric(
        "Calls & challenges",
        summary["call_challenge_count"],
    )
    metrics[4].metric("Historical", summary["historical_count"])
    metrics[5].metric(
        "Excluded/supporting",
        summary["excluded_supporting_count"],
    )

    tab_programmes, tab_calls, tab_history, tab_excluded, tab_gate = st.tabs(
        [
            "MeitY Programmes",
            "Calls & Challenges",
            "Historical Archive",
            "Excluded & Supporting",
            "Staging Projection Gate",
        ]
    )

    with tab_programmes:
        programme_rows = [
            row for row in rows
            if row.get("dashboard_section") == "PROGRAMMES"
        ]
        st.write(
            f"**{len(programme_rows)} effective permanent programme or "
            "scheme record(s)**"
        )
        columns = st.columns(2)
        for index, row in enumerate(programme_rows):
            with columns[index % 2]:
                render_card(row)

    with tab_calls:
        call_rows = [
            row for row in rows
            if row.get("dashboard_section") == "CALLS_CHALLENGES"
        ]
        st.write(
            f"**{len(call_rows)} effective call, challenge or cohort "
            "record(s)**"
        )
        st.info(
            "Call identity and current-open status are separate. "
            "A call can appear here without being treated as currently open."
        )
        columns = st.columns(2)
        for index, row in enumerate(call_rows):
            with columns[index % 2]:
                render_card(row)

    with tab_history:
        history_rows = [
            row for row in rows
            if row.get("dashboard_section") == "HISTORICAL"
        ]
        st.write(
            f"**{len(history_rows)} historical or result reference(s)**"
        )
        st.success(
            "Historical records are reference-only and never expose an "
            "Apply action."
        )
        columns = st.columns(2)
        for index, row in enumerate(history_rows):
            with columns[index % 2]:
                render_card(row)

    with tab_excluded:
        excluded_rows = [
            row for row in rows
            if row.get("dashboard_section")
            in {"EXCLUDED_SUPPORTING", "CLASSIFICATION_REVIEW"}
        ]
        st.write(
            f"**{len(excluded_rows)} supporting, invalid or unresolved "
            "record(s)**"
        )
        st.dataframe(
            [
                {
                    "Record": row.get("canonical_name", ""),
                    "Effective type": label_type(
                        row.get("effective_entity_type", "")
                    ),
                    "Projection status": row.get(
                        "projection_status",
                        "",
                    ),
                    "Reason": (
                        row.get("projection_errors")
                        or row.get("projection_warnings")
                        or "Classification review"
                    ),
                }
                for row in excluded_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

    with tab_gate:
        eligible = [
            row for row in rows
            if truthy(row.get("projection_eligible"))
        ]
        blocked = [
            row for row in rows
            if not truthy(row.get("projection_eligible"))
        ]

        st.subheader("Staging projection summary")
        gate_metrics = st.columns(4)
        gate_metrics[0].metric("Eligible", len(eligible))
        gate_metrics[1].metric("Blocked", len(blocked))
        gate_metrics[2].metric("Public changes", 0)
        gate_metrics[3].metric("Apply actions", 0)

        st.info(
            "Projection creates an internal effective-classification staging "
            "layer. It does not update scheme_staging, admin_review_queue or "
            "public_schemes."
        )

        with st.expander("Eligible projection rows", expanded=True):
            st.dataframe(
                [
                    {
                        "Record": row.get("canonical_name", ""),
                        "Type": label_type(
                            row.get("effective_entity_type", "")
                        ),
                        "Parent": row.get(
                            "effective_parent_scheme_name",
                            "",
                        ),
                        "Override": row.get("override_applied", False),
                    }
                    for row in eligible
                ],
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Blocked rows and reasons", expanded=False):
            st.dataframe(
                [
                    {
                        "Record": row.get("canonical_name", ""),
                        "Type": label_type(
                            row.get("effective_entity_type", "")
                        ),
                        "Blocking reason": row.get(
                            "projection_errors",
                            "",
                        ),
                        "Warning": row.get(
                            "projection_warnings",
                            "",
                        ),
                    }
                    for row in blocked
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Governed staging projection")
        actor = st.text_input("Admin name", value="Admin")
        acknowledgement = st.checkbox(
            "I understand that this writes only to the dedicated staging "
            "projection layer and does not publish anything."
        )
        confirmation = st.text_input(
            'Type exactly: "PROJECT TO STAGING"',
        )
        ready = (
            acknowledgement
            and confirmation
            == service.config.get("confirmation_phrase")
            and len(eligible) > 0
        )

        if st.button(
            "Write governed staging projection",
            type="primary",
            use_container_width=True,
            disabled=not ready,
        ):
            result = service.apply_projection(
                expected_signature=summary["projection_signature"],
                confirmation=confirmation,
                actor=actor,
            )
            st.success(
                "Staging projection written. Public visibility was not "
                "changed."
            )
            st.json(result)
            st.rerun()

        st.download_button(
            "Download signed staging projection plan",
            data=(
                service.paths.output_dir
                / "meity_signed_staging_projection_plan_v3_4_3_8_0_8.json"
            ).read_bytes(),
            file_name=(
                "meity_signed_staging_projection_plan_v3_4_3_8_0_8.json"
            ),
            mime="application/json",
            use_container_width=True,
        )

    st.divider()
    st.caption(
        "Projection signature: "
        + summary["projection_signature"]
        + " · Public visibility changed: No · Publication action: None"
    )


if __name__ == "__main__":
    main()
