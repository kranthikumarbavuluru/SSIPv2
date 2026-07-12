from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py"
SPEC = importlib.util.spec_from_file_location("dst_hotfix_34032", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_self_test_passes() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True
    assert all(result["tests"].values())


def test_source_url_is_target_and_reverse_link_recovers_lineage() -> None:
    review = [{
        "review_id": "r1",
        "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
        "proposed_canonical_name": "Example Scheme",
        "source_page_title": "Schemes",
        "source_url": "https://dst.gov.in/example-scheme",
    }]
    pages = [
        {
            "page_id": "category",
            "final_url": "https://dst.gov.in/schemes",
            "page_title": "Schemes",
            "page_role": "SCHEME_CATEGORY_INDEX",
        },
        {
            "page_id": "target",
            "final_url": "https://dst.gov.in/example-scheme",
            "page_title": "Example Scheme",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.95",
            "scheme_evidence_score": "0.90",
            "main_text": "Objectives eligibility funding support how to apply beneficiaries scope duration.",
        },
    ]
    links = [{
        "from_url": "https://dst.gov.in/schemes",
        "to_url": "https://dst.gov.in/example-scheme",
        "normalized_to_url": "https://dst.gov.in/example-scheme",
        "anchor_text": "Example Scheme",
    }]
    result = MODULE.process_hotfix(review, [], [], [], pages, links, MODULE.DEFAULT_CONFIG)
    row = result.direct_targets[0]
    assert row["direct_target_match"] == "1"
    assert row["target_url"] == "https://dst.gov.in/example-scheme"
    assert row["gap_classification"] == "POSSIBLE_NEW_SCHEME"
    assert result.lineage[0]["source_page_url"] == "https://dst.gov.in/schemes"


def test_call_page_cannot_become_permanent_entity() -> None:
    review = [{
        "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
        "proposed_canonical_name": "Call for Proposals 2026 under Test Programme",
        "source_page_title": "Programmes",
        "source_url": "https://dst.gov.in/callforproposals/test-2026",
    }]
    pages = [{
        "page_id": "call",
        "final_url": "https://dst.gov.in/callforproposals/test-2026",
        "page_title": "Call for Proposals 2026 under Test Programme",
        "page_role": "CALL_FOR_PROPOSALS",
        "page_role_confidence": "0.99",
        "call_evidence_score": "0.98",
        "main_text": "Applications invited. Closing date 30 September 2026.",
    }]
    result = MODULE.process_hotfix(review, [], [], [], pages, [], MODULE.DEFAULT_CONFIG)
    assert result.direct_targets[0]["gap_classification"] == "CALL_OR_TEMPORARY_OPPORTUNITY"
    assert result.new_schemes == []
    assert result.new_programmes == []


def test_generic_provisional_entities_are_removed_from_corrected_inventory() -> None:
    schemes = [
        {
            "provisional_entity_id": "s1",
            "proposed_canonical_name": "About the Schemes",
            "official_source_url": "https://dst.gov.in/about-schemes",
            "identity_confidence": "0.8",
            "master_evidence_score": "0.5",
        },
        {
            "provisional_entity_id": "s2",
            "proposed_canonical_name": "Valid Research Scheme",
            "official_source_url": "https://dst.gov.in/valid-research-scheme",
            "identity_confidence": "0.9",
            "master_evidence_score": "0.9",
        },
    ]
    pages = [
        {
            "page_id": "about",
            "final_url": "https://dst.gov.in/about-schemes",
            "page_title": "About the Schemes",
            "page_role": "GENERAL_INFORMATION",
            "main_text": "General scheme information.",
        },
        {
            "page_id": "valid",
            "final_url": "https://dst.gov.in/valid-research-scheme",
            "page_title": "Valid Research Scheme",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.95",
            "scheme_evidence_score": "0.9",
            "main_text": "Objectives eligibility financial assistance how to apply beneficiaries scope duration Department of Science and Technology.",
        },
    ]
    result = MODULE.process_hotfix([], schemes, [], [], pages, [], MODULE.DEFAULT_CONFIG)
    corrected = {MODULE.entity_name(row) for row in result.corrected_schemes}
    downgraded = {MODULE.entity_name(row) for row in result.downgrades}
    assert "Valid Research Scheme" in corrected
    assert "About the Schemes" not in corrected
    assert "About the Schemes" in downgraded


def test_validation_preserves_counts_and_identity_safeguards() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True
    assert "Archive" in result["entity_downgrade_names"]
    assert "Funding Mechanism" in result["entity_downgrade_names"]
