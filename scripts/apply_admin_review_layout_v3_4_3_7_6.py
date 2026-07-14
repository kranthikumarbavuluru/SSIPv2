from __future__ import annotations

import argparse
from pathlib import Path


VERSION = "3.4.3.7.6"

HELPER = r"""
def _render_three_column_review_workspace(
    st: Any,
    service: AdminReviewService,
    *,
    reviewer: str,
    selected_id: str,
    item: dict[str, Any],
    record: dict[str, Any],
    assessment: Any,
    duplicate_candidates: list[dict[str, Any]],
    reconciled_aliases: list[dict[str, Any]],
) -> None:
    from html import escape

    title = str(record.get("scheme_name") or item.get("scheme_name") or "Review record")
    score = item.get("validation_score")
    score_text = f"{score:.3f}" if score is not None else "—"

    st.markdown(
        "<style>"
        ".ssip-review-anchor{position:sticky;top:2.75rem;z-index:999;"
        "padding:.8rem 1rem;margin:.25rem 0 1rem 0;border:1px solid "
        "rgba(128,128,128,.35);border-radius:.75rem;"
        "background:var(--background-color);box-shadow:0 4px 16px "
        "rgba(0,0,0,.18)}"
        ".ssip-review-anchor-title{font-size:1.35rem;font-weight:750;"
        "line-height:1.25;margin-bottom:.3rem}"
        ".ssip-review-anchor-meta{font-size:.88rem;opacity:.78}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.markdown(
        (
            '<div class="ssip-review-anchor">'
            f'<div class="ssip-review-anchor-title">{escape(title)}</div>'
            '<div class="ssip-review-anchor-meta">'
            f"Queue: {escape(str(item.get('review_status') or '—'))} · "
            f"Priority: {escape(str(item.get('priority') or '—'))} · "
            f"Type: {escape(str(record.get('record_kind') or '—'))} · "
            f"Score: {escape(score_text)}"
            "</div></div>"
        ),
        unsafe_allow_html=True,
    )

    st.caption(
        "Three-column review mode keeps identity, official evidence and "
        "decision readiness visible together. All editable fields appear "
        "below without switching tabs."
    )

    identity_col, evidence_col, readiness_col = st.columns(
        [1.0, 1.15, 1.35],
        gap="large",
    )

    with identity_col:
        st.markdown("### 1. Identity & ownership")
        st.markdown(f"**Scheme / call:** {title}")
        st.write(f"**Master ID:** `{selected_id}`")
        st.write(f"**Record kind:** {record.get('record_kind') or '—'}")
        st.write(f"**Source:** {record.get('source') or item.get('source') or '—'}")
        st.write(f"**Ministry:** {record.get('ministry') or '—'}")
        st.write(f"**Department:** {record.get('department') or 'Ministry-level programme'}")
        st.write(
            "**Implementing agency:** "
            f"{record.get('implementing_entity') or record.get('implementing_agency') or '—'}"
        )
        st.write(f"**Geographic scope:** {record.get('geographic_scope') or '—'}")
        st.markdown("#### Scheme / call relationship")
        st.write(
            "**Parent scheme:** "
            f"{record.get('parent_scheme_name') or record.get('parent_master_id') or 'Standalone / requires curation'}"
        )
        st.write(
            "**Parent decision:** "
            f"{record.get('parent_resolution') or 'Requires curation'}"
        )
        st.write(
            "**Applicant layer:** "
            f"{record.get('applicant_layer') or 'Requires curation'}"
        )
        st.write(
            "**Startup relevance:** "
            f"{record.get('startup_relevance') or 'Requires curation'}"
        )
        st.write(f"**Sector scope:** {record.get('sector_scope') or '—'}")
        contact_details = record.get("contact_details") or []
        st.markdown("#### Contact details")
        if contact_details:
            st.json(contact_details, expanded=True)
        else:
            st.caption("No contact details stored.")

    with evidence_col:
        st.markdown("### 2. Official evidence & status")
        st.write(
            "**Programme status:** "
            f"{record.get('programme_status') or '—'}"
        )
        st.write(
            "**Application status:** "
            f"{record.get('application_status') or '—'}"
        )
        st.write(f"**Scheme status:** {record.get('scheme_status') or '—'}")
        st.write(f"**Opening date:** {record.get('opening_date') or '—'}")
        st.write(f"**Closing date:** {record.get('closing_date') or '—'}")
        st.write(f"**Status basis:** {record.get('status_basis') or '—'}")
        st.write(
            "**Status evidence:** "
            f"{record.get('status_evidence') or '—'}"
        )
        st.write(
            "**Last verified:** "
            f"{record.get('last_verified_at') or 'Not recorded'}"
        )

        link_columns = st.columns(2)
        if record.get("official_page_url"):
            link_columns[0].link_button(
                "Open official page",
                record["official_page_url"],
                use_container_width=True,
            )
        else:
            link_columns[0].button(
                "Official page unavailable",
                disabled=True,
                use_container_width=True,
                key=f"official_missing_{selected_id}",
            )
        if record.get("application_url"):
            link_columns[1].link_button(
                "Open application page",
                record["application_url"],
                use_container_width=True,
            )
        else:
            link_columns[1].button(
                "No verified Apply route",
                disabled=True,
                use_container_width=True,
                key=f"application_missing_{selected_id}",
            )

        st.markdown("#### Source evidence")
        sources = record.get("source_evidence") or []
        if not sources:
            st.warning("No source evidence is stored for this record.")
        else:
            for index, source in enumerate(sources, start=1):
                source_title = source.get("title") or f"Official source {index}"
                st.markdown(f"**{index}. {source_title}**")
                if source.get("url"):
                    st.caption(source["url"])
                if source.get("evidence_text"):
                    st.write(source["evidence_text"])

        st.markdown("#### Field evidence")
        field_evidence = record.get("field_evidence") or {}
        if field_evidence:
            st.json(field_evidence, expanded=True)
        else:
            st.caption("No field-level evidence stored.")

    with readiness_col:
        st.markdown("### 3. Readiness, conflicts & history")
        readiness_metrics = st.columns(3)
        readiness_metrics[0].metric(
            "Verification class",
            assessment.category,
        )
        readiness_metrics[1].metric(
            "Checks passed",
            f"{assessment.passed_checks}/{len(assessment.checks)}",
        )
        readiness_metrics[2].metric(
            "Approval",
            "Ready" if assessment.ready_for_approval else "Blocked",
        )

        st.dataframe(
            [
                {
                    "Check": check["label"],
                    "Required": "Yes" if check["required"] else "Advisory",
                    "Result": "Pass" if check["passed"] else "Missing",
                    "Why": check["reason"],
                }
                for check in assessment.checks
            ],
            use_container_width=True,
            hide_index=True,
        )

        for gap in assessment.blocking_gaps:
            st.error(gap)
        for warning in assessment.warnings:
            st.warning(warning)

        if duplicate_candidates:
            st.error(
                f"{len(duplicate_candidates)} possible duplicate record(s) require review."
            )
            st.dataframe(
                duplicate_candidates,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("No unresolved semantic duplicate is blocking this record.")

        if reconciled_aliases:
            st.info(
                f"{len(reconciled_aliases)} legacy identity record(s) are "
                "explicitly reconciled to this canonical record."
            )
            st.dataframe(
                reconciled_aliases,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("#### Decision reasons")
        for reason in item.get("decision_reasons") or []:
            st.write(f"• {reason}")

        st.markdown("#### Warnings")
        for warning in item.get("warnings") or []:
            st.warning(warning)

        st.markdown("#### Recommended actions")
        for action in item.get("recommended_actions") or []:
            st.write(f"• {action}")

        history = item.get("history") or []
        st.markdown("#### Audit history")
        if history:
            st.dataframe(
                [
                    {
                        "Action": entry["action"],
                        "Reviewer": entry["reviewer"],
                        "Notes": entry.get("notes") or "",
                        "Created": entry["created_at"],
                    }
                    for entry in history
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No prior admin action is recorded.")

    st.divider()
    st.markdown("## All editable review fields")
    st.caption(
        "Every field from the existing review form is visible on this page. "
        "Fields marked * participate in mandatory approval checks."
    )

    initial = _record_form_values(record)

    with st.form(f"three_column_review_form_{selected_id}"):
        values: dict[str, Any] = {}
        left, centre, right = st.columns(3, gap="large")

        with left:
            st.markdown("### A. Identity, organization & relationship")
            values["scheme_name"] = st.text_input(
                "Scheme / call name *",
                initial["scheme_name"],
            )
            values["short_name"] = st.text_input(
                "Short name",
                initial["short_name"],
            )
            values["source"] = st.text_input(
                "Source / owning authority *",
                initial["source"],
            )
            values["ministry"] = st.text_input(
                "Ministry",
                initial["ministry"],
            )
            values["department"] = st.text_input(
                "Department",
                initial["department"],
            )
            values["implementing_agency"] = st.text_input(
                "Implementing agency",
                initial["implementing_agency"],
            )
            values["record_kind"] = st.text_input(
                "Record kind *",
                initial["record_kind"],
            )
            values["geographic_scope"] = st.text_input(
                "Geographic scope",
                initial["geographic_scope"],
            )
            values["parent_master_id"] = st.text_input(
                "Parent master ID * (unless standalone)",
                initial["parent_master_id"],
            )
            values["parent_scheme_name"] = st.text_input(
                "Parent scheme name",
                initial["parent_scheme_name"],
            )
            parent_options = [
                "",
                "CURATED_OFFICIAL_RELATIONSHIP",
                "MONITORED_OFFICIAL_RELATIONSHIP",
                "STANDALONE_OFFICIAL_CALL",
                "UNRESOLVED",
                "UMBRELLA_ONLY_REVIEW",
            ]
            if initial["parent_resolution"] not in parent_options:
                parent_options.append(initial["parent_resolution"])
            values["parent_resolution"] = st.selectbox(
                "Parent relationship decision * (calls)",
                parent_options,
                index=parent_options.index(initial["parent_resolution"]),
            )
            values["applicant_layer"] = st.text_input(
                "Applicant layer * (calls)",
                initial["applicant_layer"],
            )
            values["startup_relevance"] = st.text_input(
                "Startup relevance",
                initial["startup_relevance"],
            )
            values["implementation_role"] = st.text_input(
                "Implementation role",
                initial["implementation_role"],
            )

        with centre:
            st.markdown("### B. Status, dates & official evidence")
            values["programme_status"] = st.text_input(
                "Programme status",
                initial["programme_status"],
            )
            values["application_status"] = st.text_input(
                "Application status * (calls)",
                initial["application_status"],
            )
            values["scheme_status"] = st.text_input(
                "Scheme status",
                initial["scheme_status"],
            )
            values["official_page_url"] = st.text_input(
                "Official page URL *",
                initial["official_page_url"],
            )
            values["application_url"] = st.text_input(
                "Application URL * (open calls)",
                initial["application_url"],
            )
            date_columns = st.columns(2)
            values["opening_date"] = date_columns[0].text_input(
                "Opening date",
                initial["opening_date"],
            )
            values["closing_date"] = date_columns[1].text_input(
                "Closing date",
                initial["closing_date"],
            )
            values["sector_scope"] = st.text_input(
                "Sector scope",
                initial["sector_scope"],
            )
            values["status_basis"] = st.text_input(
                "Status basis",
                initial["status_basis"],
            )
            values["status_evidence"] = st.text_area(
                "Status evidence *",
                initial["status_evidence"],
                height=115,
            )
            values["last_verified_at"] = st.text_input(
                "Last verified",
                initial["last_verified_at"],
            )
            values["source_evidence_urls"] = st.text_area(
                "Official source evidence URLs * — one per line",
                initial["source_evidence_urls"],
                height=145,
            )

        with right:
            st.markdown("### C. Funding & support")
            funding_row_1 = st.columns(2)
            values["funding_minimum"] = funding_row_1[0].text_input(
                "Funding minimum",
                str(initial["funding_minimum"]),
            )
            values["funding_maximum"] = funding_row_1[1].text_input(
                "Funding maximum",
                str(initial["funding_maximum"]),
            )
            funding_row_2 = st.columns(2)
            values["currency"] = funding_row_2[0].text_input(
                "Currency",
                initial["currency"],
            )
            values["scheme_corpus"] = funding_row_2[1].text_input(
                "Scheme corpus",
                str(initial["scheme_corpus"]),
            )
            support_row_1 = st.columns(2)
            values["beneficiary_minimum"] = support_row_1[0].text_input(
                "Beneficiary support minimum",
                str(initial["beneficiary_minimum"]),
            )
            values["beneficiary_maximum"] = support_row_1[1].text_input(
                "Beneficiary support maximum",
                str(initial["beneficiary_maximum"]),
            )
            values["intermediary_support_maximum"] = st.text_input(
                "Intermediary support maximum",
                str(initial["intermediary_support_maximum"]),
            )
            st.info(
                "Funding fields may remain blank when the official evidence "
                "does not provide a verified amount."
            )

        st.markdown("### D. Structured content — one item per line")
        list_columns = st.columns(3, gap="large")
        list_groups = (
            (
                "scheme_type",
                "target_beneficiaries",
                "objectives",
                "eligibility",
            ),
            (
                "startup_stage",
                "sector",
                "benefits",
                "application_process",
            ),
            (
                "states_or_uts",
                "selection_process",
                "required_documents",
                "guideline_urls",
            ),
        )
        for column, fields in zip(list_columns, list_groups, strict=True):
            with column:
                for field in fields:
                    values[field] = st.text_area(
                        field.replace("_", " ").title(),
                        initial[field],
                        height=115,
                    )

        notes = st.text_area(
            "Reviewer notes / reason",
            placeholder=(
                "Explain corrections, approval, evidence request or rejection."
            ),
            height=100,
        )

        action_cols = st.columns(4)
        save_clicked = action_cols[0].form_submit_button(
            "Save draft",
            use_container_width=True,
        )
        approve_clicked = action_cols[1].form_submit_button(
            "Approve",
            type="primary",
            use_container_width=True,
        )
        evidence_clicked = action_cols[2].form_submit_button(
            "Needs more evidence",
            use_container_width=True,
        )
        reject_clicked = action_cols[3].form_submit_button(
            "Reject",
            use_container_width=True,
        )

    if save_clicked or approve_clicked or evidence_clicked or reject_clicked:
        try:
            edited = build_edited_record(record, values)
            if save_clicked:
                service.save_draft(
                    selected_id,
                    edited,
                    reviewer=reviewer,
                    notes=notes,
                )
                st.success("Draft saved.")
            elif approve_clicked:
                edited_assessment = verification_assessment(edited)
                edited_duplicates = service.duplicate_candidates(
                    selected_id,
                    edited,
                )
                if not edited_assessment.ready_for_approval:
                    raise ValueError(
                        "Approval blocked. Mandatory checks still missing: "
                        + " | ".join(edited_assessment.blocking_gaps)
                    )
                if edited_duplicates:
                    raise ValueError(
                        "Approval blocked by possible duplicates: "
                        + " | ".join(
                            f"{candidate['scheme_name']} ({candidate['reason']})"
                            for candidate in edited_duplicates
                        )
                    )
                service.approve(
                    selected_id,
                    edited,
                    reviewer=reviewer,
                    notes=notes,
                )
                st.success(
                    "Record approved into scheme_staging. Publication remains "
                    "a separate decision."
                )
            elif evidence_clicked:
                service.mark_needs_more_evidence(
                    selected_id,
                    edited,
                    reviewer=reviewer,
                    notes=notes,
                )
                st.success(
                    "Record retained in the queue for more evidence."
                )
            elif reject_clicked:
                service.reject(
                    selected_id,
                    edited,
                    reviewer=reviewer,
                    notes=notes,
                )
                st.success(
                    "Record rejected and written to rejected_scheme_records."
                )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if item["review_status"] in {"APPROVED", "REJECTED"}:
        if st.button(
            "Reopen this record",
            key=f"reopen_three_column_{selected_id}",
        ):
            try:
                service.reopen(
                    selected_id,
                    reviewer=reviewer,
                    notes="Reopened from three-column review workspace",
                )
                st.success("Record reopened.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("### Complete stored record")
    st.caption(
        "This read-only view includes internal evidence, validation and "
        "metadata fields not directly editable above."
    )
    st.json(record, expanded=True)
"""

