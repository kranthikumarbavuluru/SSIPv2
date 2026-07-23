from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st

from services.meity_guided_review_v3_4_3_8_0_5 import (
    action_help,
    allowed_action_records,
    note_required,
    plain_action_label,
    queue_bucket,
    simple_record_summary,
    truthy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_4"

MANIFEST_PATH = OUTPUT_DIR / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
BUNDLES_PATH = OUTPUT_DIR / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
CHILDREN_PATH = OUTPUT_DIR / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
PROVENANCE_PATH = OUTPUT_DIR / "meity_url_provenance_ledger_v3_4_3_8_0_4.csv"


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
        or row.get("child_id")
        or "Unnamed record"
    )


def decision_export(
    bundles: list[dict[str, str]],
    decisions: dict[str, dict],
) -> str:
    buffer = io.StringIO()
    fields = [
        "bundle_id",
        "bundle_title",
        "link_integrity_signature",
        "admin_decision",
        "admin_decision_label",
        "selected_child_ids",
        "admin_note",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for bundle in bundles:
        saved = decisions.get(bundle.get("bundle_id", ""), {})
        code = saved.get("decision", "PENDING")
        writer.writerow(
            {
                "bundle_id": bundle.get("bundle_id", ""),
                "bundle_title": bundle.get("bundle_title", ""),
                "link_integrity_signature": bundle.get(
                    "link_integrity_signature",
                    "",
                ),
                "admin_decision": code,
                "admin_decision_label": plain_action_label(code),
                "selected_child_ids": ";".join(
                    saved.get("selected_child_ids", [])
                ),
                "admin_note": saved.get("note", ""),
            }
        )
    return buffer.getvalue()


def queue_label(
    bundle: dict[str, str],
    child: dict[str, str],
    reviewed: bool,
) -> str:
    if reviewed:
        prefix = "✓ Reviewed"
    else:
        bucket = queue_bucket(bundle, child)
        prefix = {
            "READY TO CONFIRM": "● Ready",
            "NEEDS EVIDENCE": "● Needs evidence",
            "CURRENT OPPORTUNITY CHECK": "● Current-call check",
        }.get(bucket, "● Review")
    return f"{prefix} — {child_label(child)}"


def render_verified_source(child: dict[str, str]) -> None:
    information_url = child.get("verified_information_url", "")
    information_role = child.get("verified_information_role", "")
    application_url = child.get("verified_application_url", "")
    withheld_reason = (
        child.get("application_route_withheld_reason")
        or "No verified current application route"
    )

    st.markdown("### Step 1 — Check the official source")

    if information_url:
        st.success(
            "A matching official information page was verified"
            + (f" ({information_role})" if information_role else ".")
        )
        st.link_button(
            "Open the verified official page",
            information_url,
            use_container_width=True,
        )
    else:
        st.warning(
            "No matching official information page passed all link checks."
        )
        st.button(
            "Verified official page unavailable",
            disabled=True,
            use_container_width=True,
        )

    if application_url:
        st.success("A verified current application route is available.")
        st.link_button(
            "Open the verified application route",
            application_url,
            use_container_width=True,
        )
    else:
        st.info(
            "No Apply button is shown. "
            "Reason: " + withheld_reason.replace("_", " ").title()
        )


def render_plain_summary(
    bundle: dict[str, str],
    child: dict[str, str],
) -> None:
    st.markdown("### Step 2 — Check the system summary")
    summary = simple_record_summary(bundle, child)
    for number, sentence in enumerate(summary, start=1):
        st.write(f"**{number}.** {sentence}")

    basic_1, basic_2, basic_3 = st.columns(3)
    basic_1.metric(
        "Record type",
        (
            child.get("entity_type", "")
            .replace("_", " ")
            .title()
            or "Not established"
        ),
    )
    basic_2.metric(
        "Status",
        (
            child.get("safe_application_status", "")
            .replace("_", " ")
            .title()
            or "Not established"
        ),
    )
    basic_3.metric(
        "Link check",
        (
            "Passed"
            if truthy(child.get("link_integrity_complete"))
            else "Needs evidence"
        ),
    )

    parent = child.get("repaired_parent_scheme_name", "")
    if parent:
        st.write(f"**Linked parent programme:** {parent}")
    elif child.get("parent_link_resolution") not in {"", "NOT_APPLICABLE"}:
        st.write("**Linked parent programme:** Not yet established")


def render_advanced_details(
    bundle: dict[str, str],
    child: dict[str, str],
    provenance: list[dict[str, str]],
) -> None:
    with st.expander(
        "Advanced evidence details — open only when needed",
        expanded=False,
    ):
        st.caption(
            "These technical fields are retained for audit. They are not "
            "required for routine review."
        )
        left, right = st.columns(2)
        with left:
            st.write("**Bundle ID:**", bundle.get("bundle_id", ""))
            st.write(
                "**Recommended action code:**",
                bundle.get("recommended_action", ""),
            )
            st.write(
                "**Temporal validation:**",
                child.get("temporal_validation", ""),
            )
            st.write(
                "**Parent-link result:**",
                child.get("parent_link_resolution", ""),
            )
            st.write(
                "**Link-integrity flags:**",
                bundle.get("link_integrity_flags", "") or "None",
            )
        with right:
            st.write(
                "**Original page URL:**",
                child.get("raw_application_url", "") or "None",
            )
            st.write(
                "**Verified information URL:**",
                child.get("verified_information_url", "") or "None",
            )
            st.write(
                "**Verified application URL:**",
                child.get("verified_application_url", "") or "None",
            )
            st.write(
                "**Links inspected:**",
                child.get("link_count_inspected", "0"),
            )
            st.write(
                "**Last integrity signature:**",
                bundle.get("link_integrity_signature", ""),
            )

        st.text_area(
            "Evidence excerpt",
            child.get("status_evidence")
            or child.get("evidence_excerpt")
            or "No evidence excerpt captured.",
            height=170,
            disabled=True,
            key="guided_evidence_" + child.get("child_id", "unknown"),
        )

        child_provenance = [
            row
            for row in provenance
            if row.get("child_id") == child.get("child_id")
        ]
        if child_provenance:
            st.dataframe(
                child_provenance,
                use_container_width=True,
                hide_index=True,
            )


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY Guided Review",
        page_icon="✅",
        layout="wide",
    )

    manifest = read_json(MANIFEST_PATH)
    bundles = read_csv(BUNDLES_PATH)
    children = read_csv(CHILDREN_PATH)
    provenance = read_csv(PROVENANCE_PATH)

    st.title("MeitY Guided Admin Review")
    st.caption(
        "Review one record at a time: open the official source, check the "
        "summary, then choose one clear action."
    )

    if not manifest or not bundles or not children:
        st.error(
            "The v3.4.3.8.0.4 link-integrity outputs are missing. "
            "Run that phase before opening this guided page."
        )
        return

    signature = manifest.get("session_state_signature", "")
    previous_signature = st.session_state.get(
        "meity_guided_signature",
        "",
    )
    if previous_signature != signature:
        had_decisions = bool(
            st.session_state.get("meity_guided_decisions")
        )
        st.session_state["meity_guided_decisions"] = {}
        st.session_state["meity_guided_signature"] = signature
        if had_decisions:
            st.warning(
                "Earlier session decisions were cleared because the verified "
                "links or evidence changed."
            )

    decisions: dict[str, dict] = st.session_state.setdefault(
        "meity_guided_decisions",
        {},
    )

    children_by_bundle: dict[str, list[dict[str, str]]] = {}
    for child in children:
        children_by_bundle.setdefault(
            child.get("bundle_id", ""),
            [],
        ).append(child)

    bundle_pairs: list[tuple[dict[str, str], dict[str, str]]] = []
    for bundle in bundles:
        attached = children_by_bundle.get(bundle.get("bundle_id", ""), [])
        if attached:
            bundle_pairs.append((bundle, attached[0]))

    reviewed_count = sum(
        1
        for bundle, _ in bundle_pairs
        if decisions.get(bundle.get("bundle_id", ""), {}).get("decision")
        not in {"", "PENDING", None}
    )
    remaining_count = max(len(bundle_pairs) - reviewed_count, 0)
    ready_count = sum(
        1
        for bundle, child in bundle_pairs
        if queue_bucket(bundle, child) == "READY TO CONFIRM"
    )
    evidence_count = sum(
        1
        for bundle, child in bundle_pairs
        if queue_bucket(bundle, child) == "NEEDS EVIDENCE"
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Records to review", len(bundle_pairs))
    metric_columns[1].metric("Completed this session", reviewed_count)
    metric_columns[2].metric("Remaining", remaining_count)
    metric_columns[3].metric("Need more evidence", evidence_count)

    st.info(
        "**Your task:** Choose one record. Open the verified official source. "
        "Then select one action on the right. You do not need to understand "
        "the technical codes."
    )

    control_1, control_2 = st.columns([1.3, 2.2])
    view = control_1.selectbox(
        "Show",
        [
            "Remaining records",
            "All records",
            "Ready to confirm",
            "Need more evidence",
            "Current opportunity checks",
            "Reviewed this session",
        ],
    )
    keyword = control_2.text_input(
        "Search",
        placeholder="GENESIS, SAMRIDH, challenge, historical…",
    ).strip().casefold()

    visible: list[tuple[dict[str, str], dict[str, str]]] = []
    for bundle, child in bundle_pairs:
        bundle_id = bundle.get("bundle_id", "")
        reviewed = (
            decisions.get(bundle_id, {}).get("decision")
            not in {"", "PENDING", None}
        )
        bucket = queue_bucket(bundle, child)

        if view == "Remaining records" and reviewed:
            continue
        if view == "Ready to confirm" and bucket != "READY TO CONFIRM":
            continue
        if view == "Need more evidence" and bucket != "NEEDS EVIDENCE":
            continue
        if (
            view == "Current opportunity checks"
            and bucket != "CURRENT OPPORTUNITY CHECK"
        ):
            continue
        if view == "Reviewed this session" and not reviewed:
            continue

        haystack = " ".join(
            [
                bundle.get("bundle_title", ""),
                child.get("canonical_name", ""),
                child.get("entity_type", ""),
                child.get("repaired_parent_scheme_name", ""),
            ]
        ).casefold()
        if keyword and keyword not in haystack:
            continue
        visible.append((bundle, child))

    visible.sort(
        key=lambda pair: (
            {
                "READY TO CONFIRM": 0,
                "CURRENT OPPORTUNITY CHECK": 1,
                "NEEDS EVIDENCE": 2,
            }.get(queue_bucket(pair[0], pair[1]), 3),
            pair[1].get("canonical_name", "").casefold(),
        )
    )

    st.write(f"**{len(visible)} record(s) shown**")

    if not visible:
        st.success(
            "There are no records in this view. Choose another view above."
        )
        st.download_button(
            "Download this session’s decisions",
            data=decision_export(bundles, decisions),
            file_name="meity_guided_decisions_v3_4_3_8_0_5.csv",
            mime="text/csv",
        )
        return

    queue_col, review_col, action_col = st.columns([1.0, 1.65, 1.25])

    with queue_col:
        selected_index = st.radio(
            "Choose a record",
            range(len(visible)),
            format_func=lambda index: queue_label(
                visible[index][0],
                visible[index][1],
                (
                    decisions.get(
                        visible[index][0].get("bundle_id", ""),
                        {},
                    ).get("decision")
                    not in {"", "PENDING", None}
                ),
            ),
        )
        selected_bundle, selected_child = visible[selected_index]

    bundle_id = selected_bundle.get("bundle_id", "")
    saved = decisions.get(bundle_id, {})
    attached_children = children_by_bundle.get(bundle_id, [])
    child_names = {
        child.get("child_id", ""): child_label(child)
        for child in attached_children
    }

    with review_col:
        st.header(child_label(selected_child))
        badge = queue_bucket(selected_bundle, selected_child)
        if badge == "READY TO CONFIRM":
            st.success("Ready for a careful confirmation")
        elif badge == "CURRENT OPPORTUNITY CHECK":
            st.warning("Current opportunity — check dates and Apply route")
        else:
            st.warning("More official evidence is needed")

        render_verified_source(selected_child)
        render_plain_summary(selected_bundle, selected_child)
        render_advanced_details(
            selected_bundle,
            selected_child,
            provenance,
        )

    with action_col:
        st.markdown("### Step 3 — Choose one action")
        st.caption(
            "Only actions allowed by the safety and link-integrity gates are "
            "shown."
        )

        action_records = allowed_action_records(selected_bundle)
        action_codes = [row["code"] for row in action_records]
        previous_decision = saved.get("decision", "PENDING")
        decision_code = st.radio(
            "What should happen to this record?",
            action_codes,
            index=(
                action_codes.index(previous_decision)
                if previous_decision in action_codes
                else 0
            ),
            format_func=plain_action_label,
        )
        if decision_code != "PENDING":
            st.info(action_help(decision_code))

        requires_selection = truthy(
            selected_bundle.get("requires_child_selection")
        )
        if requires_selection:
            selected_child_ids = st.multiselect(
                "Which child records does this decision cover?",
                options=list(child_names),
                default=[
                    child_id
                    for child_id in saved.get("selected_child_ids", [])
                    if child_id in child_names
                ],
                format_func=lambda child_id: child_names[child_id],
            )
        else:
            selected_child_ids = list(child_names)

        requires_note = note_required(selected_bundle, decision_code)
        note = st.text_area(
            "Reason or note"
            + (" — required" if requires_note else " — optional"),
            value=saved.get("note", ""),
            height=130,
            placeholder=(
                "Example: Official page confirms the programme name, but no "
                "current application deadline is available."
            ),
        )

        decision_ready = decision_code != "PENDING"
        selection_ready = (
            bool(selected_child_ids)
            if requires_selection
            else True
        )
        note_ready = bool(note.strip()) if requires_note else True
        positive_ready = (
            truthy(
                selected_bundle.get("safe_positive_decision_allowed")
            )
            if decision_code.startswith("CONFIRM_")
            else True
        )
        save_ready = (
            decision_ready
            and selection_ready
            and note_ready
            and positive_ready
        )

        if decision_code.startswith("CONFIRM_") and not positive_ready:
            st.error(
                "Confirmation is blocked because the official link evidence "
                "is incomplete. Choose “Needs more official evidence”, "
                "“Review this later”, or reject the classification."
            )
        if requires_selection and not selection_ready:
            st.warning("Select at least one child record.")
        if requires_note and not note_ready:
            st.warning("Add a short reason before saving.")

        if st.button(
            "Save decision and show the next record",
            type="primary",
            use_container_width=True,
            disabled=not save_ready,
        ):
            decisions[bundle_id] = {
                "decision": decision_code,
                "selected_child_ids": selected_child_ids,
                "note": note.strip(),
                "link_integrity_signature": selected_bundle.get(
                    "link_integrity_signature",
                    "",
                ),
            }
            st.session_state["meity_guided_decisions"] = decisions
            st.success("Decision saved in this browser session.")
            st.rerun()

        if st.button(
            "Clear this record’s session decision",
            use_container_width=True,
            disabled=bundle_id not in decisions,
        ):
            decisions.pop(bundle_id, None)
            st.session_state["meity_guided_decisions"] = decisions
            st.rerun()

        st.download_button(
            "Download this session’s decisions",
            data=decision_export(bundles, decisions),
            file_name="meity_guided_decisions_v3_4_3_8_0_5.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.divider()
        st.caption(
            "These decisions remain in the browser session only. "
            "Database write: No · Publication: No"
        )


if __name__ == "__main__":
    main()
