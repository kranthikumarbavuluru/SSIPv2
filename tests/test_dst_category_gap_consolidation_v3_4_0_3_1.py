from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_category_gap_consolidation_v3_4_0_3_1.py"
SPEC = importlib.util.spec_from_file_location("dst_gap_module", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_self_test_passes() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True
    assert all(result["tests"].values())


def test_url_normalization_and_duplicate_grouping() -> None:
    rows = [
        {
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "source_url": "https://DST.gov.in/example/?utm_source=x#top",
            "proposed_canonical_name": "Example Scheme",
        },
        {
            "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
            "source_url": "https://dst.gov.in/example",
            "proposed_canonical_name": "Example",
        },
    ]
    groups, duplicates = MODULE.aggregate_gaps(rows, MODULE.DEFAULT_CONFIG)
    assert len(groups) == 1
    assert len(duplicates) == 1
    assert groups[0].normalized_target_url == "https://dst.gov.in/example"


def test_call_cannot_become_permanent_candidate() -> None:
    review = [{
        "review_type": "CATEGORY_INDEX_DISCOVERY_GAP",
        "proposed_canonical_name": "Call for Proposals 2026 under Test Programme",
        "source_page_title": "Research Programmes",
        "source_url": "https://dst.gov.in/callforproposals/test-2026",
    }]
    pages = [{
        "page_id": "call1",
        "final_url": "https://dst.gov.in/callforproposals/test-2026",
        "page_title": "Call for Proposals 2026 under Test Programme",
        "page_role": "CALL_FOR_PROPOSALS",
        "page_role_confidence": "0.99",
        "call_evidence_score": "0.98",
        "main_text": "Applications invited. Closing date 30 September 2026.",
    }]
    result = MODULE.consolidate(review, [], [], [], pages, [], MODULE.DEFAULT_CONFIG)
    assert len(result.scheme_candidates) == 0
    assert len(result.programme_candidates) == 0
    assert result.unique_gaps[0]["gap_classification"] == "CALL_OR_TEMPORARY_OPPORTUNITY"


def test_validation_blocks_identity_fields_and_preserves_counts() -> None:
    built = MODULE.self_test()
    assert built["self_test_passed"] is True
    assert built["classification_counts"]["EXISTING_PROVISIONAL_ENTITY"] == 1
    assert built["classification_counts"]["POSSIBLE_NEW_SCHEME"] == 1
    assert built["classification_counts"]["POSSIBLE_NEW_PROGRAMME"] == 1