CALL_BLOCK = """    _render_three_column_review_workspace(
        st,
        service,
        reviewer=reviewer,
        selected_id=selected_id,
        item=item,
        record=record,
        assessment=assessment,
        duplicate_candidates=duplicate_candidates,
        reconciled_aliases=reconciled_aliases,
    )
    return

"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    helper_marker = "\ndef main() -> None:\n"
    if "_render_three_column_review_workspace(" not in text:
        if helper_marker not in text:
            raise RuntimeError("UI helper insertion marker not found")
        text = text.replace(
            helper_marker,
            "\n" + HELPER.rstrip() + "\n\n\ndef main() -> None:\n",
            1,
        )

    call_marker = (
        "    reconciled_aliases = service.reconciled_aliases(selected_id)\n\n"
    )
    if "reconciled_aliases=reconciled_aliases," not in text:
        if call_marker not in text:
            raise RuntimeError("Review workspace call marker not found")
        text = text.replace(
            call_marker,
            call_marker + CALL_BLOCK,
            1,
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        "def _render_three_column_review_workspace(",
        "Three-column review mode",
        "### 1. Identity & ownership",
        "### 2. Official evidence & status",
        "### 3. Readiness, conflicts & history",
        "## All editable review fields",
        "st.columns(3, gap=\"large\")",
        "Complete stored record",
        "reconciled_aliases=reconciled_aliases,",
        "service.save_draft(",
        "service.approve(",
        "service.mark_needs_more_evidence(",
        "service.reject(",
        "service.reopen(",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError(
            f"Three-column Admin review validation failed: {missing}"
        )

    call_position = text.find(
        "    _render_three_column_review_workspace(\n"
    )
    legacy_position = text.find(
        "    st.subheader(record.get(\"scheme_name\")"
    )
    if call_position < 0 or legacy_position < 0:
        raise RuntimeError("Could not locate review renderer boundaries")
    return_position = text.find("    return\n", call_position)
    if not (call_position < return_position < legacy_position):
        raise RuntimeError(
            "Three-column review renderer is not activated before the legacy layout"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = (
        Path(args.project_root).resolve()
        / "ui/admin_review_app_v1.py"
    )

    if not args.check:
        changed = patch(path)
        print(
            "Three-column Admin review patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )

    validate(path)
    print("SSIP v3.4.3.7.6 three-column review validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
