from __future__ import annotations

"""Streamlit media review workspace for SSIP v3.4.7.3.

This is intentionally separate from the public dashboard.  Reviewers see the
source asset beside extracted fields and can append corrections/decisions;
raw images and field evidence are never edited by this UI.
"""

from pathlib import Path
import sys

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.review_v3_4_7_3 import MediaReviewStore, build_review_workspace  # noqa: E402


def _safe_asset_path(relative_path: str) -> Path | None:
    candidate = (PROJECT_ROOT / relative_path).resolve()
    if PROJECT_ROOT.resolve() not in candidate.parents or not candidate.exists():
        return None
    return candidate


def main() -> None:
    st.set_page_config(page_title="SSIP Media Review", layout="wide")
    st.title("Media review workspace")
    st.caption("Raw media and field-level evidence are read-only. Corrections are stored as append-only review events.")
    ingest_date = st.text_input("Batch date", value="2026-07-22")
    try:
        store = MediaReviewStore(PROJECT_ROOT, ingest_date)
        workspace = build_review_workspace(PROJECT_ROOT, ingest_date)
    except ValueError as exc:
        st.error(str(exc))
        return
    candidates = store.candidates()
    if not candidates:
        st.info("No extracted candidates are available for this date. Run intake, extraction and entity mapping first.")
        return
    st.metric("Candidates", workspace.candidate_count)
    selected_id = st.selectbox("Candidate", [str(row.get("candidate_id", "")) for row in candidates])
    candidate = next(row for row in candidates if row.get("candidate_id") == selected_id)
    effective = store.effective_candidate(candidate)
    left, right = st.columns([1, 1.25])
    with left:
        st.subheader("Source asset")
        asset_path = _safe_asset_path(str(candidate.get("source_asset_path", "")))
        if asset_path and asset_path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
            st.image(str(asset_path), use_container_width=True)
        elif asset_path:
            st.info(f"Source file: {asset_path.name}")
        else:
            st.warning("Source asset is missing from the project.")
        st.caption(f"SHA-256: {candidate.get('source_asset_sha256', '—')}")
        st.json({"evidence_ids": candidate.get("evidence_ids", []), "warnings": candidate.get("warnings", [])})
    with right:
        st.subheader("Extracted and corrected fields")
        reviewer = st.text_input("Reviewer", value="reviewer")
        name = st.text_input("Canonical name", value=str(effective.get("canonical_name", "")))
        department = st.text_input("Department", value=str(effective.get("department", "Others / Unmapped")))
        kind = st.selectbox("Record kind", ["SCHEME", "APPLICATION_CALL", "CHALLENGE", "OTHER"], index=["SCHEME", "APPLICATION_CALL", "CHALLENGE", "OTHER"].index(str(effective.get("record_kind", "OTHER"))) if str(effective.get("record_kind", "OTHER")) in {"SCHEME", "APPLICATION_CALL", "CHALLENGE", "OTHER"} else 3)
        official_url = st.text_input("Official URL", value=str(effective.get("official_page_url", "") or ((effective.get("official_links") or [""])[0])))
        notes = st.text_area("Review notes", value=str(effective.get("decision_notes", "")))
        with st.form("media_review_actions"):
            correction = st.form_submit_button("Save correction")
            approve = st.form_submit_button("Approve for publication")
            reject = st.form_submit_button("Reject")
        if correction or approve or reject:
            changes = {"canonical_name": name, "department": department, "record_kind": kind, "official_page_url": official_url}
            store.record_correction(selected_id, changes, reviewer, notes)
            if approve:
                store.record_decision(selected_id, "APPROVE", reviewer, notes)
            elif reject:
                store.record_decision(selected_id, "REJECT", reviewer, notes)
            st.success("Review event recorded without modifying raw evidence.")
            st.rerun()


if __name__ == "__main__":
    main()
