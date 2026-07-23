from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_2"
MANIFEST_PATH = (
    OUTPUT_DIR / "meity_review_compression_manifest_v3_4_3_8_0_2.json"
)
BUNDLES_PATH = (
    OUTPUT_DIR / "meity_admin_decision_bundles_v3_4_3_8_0_2.csv"
)
AUTO_PATH = (
    OUTPUT_DIR / "meity_auto_resolved_groups_v3_4_3_8_0_2.csv"
)
CHILDREN_PATH = (
    OUTPUT_DIR / "meity_decision_bundle_children_v3_4_3_8_0_2.csv"
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


def child_label(row: dict[str, str]) -> str:
    return (
        row.get("canonical_name")
        or row.get("original_canonical_name")
        or row.get("source_titles")
        or row.get("child_id")
        or "Unnamed child"
    )


def decision_export(
    bundles: list[dict[str, str]],
    decisions: dict[str, dict],
) -> str:
    fields = [
        "bundle_id",
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


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY v3.4.3.8.0.2 Family Review",
        page_icon="🗂️",
        layout="wide",
    )

    manifest = read_json(MANIFEST_PATH)
    bundles = read_csv(BUNDLES_PATH)
    auto_groups = read_csv(AUTO_PATH)
    children = read_csv(CHILDREN_PATH)

    st.title("MeitY Family-Level Admin Review")
    st.caption(
        "Compressed decision bundles with auto-resolved audit groups. "
        "Session decisions are not written to the database or published."
    )

    if not manifest:
        st.error(
            "Run SSIP v3.4.3.8.0.2 review compression before opening this page."
        )
        return

    metrics = (
        ("Source evidence", manifest.get("source_evidence_weight", 0)),
        ("Auto-resolved evidence", manifest.get("auto_resolved_evidence_weight", 0)),
        ("Admin decision bundles", manifest.get("admin_decision_bundle_count", 0)),
        ("Batch confirmations", manifest.get("batch_confirmation_bundle_count", 0)),
        ("Deep review", manifest.get("deep_review_bundle_count", 0)),
        ("Maximum workload", manifest.get("max_admin_decision_bundles", 20)),
    )
    metric_columns = st.columns(len(metrics))
    for column, (label, value) in zip(metric_columns, metrics):
        column.metric(label, value)

    source_weight = int(manifest.get("source_evidence_weight", 0) or 0)
    auto_weight = int(manifest.get("auto_resolved_evidence_weight", 0) or 0)
    reduction = round((auto_weight / source_weight) * 100, 1) if source_weight else 0
    st.success(
        f"{auto_weight} of {source_weight} source-evidence records "
        f"({reduction}%) are handled automatically. "
        f"The Admin queue is compressed to "
        f"{manifest.get('admin_decision_bundle_count', 0)} decision bundle(s)."
    )

    children_by_bundle: dict[str, list[dict[str, str]]] = {}
    for child in children:
        children_by_bundle.setdefault(child.get("bundle_id", ""), []).append(child)

    if "meity_bundle_decisions" not in st.session_state:
        st.session_state["meity_bundle_decisions"] = {}
    decisions: dict[str, dict] = st.session_state["meity_bundle_decisions"]

    tab_queue, tab_auto, tab_ledger = st.tabs(
        [
            "Admin Decision Queue",
            "Auto-Resolved Audit",
            "Complete Child Ledger",
        ]
    )

    with tab_queue:
        if not bundles:
            st.warning("No Admin decision bundles were generated.")
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

            f1, f2, f3, f4 = st.columns([2, 1, 1, 1.4])
            keyword = f1.text_input(
                "Search bundles",
                placeholder="SAMRIDH, GENESIS, challenge, programme…",
            ).strip().casefold()
            lane = f2.selectbox("Lane", ["ALL", *lanes])
            priority = f3.selectbox("Priority", ["ALL", *priorities])
            action = f4.selectbox("Recommended action", ["ALL", *actions])

            visible = []
            for row in bundles:
                haystack = " ".join(str(value) for value in row.values()).casefold()
                if keyword and keyword not in haystack:
                    continue
                if lane != "ALL" and row.get("lane") != lane:
                    continue
                if priority != "ALL" and row.get("priority") != priority:
                    continue
                if action != "ALL" and row.get("recommended_action") != action:
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
            st.write(f"**{len(visible)} matching decision bundle(s)**")
            if visible:
                left, centre, right = st.columns([1.1, 1.35, 1.55])

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

                with centre:
                    st.subheader(selected.get("bundle_title", "Untitled bundle"))
                    st.write("**Lane:**", selected.get("lane"))
                    st.write("**Priority:**", selected.get("priority"))
                    st.write(
                        "**Recommended action:**",
                        selected.get("recommended_action"),
                    )
                    st.write(
                        "**Children:**",
                        selected.get("child_record_count"),
                        "· **Source evidence:**",
                        selected.get("source_evidence_weight"),
                    )
                    st.write("**Families:**", selected.get("families") or "Unresolved")
                    st.write("**Entity types:**", selected.get("entity_types") or "Unknown")
                    st.info(selected.get("rationale", ""))

                    child_names = {
                        child.get("child_id", ""): child_label(child)
                        for child in bundle_children
                    }
                    if selected.get("requires_individual_child_selection") == "True":
                        default_ids = saved.get("selected_child_ids", [])
                        selected_ids = st.multiselect(
                            "Select children included in this decision",
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
                            "The recommendation may be applied to the full bundle. "
                            "All child evidence remains individually auditable."
                        )

                with right:
                    st.subheader("Session decision")
                    decision_options = [
                        "PENDING",
                        "ACCEPT_RECOMMENDATION",
                        "NEEDS_DEEP_REVIEW",
                        "DEFER",
                        "REJECT_RECOMMENDATION",
                    ]
                    previous = saved.get("decision", "PENDING")
                    decision = st.selectbox(
                        "Decision",
                        decision_options,
                        index=(
                            decision_options.index(previous)
                            if previous in decision_options
                            else 0
                        ),
                    )
                    note = st.text_area(
                        "Admin note",
                        value=saved.get("note", ""),
                        height=120,
                        placeholder=(
                            "Record the reason, correction, parent linkage "
                            "or evidence still required."
                        ),
                    )
                    if st.button(
                        "Save session decision",
                        type="primary",
                        use_container_width=True,
                    ):
                        decisions[bundle_id] = {
                            "decision": decision,
                            "selected_child_ids": selected_ids,
                            "note": note,
                        }
                        st.session_state["meity_bundle_decisions"] = decisions
                        st.success(
                            "Saved in this browser session only. "
                            "No database or publication change was made."
                        )

                    decided = sum(
                        1
                        for value in decisions.values()
                        if value.get("decision") not in {"", "PENDING"}
                    )
                    st.metric("Session decisions saved", decided)
                    st.download_button(
                        "Download decision worksheet",
                        data=decision_export(bundles, decisions),
                        file_name=(
                            "meity_family_decisions_v3_4_3_8_0_2.csv"
                        ),
                        mime="text/csv",
                        use_container_width=True,
                    )

                with st.expander(
                    f"Bundle children ({len(bundle_children)})",
                    expanded=True,
                ):
                    display_fields = [
                        "canonical_name",
                        "original_canonical_name",
                        "entity_type",
                        "application_status",
                        "inferred_family",
                        "parent_resolution",
                        "official_page_url",
                        "priority",
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

                with st.expander("Complete bundle record", expanded=False):
                    st.json(selected)

    with tab_auto:
        st.write(
            f"**{len(auto_groups)} grouped automatic resolutions** — "
            "no Admin action is required unless an audit exception is raised."
        )
        if auto_groups:
            auto_actions = sorted(
                {
                    row.get("recommended_action", "")
                    for row in auto_groups
                    if row.get("recommended_action")
                }
            )
            selected_action = st.selectbox(
                "Automatic resolution type",
                ["ALL", *auto_actions],
            )
            visible_auto = [
                row
                for row in auto_groups
                if selected_action == "ALL"
                or row.get("recommended_action") == selected_action
            ]
            st.dataframe(
                visible_auto,
                use_container_width=True,
                hide_index=True,
            )
            selected_auto = st.selectbox(
                "Inspect an automatic group",
                options=[row["bundle_id"] for row in visible_auto],
                format_func=lambda bundle_id: next(
                    row["bundle_title"]
                    for row in visible_auto
                    if row["bundle_id"] == bundle_id
                ),
            )
            auto_children = children_by_bundle.get(selected_auto, [])
            with st.expander(
                f"Audit children ({len(auto_children)})",
                expanded=False,
            ):
                st.dataframe(
                    auto_children,
                    use_container_width=True,
                    hide_index=True,
                )

    with tab_ledger:
        st.write(
            f"**{len(children)} child records** — each purified input row "
            "appears in exactly one automatic or Admin bundle."
        )
        st.dataframe(
            children,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.caption(
        "Manifest signature: "
        + str(manifest.get("signature", ""))
        + " · Database write: No · Publication: No"
    )


if __name__ == "__main__":
    main()
