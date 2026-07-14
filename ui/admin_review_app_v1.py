from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.admin_review_service_v3_4_3_7_2 import AdminReviewService  # noqa: E402
from services.admin_publication_service_v1 import AdminPublicationService  # noqa: E402
from services.dst_historical_archive_approval_v1 import (  # noqa: E402
    DSTHistoricalArchiveApprovalService,
)
from services.admin_verification_intelligence_v1 import (  # noqa: E402
    record_category,
    verification_assessment,
)
from services.department_review_intake_v1 import (  # noqa: E402
    available_intakes,
    get_intake,
)
from ssip_dashboard.dst_history import (  # noqa: E402
    RELEVANCE_ORDER,
    load_dst_historical_archive,
)


LIST_FIELDS = (
    "scheme_type",
    "target_beneficiaries",
    "startup_stage",
    "sector",
    "states_or_uts",
    "objectives",
    "eligibility",
    "benefits",
    "application_process",
    "selection_process",
    "required_documents",
    "guideline_urls",
)


def lines_to_list(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def list_to_lines(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    output: list[str] = []
    for item in value:
        if isinstance(item, (dict, list)):
            output.append(json.dumps(item, ensure_ascii=False))
        else:
            text = str(item).strip()
            if text:
                output.append(text)
    return "\n".join(output)


def source_evidence_to_lines(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "\n".join(
        str(item.get("url") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    )


def _render_agent_intake(st: Any, service: AdminReviewService) -> None:
    st.subheader("Department Agent Intake")
    st.caption(
        "Run a non-writing comparison first, inspect duplicates and exact queue changes, "
        "then import only into admin_review_queue. Approval and publication remain separate."
    )
    descriptors = available_intakes(PROJECT_ROOT, service.database_path)
    if not descriptors:
        st.info("No department-agent review packages are available.")
        return
    labels = {item.provider_id: f"{item.department} — {item.version}" for item in descriptors}
    provider_id = st.selectbox("Agent review package", list(labels), format_func=lambda value: labels[value])
    descriptor = next(item for item in descriptors if item.provider_id == provider_id)
    st.info(descriptor.description)
    st.caption(f"Source package: {descriptor.source_path}")
    state_key = f"admin_intake_report_{provider_id}"
    fresh_key = f"admin_intake_fresh_{provider_id}"
    if st.button("Run comparison / dry run", type="primary", key=f"dry_run_{provider_id}"):
        try:
            report = get_intake(provider_id, PROJECT_ROOT, service.database_path).run(apply=False)
            st.session_state[state_key] = report
            st.session_state[fresh_key] = True
            st.success("Dry run completed. The approval database was not modified.")
        except Exception as exc:
            st.session_state[fresh_key] = False
            st.error(str(exc))

    report = st.session_state.get(state_key)
    if not report:
        st.warning("Run a fresh dry run before importing this department package.")
        return

    columns = st.columns(5)
    columns[0].metric("Source records", report["source_queue_count"])
    columns[1].metric("New pending", report["proposed_insert_count"])
    columns[2].metric("Pending updates", report["proposed_update_count"])
    columns[3].metric("Duplicates skipped", report["skipped_semantic_duplicate_count"])
    columns[4].metric("Decisions protected", report["skipped_existing_decision_count"])
    st.caption(f"Plan signature: {report.get('plan_signature', 'Unavailable')} · Generated {report['generated_at']}")

    action_rows = [
        {
            "Action": action["action"],
            "Record": action["scheme_name"],
            "Type": action["record_kind"],
            "Status": action["application_status"],
            "Existing match": "; ".join(match["scheme_name"] for match in action.get("matches", [])),
        }
        for action in report["actions"]
    ]
    st.dataframe(action_rows, use_container_width=True, hide_index=True)
    st.download_button(
        "Download full dry-run report",
        data=json.dumps(report, indent=2, ensure_ascii=False),
        file_name=f"{provider_id}_dry_run.json",
        mime="application/json",
    )
    st.warning(
        "Import creates pending review records only. It does not approve, stage, publish or alter existing decisions."
    )
    fresh = bool(st.session_state.get(fresh_key))
    confirmed = st.checkbox(
        "I reviewed this exact dry-run plan and want to import its proposed pending records.",
        disabled=not fresh,
        key=f"confirm_{provider_id}",
    )
    apply_clicked = st.button(
        "Import to Review Queue",
        disabled=not (fresh and confirmed and bool(report.get("plan_signature"))),
        key=f"apply_{provider_id}",
    )
    if apply_clicked:
        try:
            result = get_intake(provider_id, PROJECT_ROOT, service.database_path).run(
                apply=True,
                expected_signature=report["plan_signature"],
            )
            st.session_state[state_key] = result
            st.session_state[fresh_key] = False
            st.cache_resource.clear()
            st.success(
                f"Imported {result['proposed_insert_count']} new and "
                f"{result['proposed_update_count']} updated pending review records."
            )
            st.rerun()
        except Exception as exc:
            st.session_state[fresh_key] = False
            st.error(str(exc))


def _render_import_runs(st: Any, service: AdminReviewService) -> None:
    st.subheader("Ingestion & Decision Runs")
    st.caption("Every loader and admin decision remains traceable through import_runs.")
    rows = service.list_import_runs(limit=200)
    if not rows:
        st.info("No import runs are recorded.")
        return
    st.dataframe([
        {
            "Run": row["run_id"], "Status": row["status"], "Started": row["started_at"],
            "Completed": row["completed_at"], "Approved input": row["approved_input_count"],
            "Review input": row["review_input_count"], "Rejected input": row["rejected_input_count"],
        }
        for row in rows
    ], use_container_width=True, hide_index=True)
    selected = st.selectbox("Inspect run", [row["run_id"] for row in rows])
    st.json(next(row for row in rows if row["run_id"] == selected)["summary"], expanded=True)


def _render_global_audit(st: Any, service: AdminReviewService) -> None:
    st.subheader("Approval Audit Trail")
    st.caption("Immutable before/after review actions across every department and agent batch.")
    rows = service.list_actions(limit=500)
    if not rows:
        st.info("No admin actions are recorded.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_historical_archive(st: Any, service: AdminReviewService) -> None:
    archive = load_dst_historical_archive(PROJECT_ROOT)
    manifest = archive.manifest
    approval = DSTHistoricalArchiveApprovalService(service.database_path, PROJECT_ROOT)
    st.subheader("DST Historical Archive Batch")
    st.caption(
        "Exception-only verification for official closed DST calls. This workspace qualifies the archive, "
        "selects a deterministic human sample and keeps current calls outside the batch."
    )
    metrics = st.columns(5)
    metrics[0].metric("Normalized", manifest["total_normalized_calls"])
    metrics[1].metric("Historical qualified", manifest["qualified_historical_calls"])
    metrics[2].metric("Current excluded", manifest["current_calls_excluded"])
    metrics[3].metric("Exceptions", manifest["exception_count"])
    metrics[4].metric("Human sample", len(manifest["sample_ids"]))
    st.success(
        "Archive qualification passed: official source, individual-call identity, past closing date, "
        "closed status and duplicate checks completed."
    )
    st.caption(f"Manifest signature: {manifest['signature']} · Service {manifest['service_version']}")

    summary_tab, exceptions_tab, sample_tab, manifest_tab = st.tabs(
        ["Batch summary", "Exceptions", "Stratified sample", "Signed manifest"]
    )
    with summary_tab:
        left, right = st.columns(2)
        left.markdown("#### Closing-year distribution")
        left.dataframe(
            [{"Year": year, "Closed calls": count} for year, count in manifest["year_counts"].items()],
            use_container_width=True,
            hide_index=True,
        )
        right.markdown("#### Relevance distribution")
        right.dataframe(
            [
                {"Relevance": value.replace("_", " ").title(), "Calls": manifest["relevance_counts"].get(value, 0)}
                for value in RELEVANCE_ORDER
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.warning(
            "General DST calls are historical evidence only. They must never be presented as direct startup opportunities."
        )
    with exceptions_tab:
        if not archive.exceptions:
            st.success("No records require exception review in this archive build.")
        else:
            st.dataframe(
                [
                    {
                        "Call": item.call.call_title,
                        "Status": item.call.application_status,
                        "Closing date": item.call.closing_date,
                        "Blockers": " | ".join(item.blocking_gaps),
                        "Official URL": item.call.detail_url,
                    }
                    for item in archive.exceptions
                ],
                use_container_width=True,
                hide_index=True,
            )
    with sample_tab:
        by_id = {item.call.call_id: item for item in archive.historical_records}
        sample = [by_id[item_id] for item_id in manifest["sample_ids"] if item_id in by_id]
        st.markdown(f"**Review these {len(sample)} records instead of all {len(archive.historical_records)} historical calls.**")
        st.dataframe(
            [
                {
                    "Year": item.closing_year,
                    "Call": item.call.call_title,
                    "Relevance": item.relevance_group.replace("_", " ").title(),
                    "Closing date": item.call.closing_date,
                    "Applicant": item.call.eligible_applicants or item.call.applicant_layer,
                    "Official URL": item.call.detail_url,
                    "Warnings": " | ".join(item.warnings),
                }
                for item in sample
            ],
            use_container_width=True,
            hide_index=True,
        )
    with manifest_tab:
        st.json(manifest, expanded=True)
        st.download_button(
            "Download signed qualification manifest",
            data=json.dumps(manifest, indent=2, ensure_ascii=False),
            file_name="dst_historical_archive_manifest_v1.json",
            mime="application/json",
        )
    st.divider()
    st.markdown("### Batch approval controls")
    state = approval.status()
    if not state["schema_ready"]:
        st.warning(
            "Historical archive database migration is not installed. Approval controls will be enabled after the "
            "separate migration is explicitly approved and applied."
        )
        st.code("database/migrations/20260712_dst_historical_archive_v1.sql")
        disabled_columns = st.columns(2)
        disabled_columns[0].button(
            f"Approve {len(manifest['sample_ids'])}-record stratified sample",
            disabled=True,
            key="dst_archive_sample_disabled",
            use_container_width=True,
        )
        disabled_columns[1].button(
            f"Publish {manifest['qualified_historical_calls']}-call historical archive",
            disabled=True,
            key="dst_archive_publish_disabled",
            use_container_width=True,
        )
        st.caption(
            "Required sequence: explicitly approve migration → review and approve sample → separate publication decision."
        )
        return

    status_columns = st.columns(3)
    status_columns[0].metric("Batch status", state["approval_status"])
    status_columns[1].metric("Archive records", state["archive_records"])
    status_columns[2].metric("Public historical calls", state["public_records"])

    if state["approval_status"] == "APPROVED":
        st.success(
            f"Historical archive is published. {state['public_records']} records are available through the governed archive view."
        )
        return

    if state["approval_status"] == "PREVIEW":
        st.markdown("#### Step 1 — approve the 36-record stratified sample")
        st.caption(
            "This confirms that the reviewed sample represents the signed 348-call archive. "
            "It imports the archive as non-public records; it does not publish them."
        )
        reviewer = st.text_input("Archive reviewer identity *", key="dst_archive_reviewer")
        review_notes = st.text_area(
            "Sample review notes *",
            key="dst_archive_review_notes",
            placeholder="Record the sample checks performed and any observations.",
        )
        reviewed = st.checkbox(
            f"I reviewed all {len(manifest['sample_ids'])} records in the signed stratified sample and found no material mismatch.",
            key="dst_archive_sample_reviewed",
        )
        review_phrase = f"REVIEW {len(manifest['sample_ids'])}"
        review_confirmation = st.text_input(
            f"Type {review_phrase} to confirm *",
            key="dst_archive_review_confirmation",
        )
        if st.button(
            "Approve stratified sample",
            type="primary",
            key="dst_archive_approve_sample",
            disabled=not (
                reviewer.strip() and review_notes.strip() and reviewed
                and review_confirmation.strip() == review_phrase
            ),
        ):
            try:
                result = approval.review_sample(
                    reviewer=reviewer,
                    notes=review_notes,
                    expected_signature=manifest["signature"],
                    reviewed_sample_ids=manifest["sample_ids"],
                )
                st.success(
                    f"Sample approved. {result['record_count']} historical records were staged as non-public archive records."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        return

    if state["approval_status"] == "SAMPLE_REVIEWED":
        st.success(
            f"The {len(manifest['sample_ids'])}-record sample is approved and {state['archive_records']} archive records are staged."
        )
        st.markdown("#### Step 2 — separate archive publication decision")
        st.caption(
            "Publishing exposes all qualified historical calls as reference records. "
            "General DST calls remain explicitly labelled as non-startup opportunities."
        )
        publisher = st.text_input("Archive publisher identity *", key="dst_archive_publisher")
        publication_notes = st.text_area(
            "Archive publication notes *",
            key="dst_archive_publication_notes",
            placeholder="Explain why this signed historical batch is approved for public reference.",
        )
        publish_phrase = f"PUBLISH {manifest['qualified_historical_calls']}"
        publish_confirmation = st.text_input(
            f"Type {publish_phrase} to confirm *",
            key="dst_archive_publish_confirmation",
        )
        if st.button(
            "Publish qualified historical archive",
            type="primary",
            key="dst_archive_publish",
            disabled=not (
                publisher.strip() and publication_notes.strip()
                and publish_confirmation.strip() == publish_phrase
            ),
        ):
            try:
                result = approval.publish(
                    publisher=publisher,
                    notes=publication_notes,
                    expected_signature=manifest["signature"],
                )
                st.success(f"Published {result['public_count']} historical reference calls.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_publication_queue(st: Any, service: AdminReviewService) -> None:
    publication = AdminPublicationService(service.database_path)
    counts = publication.status_counts()
    st.subheader("Publication Queue")
    st.caption(
        "Curator approval and public publication are separate. Prepare approved staging records, "
        "then publish only records that pass a fresh bulk preflight."
    )
    metrics = st.columns(4)
    metrics[0].metric("Staged", counts.get("STAGED", 0))
    metrics[1].metric("Ready", counts.get("READY_FOR_PUBLICATION", 0))
    metrics[2].metric("Published", counts.get("PUBLISHED", 0))
    metrics[3].metric("Unpublished", counts.get("UNPUBLISHED", 0))

    view = st.radio(
        "Publication stage",
        ["Prepare approved staging", "Publish ready records", "Public records & audit"],
        horizontal=True,
    )
    if view == "Public records & audit":
        public_rows = publication.list_public_records()
        st.markdown(f"**{len(public_rows)} publicly visible record(s)**")
        if public_rows:
            st.dataframe(public_rows, use_container_width=True, hide_index=True)
        st.markdown("#### Publication audit")
        audit_rows = publication.list_audit(limit=500)
        if audit_rows:
            st.dataframe(audit_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No publication actions are recorded.")
        return

    action = "mark-ready" if view == "Prepare approved staging" else "publish"
    all_plan = publication.plan(action)
    eligible = [row for row in all_plan["records"] if row["eligible"]]
    excluded = [row for row in all_plan["records"] if not row["eligible"]]
    st.markdown(f"**Eligible: {len(eligible)} · Excluded: {len(excluded)}**")
    if excluded:
        with st.expander("Why records are excluded", expanded=False):
            st.dataframe([
                {
                    "Record": row["scheme_name"], "Type": row["record_kind"],
                    "Status": row["publication_status"], "Blockers": " | ".join(row["blockers"]),
                }
                for row in excluded
            ], use_container_width=True, hide_index=True)
    if not eligible:
        st.info("No records currently pass this publication stage.")
        return

    names = {row["master_id"]: f"{row['scheme_name']} — {row['record_kind'] or 'Unclassified'}" for row in eligible}
    select_all = st.checkbox(
        f"Select all {len(eligible)} eligible record(s)",
        key=f"publication_select_all_{action}",
    )
    selected_ids = list(names) if select_all else st.multiselect(
        "Select records",
        options=list(names),
        format_func=lambda value: names[value],
        key=f"publication_selection_{action}",
    )
    plan_key = f"publication_preflight_{action}"
    if st.button(
        "Run bulk publication preflight",
        disabled=not selected_ids,
        key=f"publication_preflight_button_{action}",
    ):
        st.session_state[plan_key] = publication.plan(action, selected_ids)
        st.success("Preflight completed without changing publication state.")

    preflight = st.session_state.get(plan_key)
    preflight_current = bool(
        preflight
        and sorted(preflight.get("selected_ids", [])) == sorted(selected_ids)
        and not preflight.get("excluded_ids")
    )
    if preflight:
        st.caption(f"Preflight signature: {preflight['signature']}")
        st.dataframe([
            {
                "Record": row["scheme_name"], "Current status": row["publication_status"],
                "Ready": "Yes" if row["eligible"] else "No",
                "Warnings": " | ".join(row["warnings"]), "Blockers": " | ".join(row["blockers"]),
            }
            for row in preflight["records"]
        ], use_container_width=True, hide_index=True)
    if not preflight_current:
        st.warning("Run a fresh preflight for the exact current selection before continuing.")

    publisher = st.text_input("Publisher identity *", key=f"publication_actor_{action}")
    reason = st.text_area(
        "Publication notes / reason *",
        key=f"publication_reason_{action}",
        placeholder="Explain why this reviewed batch is ready for the next publication state.",
    )
    verb = "READY" if action == "mark-ready" else "PUBLISH"
    phrase = f"{verb} {len(selected_ids)}"
    confirmation = st.text_input(
        f"Type {phrase} to confirm *",
        key=f"publication_confirmation_{action}",
    )
    button_label = "Mark selected records ready" if action == "mark-ready" else "Publish selected records"
    commit_clicked = st.button(
        button_label,
        type="primary",
        disabled=not (
            preflight_current and publisher.strip() and reason.strip() and confirmation.strip() == phrase
        ),
        key=f"publication_commit_{action}",
    )
    if commit_clicked:
        try:
            result = publication.bulk_action(
                action=action,
                master_ids=selected_ids,
                actor=publisher,
                reason=reason,
                expected_signature=preflight["signature"],
            )
            st.session_state.pop(plan_key, None)
            st.cache_resource.clear()
            st.success(
                f"Bulk action completed for {result['record_count']} record(s). "
                f"Public count: {result['public_count_before']} → {result['public_count_after']}."
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def parse_optional_int(value: Any) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    number = int(text)
    if number < 0:
        raise ValueError("Funding values cannot be negative")
    return number


def build_edited_record(original: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(original)
    scalar_fields = (
        "scheme_name",
        "short_name",
        "source",
        "ministry",
        "department",
        "implementing_agency",
        "record_kind",
        "programme_status",
        "application_status",
        "scheme_status",
        "geographic_scope",
        "official_page_url",
        "application_url",
        "opening_date",
        "closing_date",
        "parent_master_id",
        "parent_scheme_name",
        "parent_resolution",
        "applicant_layer",
        "startup_relevance",
        "implementation_role",
        "sector_scope",
        "status_basis",
        "status_evidence",
        "last_verified_at",
    )
    for field in scalar_fields:
        value = str(values.get(field) or "").strip()
        record[field] = value or None
    record["scheme_name"] = str(values.get("scheme_name") or "").strip()
    record["source"] = str(values.get("source") or "").strip()

    for field in LIST_FIELDS:
        record[field] = lines_to_list(str(values.get(field) or ""))

    existing_evidence = {
        str(item.get("url") or "").strip(): item
        for item in record.get("source_evidence") or []
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    }
    record["source_evidence"] = [
        copy.deepcopy(existing_evidence.get(url))
        if url in existing_evidence
        else {
            "url": url,
            "title": "Curator-added official evidence",
            "content_kind": "pdf" if url.lower().split("?", 1)[0].endswith(".pdf") else "html",
        }
        for url in lines_to_list(str(values.get("source_evidence_urls") or ""))
    ]

    funding = copy.deepcopy(record.get("funding_amount") or {})
    beneficiary = copy.deepcopy(funding.get("beneficiary_support") or {})
    funding["minimum"] = parse_optional_int(values.get("funding_minimum"))
    funding["maximum"] = parse_optional_int(values.get("funding_maximum"))
    funding["currency"] = str(values.get("currency") or "INR").strip() or "INR"
    beneficiary["minimum"] = parse_optional_int(values.get("beneficiary_minimum"))
    beneficiary["maximum"] = parse_optional_int(values.get("beneficiary_maximum"))
    funding["beneficiary_support"] = beneficiary
    funding["intermediary_support_maximum"] = parse_optional_int(
        values.get("intermediary_support_maximum")
    )
    funding["scheme_corpus"] = parse_optional_int(values.get("scheme_corpus"))
    record["funding_amount"] = funding
    return record


def _record_form_values(record: dict[str, Any]) -> dict[str, Any]:
    funding = record.get("funding_amount") or {}
    beneficiary = funding.get("beneficiary_support") or {}
    values: dict[str, Any] = {
        field: record.get(field) or ""
        for field in (
            "scheme_name",
            "short_name",
            "source",
            "ministry",
            "department",
            "implementing_agency",
            "record_kind",
            "programme_status",
            "application_status",
            "scheme_status",
            "geographic_scope",
            "official_page_url",
            "application_url",
            "opening_date",
            "closing_date",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "applicant_layer",
            "startup_relevance",
            "implementation_role",
            "sector_scope",
            "status_basis",
            "status_evidence",
            "last_verified_at",
        )
    }
    for field in LIST_FIELDS:
        values[field] = list_to_lines(record.get(field))
    values["source_evidence_urls"] = source_evidence_to_lines(record.get("source_evidence"))
    values.update(
        {
            "funding_minimum": funding.get("minimum") or "",
            "funding_maximum": funding.get("maximum") or "",
            "currency": funding.get("currency") or "INR",
            "beneficiary_minimum": beneficiary.get("minimum") or "",
            "beneficiary_maximum": beneficiary.get("maximum") or "",
            "intermediary_support_maximum": funding.get("intermediary_support_maximum") or "",
            "scheme_corpus": funding.get("scheme_corpus") or "",
        }
    )
    return values


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="SSIP Admin Verification",
        page_icon="✅",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    @st.cache_resource
    def get_service() -> AdminReviewService:
        return AdminReviewService()

    service = get_service()
    counts = service.dashboard_counts()
    options = service.filter_options()

    st.title("SSIP Scheme & Call Admin Verification")
    st.caption(
        "Verify department-agent evidence, relationships and application status; "
        "then approve records into staging before a separate publication decision."
    )

    metric_columns = st.columns(5)
    metric_columns[0].metric("Staged records", counts["staged_schemes"])
    metric_columns[1].metric("Pending", counts["pending_reviews"])
    metric_columns[2].metric("Approved reviews", counts["approved_reviews"])
    metric_columns[3].metric("Rejected reviews", counts["rejected_reviews"])
    metric_columns[4].metric("Audit actions", counts["review_actions"])

    with st.sidebar:
        st.header("Admin workspace")
        workspace = st.radio(
            "Workspace",
            ["Review Inbox", "Publication Queue", "Historical Archive", "Department Agent Intake", "Ingestion Runs", "Audit Trail"],
        )

    if workspace == "Department Agent Intake":
        _render_agent_intake(st, service)
        return
    if workspace == "Publication Queue":
        _render_publication_queue(st, service)
        return
    if workspace == "Historical Archive":
        _render_historical_archive(st, service)
        return
    if workspace == "Ingestion Runs":
        _render_import_runs(st, service)
        return
    if workspace == "Audit Trail":
        _render_global_audit(st, service)
        return

    with st.sidebar:
        st.header("Review controls")
        reviewer = st.text_input("Reviewer name", value="Admin")
        status_filter = st.selectbox(
            "Queue status", ["PENDING", "ALL", "APPROVED", "REJECTED"], index=0
        )
        priority_filter = st.selectbox(
            "Priority", ["ALL", "HIGH", "MEDIUM", "NORMAL"], index=0
        )
        decision_filter = st.selectbox(
            "Decision", ["ALL", *options["decisions"]], index=0
        )
        source_filter = st.selectbox("Source", ["ALL", *options["sources"]], index=0)
        record_kind_filter = st.selectbox(
            "Record type", ["ALL", *options["record_kinds"]], index=0
        )
        applicant_layer_filter = st.selectbox(
            "Applicant layer", ["ALL", *options["applicant_layers"]], index=0
        )
        department_filter = st.selectbox(
            "Department", ["ALL", *options["departments"]], index=0
        )
        ministry_filter = st.selectbox(
            "Ministry", ["ALL", *options["ministries"]], index=0
        )
        import_run_filter = st.selectbox(
            "Ingestion batch", ["ALL", *options["import_runs"]], index=0
        )
        search = st.text_input("Search")

    reviews = service.list_reviews(
        review_status=status_filter,
        priority=priority_filter,
        decision=decision_filter,
        source=source_filter,
        record_kind=record_kind_filter,
        applicant_layer=applicant_layer_filter,
        department=department_filter,
        ministry=ministry_filter,
        import_run=import_run_filter,
        search=search,
    )
    if not reviews:
        st.info("No records match the selected filters.")
        return

    st.markdown(f"**{len(reviews)} review record(s) match the current controls.**")
    st.dataframe([
        {
            "Priority": row["priority"], "Record": row["scheme_name"],
            "Type": row.get("record_kind") or "Unclassified",
            "Department": row.get("department") or row.get("source") or "Unknown",
            "Applicant layer": row.get("applicant_layer") or "Unverified",
            "Application": row.get("application_status") or "Unverified",
            "Queue": row["review_status"], "Batch": row.get("last_import_run_id") or "Legacy",
        }
        for row in reviews
    ], use_container_width=True, hide_index=True)

    labels = {
        item["master_id"]: (
            f"[{item['priority']}] {item['scheme_name']} — {item.get('source') or 'Unknown'}"
        )
        for item in reviews
    }
    selected_id = st.selectbox(
        "Select a review record",
        options=list(labels),
        format_func=lambda key: labels[key],
    )
    item = service.get_review(selected_id)
    record = item["validated_record"]
    assessment = verification_assessment(record)
    duplicate_candidates = service.duplicate_candidates(selected_id, record)
    reconciled_aliases = service.reconciled_aliases(selected_id)

    st.subheader(record.get("scheme_name") or item["scheme_name"])
    status_columns = st.columns(5)
    status_columns[0].write(f"**Priority:** {item['priority']}")
    status_columns[1].write(f"**Queue:** {item['review_status']}")
    status_columns[2].write(f"**Decision:** {item['decision']}")
    score = item.get("validation_score")
    status_columns[3].write(f"**Score:** {score:.3f}" if score is not None else "**Score:** —")
    status_columns[4].write(f"**Source:** {item.get('source') or '—'}")

    relationship = st.columns(3)
    relationship[0].write(
        f"**Parent scheme:** {record.get('parent_scheme_name') or record.get('parent_master_id') or 'Requires curation'}"
    )
    relationship[1].write(
        f"**Implementing entity:** {record.get('implementing_entity') or record.get('implementing_agency') or 'Requires curation'}"
    )
    relationship[2].write(
        f"**Applicant layer:** {record.get('applicant_layer') or 'Requires curation'}"
    )

    readiness_columns = st.columns(3)
    readiness_columns[0].write(f"**Verification class:** {assessment.category}")
    readiness_columns[1].write(
        f"**Evidence checks:** {assessment.passed_checks}/{len(assessment.checks)} passed"
    )
    readiness_columns[2].write(
        "**Approval readiness:** Ready" if assessment.ready_for_approval else "**Approval readiness:** Blocked"
    )
    if duplicate_candidates:
        st.warning(
            f"{len(duplicate_candidates)} possible duplicate record(s) found. Review them before deciding."
        )
    if reconciled_aliases:
        st.info(
            f"{len(reconciled_aliases)} legacy rejected identity record(s) are explicitly reconciled to this canonical ID. Their rejection and audit history remain preserved."
        )

    overview_tab, edit_tab, evidence_tab, history_tab = st.tabs(
        ["Overview", "Edit & Decide", "Evidence", "Audit history"]
    )

    with overview_tab:
        st.markdown("#### Evidence readiness checklist")
        st.dataframe([
            {
                "Check": check["label"],
                "Required": "Yes" if check["required"] else "Advisory",
                "Result": "Pass" if check["passed"] else "Missing",
                "Why it matters": check["reason"],
            }
            for check in assessment.checks
        ], use_container_width=True, hide_index=True)
        for gap in assessment.blocking_gaps:
            st.error(gap)
        for warning in assessment.warnings:
            st.warning(warning)
        if duplicate_candidates:
            st.markdown("#### Possible duplicates")
            st.dataframe(duplicate_candidates, use_container_width=True, hide_index=True)
        if reconciled_aliases:
            st.markdown("#### Reconciled legacy identities")
            st.dataframe(reconciled_aliases, use_container_width=True, hide_index=True)
        left, right = st.columns(2)
        with left:
            st.markdown("#### Decision reasons")
            for reason in item.get("decision_reasons") or []:
                st.write(f"• {reason}")
            st.markdown("#### Warnings")
            for warning in item.get("warnings") or []:
                st.warning(warning)
        with right:
            st.markdown("#### Recommended actions")
            for action in item.get("recommended_actions") or []:
                st.write(f"• {action}")
            st.markdown("#### Official links")
            if record.get("official_page_url"):
                st.link_button("Open official page", record["official_page_url"])
            if record.get("application_url"):
                st.link_button("Open application page", record["application_url"])
        st.markdown("#### Current validated record")
        st.json(record, expanded=False)

    with edit_tab:
        initial = _record_form_values(record)
        if assessment.ready_for_approval and not duplicate_candidates:
            st.success("All mandatory approval checks currently pass.")
        else:
            st.error("Approval requires the following corrections:")
            for gap in assessment.blocking_gaps:
                st.write(f"- {gap}")
            if duplicate_candidates:
                st.write("- Resolve the possible duplicate record(s) shown on the Overview tab.")
            st.info(
                "Fields marked * participate in mandatory checks. You may correct them and click Approve directly; "
                "the edited values will be revalidated before any database action."
            )
        with st.form(f"review_form_{selected_id}"):
            st.markdown("#### Core details")
            st.caption("* Mandatory for approval. Conditional call requirements are explained below.")
            col1, col2 = st.columns(2)
            values: dict[str, Any] = {}
            with col1:
                values["scheme_name"] = st.text_input("Scheme name *", initial["scheme_name"])
                values["short_name"] = st.text_input("Short name", initial["short_name"])
                values["source"] = st.text_input("Source / owning authority *", initial["source"])
                values["ministry"] = st.text_input("Ministry", initial["ministry"])
                values["department"] = st.text_input("Department", initial["department"])
                values["implementing_agency"] = st.text_input(
                    "Implementing agency", initial["implementing_agency"]
                )
                values["record_kind"] = st.text_input("Record kind *", initial["record_kind"])
                values["programme_status"] = st.text_input(
                    "Programme status", initial["programme_status"]
                )
            with col2:
                values["application_status"] = st.text_input(
                    "Application status * (calls)", initial["application_status"]
                )
                values["scheme_status"] = st.text_input(
                    "Scheme status", initial["scheme_status"]
                )
                values["geographic_scope"] = st.text_input(
                    "Geographic scope", initial["geographic_scope"]
                )
                values["official_page_url"] = st.text_input(
                    "Official page URL *", initial["official_page_url"]
                )
                values["application_url"] = st.text_input(
                    "Application URL * (open calls)", initial["application_url"]
                )
                values["opening_date"] = st.text_input(
                    "Opening date (YYYY-MM-DD)", initial["opening_date"]
                )
                values["closing_date"] = st.text_input(
                    "Closing date (YYYY-MM-DD)", initial["closing_date"]
                )

            st.markdown("#### Funding")
            fund_cols = st.columns(4)
            values["funding_minimum"] = fund_cols[0].text_input(
                "Funding minimum", str(initial["funding_minimum"])
            )
            values["funding_maximum"] = fund_cols[1].text_input(
                "Funding maximum", str(initial["funding_maximum"])
            )
            values["currency"] = fund_cols[2].text_input("Currency", initial["currency"])
            values["scheme_corpus"] = fund_cols[3].text_input(
                "Scheme corpus", str(initial["scheme_corpus"])
            )
            support_cols = st.columns(3)
            values["beneficiary_minimum"] = support_cols[0].text_input(
                "Beneficiary support minimum", str(initial["beneficiary_minimum"])
            )
            values["beneficiary_maximum"] = support_cols[1].text_input(
                "Beneficiary support maximum", str(initial["beneficiary_maximum"])
            )
            values["intermediary_support_maximum"] = support_cols[2].text_input(
                "Intermediary support maximum",
                str(initial["intermediary_support_maximum"]),
            )

            st.markdown("#### Scheme/call relationship and verification")
            st.caption(
                "Calls require either a verified Parent master ID or Parent relationship decision = STANDALONE_OFFICIAL_CALL."
            )
            relation_cols = st.columns(2)
            with relation_cols[0]:
                values["parent_master_id"] = st.text_input(
                    "Parent master ID * (unless standalone)", initial["parent_master_id"]
                )
                values["parent_scheme_name"] = st.text_input(
                    "Parent scheme name", initial["parent_scheme_name"]
                )
                parent_options = [
                    "", "CURATED_OFFICIAL_RELATIONSHIP", "MONITORED_OFFICIAL_RELATIONSHIP",
                    "STANDALONE_OFFICIAL_CALL", "UNRESOLVED", "UMBRELLA_ONLY_REVIEW",
                ]
                if initial["parent_resolution"] not in parent_options:
                    parent_options.append(initial["parent_resolution"])
                values["parent_resolution"] = st.selectbox(
                    "Parent relationship decision * (calls)",
                    parent_options,
                    index=parent_options.index(initial["parent_resolution"]),
                )
                values["applicant_layer"] = st.text_input(
                    "Applicant layer * (calls)", initial["applicant_layer"]
                )
                values["startup_relevance"] = st.text_input(
                    "Startup relevance", initial["startup_relevance"]
                )
                values["implementation_role"] = st.text_input(
                    "Implementation role", initial["implementation_role"]
                )
            with relation_cols[1]:
                values["sector_scope"] = st.text_input(
                    "Sector scope", initial["sector_scope"]
                )
                values["status_basis"] = st.text_input(
                    "Status basis", initial["status_basis"]
                )
                values["status_evidence"] = st.text_area(
                    "Status evidence * (open/upcoming call, unless dated)", initial["status_evidence"], height=100
                )
                values["last_verified_at"] = st.text_input(
                    "Last verified", initial["last_verified_at"]
                )

            values["source_evidence_urls"] = st.text_area(
                "Official source evidence URLs * — one URL per line",
                initial["source_evidence_urls"],
                height=100,
            )

            st.markdown("#### Structured lists — one item per line")
            list_cols = st.columns(2)
            for index, field in enumerate(LIST_FIELDS):
                label = field.replace("_", " ").title()
                with list_cols[index % 2]:
                    values[field] = st.text_area(
                        label,
                        initial[field],
                        height=120 if field in {"objectives", "eligibility", "benefits"} else 90,
                    )

            notes = st.text_area(
                "Reviewer notes / reason",
                placeholder="Explain corrections, approval, evidence request or rejection.",
            )
            action_cols = st.columns(4)
            save_clicked = action_cols[0].form_submit_button("Save draft", use_container_width=True)
            approve_clicked = action_cols[1].form_submit_button(
                "Approve",
                type="primary",
                use_container_width=True,
            )
            evidence_clicked = action_cols[2].form_submit_button(
                "Needs more evidence", use_container_width=True
            )
            reject_clicked = action_cols[3].form_submit_button(
                "Reject", use_container_width=True
            )

        if save_clicked or approve_clicked or evidence_clicked or reject_clicked:
            try:
                edited = build_edited_record(record, values)
                if save_clicked:
                    service.save_draft(selected_id, edited, reviewer=reviewer, notes=notes)
                    st.success("Draft saved.")
                elif approve_clicked:
                    edited_assessment = verification_assessment(edited)
                    edited_duplicates = service.duplicate_candidates(selected_id, edited)
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
                    service.approve(selected_id, edited, reviewer=reviewer, notes=notes)
                    st.success("Record approved into scheme_staging. Publication remains a separate decision.")
                elif evidence_clicked:
                    service.mark_needs_more_evidence(
                        selected_id, edited, reviewer=reviewer, notes=notes
                    )
                    st.success("Record retained in the queue for more evidence.")
                elif reject_clicked:
                    service.reject(selected_id, edited, reviewer=reviewer, notes=notes)
                    st.success("Record rejected and written to rejected_scheme_records.")
                st.rerun()
            except Exception as exc:  # Streamlit must show actionable validation errors.
                st.error(str(exc))

        if item["review_status"] in {"APPROVED", "REJECTED"}:
            if st.button("Reopen this record"):
                try:
                    service.reopen(selected_id, reviewer=reviewer, notes="Reopened from UI")
                    st.success("Record reopened.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    with evidence_tab:
        st.markdown("#### Source evidence")
        sources = record.get("source_evidence") or []
        if not sources:
            st.info("No source evidence is stored for this record.")
        for index, source in enumerate(sources, start=1):
            title = source.get("title") or source.get("url") or f"Source {index}"
            with st.expander(f"{index}. {title}"):
                st.json(source)
        st.markdown("#### Field evidence")
        st.json(record.get("field_evidence") or {}, expanded=False)

    with history_tab:
        history = item.get("history") or []
        if not history:
            st.info("No admin review actions have been recorded yet.")
        else:
            display_rows = [
                {
                    "Action": entry["action"],
                    "Reviewer": entry["reviewer"],
                    "Notes": entry.get("notes") or "",
                    "Created": entry["created_at"],
                }
                for entry in history
            ]
            st.dataframe(display_rows, use_container_width=True, hide_index=True)
            for entry in history:
                with st.expander(
                    f"{entry['action']} by {entry['reviewer']} — {entry['created_at']}"
                ):
                    if entry.get("notes"):
                        st.write(entry["notes"])
                    st.markdown("**Before**")
                    st.json(entry.get("before"), expanded=False)
                    st.markdown("**After**")
                    st.json(entry.get("after"), expanded=False)


if __name__ == "__main__":
    main()
