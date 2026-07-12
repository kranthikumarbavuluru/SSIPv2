from __future__ import annotations

from pathlib import Path

from services.admin_verification_intelligence_v1 import (
    record_category,
    verification_assessment,
)
from ssip_agents.dst_pilot.admin_bridge import BridgePaths, DSTAdminBridge


ROOT = Path(__file__).resolve().parents[1]


def dst_items():
    return DSTAdminBridge(BridgePaths.defaults(ROOT)).build_items()


def test_verified_rdif_call_passes_identifiable_evidence_checks() -> None:
    item = next(item for item in dst_items() if "RDI Fund" in item["scheme_name"])
    assessment = verification_assessment(item["validated_record"])
    assert assessment.category == "APPLICATION_CALL"
    assert assessment.ready_for_approval is True
    assert not assessment.blocking_gaps
    assert assessment.passed_checks == len(assessment.checks)


def test_open_call_without_status_parent_or_application_route_is_blocked() -> None:
    record = {
        "master_id": "call-1",
        "scheme_name": "Unverified call",
        "source": "Department",
        "record_kind": "APPLICATION_CALL",
        "application_status": "OPEN",
        "official_page_url": "https://example.gov.in/call",
        "source_evidence": [{"url": "https://example.gov.in/call"}],
    }
    assessment = verification_assessment(record)
    assert assessment.ready_for_approval is False
    missing = {check["code"] for check in assessment.checks if check["required"] and not check["passed"]}
    assert {"CALL_STATUS", "APPLICANT_LAYER", "PARENT_RELATIONSHIP", "APPLICATION_ROUTE"}.issubset(missing)


def test_intermediary_call_is_never_labelled_direct() -> None:
    item = next(
        item for item in dst_items()
        if item["validated_record"].get("applicant_layer") == "INTERMEDIARY_IMPLEMENTER"
    )
    assert record_category(item["validated_record"]) == "ECOSYSTEM_CALL"


def test_admin_ui_exposes_scalable_workspaces_and_approval_guard() -> None:
    source = (ROOT / "ui/admin_review_app_v1.py").read_text(encoding="utf-8-sig")
    assert '"Review Inbox", "Publication Queue", "Historical Archive", "Department Agent Intake", "Ingestion Runs", "Audit Trail"' in source
    assert "Run comparison / dry run" in source
    assert "Import to Review Queue" in source
    assert "verification_assessment(record)" in source
    assert "Fields marked * participate in mandatory checks" in source
    assert "edited_assessment = verification_assessment(edited)" in source
    assert "Official source evidence URLs *" in source
