from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dst_selective_queue_calibration_v3_4_0_3_3_1.py"
spec = importlib.util.spec_from_file_location("hotfix", MODULE_PATH)
assert spec and spec.loader
hotfix = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hotfix
spec.loader.exec_module(hotfix)


def cfg():
    import json
    return json.loads(json.dumps(hotfix.DEFAULT_CONFIG))


def unresolved(name: str, url: str, sources: int = 1, relevance: int = 0):
    return {
        "target_url": url,
        "normalized_target_url": url,
        "proposed_name": name,
        "final_gap_classification": "UNRESOLVED",
        "unique_source_pages": str(sources),
        "main_content_occurrences": "0",
        "max_relevance_score": str(relevance),
    }


def test_sitewide_category_override():
    row = unresolved("National Missions", "https://dst.gov.in/national-missions", 416, 75)
    scored = hotfix.score_target(row, cfg())
    assert scored["calibrated_classification"] == "CATEGORY_OR_INDEX_PAGE"
    assert scored["calibrated_decision"] == "OFFLINE_CLOSE"


def test_policy_document_override():
    row = unresolved("Science, Technology & Innovation Policy 2013", "https://dst.gov.in/st-system-india/science-and-technology-policy-2013", 416, 75)
    scored = hotfix.score_target(row, cfg())
    assert scored["calibrated_classification"] == "POLICY_REPORT_OR_DOCUMENT"


def test_press_release_never_queued():
    row = unresolved("ARCI develops technology", "https://dst.gov.in/pressrelease/arci-develops-technology", 1, 55)
    scored = hotfix.score_target(row, cfg())
    assert scored["calibrated_classification"] == "NEWS_EVENT_OR_RECRUITMENT"
    assert not scored["calibrated_decision"].startswith("SELECTIVE_CRAWL")


def test_foundation_is_institution_not_programme():
    row = unresolved("Anusandhan National Research Foundation (ANRF)", "https://dst.gov.in/anusandhan-national-research-foundation-anrf", 1, 55)
    scored = hotfix.score_target(row, cfg())
    assert scored["calibrated_classification"] == "INSTITUTION_OR_RESOURCE"


def test_named_initiative_enters_calibrated_queue():
    row = unresolved("Science Wings Abroad", "https://dst.gov.in/science-wings-abroad-0", 1, 0)
    scored = hotfix.score_target(row, cfg())
    assert scored["calibrated_decision"] in {"SELECTIVE_CRAWL_HIGH", "SELECTIVE_CRAWL_MEDIUM"}


def test_prepare_only_preserves_pending_queue():
    row = unresolved("Science Wings Abroad", "https://dst.gov.in/science-wings-abroad-0", 1, 0)
    result = hotfix.process([row], [], [], [], cfg(), run_crawl=False)
    assert len(result.queue) == 1
    assert len(result.final_context) == 1
    assert result.final_context[0]["final_gap_classification"] == "UNRESOLVED"
    assert result.final_context[0]["selective_crawl_required"] == "1"


def test_fake_fetch_creates_only_provisional_programme():
    row = unresolved("Science Wings Abroad", "https://dst.gov.in/science-wings-abroad-0", 1, 0)

    def fake_fetch(queue_row):
        return {
            **queue_row,
            "crawl_status": "FETCHED",
            "http_status": "200",
            "final_url": queue_row["target_url"],
            "content_type": "text/html",
            "page_title": "Science Wings Abroad Programme",
            "fetched_classification": "POSSIBLE_NEW_PROGRAMME",
            "fetched_confidence": "0.9200",
            "fetched_reasons": "PROGRAMME_TITLE_SIGNAL;MASTER_EVIDENCE",
            "inferred_entity_type": "PROGRAMME",
        }

    result = hotfix.process([row], [], [], [], cfg(), run_crawl=True, output_dir=Path("."), fetcher=fake_fetch)
    assert len(result.new_programmes) == 1
    assert len(result.new_schemes) == 0
    candidate = result.new_programmes[0]
    assert candidate["identity_state"] == "PROVISIONAL_NOT_LOCKED"
    assert candidate["identity_locked"] == "0"


def test_existing_inventory_and_quality_reviews_are_preserved():
    scheme = {"provisional_entity_id": "s1", "proposed_canonical_name": "Valid Scheme", "official_source_url": "https://dst.gov.in/valid-scheme"}
    programme = {"provisional_entity_id": "p1", "proposed_canonical_name": "Valid Programme", "official_source_url": "https://dst.gov.in/valid-programme"}
    review = {"review_type": "PROVISIONAL_ENTITY_QUALITY", "provisional_entity_id": "q1", "proposed_name": "Ambiguous"}
    result = hotfix.process([], [review], [scheme], [programme], cfg())
    assert result.final_schemes == [scheme]
    assert result.final_programmes == [programme]
    assert result.final_review == [review]


def test_accessibility_link_is_valid_final_classification():
    context = {
        "target_url": "https://dst.gov.in/accessibility-options",
        "proposed_name": "Accessibility Options",
        "final_gap_classification": "ACCESSIBILITY_LINK",
    }
    result = hotfix.process([context], [], [], [], cfg(), run_crawl=False)
    validation = hotfix.validate(
        result,
        [context],
        [],
        [],
        [],
        {"counts": {"input_unique_gap_count": 1, "input_duplicate_gap_occurrences": 0}},
        cfg(),
        False,
        0,
    )
    assert validation["quality"]["invalid_final_classifications"] == []
    assert validation["checks"]["all_final_classifications_valid"] is True
    assert validation["checks"]["identity_locked"] is False
    assert validation["calibration_validation_passed"] is True
    assert validation["ready_for_v3_4_0_4"] is True
