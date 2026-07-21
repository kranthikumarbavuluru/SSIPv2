from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_3"
SOURCE_OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_2"

MANIFEST_PATH = (
    OUTPUT_DIR
    / "meity_temporal_parent_safety_manifest_v3_4_3_8_0_3.json"
)
BUNDLES_PATH = (
    OUTPUT_DIR
    / "meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv"
)
CHILDREN_PATH = (
    OUTPUT_DIR
    / "meity_safe_decision_children_v3_4_3_8_0_3.csv"
)
AUTO_PATH = (
    SOURCE_OUTPUT_DIR
    / "meity_auto_resolved_groups_v3_4_3_8_0_2.csv"
)
FULL_LEDGER_PATH = (
    SOURCE_OUTPUT_DIR
    / "meity_decision_bundle_children_v3_4_3_8_0_2.csv"
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


def truthy(value: str) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def child_label(row: dict[str, str]) -> str:
    return (
        row.get("canonical_name")
        or row.get("original_canonical_name")
        or row.get("child_id")
        or "Unnamed child"
    )


def decision_export(
    bundles: list[dict[str, str]],
    decisions: dict[str, dict],
) -> str:
    fields = [
        "bundle_id",
        "bundle_signature",
        "bundle_title",
        "lane",
        "recommended_action",
        "admin_decision",
        "selected_child_ids",
        "admin_note",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for bundle in bundles:
        bundle_id = bundle["bundle_id"]
        saved = decisions.get(bundle_id, {})
        writer.writerow(
            {
                "bundle_id": bundle_id,
                "bundle_signature": bundle.get("bundle_signature", ""),
                "bundle_title": bundle.get("bundle_title", ""),
                "lane": bundle.get("lane", ""),
                "recommended_action": bundle.get(
                    "recommended_action",
                    "",
                ),
                "admin_decision": saved.get("decision", "PENDING"),
                "selected_child_ids": ";".join(
                    saved.get("selected_child_ids", [])
                ),
                "admin_note": saved.get("note", ""),
            }
        )
    return buffer.getvalue()


def render_evidence_panel(child: dict[str, str]) -> None:
    st.subheader("Evidence at a glance")

    status_col, temporal_col, parent_col = st.columns(3)
    status_col.write(
        "**Safe status**  \n"
        + (child.get("safe_application_status") or "Not established")
    )
    temporal_col.write(
        "**Temporal validation**  \n"
        + (child.get("temporal_validation") or "Not established")
    )
    parent_col.write(
        "**Parent-link result**  \n"
        + (child.get("parent_link_resolution") or "Not applicable")
    )

    dates_col, route_col, verified_col = st.columns(3)
    dates_col.write(
        "**Application window**  \n"
        f"Opening: {child.get('opening_date') or 'Not proven'}  \n"
        f"Closing: {child.get('closing_date') or 'Not proven'}"
    )
    route_col.write(
        "**Application route**  \n"
        + (
            child.get("application_url")
            if child.get("official_application_route") == "True"
            else "Official route not proven"
        )
    )
    verified_col.write(
        "**Last verified**  \n"
        + (child.get("last_verified_at") or "Recent verification not proven")
    )

    parent_name = child.get("repaired_parent_scheme_name") or "Unresolved"
    parent_id = child.get("repaired_parent_master_id") or "Not linked"
    st.write(
        f"**Repaired parent:** {parent_name}  \n"
        f"**Parent master ID:** {parent_id}"
    )

    official_url = child.get("official_page_url", "")
    application_url = child.get("application_url", "")
    link_columns = st.columns(2)
    if official_url:
        link_columns[0].link_button(
            "Open official evidence page",
            official_url,
            use_container_width=True,
        )
    else:
        link_columns[0].button(
            "Official evidence page unavailable",
            disabled=True,
            use_container_width=True,
        )

    if application_url and child.get("official_application_route") == "True":
        link_columns[1].link_button(
            "Inspect official application route",
            application_url,
            use_container_width=True,
        )
    else:
        link_columns[1].button(
            "Official application route not proven",
            disabled=True,
            use_container_width=True,
        )

    with st.expander("Current-status evidence", expanded=True):
        st.text_area(
            "Status evidence",
            child.get("status_evidence")
            or child.get("evidence_excerpt")
            or "No status evidence was captured.",
            height=170,
            disabled=True,
            key="safe_status_evidence_" + child.get("child_id", "unknown"),
        )

    flags = [
        value
        for value in (
            (child.get("temporal_flags") or "")
            + ";"
            + (child.get("parent_link_flags") or "")
        ).split(";")
        if value
    ]
    if flags:
        st.warning("Safety flags: " + ", ".join(flags))


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY v3.4.3.8.0.3 Safe Review",
        page_icon="🛡️",
        layout="wide",
    )

    manifest = read_json(MANIFEST_PATH)
    bundles = read_csv(BUNDLES_PATH)
    children = read_csv(CHILDREN_PATH)
    auto_groups = read_csv(AUTO_PATH)
    full_ledger = read_csv(FULL_LEDGER_PATH)

    st.title("MeitY Decision-Safety Review")
    st.caption(
        "Temporal validation, parent-link repair and safe Admin decisions. "
        "No database write and no publication action."
    )

    if not manifest:
        st.error(
            "Run SSIP v3.4.3.8.0.3 before opening this workspace."
        )
        return

    current_signature = manifest.get("session_state_signature", "")
    previous_signature = st.session_state.get(
        "meity_safety_session_signature",
        "",
    )
    if previous_signature != current_signature:
        had_decisions = bool(
            st.session_state.get("meity_safe_bundle_decisions")
        )
        st.session_state["meity_safe_bundle_decisions"] = {}
        st.session_state["meity_safety_session_signature"] = current_signature
        if had_decisions:
            st.warning(
                "Previous session decisions were cleared because the "
                "bundle evidence or safety signature changed."
            )

    decisions: dict[str, dict] = st.session_state.setdefault(
        "meity_safe_bundle_decisions",
        {},
    )

    metrics = (
        ("Decision bundles", manifest.get("safe_decision_bundle_count", 0)),
        ("Temporal downgrades", manifest.get("temporal_downgrade_count", 0)),
        ("Parent links repaired", manifest.get("parent_link_repair_count", 0)),
        (
            "Current evidence complete",
            manifest.get("current_status_evidence_complete_count", 0),
        ),
        (
            "Historical classifications",
            manifest.get("historical_classification_count", 0),
        ),
        ("Unsafe current status", manifest.get("unsafe_current_status_count", 0)),
    )
    metric_columns = st.columns(len(metrics))
    for column, (label, value) in zip(metric_columns, metrics):
        column.metric(label, value)

    st.success(
        "Current status requires explicit open language, a future deadline, "
        "an official application route and recent verification. Old years in "
        "titles are historical unless official reopened evidence is present."
    )

    tab_queue, tab_auto, tab_ledger = st.tabs(
        [
            "Safe Admin Decision Queue",
            "Auto-Resolved Audit",
            "Complete Evidence Ledger",
        ]
    )

    children_by_bundle: dict[str, list[dict[str, str]]] = {}
    for child in children:
        children_by_bundle.setdefault(child.get("bundle_id", ""), []).append(child)

    with tab_queue:
        if not bundles:
            st.warning("No safe Admin decision bundles were generated.")
        else:
            lanes = sorted({row.get("lane", "") for row in bundles if row.get("lane")})
            priorities = sorted(
                {row.get("priority", "") for row in bundles if row.get("priority")}
            )
            actions = sorted(
                {
                    row.get("recommended_action", "")
                    for row in bundles
                    if row.get("recommended_action")
                }
            )

            f1, f2, f3, f4 = st.columns([2, 1, 1, 1.5])
            keyword = f1.text_input(
                "Search safe bundles",
                placeholder="SAMRIDH, Appscale, historical, parent…",
            ).strip().casefold()
            lane_filter = f2.selectbox("Lane", ["ALL", *lanes])
            priority_filter = f3.selectbox("Priority", ["ALL", *priorities])
            action_filter = f4.selectbox(
                "Safe recommended action",
                ["ALL", *actions],
            )

            visible = []
            for row in bundles:
                haystack = " ".join(str(value) for value in row.values()).casefold()
                if keyword and keyword not in haystack:
                    continue
                if lane_filter != "ALL" and row.get("lane") != lane_filter:
                    continue
                if (
                    priority_filter != "ALL"
                    and row.get("priority") != priority_filter
                ):
                    continue
                if (
                    action_filter != "ALL"
                    and row.get("recommended_action") != action_filter
                ):
                    continue
                visible.append(row)

            visible.sort(
                key=lambda row: (
                    {
                        "CRITICAL": 0,
                        "HIGH": 1,
                        "MEDIUM": 2,
                        "LOW": 3,
                    }.get(row.get("priority", ""), 4),
                    row.get("bundle_title", "").casefold(),
                )
            )
            st.write(f"**{len(visible)} matching safe decision bundle(s)**")

            if visible:
                left, centre, right = st.columns([1.05, 1.35, 1.6])

                with left:
                    selected_index = st.radio(
                        "Select bundle",
                        range(len(visible)),
                        format_func=lambda index: (
                            f"[{visible[index].get('priority', 'LOW')}] "
                            f"{visible[index].get('bundle_title', 'Untitled')}"
                        ),
                        label_visibility="collapsed",
                    )
                    selected = visible[selected_index]

                bundle_id = selected["bundle_id"]
                bundle_children = children_by_bundle.get(bundle_id, [])
                saved = decisions.get(bundle_id, {})
                child_names = {
                    child.get("child_id", ""): child_label(child)
                    for child in bundle_children
                }

                with centre:
                    st.subheader(selected.get("bundle_title", "Untitled bundle"))
                    st.write("**Lane:**", selected.get("lane"))
                    st.write("**Priority:**", selected.get("priority"))
                    st.write(
                        "**Safe recommended action:**",
                        selected.get("recommended_action"),
                    )
                    st.write(
                        "**Original recommendation:**",
                        selected.get("original_recommended_action"),
                    )
                    st.write(
                        "**Temporal states:**",
                        selected.get("temporal_states") or "Not applicable",
                    )
                    st.write(
                        "**Parent-link states:**",
                        selected.get("parent_link_states") or "Not applicable",
                    )
                    st.info(selected.get("rationale", ""))

                    requires_selection = truthy(
                        selected.get("requires_child_selection", "")
                    )
                    if requires_selection:
                        default_ids = saved.get("selected_child_ids", [])
                        selected_ids = st.multiselect(
                            "Select child records included in this decision",
                            options=list(child_names),
                            default=[
                                child_id
                                for child_id in default_ids
                                if child_id in child_names
                            ],
                            format_func=lambda child_id: child_names[child_id],
                        )
                    else:
                        selected_ids = list(child_names)
                        st.caption(
                            "This batch bundle includes all listed child records. "
                            "Every child remains individually auditable."
                        )

                    evidence_options = (
                        selected_ids
                        if selected_ids
                        else list(child_names)
                    )
                    evidence_child_id = st.selectbox(
                        "Evidence record shown on the right",
                        options=evidence_options,
                        format_func=lambda child_id: child_names[child_id],
                    )

                with right:
                    evidence_child = next(
                        child
                        for child in bundle_children
                        if child.get("child_id") == evidence_child_id
                    )
                    render_evidence_panel(evidence_child)

                    st.subheader("Safe session decision")
                    allowed = [
                        value
                        for value in selected.get("allowed_decisions", "").split(";")
                        if value
                    ]
                    if "ACCEPT_RECOMMENDATION" in allowed:
                        st.error(
                            "Unsafe decision wording detected. Saving is blocked."
                        )
                        allowed = ["PENDING"]

                    previous = saved.get("decision", "PENDING")
                    decision = st.selectbox(
                        "Decision",
                        allowed or ["PENDING"],
                        index=(
                            allowed.index(previous)
                            if previous in allowed
                            else 0
                        ),
                    )
                    note = st.text_area(
                        "Admin note",
                        value=saved.get("note", ""),
                        height=120,
                        placeholder=(
                            "Record deadline verification, parent evidence, "
                            "missing proof or the reason for classification."
                        ),
                    )

                    requires_note = truthy(
                        selected.get("requires_admin_note", "")
                    )
                    selection_ready = (
                        bool(selected_ids)
                        if requires_selection
                        else True
                    )
                    note_ready = bool(note.strip()) if requires_note else True
                    decision_ready = decision != "PENDING"
                    save_ready = (
                        selection_ready
                        and note_ready
                        and decision_ready
                        and "ACCEPT_RECOMMENDATION" not in allowed
                    )

                    if requires_selection and not selection_ready:
                        st.warning(
                            "Select at least one child record before saving."
                        )
                    if requires_note and not note_ready:
                        st.warning(
                            "A written Admin note is required for deep review."
                        )
                    if not decision_ready:
                        st.info("Choose a non-pending decision before saving.")

                    if st.button(
                        "Save safe session decision",
                        type="primary",
                        use_container_width=True,
                        disabled=not save_ready,
                    ):
                        decisions[bundle_id] = {
                            "bundle_signature": selected.get(
                                "bundle_signature",
                                "",
                            ),
                            "decision": decision,
                            "selected_child_ids": selected_ids,
                            "note": note.strip(),
                        }
                        st.session_state["meity_safe_bundle_decisions"] = decisions
                        st.success(
                            "Saved in this browser session only. "
                            "No database or publication change was made."
                        )

                    st.metric(
                        "Safe session decisions saved",
                        sum(
                            1
                            for value in decisions.values()
                            if value.get("decision") not in {"", "PENDING"}
                        ),
                    )
                    st.download_button(
                        "Download safe decision worksheet",
                        data=decision_export(bundles, decisions),
                        file_name=(
                            "meity_safe_decisions_v3_4_3_8_0_3.csv"
                        ),
                        mime="text/csv",
                        use_container_width=True,
                    )

                with st.expander(
                    f"Bundle children ({len(bundle_children)})",
                    expanded=False,
                ):
                    display_fields = [
                        "canonical_name",
                        "entity_type",
                        "safe_application_status",
                        "temporal_validation",
                        "closing_date",
                        "repaired_parent_scheme_name",
                        "parent_link_resolution",
                        "official_page_url",
                    ]
                    st.dataframe(
                        [
                            {
                                field: child.get(field, "")
                                for field in display_fields
                            }
                            for child in bundle_children
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                with st.expander("Complete safe bundle record", expanded=False):
                    st.json(selected)

    with tab_auto:
        st.write(
            f"**{len(auto_groups)} grouped automatic resolutions** from the "
            "previous compression phase. They remain auditable and require no "
            "routine Admin action."
        )
        if auto_groups:
            st.dataframe(
                auto_groups,
                use_container_width=True,
                hide_index=True,
            )

    with tab_ledger:
        st.write(
            f"**{len(full_ledger)} complete evidence-ledger rows**. "
            "The safe decision queue above contains only decision-bearing children."
        )
        if full_ledger:
            st.dataframe(
                full_ledger,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.caption(
        "Safety signature: "
        + str(manifest.get("signature", ""))
        + " · Session-state signature: "
        + str(manifest.get("session_state_signature", ""))
        + " · Database write: No · Publication: No"
    )


if __name__ == "__main__":
    main()
