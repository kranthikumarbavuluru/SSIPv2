from __future__ import annotations

from pathlib import Path
from typing import Any

from services.admin_quick_editor_v3_4_3_8_1 import (
    build_service,
    clean,
)


def _category_label(code: str, labels: dict[str, str]) -> str:
    return labels.get(code, code.replace("_", " ").title())


def _current_category(record: dict[str, Any]) -> str:
    explicit = clean(
        (record.get("raw_record") or {}).get("admin_category")
    )
    if explicit:
        return explicit
    kind = clean(record.get("record_kind")).upper()
    return {
        "SCHEME": "SCHEME",
        "PROGRAMME": "PROGRAMME",
        "PROGRAM": "PROGRAMME",
        "APPLICATION_CALL": "APPLICATION_CALL",
        "CALL": "APPLICATION_CALL",
        "CHALLENGE": "CHALLENGE",
        "ACCELERATOR_COHORT": "COHORT",
        "HISTORICAL_REFERENCE": "HISTORICAL_REFERENCE",
        "RESULT_ANNOUNCEMENT": "HISTORICAL_REFERENCE",
        "SUPPORTING_DOCUMENT": "SUPPORTING_DOCUMENT",
        "NON_CATALOGUE": "NON_CATALOGUE",
    }.get(kind, "PROGRAMME")


def _current_status(record: dict[str, Any], category: str) -> str:
    if category in {"SCHEME", "PROGRAMME"}:
        value = clean(
            record.get("scheme_status")
            or record.get("programme_status")
        ).upper()
        return value if value in {"OPEN", "CLOSED"} else "OPEN"
    value = clean(record.get("application_status")).upper()
    return (
        value
        if value
        in {"OPEN", "UPCOMING", "CLOSED", "VERIFICATION_REQUIRED"}
        else "VERIFICATION_REQUIRED"
    )


def _record_multi(
    record: dict[str, Any],
    key: str,
    allowed: list[str],
) -> list[str]:
    raw = record.get(key) or (record.get("raw_record") or {}).get(key)
    if isinstance(raw, str):
        raw = [item for item in raw.replace(",", ";").split(";")]
    values = {clean(item).upper().replace(" ", "_") for item in (raw or [])}
    selected = [value for value in allowed if value in values]
    return selected or list(allowed)


def _multi_checkboxes(
    st: Any,
    *,
    title: str,
    options: list[str],
    labels: dict[str, str],
    current: list[str],
    key_prefix: str,
) -> list[str]:
    st.markdown(f"#### {title}")
    all_key = f"{key_prefix}_all"
    child_keys = {
        option: f"{key_prefix}_{option}"
        for option in options
    }

    if all_key not in st.session_state:
        st.session_state[all_key] = set(current) == set(options)
    for option, child_key in child_keys.items():
        if child_key not in st.session_state:
            st.session_state[child_key] = option in current

    def sync_all() -> None:
        checked = bool(st.session_state.get(all_key))
        for child_key in child_keys.values():
            st.session_state[child_key] = checked

    all_selected = st.checkbox(
        "All",
        key=all_key,
        on_change=sync_all,
    )
    selected: list[str] = []
    for option, child_key in child_keys.items():
        checked = st.checkbox(
            labels.get(option, option.replace("_", " ").title()),
            key=child_key,
            disabled=all_selected,
        )
        if all_selected or checked:
            selected.append(option)
    return selected


