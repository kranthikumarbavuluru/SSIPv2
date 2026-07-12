from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py"
SPEC = importlib.util.spec_from_file_location("dst_gap_34033", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_self_test_passes() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True
    assert all(result["tests"].values())


def test_global_navigation_is_filtered_without_crawl() -> None:
    ctx = MODULE.TargetContext(
        target_url="https://dst.gov.in/screen-reader-access",
        normalized_target_url="https://dst.gov.in/screen-reader-access",
        proposed_name="Screen Reader Access",
        link_occurrences=100,
        unique_source_pages=50,
        main_content_occurrences=0,
        max_relevance_score=10,
    )
    classification, confidence, reasons, queued = MODULE.classify_context_offline(ctx, {}, MODULE.DEFAULT_CONFIG)
    assert classification == "ACCESSIBILITY_LINK"
    assert confidence >= 0.9
    assert queued is False
    assert reasons


def test_high_value_category_link_is_selectively_queued() -> None:
    ctx = MODULE.TargetContext(
        target_url="https://dst.gov.in/new-science-programme",
        normalized_target_url="https://dst.gov.in/new-science-programme",
        proposed_name="New Science Programme",
        link_occurrences=2,
        unique_source_pages=1,
        main_content_occurrences=1,
        max_relevance_score=80,
        source_page_roles=["PROGRAMME_CATEGORY_INDEX"],
        anchor_texts=["New Science Programme"],
    )
    classification, confidence, reasons, queued = MODULE.classify_context_offline(ctx, {}, MODULE.DEFAULT_CONFIG)
    assert classification == "UNRESOLVED"
    assert queued is True
    assert confidence > 0.5
    assert "SELECTIVE_CRAWL_REQUIRED" in reasons


def test_call_target_never_enters_selective_queue() -> None:
    ctx = MODULE.TargetContext(
        target_url="https://dst.gov.in/callforproposals/test-2026",
        normalized_target_url="https://dst.gov.in/callforproposals/test-2026",
        proposed_name="Call for Proposals 2026 under Test Programme",
        link_occurrences=1,
        unique_source_pages=1,
        main_content_occurrences=1,
        max_relevance_score=100,
        source_page_roles=["PROGRAMME_CATEGORY_INDEX"],
    )
    classification, _, _, queued = MODULE.classify_context_offline(ctx, {}, MODULE.DEFAULT_CONFIG)
    assert classification == "CALL_OR_TEMPORARY_PAGE"
    assert queued is False


def test_fetched_scheme_requires_master_evidence() -> None:
    text = (
        "Objectives of the scheme. Eligibility and who can apply. Financial assistance and grant support. "
        "Application process and how to apply. Scope and focus areas. Beneficiaries include researchers. "
        "Duration of support. Implemented by the Department of Science and Technology."
    )
    classification, confidence, reasons, entity_type = MODULE.classify_fetched_page(
        "https://dst.gov.in/young-researcher-support-scheme",
        "Young Researcher Support Scheme",
        text,
        200,
        "text/html; charset=utf-8",
        MODULE.DEFAULT_CONFIG,
    )
    assert classification == "POSSIBLE_NEW_SCHEME"
    assert entity_type == "SCHEME"
    assert confidence >= 0.8
    assert reasons


def test_process_pipeline_preserves_inventory_and_adds_candidate() -> None:
    direct = [{
        "target_url": "https://dst.gov.in/new-programme",
        "normalized_target_url": "https://dst.gov.in/new-programme",
        "target_page_title": "New Programme",
        "occurrence_count": "1",
        "gap_classification": "UNRESOLVED",
    }]
    schemes = [{
        "provisional_entity_id": "s1",
        "proposed_canonical_name": "Existing Scheme",
        "official_source_url": "https://dst.gov.in/existing-scheme",
    }]
    programmes = []
    pages = [{
        "final_url": "https://dst.gov.in/programmes",
        "page_title": "Programmes",
        "page_role": "PROGRAMME_CATEGORY_INDEX",
    }]
    links = [{
        "from_url": "https://dst.gov.in/programmes",
        "to_url": "https://dst.gov.in/new-programme",
        "normalized_to_url": "https://dst.gov.in/new-programme",
        "anchor_text": "New Programme",
        "in_main_content": "1",
        "relevance_score": "90",
        "enqueue_decision": "QUEUED",
    }]

    def fake_fetch(row):
        return {
            **dict(row),
            "crawl_status": "FETCHED",
            "http_status": "200",
            "final_url": row["target_url"],
            "content_type": "text/html",
            "page_title": "New Programme",
            "fetched_classification": "POSSIBLE_NEW_PROGRAMME",
            "fetched_confidence": "0.9100",
            "fetched_reasons": "PROGRAMME_TITLE_SIGNAL;MASTER_EVIDENCE",
            "inferred_entity_type": "PROGRAMME",
        }

    result = MODULE.process_pipeline(
        direct, [], [], schemes, programmes, [], pages, links, [],
        MODULE.DEFAULT_CONFIG, run_crawl=True, output_dir=Path("."), fetcher=fake_fetch,
    )
    assert len(result.final_schemes) == 1
    assert len(result.final_programmes) == 1
    assert result.final_programmes[0]["identity_state"] == "PROVISIONAL_NOT_LOCKED"
    assert "canonical_scheme_name" not in result.final_programmes[0]


def test_prepare_only_project_run_writes_queue_without_network(tmp_path: Path) -> None:
    root = tmp_path
    input_dir = root / "data" / "departments" / "dst" / "v3_4_0_3_2"
    classifier_dir = root / "data" / "departments" / "dst" / "v3_4_0_2"
    crawl_dir = root / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    input_dir.mkdir(parents=True)
    classifier_dir.mkdir(parents=True)
    crawl_dir.mkdir(parents=True)

    def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        MODULE.write_csv(path, rows)

    write_csv(input_dir / MODULE.DIRECT_TARGET_INPUT, [{
        "target_url": "https://dst.gov.in/new-scheme",
        "normalized_target_url": "https://dst.gov.in/new-scheme",
        "target_page_title": "New Scheme",
        "occurrence_count": "1",
        "gap_classification": "UNRESOLVED",
    }])
    write_csv(input_dir / MODULE.REVIEW_INPUT, [])
    write_csv(input_dir / MODULE.DUPLICATE_INPUT, [])
    write_csv(input_dir / MODULE.CORRECTED_SCHEMES_INPUT, [{
        "provisional_entity_id": "s1",
        "proposed_canonical_name": "Existing Scheme",
        "official_source_url": "https://dst.gov.in/existing-scheme",
    }])
    write_csv(input_dir / MODULE.CORRECTED_PROGRAMMES_INPUT, [])
    write_csv(input_dir / MODULE.DOWNGRADES_INPUT, [])
    write_csv(classifier_dir / MODULE.CLASSIFIED_PAGES_INPUT, [{
        "final_url": "https://dst.gov.in/schemes",
        "page_title": "Schemes",
        "page_role": "SCHEME_CATEGORY_INDEX",
    }])
    write_csv(crawl_dir / MODULE.LINK_GRAPH_INPUT, [{
        "from_url": "https://dst.gov.in/schemes",
        "to_url": "https://dst.gov.in/new-scheme",
        "normalized_to_url": "https://dst.gov.in/new-scheme",
        "anchor_text": "New Scheme",
        "in_main_content": "1",
        "relevance_score": "85",
        "enqueue_decision": "QUEUED",
    }])

    _, summary = MODULE.run_pipeline(root, MODULE.DEFAULT_CONFIG, prepare_only=True)
    output_dir = root / "data" / "departments" / "dst" / "v3_4_0_3_3"
    assert (output_dir / MODULE.CRAWL_QUEUE_OUTPUT).exists()
    assert summary["network_access_used"] is False
    validation = json.loads((output_dir / MODULE.VALIDATION_OUTPUT).read_text(encoding="utf-8"))
    assert validation["counts"]["selective_crawl_queue"] == 1
    assert validation["ready_for_v3_4_0_4"] is False
