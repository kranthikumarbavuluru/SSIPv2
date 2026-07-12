from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_evidence_page_role_classifier_v3_4_0_2.py"
SPEC = importlib.util.spec_from_file_location("dst_classifier_v3402", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def base_page(**updates: str) -> dict[str, str]:
    row = {
        "page_id": "p1",
        "requested_url": "https://dst.gov.in/example",
        "final_url": "https://dst.gov.in/example",
        "page_title": "Example",
        "main_text": "General information",
        "page_role_hint": "UNCLASSIFIED_SOURCE_PAGE",
        "source_role_hint": "UNKNOWN",
        "http_status": "200",
        "content_type": "text/html",
        "text_extraction_status": "SUCCESS_MAIN_CONTENT",
        "word_count": "100",
    }
    row.update(updates)
    return row


def test_self_test_passes() -> None:
    result = MODULE.self_test()
    assert result["self_test_passed"] is True


def test_call_is_not_promoted_to_scheme() -> None:
    row = base_page(
        page_id="call1",
        final_url="https://dst.gov.in/callforproposals/advanced-materials-2026",
        page_title="Call for Proposals under National Programme on Nano Science and Technology",
        main_text="Proposals are invited. Closing date is 31 August 2026.",
        page_role_hint="CALL_CANDIDATE",
    )
    pages, _ = MODULE.classify_pages(
        [row],
        [{"page_id": "call1", "call_pattern": "CALL_FOR_PROPOSALS"}],
        {},
        MODULE.DEFAULT_CONFIG,
    )
    assert pages[0]["page_role"] == "CALL_FOR_PROPOSALS"
    assert pages[0]["page_role"] not in MODULE.MASTER_CANDIDATE_ROLES
    assert "canonical_scheme_name" not in pages[0]
    assert pages[0]["possible_parent_name_text"]


def test_scheme_and_programme_candidate_separation() -> None:
    scheme = base_page(
        page_id="scheme",
        final_url="https://dst.gov.in/women-scientist-scheme",
        page_title="Women Scientist Scheme",
        main_text="Objectives Eligibility Financial assistance Beneficiaries How to apply Duration Scope",
        page_role_hint="SCHEME_PROGRAMME_CANDIDATE",
    )
    programme = base_page(
        page_id="programme",
        final_url="https://dst.gov.in/technology-development-programme",
        page_title="Technology Development Programme",
        main_text="Objectives Eligibility Funding support Beneficiaries Application process Duration Focus areas",
        page_role_hint="SCHEME_PROGRAMME_CANDIDATE",
    )
    pages, _ = MODULE.classify_pages([scheme, programme], [], {}, MODULE.DEFAULT_CONFIG)
    roles = {row["page_id"]: row["page_role"] for row in pages}
    assert roles["scheme"] == "SCHEME_MASTER_CANDIDATE"
    assert roles["programme"] == "PROGRAMME_MASTER_CANDIDATE"


def test_end_to_end_outputs(tmp_path: Path) -> None:
    input_dir = tmp_path / "data" / "departments" / "dst" / "v3_4_0_1_1"
    crawl_dir = tmp_path / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    output_dir = tmp_path / "data" / "departments" / "dst" / "v3_4_0_2"

    pages = [
        base_page(
            page_id="call1",
            final_url="https://dst.gov.in/callforproposals/tdp-2026",
            page_title="Call for Project Proposals under Technology Development Programme",
            main_text="Call for proposals. Closing date. Proposals are invited.",
            page_role_hint="CALL_CANDIDATE",
        ),
        base_page(
            page_id="broken",
            final_url="https://dst.gov.in/broken",
            page_title="Broken",
            main_text="",
            http_status="404",
            word_count="0",
            text_extraction_status="HTTP_ERROR_PAGE",
        ),
    ]
    docs = [{
        "document_id": "d1",
        "document_url": "https://dst.gov.in/files/tdp-guidelines.pdf",
        "source_page_url": pages[0]["final_url"],
        "filename": "TDP-Guidelines.pdf",
        "anchor_text": "Guidelines",
        "document_role_hint": "GUIDELINE",
    }]
    audit = [{"page_id": "call1", "call_pattern": "CALL_FOR_PROPOSALS"}]
    links = [{
        "from_url": pages[0]["final_url"],
        "to_url": docs[0]["document_url"],
        "normalized_to_url": docs[0]["document_url"],
        "anchor_text": "Guidelines",
        "in_main_content": "1",
        "is_internal": "1",
        "is_document": "1",
        "role_hint": "DOCUMENT",
    }]

    write_csv(input_dir / MODULE.PAGE_INPUT, pages)
    write_csv(input_dir / MODULE.DOCUMENT_INPUT, docs)
    write_csv(input_dir / MODULE.CALL_AUDIT_INPUT, audit)
    write_csv(crawl_dir / MODULE.LINK_GRAPH_INPUT, links)

    summary = MODULE.run_classifier(
        input_dir,
        crawl_dir / MODULE.LINK_GRAPH_INPUT,
        output_dir,
        MODULE.DEFAULT_CONFIG,
    )
    assert summary["classifier_validation_passed"] is True
    assert (output_dir / MODULE.CLASSIFIED_PAGES_OUTPUT).exists()
    assert (output_dir / MODULE.CLASSIFIED_DOCUMENTS_OUTPUT).exists()
    assert (output_dir / MODULE.SUMMARY_OUTPUT).exists()

    validation = json.loads((output_dir / MODULE.VALIDATION_OUTPUT).read_text(encoding="utf-8"))
    assert validation["checks"]["call_candidates_not_promoted_to_master"] is True
    assert validation["checks"]["forbidden_identity_fields_absent"] is True
