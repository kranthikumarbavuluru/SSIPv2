from __future__ import annotations

from pathlib import Path

import streamlit as st

from services.meity_transparent_classification_v3_4_3_8_0_7 import (
    build_service,
    classification_family,
    clean,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def label_for(code: str, labels: dict[str, str]) -> str:
    return labels.get(code, code.replace("_", " ").title())


def reason_line(reason: dict) -> str:
    symbol = "✓" if reason.get("passed") else "✗"
    return f"{symbol} {reason.get('label', '')}"


def main() -> None:
    st.set_page_config(
        page_title="SSIP MeitY Transparent Classification",
        page_icon="🧭",
        layout="wide",
    )

    service = build_service(PROJECT_ROOT)
    config = service.config
    inventory = service.inventory()
    overrides = service.active_overrides()
    labels = config.get("entity_type_labels", {})
    allowed_types = config.get("allowed_entity_types", [])

    st.title("MeitY Transparent Classification Review")
    st.caption(
        "See why each record is treated as a programme, call, challenge, "
        "cohort, historical reference or supporting document. Admin write "
        "mode records corrections in a governed override layer."
    )

    st.warning(
        "Classification write mode does not publish records and does not "
        "change public visibility. It writes only to the dedicated override "
        "and audit tables after an exact confirmation."
    )

    confirmed_count = len(overrides)
    changed_count = sum(
        1
        for row in overrides.values()
        if row.get("corrected_entity_type")
        != row.get("original_entity_type")
    )
    cols = st.columns(4)
    cols[0].metric("Records", len(inventory))
    cols[1].metric("Written classifications", confirmed_count)
    cols[2].metric("Type corrections", changed_count)
    cols[3].metric("Publication changes", 0)

    keyword = st.text_input(
        "Search records",
        placeholder="CREST, SAMRIDH, challenge, cohort…",
    ).strip().casefold()

    visible = [
        row
        for row in inventory
        if not keyword
        or keyword
        in " ".join(
            [
                clean(row.get("canonical_name")),
                clean(row.get("suggested_label")),
                clean(row.get("entity_type")),
                clean(row.get("bundle_title")),
            ]
        ).casefold()
    ]
    visible.sort(
        key=lambda row: (
            0 if clean(row.get("child_id")) not in overrides else 1,
            clean(row.get("canonical_name")).casefold(),
        )
    )

    if not visible:
        st.info("No matching records.")
        return

    queue_col, explanation_col, correction_col = st.columns(
        [1.0, 1.55, 1.35]
    )

    with queue_col:
        selected_index = st.radio(
            "Choose a record",
            range(len(visible)),
            format_func=lambda index: (
                ("✓ " if clean(visible[index].get("child_id")) in overrides else "● ")
                + clean(visible[index].get("canonical_name"))
            ),
        )
    row = visible[selected_index]
    child_id = clean(row.get("child_id"))
    active = overrides.get(child_id)

    with explanation_col:
        st.header(clean(row.get("canonical_name")) or "Unnamed record")

        current_type = clean(
            active.get("corrected_entity_type")
            if active
            else row.get("suggested_entity_type")
        )
        st.success(
            "Effective classification: "
            + label_for(current_type, labels)
        )

        st.markdown("### Why the system classified it this way")
        for reason in row.get("classification_reasons", []):
            if reason.get("passed"):
                st.write(reason_line(reason))
            else:
                st.caption(reason_line(reason))

        st.markdown("### Programme or call distinction")
        is_permanent = current_type in {
            "PERMANENT_PROGRAMME",
            "PERMANENT_SCHEME",
        }
        is_call = current_type in {
            "APPLICATION_CALL",
            "CHALLENGE_CALL",
            "ACCELERATOR_COHORT",
        }
        is_historical = current_type in {
            "HISTORICAL_REFERENCE",
            "RESULT_ANNOUNCEMENT",
        }

        if is_permanent:
            st.info(
                "This is treated as a permanent identity. A temporary cohort, "
                "challenge or application window must be stored separately."
            )
        elif is_call:
            st.info(
                "This is treated as a time-bound opportunity. It must remain "
                "separate from its permanent parent programme."
            )
        elif is_historical:
            st.info(
                "This is retained as past evidence or a result reference. "
                "It cannot expose an Apply action."
            )
        else:
            st.info(
                "This record is supporting evidence or is not yet suitable "
                "for the public catalogue."
            )

        basic = st.columns(3)
        basic[0].metric(
            "Upstream type",
            clean(row.get("entity_type")).replace("_", " ").title(),
        )
        basic[1].metric(
            "Suggested confidence",
            f"{float(row.get('classification_confidence') or 0):.0%}",
        )
        basic[2].metric(
            "Verified Apply route",
            "Yes" if clean(row.get("verified_application_url")) else "No",
        )

        official_url = clean(row.get("verified_information_url"))
        if official_url:
            st.link_button(
                "Open verified official source",
                official_url,
                use_container_width=True,
            )
        else:
            st.button(
                "Verified official source unavailable",
                disabled=True,
                use_container_width=True,
            )

        with st.expander("Advanced evidence", expanded=False):
            st.write("**Bundle:**", clean(row.get("bundle_title")))
            st.write(
                "**Temporal validation:**",
                clean(row.get("temporal_validation")),
            )
            st.write(
                "**Verified page role:**",
                clean(row.get("verified_information_role")),
            )
            st.write(
                "**Parent-link result:**",
                clean(row.get("parent_link_resolution")),
            )
            st.write(
                "**Suggested type:**",
                clean(row.get("suggested_entity_type")),
            )
            st.text_area(
                "Evidence excerpt",
                clean(row.get("status_evidence"))
                or clean(row.get("evidence_excerpt"))
                or "No evidence excerpt.",
                height=180,
                disabled=True,
                key=f"evidence_{child_id}",
            )

    with correction_col:
        st.markdown("### Admin type correction")

        default_type = (
            active.get("corrected_entity_type")
            if active
            else row.get("suggested_entity_type")
        )
        default_index = (
            allowed_types.index(default_type)
            if default_type in allowed_types
            else 0
        )
        corrected_type = st.selectbox(
            "Correct record type",
            allowed_types,
            index=default_index,
            format_func=lambda code: label_for(code, labels),
        )

        call_like = corrected_type in {
            "APPLICATION_CALL",
            "CHALLENGE_CALL",
            "ACCELERATOR_COHORT",
        }
        programme_options = [
            item
            for item in inventory
            if item.get("suggested_entity_type")
            in {"PERMANENT_PROGRAMME", "PERMANENT_SCHEME"}
            and item.get("child_id") != child_id
        ]
        parent_labels = {
            "": "No parent / unresolved",
            **{
                clean(item.get("child_id")): clean(item.get("canonical_name"))
                for item in programme_options
            },
        }

        if call_like:
            current_parent_id = (
                active.get("corrected_parent_master_id")
                if active
                else clean(row.get("repaired_parent_master_id"))
            )
            options = list(parent_labels)
            parent_id = st.selectbox(
                "Parent programme",
                options,
                index=options.index(current_parent_id)
                if current_parent_id in options
                else 0,
                format_func=lambda value: parent_labels[value],
            )
            parent_name = parent_labels[parent_id] if parent_id else ""
        else:
            parent_id = ""
            parent_name = ""
            st.caption(
                "Permanent schemes, historical references and supporting "
                "documents do not receive a parent call relationship."
            )

        original_type = clean(row.get("entity_type"))
        changing_type = (
            classification_family(corrected_type)
            != classification_family(original_type)
        )
        note = st.text_area(
            "Admin reason"
            + (" — required for a correction" if changing_type else " — optional"),
            value=active.get("admin_note", "") if active else "",
            height=130,
            placeholder=(
                "Example: Official page is a permanent accelerator programme; "
                "the cohort page is stored separately as a call instance."
            ),
        )
        actor = st.text_input(
            "Admin name",
            value=active.get("actor", "Admin") if active else "Admin",
        )

        st.markdown("### Save mode")
        mode = st.radio(
            "Choose save mode",
            ["Preview only", "Governed database write"],
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
            preview_error = ""
        except Exception as exc:
            preview = {}
            preview_error = str(exc)
            st.error(preview_error)

        if mode == "Preview only":
            st.info(
                "Preview mode checks the correction but does not write it."
            )
            if preview:
                st.json(
                    {
                        "record": preview["canonical_name"],
                        "original_type": preview["original_entity_type"],
                        "corrected_type": preview["corrected_entity_type"],
                        "record_kind": preview["corrected_record_kind"],
                        "parent": preview["corrected_parent_scheme_name"],
                        "database_write": False,
                        "publication_action": "NONE",
                    }
                )
        else:
            st.warning(
                "Write mode creates a consistent SQLite backup, writes one "
                "active classification override and one audit record, and "
                "preserves staging and publication table counts."
            )
            acknowledgement = st.checkbox(
                "I understand this writes only the classification override "
                "and does not publish the record."
            )
            confirmation = st.text_input(
                'Type exactly: "WRITE CLASSIFICATION"',
            )
            ready = (
                bool(preview)
                and acknowledgement
                and confirmation
                == config.get("confirmation_phrase")
            )

            if st.button(
                "Write governed classification",
                type="primary",
                use_container_width=True,
                disabled=not ready,
            ):
                result = service.apply(preview, confirmation)
                st.success(
                    "Classification override written successfully. "
                    "Public visibility was not changed."
                )
                st.write("**Database backup:**", result["backup_path"])
                st.write(
                    "**Core staging/publication counts preserved:**",
                    result["core_table_counts_preserved"],
                )
                st.write(
                    "**Publication action:**",
                    result["publication_action"],
                )
                st.rerun()

        if active:
            st.divider()
            st.success("A governed classification is already active.")
            st.write(
                "**Written type:**",
                label_for(active["corrected_entity_type"], labels),
            )
            st.write("**Written by:**", active["actor"])
            st.write("**Written at:**", active["created_at"])
            st.write("**Action ID:**", active["action_id"])

    st.divider()
    st.caption(
        "Write scope: dedicated MeitY classification override and audit "
        "tables only · Publication action: None"
    )


if __name__ == "__main__":
    main()
