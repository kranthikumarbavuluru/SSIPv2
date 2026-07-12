from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dst_permanent_inventory_builder_v3_4_0_3.py"


def load_module():
    spec = importlib.util.spec_from_file_location("dst_inventory_v3403", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fixture_rows():
    pages = [
        {
            "classified_page_id": "scheme1",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.93",
            "scheme_evidence_score": "84",
            "call_evidence_score": "0",
            "page_title": "Promotion of University Research and Scientific Excellence (PURSE)",
            "final_url": "https://dst.gov.in/purse",
            "main_text": "Objectives Eligibility Financial assistance Who can apply Application process Beneficiaries Scope.",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "requires_admin_review": "0",
        },
        {
            "classified_page_id": "programme1",
            "page_role": "PROGRAMME_MASTER_CANDIDATE",
            "page_role_confidence": "0.91",
            "scheme_evidence_score": "70",
            "call_evidence_score": "0",
            "page_title": "Technology Development Programme (TDP)",
            "final_url": "https://dst.gov.in/tdp",
            "main_text": "Programme objectives, eligibility, financial assistance and application procedure.",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "requires_admin_review": "0",
        },
        {
            "classified_page_id": "badmaster",
            "page_role": "SCHEME_MASTER_CANDIDATE",
            "page_role_confidence": "0.84",
            "scheme_evidence_score": "40",
            "call_evidence_score": "90",
            "page_title": "Call for Proposals under Technology Development Programme 2026",
            "final_url": "https://dst.gov.in/call/tdp-2026",
            "main_text": "Applications are invited with a closing date.",
            "text_extraction_status": "SUCCESS_MAIN_CONTENT",
            "requires_admin_review": "1",
        },
        {
            "classified_page_id": "call1",
            "page_role": "CALL_FOR_PROPOSALS",
            "page_role_confidence": "0.99",
            "scheme_evidence_score": "10",
            "call_evidence_score": "100",
            "page_title": "Special Call for Proposals 2026",
            "final_url": "https://dst.gov.in/call/special-2026",
            "main_text": "Applications are invited.",
        },
        {
            "classified_page_id": "category1",
            "page_role": "SCHEME_CATEGORY_INDEX",
            "page_title": "Schemes/Programmes",
            "final_url": "https://dst.gov.in/schemes-programmes",
        },
    ]
    documents = [
        {
            "document_id": "doc1",
            "source_page_url": "https://dst.gov.in/purse",
            "document_url": "https://dst.gov.in/purse-guidelines.pdf",
            "filename": "PURSE Guidelines.pdf",
            "document_role": "GUIDELINE",
            "document_role_confidence": "0.95",
        }
    ]
    links = [
        {
            "from_url": "https://dst.gov.in/schemes-programmes",
            "to_url": "https://dst.gov.in/purse",
            "anchor_text": "Promotion of University Research and Scientific Excellence",
            "is_internal": "1",
            "is_document": "0",
        },
        {
            "from_url": "https://dst.gov.in/schemes-programmes",
            "to_url": "https://dst.gov.in/tdp",
            "anchor_text": "Technology Development Programme",
            "is_internal": "1",
            "is_document": "0",
        },
    ]
    return pages, documents, links


def test_self_test_passes():
    module = load_module()
    result = module.self_test()
    assert result["self_test_passed"] is True


def test_call_like_master_is_rejected_and_identity_stays_provisional():
    module = load_module()
    pages, documents, links = fixture_rows()
    result = module.build_inventory(pages, documents, links, module.DEFAULT_CONFIG)
    entities = result.schemes + result.programmes

    assert len(entities) == 2
    assert all(row["identity_state"] == "PROVISIONAL_NOT_LOCKED" for row in entities)
    assert not any("2026" in row["proposed_canonical_name"] for row in entities)
    assert any(
        row["rejection_reason"] == "CALL_LIKE_TITLE_BLOCKED_FROM_PERMANENT_INVENTORY"
        for row in result.rejected
    )


def test_abbreviation_category_and_guideline_evidence():
    module = load_module()
    pages, documents, links = fixture_rows()
    result = module.build_inventory(pages, documents, links, module.DEFAULT_CONFIG)

    assert any(row["alias_text"] == "PURSE" for row in result.aliases)
    assert any(row["evidence_type"] == "CATEGORY_INDEX_LINK" for row in result.evidence)
    assert any(row["evidence_type"] == "OFFICIAL_DOCUMENT_GUIDELINE" for row in result.evidence)


def test_end_to_end_cli(tmp_path: Path):
    pages, documents, links = fixture_rows()
    project = tmp_path / "SSIP"
    input_dir = project / "data" / "departments" / "dst" / "v3_4_0_2"
    link_dir = project / "data" / "departments" / "dst" / "v3_4_0_1" / "crawl"
    output_dir = project / "data" / "departments" / "dst" / "v3_4_0_3"

    write_csv(input_dir / "dst_classified_pages_v3_4_0_2.csv", pages)
    write_csv(input_dir / "dst_classified_documents_v3_4_0_2.csv", documents)
    write_csv(link_dir / "dst_link_graph_v3_4_0_1.csv", links)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project-root",
            str(project),
            "--strict",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    validation = json.loads((output_dir / "dst_inventory_validation_v3_4_0_3.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "dst_inventory_summary_v3_4_0_3.json").read_text(encoding="utf-8"))
    assert validation["inventory_validation_passed"] is True
    assert validation["quality"]["call_seeded_entities"] == 0
    assert summary["counts"]["provisional_entities_total"] == 2
