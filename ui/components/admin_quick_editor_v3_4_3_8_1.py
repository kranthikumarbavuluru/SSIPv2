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
        "its category, status and funding values."
    )
    st.warning(
        "Published records are never changed live by this editor. "
        "Their edits are saved as pending publication review."
    )

    options = service.filter_options()
    filter_1, filter_2, filter_3 = st.columns([1.2, 1.2, 1.8])
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

    records = service.list_records(
        ministry=ministry,
        department=department,
        keyword=keyword,
    )
    if not records:
        st.info("No records match the selected ministry or department.")
        return

    st.write(f"**{len(records)} record(s) available**")
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

    summary = st.columns(4)
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

    st.markdown("### 4. Preview and save")
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
                    "Public action": "None",
                }
            ],
            use_container_width=True,
            hide_index=True,
        )

    acknowledgement = st.checkbox(
        "I reviewed this category, status and funding update.",
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
