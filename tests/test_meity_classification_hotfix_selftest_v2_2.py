from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from ssip_agents.classifier.meity_classification_hotfix_v2_2 import (
    HOTFIX_VERSION,
    SOURCE_NAME,
    apply_hotfix_payloads,
    load_mapping,
)


def make_record(url: str, classification: str = "SCHEME") -> dict:
    return {
        "url": url,
        "canonical_url": url,
        "source": SOURCE_NAME,
        "title": "MeityStartupHub",
        "anchor_text": "MeitY Startup Hub",
        "classification": classification,
        "classification_confidence": 0.5,
        "classification_reasons": [],
        "programme_family": None,
        "programme_family_confidence": 0.0,
        "programme_family_method": "none",
        "lifecycle_status": "NOT_APPLICABLE" if classification == "OTHER" else "CURRENT_UNVERIFIED",
        "lifecycle_confidence": 0.35,
        "review_decision": "MANUAL_REVIEW",
        "dashboard_relevance": "MEDIUM",
        "dashboard_relevance_score": 4,
        "relevance_score": 38.0,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    mapping = load_mapping(root / "config" / "meity_classification_hotfix_v2_2.json")

    non_meity_record = {
        "url": "https://example.gov.in/scheme",
        "canonical_url": "https://example.gov.in/scheme",
        "source": "Example",
        "title": "Example Scheme",
        "classification": "SCHEME",
        "lifecycle_status": "CURRENT_UNVERIFIED",
        "review_decision": "PRIORITY_REVIEW",
        "dashboard_relevance": "HIGH",
    }
    records = [copy.deepcopy(non_meity_record)]
    for path, details in mapping.items():
        records.append(
            make_record(
                "https://msh.meity.gov.in" + path,
                "OTHER" if details["classification"] == "CALL" else "SCHEME",
            )
        )

    generic_master = {
        "master_id": "generic",
        "canonical_name": "MeityStartupHub",
        "source": SOURCE_NAME,
        "current_status": "SCHEME_INFORMATION_AVAILABLE",
    }
    example_master = {
        "master_id": "example",
        "canonical_name": "Example Scheme",
        "source": "Example",
        "current_status": "SCHEME_INFORMATION_AVAILABLE",
    }

    patched_records, patched_masters, summary, hotfix_summary = apply_hotfix_payloads(
        records,
        [example_master, generic_master],
        mapping,
        existing_summary={"input_record_count": 7},
        generated_at="2026-07-08T00:00:00+00:00",
    )

    meity_records = [r for r in patched_records if r.get("source") == SOURCE_NAME]
    meity_masters = [m for m in patched_masters if m.get("source") == SOURCE_NAME]

    assert len(meity_records) == 6
    assert len(meity_masters) == 6
    assert len({m["master_id"] for m in meity_masters}) == 6
    assert {m["canonical_name"] for m in meity_masters} == {
        details["canonical_name"] for details in mapping.values()
    }
    assert sum(1 for r in meity_records if r["classification"] == "SCHEME") == 4
    assert sum(1 for r in meity_records if r["classification"] == "CALL") == 2
    assert non_meity_record in patched_records
    assert example_master in patched_masters
    assert summary["master_candidate_count"] == 7
    assert summary["masters_by_source"][SOURCE_NAME] == 6
    assert hotfix_summary["meity_master_count_before"] == 1
    assert hotfix_summary["meity_master_count_after"] == 6

    print("MeitY Classification Hotfix self-test passed.")
    print("Resolved classified records: 6")
    print("Separate MeitY masters: 6")
    print("Hotfix version:", HOTFIX_VERSION)


if __name__ == "__main__":
    main()
