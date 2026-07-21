from __future__ import annotations

from pathlib import Path
from typing import Any

from services.meity_transparent_classification_v3_4_3_8_0_7 import (
    build_service as build_classification_service,
)
from services.meity_unified_workflow_v3_4_3_8_1 import (
    build_service as build_unified_service,
    clean,
    truthy,
)


def _label(value: str) -> str:
    return clean(value).replace("_", " ").title()


def _record_title(row: dict[str, Any]) -> str:
    return clean(
        row.get("canonical_name")
        or row.get("original_canonical_name")
        or row.get("child_id")
        or "Unnamed record"
    )


def _render_effective_table(
    st: Any,
    rows: list[dict[str, Any]],
) -> None:
    st.dataframe(
        [
            {
                "Record": _record_title(row),
                "Effective category": _label(
                    row.get("effective_entity_type", "")
                ),
                "Parent programme": clean(
                    row.get("effective_parent_scheme_name")
                ),
                "Status": _label(
                    row.get("application_status", "")
                ),
                "Official source": clean(
                    row.get("verified_information_url")
                ),
                "Projection": row.get("projection_status", ""),
                "Reason": (
                    row.get("projection_errors")
                    or row.get("projection_warnings")
                    or "Ready"
                ),
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_overview(
    st: Any,
    unified: Any,
) -> None:
    summary = unified.summary()
    rows = unified.effective_inventory()

    metrics = st.columns(6)
    metrics[0].metric("Source records", summary["record_count"])
    metrics[1].metric("Written classifications", summary["override_count"])
    metrics[2].metric("Programmes", summary["programme_count"])
    metrics[3].metric(
        "Calls & challenges",
        summary["call_challenge_count"],
    )
    metrics[4].metric("Historical", summary["historical_count"])
    metrics[5].metric(
        "Projection eligible",
        summary["projection_eligible_count"],
    )

    st.info(
        "This is the embedded MeitY Admin workspace. Classification, link "
        "review and staging projection are handled here; separate ports "
        "8510–8514 are no longer required for normal Admin work."
    )

    section_counts = {
        "Programmes": summary["programme_count"],
        "Calls / challenges": summary["call_challenge_count"],
        "Historical": summary["historical_count"],
        "Excluded / supporting": summary["excluded_supporting_count"],
        "Needs classification": summary["classification_review_count"],
        "Projection blocked": summary["projection_blocked_count"],
    }
    st.dataframe(
        [
            {"Section": key, "Records": value}
            for key, value in section_counts.items()
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("All effective MeitY records", expanded=False):
        _render_effective_table(st, rows)


def _render_classification(
    st: Any,
    project_root: Path,
) -> None:
    service = build_classification_service(project_root)
    inventory = service.inventory()
    overrides = service.active_overrides()
    labels = service.config.get("entity_type_labels", {})
    allowed = service.config.get("allowed_entity_types", [])

    st.markdown("### Transparent classification and correction")
    st.caption(
        "Select a record, review why it was classified that way, and correct "
        "the type or parent relationship when the official source supports it."
    )

    search = st.text_input(
        "Search MeitY classification records",
        placeholder="CREST, SAMRIDH, challenge, cohort…",
        key="embedded_meity_classification_search",
    ).strip().casefold()
    visible = [
        row
        for row in inventory
        if not search
        or search
        in " ".join(
            [
                _record_title(row),
                clean(row.get("entity_type")),
                clean(row.get("suggested_entity_type")),
            ]
        ).casefold()
    ]
    if not visible:
        st.info("No matching MeitY classification records.")
        return

    selector_col, evidence_col, correction_col = st.columns(
        [1.0, 1.45, 1.25]
    )
    with selector_col:
        selected_index = st.radio(
            "Select a record",
            range(len(visible)),
            format_func=lambda index: (
                ("✓ " if clean(visible[index].get("child_id")) in overrides else "● ")
                + _record_title(visible[index])
            ),
            key="embedded_meity_classification_record",
        )
    row = visible[selected_index]
    child_id = clean(row.get("child_id"))
    active = overrides.get(child_id)

    with evidence_col:
        st.subheader(_record_title(row))
        effective = clean(
            active.get("corrected_entity_type")
            if active
            else row.get("suggested_entity_type")
        )
        st.success(
            "Effective category: "
            + labels.get(effective, _label(effective))
        )
        st.markdown("#### Why it is classified this way")
        for reason in row.get("classification_reasons", []):
            marker = "✓" if reason.get("passed") else "✗"
            if reason.get("passed"):
                st.write(f"{marker} {reason.get('label', '')}")
            else:
                st.caption(f"{marker} {reason.get('label', '')}")

        official_url = clean(row.get("verified_information_url"))
        if official_url:
            st.link_button(
                "Open verified official source",
                official_url,
                use_container_width=True,
            )
        else:
            st.button(
                "Verified source unavailable",
                disabled=True,
                use_container_width=True,
            )

        st.write(
            "**Upstream type:**",
            _label(row.get("entity_type", "")),
        )
        st.write(
            "**Suggested confidence:**",
            f"{float(row.get('classification_confidence') or 0):.0%}",
        )
        st.write(
            "**Current parent:**",
            clean(row.get("repaired_parent_scheme_name"))
            or "No parent / unresolved",
        )

        with st.expander("Advanced evidence", expanded=False):
            st.json(
                {
                    "temporal_validation": row.get(
                        "temporal_validation"
                    ),
                    "verified_information_role": row.get(
                        "verified_information_role"
                    ),
                    "verified_application_url": row.get(
                        "verified_application_url"
                    ),
                    "parent_link_resolution": row.get(
                        "parent_link_resolution"
                    ),
                    "classification_reasons": row.get(
                        "classification_reasons"
                    ),
                }
            )

    with correction_col:
        st.markdown("#### Correct the type")
        current_type = (
            active.get("corrected_entity_type")
            if active
            else row.get("suggested_entity_type")
        )
        corrected_type = st.selectbox(
            "Record category",
            allowed,
            index=allowed.index(current_type)
            if current_type in allowed
            else 0,
            format_func=lambda code: labels.get(code, _label(code)),
            key=f"embedded_meity_type_{child_id}",
        )

        call_like = corrected_type in {
            "APPLICATION_CALL",
            "CHALLENGE_CALL",
            "ACCELERATOR_COHORT",
        }
        programmes = [
            item
            for item in inventory
            if clean(item.get("suggested_entity_type"))
            in {"PERMANENT_PROGRAMME", "PERMANENT_SCHEME"}
            and clean(item.get("child_id")) != child_id
        ]
        parent_map = {
            "": "No parent / unresolved",
            **{
                clean(item.get("child_id")): _record_title(item)
                for item in programmes
            },
        }
        if call_like:
            existing_parent = clean(
                active.get("corrected_parent_master_id")
                if active
                else row.get("repaired_parent_master_id")
            )
            parent_id = st.selectbox(
                "Parent programme",
                list(parent_map),
                index=(
                    list(parent_map).index(existing_parent)
                    if existing_parent in parent_map
                    else 0
                ),
                format_func=lambda value: parent_map[value],
                key=f"embedded_meity_parent_{child_id}",
            )
            parent_name = parent_map[parent_id] if parent_id else ""
        else:
            parent_id = ""
            parent_name = ""
            st.caption(
                "Parent programme is used only for calls, challenges and "
                "cohort/application windows."
            )

        note = st.text_area(
            "Admin reason",
            value=active.get("admin_note", "") if active else "",
            placeholder=(
                "Example: The official page is a permanent programme. "
                "The dated cohort is maintained separately."
            ),
            key=f"embedded_meity_reason_{child_id}",
        )
        actor = st.text_input(
            "Admin name",
            value=active.get("actor", "Admin") if active else "Admin",
            key=f"embedded_meity_actor_{child_id}",
        )

        try:
            preview = service.preview(
                child_id=child_id,
                corrected_entity_type=corrected_type,
                corrected_parent_scheme_name=parent_name,
                corrected_parent_master_id=parent_id,
                admin_note=note,
                actor=actor,
            )
        except Exception as exc:
            preview = {}
            st.warning(str(exc))

        confirmation = st.text_input(
            'Type exactly: "WRITE CLASSIFICATION"',
            key=f"embedded_meity_confirm_{child_id}",
        )
        acknowledgement = st.checkbox(
            "I reviewed the official source and this classification.",
            key=f"embedded_meity_ack_{child_id}",
        )
        ready = (
            bool(preview)
            and acknowledgement
            and confirmation == "WRITE CLASSIFICATION"
        )
        if st.button(
            "Save governed classification",
            type="primary",
            use_container_width=True,
            disabled=not ready,
            key=f"embedded_meity_save_{child_id}",
        ):
            result = service.apply(preview, confirmation)
            st.success(
                "Classification saved. Public visibility was not changed."
            )
            st.write("**Database backup:**", result["backup_path"])
            st.rerun()


def _render_link_parent_review(
    st: Any,
    unified: Any,
) -> None:
    rows = unified.effective_inventory()
    st.markdown("### Link, date and parent validation")
    st.caption(
        "Review verified official pages, application-route safety, temporal "
        "status and the parent programme in one place."
    )

    search = st.text_input(
        "Search validation records",
        placeholder="Challenge, cohort, programme or official page",
        key="embedded_meity_link_search",
    ).strip().casefold()
    visible = [
        row
        for row in rows
        if not search
        or search
        in " ".join(
            [
                _record_title(row),
                clean(row.get("effective_entity_type")),
                clean(row.get("verified_information_url")),
                clean(row.get("effective_parent_scheme_name")),
            ]
        ).casefold()
    ]
    if not visible:
        st.info("No matching validation records.")
        return

    index = st.selectbox(
        "Select a record",
        range(len(visible)),
        format_func=lambda value: _record_title(visible[value]),
        key="embedded_meity_link_record",
    )
    row = visible[index]

    metrics = st.columns(4)
    metrics[0].metric(
        "Category",
        _label(row.get("effective_entity_type", "")),
    )
    metrics[1].metric(
        "Status",
        _label(row.get("application_status", "")),
    )
    metrics[2].metric(
        "Link integrity",
        "Complete"
        if truthy(row.get("link_integrity_complete"))
        else "Needs evidence",
    )
    metrics[3].metric(
        "Projection",
        row.get("projection_status", ""),
    )

    left, right = st.columns(2)
    with left:
        st.write(
            "**Verified information page:**",
            clean(row.get("verified_information_url"))
            or "Not verified",
        )
        if clean(row.get("verified_information_url")):
            st.link_button(
                "Open official information page",
                row["verified_information_url"],
                use_container_width=True,
            )
        st.write(
            "**Verified application route:**",
            clean(row.get("verified_application_url"))
            or "Withheld / unavailable",
        )
        if row.get("apply_action_allowed"):
            st.link_button(
                "Open verified application route",
                row["verified_application_url"],
                use_container_width=True,
            )
        else:
            st.button(
                "No safe Apply action",
                disabled=True,
                use_container_width=True,
            )
    with right:
        st.write(
            "**Temporal validation:**",
            _label(row.get("temporal_validation", "")),
        )
        st.write(
            "**Parent programme:**",
            clean(row.get("effective_parent_scheme_name"))
            or "No parent / unresolved",
        )
        st.write(
            "**Parent ID:**",
            clean(row.get("effective_parent_master_id"))
            or "Not recorded",
        )
        st.write(
            "**Blocking reason:**",
            clean(row.get("projection_errors")) or "None",
        )
        st.write(
            "**Warnings:**",
            clean(row.get("projection_warnings")) or "None",
        )


def _render_dashboard_projection(
    st: Any,
    unified: Any,
) -> None:
    rows = unified.effective_inventory()
    plan = unified.projection_plan()

    st.markdown("### Dashboard preview and Admin-review projection")
    st.caption(
        "Preview the effective MeitY categories here. Eligible records can be "
        "projected into the normal Admin Review Inbox as PENDING."
    )

    tab_programmes, tab_calls, tab_history, tab_excluded, tab_gate = st.tabs(
        [
            "Programmes",
            "Calls & Challenges",
            "Historical",
            "Excluded / Blocked",
            "Project to Admin Review",
        ]
    )
    with tab_programmes:
        _render_effective_table(
            st,
            [
                row
                for row in rows
                if row["dashboard_section"] == "PROGRAMMES"
            ],
        )
    with tab_calls:
        st.info(
            "A call identity can be retained without being marked OPEN. "
            "OPEN requires a verified current application route."
        )
        _render_effective_table(
            st,
            [
                row
                for row in rows
                if row["dashboard_section"] == "CALLS_CHALLENGES"
            ],
        )
    with tab_history:
        st.success(
            "Historical references never expose an Apply action."
        )
        _render_effective_table(
            st,
            [
                row
                for row in rows
                if row["dashboard_section"] == "HISTORICAL"
            ],
        )
    with tab_excluded:
        _render_effective_table(
            st,
            [
                row
                for row in rows
                if not row["projection_eligible"]
            ],
        )
    with tab_gate:
        eligible = [
            row for row in rows if row["projection_eligible"]
        ]
        blocked = [
            row for row in rows if not row["projection_eligible"]
        ]
        metrics = st.columns(4)
        metrics[0].metric("Eligible", len(eligible))
        metrics[1].metric("Blocked", len(blocked))
        metrics[2].metric("Public changes", 0)
        metrics[3].metric("Publication actions", 0)

        st.warning(
            "Projection imports eligible records as PENDING into the existing "
            "Admin Review Inbox. It does not approve, stage or publish them."
        )
        actor = st.text_input(
            "Admin name",
            value="Admin",
            key="embedded_meity_projection_actor",
        )
        acknowledgement = st.checkbox(
            "I reviewed the eligible and blocked records.",
            key="embedded_meity_projection_ack",
        )
        confirmation = st.text_input(
            'Type exactly: "PROJECT TO ADMIN REVIEW"',
            key="embedded_meity_projection_confirm",
        )
        ready = (
            bool(eligible)
            and acknowledgement
            and confirmation == "PROJECT TO ADMIN REVIEW"
        )
        if st.button(
            "Import eligible MeitY records as PENDING",
            type="primary",
            use_container_width=True,
            disabled=not ready,
            key="embedded_meity_projection_apply",
        ):
            result = unified.apply_projection(
                expected_signature=plan["plan_signature"],
                confirmation=confirmation,
                actor=actor,
            )
            st.success(
                "MeitY projection completed. Open Verify Pending Records to "
                "review the imported records."
            )
            st.json(result)
            st.cache_resource.clear()
            st.rerun()

        st.caption(
            "Plan signature: " + plan["plan_signature"]
        )


def _render_audit(
    st: Any,
    unified: Any,
) -> None:
    audits = unified.audit_rows()
    st.markdown("### MeitY audit")
    classification_tab, projection_tab = st.tabs(
        ["Classification writes", "Projection actions"]
    )
    with classification_tab:
        if audits["classification"]:
            st.dataframe(
                audits["classification"],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No classification writes are recorded.")
    with projection_tab:
        if audits["projection"]:
            st.dataframe(
                audits["projection"],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No projection actions are recorded.")


def render_meity_admin_intelligence(
    st: Any,
    project_root: Path,
) -> None:
    unified = build_unified_service(project_root)

    st.subheader("MeitY Intelligence Review")
    st.caption(
        "Classification, official-link validation, dashboard preview and "
        "projection into the normal Admin Review Inbox."
    )

    overview, classification, links, projection, audit = st.tabs(
        [
            "Overview",
            "Classification & Type Correction",
            "Links, Dates & Parent",
            "Dashboard & Projection",
            "Audit",
        ]
    )
    with overview:
        _render_overview(st, unified)
    with classification:
        _render_classification(st, project_root)
    with links:
        _render_link_parent_review(st, unified)
    with projection:
        _render_dashboard_projection(st, unified)
    with audit:
        _render_audit(st, unified)