def render_admin_quick_editor(
    st: Any,
    project_root: Path,
) -> None:
    service = build_service(project_root)
    config = service.config
    labels = config.get("category_labels", {})
    categories = config.get("categories", [])

    st.subheader("Quick Scheme, Programme & Call Editor")
    st.caption(
        "Filter by ministry or department, select one record and update only "
        "its category, status, applicant type, startup stage and funding values."
    )
    st.warning(
        "Published records are never changed live by this editor. "
        "Their edits are saved as pending publication review."
    )

    all_records = service.list_records()
    counters = service.completeness_dashboard(all_records)
    metric_labels = [
        ("total_records", "Total records"),
        ("category_missing", "Category missing"),
        ("status_missing", "Status missing"),
        ("type_missing", "Type missing"),
        ("stage_missing", "Stage missing"),
        ("funding_missing", "Funding missing"),
        ("official_source_missing", "Official source missing"),
        ("parent_programme_missing", "Parent programme missing"),
        ("ready_for_publication_review", "Ready for publication review"),
    ]
    for start in range(0, len(metric_labels), 3):
        columns = st.columns(3)
        for column, (key, label) in zip(columns, metric_labels[start:start + 3]):
            column.metric(label, counters[key])

    options = service.filter_options()
    filter_1, filter_2, filter_3, filter_4 = st.columns([1.1, 1.1, 1.5, 1.4])
    ministry = filter_1.selectbox(
        "Ministry",
        ["", *options["ministries"]],
        format_func=lambda value: value or "All ministries",
        key="quick_editor_ministry",
    )
    department = filter_2.selectbox(
        "Department",
        ["", *options["departments"]],
        format_func=lambda value: value or "All departments",
        key="quick_editor_department",
    )
    keyword = filter_3.text_input(
        "Search",
        placeholder="Scheme, programme, challenge or call name",
        key="quick_editor_search",
    )
    completeness_filter = filter_4.selectbox(
        "Completion filter",
        [
            "ALL", "INCOMPLETE", "MISSING_CATEGORY", "MISSING_STATUS",
            "MISSING_TYPE", "MISSING_STAGE", "MISSING_FUNDING",
            "PUBLISHED_PENDING",
        ],
        format_func=lambda value: {
            "ALL": "All records",
            "INCOMPLETE": "Only incomplete records",
            "MISSING_CATEGORY": "Missing category",
            "MISSING_STATUS": "Missing status",
            "MISSING_TYPE": "Missing Type",
            "MISSING_STAGE": "Missing Stage",
            "MISSING_FUNDING": "Missing funding",
            "PUBLISHED_PENDING": "Published changes pending",
        }[value],
        key="quick_editor_completion_filter",
    )

    records = service.list_records(
        ministry=ministry,
        department=department,
        keyword=keyword,
        completeness_filter=completeness_filter,
    )
    if not records:
        st.info("No records match the selected ministry or department.")
        return

    count_col, download_col = st.columns([2.4, 1.0])
    count_col.write(f"**{len(records)} record(s) available**")
    download_col.download_button(
        "Download filtered CSV",
        data=service.export_csv(records),
        file_name=f"SSIP_Quick_Editor_{len(records)}_Records.csv",
        mime="text/csv",
        use_container_width=True,
        key="quick_editor_csv_download",
    )
    uploaded_csv = st.file_uploader(
        "Upload completed Quick Editor CSV",
        type=["csv"],
        help="Only category, status, Type, Stage, funding and Admin note may change.",
        key="quick_editor_csv_upload",
    )
    if uploaded_csv is not None:
        import_preview = service.preview_csv_import(uploaded_csv.getvalue())
        if import_preview["errors"]:
            for error in import_preview["errors"]:
                st.error(error)
        else:
            st.success(f"Validated {len(import_preview['previews'])} CSV change(s).")
            st.dataframe(
                [
                    {
                        "Master ID": item["master_id"],
                        "Record": item["columns"]["scheme_name"],
                        "Category": item["category"],
                        "Status": item["status_value"],
                        "Publication action": "NONE",
                    }
                    for item in import_preview["previews"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            csv_confirmation = st.text_input(
                'Confirm CSV import by typing "SAVE QUICK EDIT"',
                key="quick_editor_csv_confirmation",
            )
            if st.button(
                "Apply validated CSV changes",
                disabled=csv_confirmation != config.get("confirmation_phrase"),
                key="quick_editor_csv_apply",
            ):
                results = service.apply_csv_import(import_preview, confirmation=csv_confirmation)
                st.success(f"Applied {len(results)} governed change(s); publication action: NONE.")
    labels_by_index = {
        index: (
            f"{record.get('scheme_name') or 'Unnamed'} — "
            f"{record.get('department') or record.get('ministry') or record.get('source') or 'Unassigned'}"
        )
        for index, record in enumerate(records)
    }
    selected_index = st.selectbox(
        "Select scheme, programme, call or challenge",
        list(labels_by_index),
        format_func=lambda index: labels_by_index[index],
        key="quick_editor_record",
    )
    record = records[selected_index]
    st.caption(
        "Metadata status: " + clean(record.get("readiness_status")).replace("_", " ").title()
    )

    summary = st.columns(6)
    summary[0].metric(
        "Current category",
        clean(record.get("record_kind")).replace("_", " ").title()
        or "Unclassified",
    )
    summary[1].metric(
        "Current status",
        clean(
            record.get("scheme_status")
            or record.get("application_status")
            or record.get("programme_status")
        ).replace("_", " ").title()
        or "Not recorded",
    )
    summary[2].metric(
        "Minimum fund",
        record.get("funding_minimum")
        if record.get("funding_minimum") not in (None, "")
        else "Not recorded",
    )
    summary[3].metric(
        "Maximum fund",
        record.get("funding_maximum")
        if record.get("funding_maximum") not in (None, "")
        else "Not recorded",
    )
    applicant_options = config.get("applicant_types", [])
    stage_options = config.get("startup_stages", [])
    current_applicant_types = _record_multi(
        record, "applicant_types", applicant_options
    )
    current_startup_stages = _record_multi(
        record, "startup_stages", stage_options
    )
    summary[4].metric(
        "Type",
        "All"
        if set(current_applicant_types) == set(applicant_options)
        else ", ".join(
            config.get("applicant_type_labels", {}).get(value, value)
            for value in current_applicant_types
        ),
    )
    summary[5].metric(
        "Stage",
        "All"
        if set(current_startup_stages) == set(stage_options)
        else ", ".join(
            config.get("startup_stage_labels", {}).get(value, value)
            for value in current_startup_stages
        ),
    )

    left, middle, right = st.columns([1.25, 1.0, 1.0])

    with left:
        st.markdown("### 1. Select one category")
        current_category = _current_category(record)
        selected_categories: list[str] = []
        category_columns = st.columns(2)
        for index, category in enumerate(categories):
            checked = category_columns[index % 2].checkbox(
                _category_label(category, labels),
                value=category == current_category,
                key=(
                    f"quick_category_{record['master_id']}_{category}"
                ),
            )
            if checked:
                selected_categories.append(category)

        if len(selected_categories) != 1:
            st.error("Select exactly one category checkbox.")

    with middle:
        selected_category = (
            selected_categories[0]
            if len(selected_categories) == 1
            else current_category
        )
        st.markdown("### 2. Select one status")
        permanent = selected_category in {"SCHEME", "PROGRAMME"}
        status_options = config.get(
            "scheme_programme_statuses"
            if permanent
            else "call_statuses",
            [],
        )
        current_status = _current_status(record, selected_category)
        selected_statuses: list[str] = []
        for status in status_options:
            checked = st.checkbox(
                status.replace("_", " ").title(),
                value=status == current_status,
                key=(
                    f"quick_status_{record['master_id']}_{status}"
                ),
            )
            if checked:
                selected_statuses.append(status)

        if permanent:
            st.caption(
                "For schemes and programmes, choose Open or Closed."
            )
        else:
            st.caption(
                "Calls and challenges may be Open, Upcoming, Closed or "
                "Verification Required."
            )
        if len(selected_statuses) != 1:
            st.error("Select exactly one status checkbox.")

    with right:
        st.markdown("### 3. Enter funding")
        existing_minimum = record.get("funding_minimum")
        existing_maximum = record.get("funding_maximum")
        funding_minimum = st.number_input(
            "Minimum fund value (INR)",
            min_value=0.0,
            value=float(existing_minimum or 0),
            step=1000.0,
            key=f"quick_fund_min_{record['master_id']}",
        )
        funding_maximum = st.number_input(
            "Maximum fund value (INR)",
            min_value=0.0,
            value=float(existing_maximum or 0),
            step=1000.0,
            key=f"quick_fund_max_{record['master_id']}",
        )
        no_minimum = st.checkbox(
            "Minimum not available",
            value=existing_minimum in (None, ""),
            key=f"quick_no_min_{record['master_id']}",
        )
        no_maximum = st.checkbox(
            "Maximum not available",
            value=existing_maximum in (None, ""),
            key=f"quick_no_max_{record['master_id']}",
        )
        minimum_value = None if no_minimum else funding_minimum
        maximum_value = None if no_maximum else funding_maximum

    st.markdown("### 4. Select applicant type and startup stage")
    type_col, stage_col = st.columns(2)
    with type_col:
        selected_applicant_types = _multi_checkboxes(
            st,
            title="TYPE",
            options=applicant_options,
            labels=config.get("applicant_type_labels", {}),
            current=current_applicant_types,
            key_prefix=f"quick_type_{record['master_id']}",
        )
    with stage_col:
        selected_startup_stages = _multi_checkboxes(
            st,
            title="STAGE",
            options=stage_options,
            labels=config.get("startup_stage_labels", {}),
            current=current_startup_stages,
            key_prefix=f"quick_stage_{record['master_id']}",
        )

    st.markdown("### 5. Preview and save")
    editor_col, note_col = st.columns([1, 2])
    editor = editor_col.text_input(
        "Admin name",
        value="Admin",
        key=f"quick_editor_name_{record['master_id']}",
    )
    note = note_col.text_area(
        "Reason or note",
        placeholder=(
            "Example: Official scheme page confirms that this is a "
            "permanent programme and the maximum support is ₹50 lakh."
        ),
        height=90,
        key=f"quick_editor_note_{record['master_id']}",
    )

    try:
        preview = service.preview(
            master_id=record["master_id"],
            source_table=record["source_table"],
            selected_categories=selected_categories,
            selected_statuses=selected_statuses,
            selected_applicant_types=selected_applicant_types,
            selected_startup_stages=selected_startup_stages,
            funding_minimum=minimum_value,
            funding_maximum=maximum_value,
            editor=editor,
            note=note,
        )
        preview_error = ""
    except Exception as exc:
        preview = {}
        preview_error = str(exc)
        st.warning(preview_error)

    if preview:
        st.dataframe(
            [
                {
                    "Record": preview["columns"]["scheme_name"],
                    "Category": _category_label(
                        preview["category"],
                        labels,
                    ),
                    "Status": preview["status_value"].replace(
                        "_",
                        " ",
                    ).title(),
                    "Minimum fund": preview["columns"][
                        "funding_minimum"
                    ],
                    "Maximum fund": preview["columns"][
                        "funding_maximum"
                    ],
                    "Type": "; ".join(
                        config.get("applicant_type_labels", {}).get(value, value)
                        for value in preview["applicant_types"]
                    ),
                    "Stage": "; ".join(
                        config.get("startup_stage_labels", {}).get(value, value)
                        for value in preview["startup_stages"]
                    ),
                    "Public action": "None",
                }
            ],
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("Preview in Main Dashboard", expanded=False):
            projected = {**record, "raw_record": preview["after"]}
            public_preview = service.public_dashboard_preview(projected)
            st.dataframe([public_preview], use_container_width=True, hide_index=True)
            st.caption("Preview only. No publication action is performed.")

    acknowledgement = st.checkbox(
        "I reviewed this category, status, type, stage and funding update.",
        key=f"quick_ack_{record['master_id']}",
    )
    confirmation = st.text_input(
        'Type exactly: "SAVE QUICK EDIT"',
        key=f"quick_confirm_{record['master_id']}",
    )
    ready = (
        bool(preview)
        and acknowledgement
        and confirmation == config.get("confirmation_phrase")
    )
    if st.button(
        "Save governed quick edit",
        type="primary",
        use_container_width=True,
        disabled=not ready,
        key=f"quick_save_{record['master_id']}",
    ):
        result = service.apply(
            preview,
            confirmation=confirmation,
        )
        st.success(
            "Quick edit saved. "
            + (
                "The published record was not changed live; it now requires "
                "publication review."
                if result["write_result"]
                == "PENDING_PUBLICATION_REVIEW"
                else "The Admin record was updated."
            )
        )
        st.write("**Database backup:**", result["backup_path"])
        st.write("**Write result:**", result["write_result"])
        st.write("**Publication action:**", result["publication_action"])
        st.rerun()

    with st.expander("Recent quick edits", expanded=False):
        edits = service.recent_edits()
        if edits:
            st.dataframe(
                edits,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No quick edits have been recorded.")
