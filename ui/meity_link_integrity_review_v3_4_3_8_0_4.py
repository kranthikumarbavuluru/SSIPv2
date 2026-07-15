from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_4"
SOURCE_DIR = PROJECT_ROOT / "data/departments/meity/v3_4_3_8_0_3"

MANIFEST_PATH = OUTPUT_DIR / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
BUNDLES_PATH = OUTPUT_DIR / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv"
CHILDREN_PATH = OUTPUT_DIR / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
PROVENANCE_PATH = OUTPUT_DIR / "meity_url_provenance_ledger_v3_4_3_8_0_4.csv"
WITHHELD_PATH = OUTPUT_DIR / "meity_withheld_application_routes_v3_4_3_8_0_4.csv"


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
        "link_integrity_signature",
        "bundle_title",
        "recommended_action",
        "link_integrity_complete",
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
                "link_integrity_signature": bundle.get(
                    "link_integrity_signature",
                    "",
                ),
                "bundle_title": bundle.get("bundle_title", ""),
                "recommended_action": bundle.get("recommended_action", ""),
                "link_integrity_complete": bundle.get(
                    "link_integrity_complete",
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


def render_verified_links(
    child: dict[str, str],
    provenance_by_id: dict[str, dict[str, str]],
) -> None:
    st.subheader("Verified links and provenance")

    info_url = child.get("verified_information_url", "")
    info_role = child.get("verified_information_role", "")
    info_title = child.get("verified_information_title", "")
    info_provenance = provenance_by_id.get(
        child.get("verified_information_provenance_id", ""),
        {},
    )

    app_url = child.get("verified_application_url", "")
    app_role = child.get("verified_application_role", "")
    app_title = child.get("verified_application_title", "")
    app_provenance = provenance_by_id.get(
        child.get("verified_application_provenance_id", ""),
        {},
    )

    info_col, app_col = st.columns(2)

    with info_col:
        st.write("**Information source**")
        if info_url:
            st.success(
                f"{info_role or 'VERIFIED INFORMATION'}"
                + (f" · {info_title}" if info_title else "")
            )
            st.link_button(
                "Open verified information source",
                info_url,
                use_container_width=True,
            )
        else:
            st.warning(
                "Information link withheld — page role, entity match or "
                "reachability was not verified."
            )
            st.button(
                "No verified information link",
                disabled=True,
                use_container_width=True,
            )

    with app_col:
        st.write("**Application or registration route**")
        if app_url:
            st.success(
                f"{app_role or 'VERIFIED APPLICATION ROUTE'}"
                + (f" · {app_title}" if app_title else "")
            )
            st.link_button(
                "Open verified application route",
                app_url,
                use_container_width=True,
            )
        else:
            reason = (
                child.get("application_route_withheld_reason")
                or "LINK_ROLE_NOT_VERIFIED"
            )
            st.warning(f"Application route withheld — {reason}")
            st.button(
                "Application route withheld",
                disabled=True,
                use_container_width=True,
            )

    provenance = info_provenance or app_provenance
    if provenance:
        p1, p2, p3 = st.columns(3)
        p1.write(
            "**Final page role**  \n"
            + (provenance.get("page_role") or "Not established")
        )
        p2.write(
            "**HTTP result**  \n"
            + (provenance.get("http_status") or "Unknown")
        )
        p3.write(
            "**Entity match**  \n"
            + (provenance.get("entity_match_confidence") or "0")
        )
        st.write(
            "**Final redirected URL:** "
            + (provenance.get("final_url") or "Not established")
        )
        st.write(
            "**Source child:** "
            + (provenance.get("child_id") or "Unknown")
            + " · **Source field:** "
            + (provenance.get("source_field") or "Unknown")
        )
        st.write(
            "**Last checked:** "
            + (provenance.get("last_checked_at") or "Unknown")
        )


def render_evidence(
    child: dict[str, str],
    provenance_by_id: dict[str, dict[str, str]],
) -> None:
    status_col, temporal_col, integrity_col = st.columns(3)
    status_col.write(
        "**Safe status**  \n"
        + (child.get("safe_application_status") or "Not established")
    )
    temporal_col.write(
        "**Temporal status**  \n"
        + (child.get("temporal_validation") or "Not established")
    )
    integrity_col.write(
        "**Link integrity**  \n"
        + (
            "COMPLETE"
            if truthy(child.get("link_integrity_complete", ""))
            else "INCOMPLETE"
        )
    )

    dates_col, parent_col, inspected_col = st.columns(3)
    dates_col.write(
        "**Application window**  \n"
        f"Opening: {child.get('opening_date') or 'Not proven'}  \n"
        f"Closing: {child.get('closing_date') or 'Not proven'}"
    )
    parent_col.write(
        "**Repaired parent**  \n"
        + (child.get("repaired_parent_scheme_name") or "Unresolved")
        + "  \n"
        + (child.get("parent_link_resolution") or "Not applicable")
    )
    inspected_col.write(
        "**Links inspected**  \n"
        + (child.get("link_count_inspected") or "0")
    )

    render_verified_links(child, provenance_by_id)

    with st.expander("Status and source evidence", expanded=True):
        st.text_area(
            "Evidence",
            child.get("status_evidence")
            or child.get("evidence_excerpt")
            or "No evidence text captured.",
            height=180,
            disabled=True,
            key="link_safe_evidence_" + child.get("child_id", "unknown"),
        )

    if child.get("quality_flags"):
        st.warning("Evidence flags: " + child["quality_flags"])


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY v3.4.3.8.0.4 Link Integrity",
        page_icon="🔗",
        layout="wide",
    )

    manifest = read_json(MANIFEST_PATH)
    bundles = read_csv(BUNDLES_PATH)
    children = read_csv(CHILDREN_PATH)
    provenance = read_csv(PROVENANCE_PATH)
    withheld = read_csv(WITHHELD_PATH)

    st.title("MeitY Link-Integrity Review")
    st.caption(
        "URL provenance, final-page role validation and cross-entity link "
        "protection. No database write and no publication."
    )

    if not manifest:
        st.error(
            "Run SSIP v3.4.3.8.0.4 before opening this workspace."
        )
        return

    current_signature = manifest.get("session_state_signature", "")
    previous_signature = st.session_state.get(
        "meity_link_integrity_signature",
        "",
    )
    if previous_signature != current_signature:
        had_decisions = bool(
            st.session_state.get("meity_link_safe_decisions")
        )
        st.session_state["meity_link_safe_decisions"] = {}
        st.session_state["meity_link_integrity_signature"] = current_signature
        if had_decisions:
            st.warning(
                "Earlier session decisions were cleared because link "
                "provenance or final-page validation changed."
            )

    decisions: dict[str, dict] = st.session_state.setdefault(
        "meity_link_safe_decisions",
        {},
    )

    metrics = (
        ("Links inspected", manifest.get("links_inspected", 0)),
        (
            "Verified information links",
            manifest.get("verified_information_links", 0),
        ),
        (
            "Verified application routes",
            manifest.get("verified_application_routes", 0),
        ),
        (
            "Application routes withheld",
            manifest.get("withheld_application_routes", 0),
        ),
        (
            "Broken/unverified",
            manifest.get("broken_or_unverified_links", 0),
        ),
        (
            "Cross-entity contamination",
            manifest.get("cross_entity_link_contamination_count", 0),
        ),
    )
    columns = st.columns(len(metrics))
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)

    if manifest.get("global_application_routes_withheld"):
        st.warning(
            "All application and registration routes are globally withheld "
            "because no MeitY child currently has complete current-status "
            "evidence."
        )
    else:
        st.success(
            "Application links are shown only when the exact child, final "
            "page role, official domain, entity match and current-status gate "
            "all pass."
        )

    tab_queue, tab_provenance, tab_withheld = st.tabs(
        [
            "Link-Safe Decision Queue",
            "Complete URL Provenance",
            "Withheld Application Routes",
        ]
    )

    provenance_by_id = {
        row.get("provenance_id", ""): row
        for row in provenance
        if row.get("provenance_id")
    }
    children_by_bundle: dict[str, list[dict[str, str]]] = {}
    for child in children:
        children_by_bundle.setdefault(
            child.get("bundle_id", ""),
            [],
        ).append(child)

    with tab_queue:
        lanes = sorted({row.get("lane", "") for row in bundles if row.get("lane")})
        actions = sorted(
            {
                row.get("recommended_action", "")
                for row in bundles
                if row.get("recommended_action")
            }
        )
        integrity_states = sorted(
            {
                row.get("link_integrity_complete", "")
                for row in bundles
                if row.get("link_integrity_complete")
            }
        )

        f1, f2, f3, f4 = st.columns([2, 1, 1.5, 1])
        keyword = f1.text_input(
            "Search link-safe bundles",
            placeholder="GENESIS, Appscale, SAMRIDH, historical…",
        ).strip().casefold()
        lane_filter = f2.selectbox("Lane", ["ALL", *lanes])
        action_filter = f3.selectbox("Action", ["ALL", *actions])
        integrity_filter = f4.selectbox(
            "Link integrity",
            ["ALL", *integrity_states],
        )

        visible = []
        for row in bundles:
            haystack = " ".join(str(value) for value in row.values()).casefold()
            if keyword and keyword not in haystack:
                continue
            if lane_filter != "ALL" and row.get("lane") != lane_filter:
                continue
            if action_filter != "ALL" and row.get("recommended_action") != action_filter:
                continue
            if (
                integrity_filter != "ALL"
                and row.get("link_integrity_complete") != integrity_filter
            ):
                continue
            visible.append(row)

        visible.sort(
            key=lambda row: (
                0 if row.get("link_integrity_complete") == "False" else 1,
                {
                    "CRITICAL": 0,
                    "HIGH": 1,
                    "MEDIUM": 2,
                    "LOW": 3,
                }.get(row.get("priority", ""), 4),
                row.get("bundle_title", "").casefold(),
            )
        )
        st.write(f"**{len(visible)} matching link-safe bundle(s)**")

        if visible:
            left, centre, right = st.columns([1.0, 1.35, 1.65])

            with left:
                selected_index = st.radio(
                    "Select bundle",
                    range(len(visible)),
                    format_func=lambda index: (
                        ("[LINK OK] " if visible[index].get(
                            "link_integrity_complete"
                        ) == "True" else "[LINK REVIEW] ")
                        + visible[index].get("bundle_title", "Untitled")
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
                    "**Recommended action:**",
                    selected.get("recommended_action"),
                )
                st.write(
                    "**Link integrity:**",
                    "COMPLETE"
                    if truthy(selected.get("link_integrity_complete", ""))
                    else "INCOMPLETE",
                )
                if selected.get("link_integrity_flags"):
                    st.warning(
                        "Bundle link flags: "
                        + selected["link_integrity_flags"]
                    )
                st.info(selected.get("rationale", ""))

                requires_selection = truthy(
                    selected.get("requires_child_selection", "")
                )
                if requires_selection:
                    selected_ids = st.multiselect(
                        "Select child records included in this decision",
                        options=list(child_names),
                        default=[
                            child_id
                            for child_id in saved.get(
                                "selected_child_ids",
                                [],
                            )
                            if child_id in child_names
                        ],
                        format_func=lambda child_id: child_names[child_id],
                    )
                else:
                    selected_ids = list(child_names)
                    st.caption("This bundle includes all listed child records.")

                evidence_options = selected_ids or list(child_names)
                evidence_child_id = st.selectbox(
                    "Evidence child displayed",
                    options=evidence_options,
                    format_func=lambda child_id: child_names[child_id],
                )

            with right:
                child = next(
                    row
                    for row in bundle_children
                    if row.get("child_id") == evidence_child_id
                )
                render_evidence(child, provenance_by_id)

                st.subheader("Link-safe session decision")
                allowed = [
                    value
                    for value in selected.get("allowed_decisions", "").split(";")
                    if value
                ] or ["PENDING", "NEEDS_MORE_EVIDENCE", "DEFER"]

                previous = saved.get("decision", "PENDING")
                decision = st.selectbox(
                    "Decision",
                    allowed,
                    index=allowed.index(previous) if previous in allowed else 0,
                )
                note = st.text_area(
                    "Admin note",
                    value=saved.get("note", ""),
                    height=110,
                    placeholder=(
                        "Record link role, final URL, entity match, missing "
                        "application evidence or reason for withholding."
                    ),
                )

                requires_note = truthy(
                    selected.get("requires_admin_note", "")
                )
                selection_ready = bool(selected_ids) if requires_selection else True
                note_ready = bool(note.strip()) if requires_note else True
                decision_ready = decision != "PENDING"
                positive_decision = decision.startswith("CONFIRM_")
                positive_ready = (
                    truthy(
                        selected.get(
                            "safe_positive_decision_allowed",
                            "",
                        )
                    )
                    if positive_decision
                    else True
                )
                save_ready = (
                    selection_ready
                    and note_ready
                    and decision_ready
                    and positive_ready
                )

                if positive_decision and not positive_ready:
                    st.error(
                        "A positive confirmation is blocked until every "
                        "required link-integrity condition passes."
                    )
                if requires_selection and not selection_ready:
                    st.warning("Select at least one child record.")
                if requires_note and not note_ready:
                    st.warning("A written Admin note is required.")

                if st.button(
                    "Save link-safe session decision",
                    type="primary",
                    use_container_width=True,
                    disabled=not save_ready,
                ):
                    decisions[bundle_id] = {
                        "decision": decision,
                        "selected_child_ids": selected_ids,
                        "note": note.strip(),
                        "bundle_signature": selected.get(
                            "bundle_signature",
                            "",
                        ),
                        "link_integrity_signature": selected.get(
                            "link_integrity_signature",
                            "",
                        ),
                    }
                    st.session_state["meity_link_safe_decisions"] = decisions
                    st.success(
                        "Saved in this browser session only. "
                        "No database or publication change was made."
                    )

                st.download_button(
                    "Download link-safe decision worksheet",
                    data=decision_export(bundles, decisions),
                    file_name=(
                        "meity_link_safe_decisions_v3_4_3_8_0_4.csv"
                    ),
                    mime="text/csv",
                    use_container_width=True,
                )

            with st.expander(
                f"Bundle children ({len(bundle_children)})",
                expanded=False,
            ):
                st.dataframe(
                    [
                        {
                            "canonical_name": child.get("canonical_name", ""),
                            "entity_type": child.get("entity_type", ""),
                            "temporal_validation": child.get(
                                "temporal_validation",
                                "",
                            ),
                            "verified_information_role": child.get(
                                "verified_information_role",
                                "",
                            ),
                            "verified_information_url": child.get(
                                "verified_information_url",
                                "",
                            ),
                            "application_route_withheld": child.get(
                                "application_route_withheld",
                                "",
                            ),
                            "withheld_reason": child.get(
                                "application_route_withheld_reason",
                                "",
                            ),
                        }
                        for child in bundle_children
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    with tab_provenance:
        st.write(
            f"**{len(provenance)} URL provenance record(s)** with requested "
            "URL, final redirected URL, HTTP status, page role, source child "
            "and entity-match confidence."
        )
        if provenance:
            role_filter = st.selectbox(
                "Page role",
                [
                    "ALL",
                    *sorted(
                        {
                            row.get("page_role", "")
                            for row in provenance
                            if row.get("page_role")
                        }
                    ),
                ],
                key="provenance_role_filter",
            )
            status_filter = st.selectbox(
                "Integrity status",
                [
                    "ALL",
                    *sorted(
                        {
                            row.get("link_integrity_status", "")
                            for row in provenance
                            if row.get("link_integrity_status")
                        }
                    ),
                ],
                key="provenance_status_filter",
            )
            visible_links = [
                row
                for row in provenance
                if (
                    role_filter == "ALL"
                    or row.get("page_role") == role_filter
                )
                and (
                    status_filter == "ALL"
                    or row.get("link_integrity_status") == status_filter
                )
            ]
            st.dataframe(
                visible_links,
                use_container_width=True,
                hide_index=True,
            )

    with tab_withheld:
        st.write(
            f"**{len(withheld)} withheld application-route record(s)**. "
            "These raw URLs are visible only for audit and are never rendered "
            "as public or Admin application buttons."
        )
        if withheld:
            st.dataframe(
                withheld,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.caption(
        "Link-integrity signature: "
        + str(manifest.get("link_integrity_signature", ""))
        + " · Historical application links exposed: "
        + str(manifest.get("historical_application_links_exposed", 0))
        + " · Cross-entity contamination: "
        + str(manifest.get("cross_entity_link_contamination_count", 0))
        + " · Database write: No · Publication: No"
    )


if __name__ == "__main__":
    main()
