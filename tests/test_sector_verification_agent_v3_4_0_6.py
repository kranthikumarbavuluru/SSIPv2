from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sector_verification_agent_v3_4_0_6.py"
spec = importlib.util.spec_from_file_location("sector_agent", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def taxonomy():
    return module.Taxonomy(json.loads((ROOT / "config" / "sector_taxonomy_v3_4_0_6.json").read_text(encoding="utf-8")))


def classify(row):
    return module.classify_row(row, taxonomy(), allow_network=False, use_lm=False, lm_url="", lm_model="", delay=0)


def test_nidhi_is_cross_sector_innovation():
    result = classify({"master_id": "1", "scheme_name": "NIDHI PRAYAS", "record_kind": "INCUBATION_SUPPORT", "objectives": "prototype support for innovators and startups"})
    assert result.primary_sector == "Cross-sector Innovation & Entrepreneurship"


def test_credit_guarantee_is_cross_sector_finance_not_fintech():
    result = classify({"master_id": "2", "scheme_name": "Credit Guarantee Scheme for Startups", "record_kind": "CREDIT_GUARANTEE", "benefits": "credit guarantee support across eligible sectors"})
    assert result.primary_sector == "Cross-sector MSME & Startup Finance"
    assert "Financial Services & FinTech" not in result.all_sectors


def test_biotechnology_specific_sector():
    result = classify({"master_id": "3", "scheme_name": "Bio manufacturing innovation programme", "record_kind": "GRANT", "objectives": "biotechnology, genomics and biomanufacturing"})
    assert result.primary_sector == "Biotechnology & Life Sciences"


def test_agriculture_specific_sector():
    result = classify({"master_id": "4", "scheme_name": "Agritech startup challenge", "record_kind": "GRANT", "objectives": "farm, crop and agriculture technology"})
    assert result.primary_sector == "Agriculture & AgriTech"


def test_unknown_becomes_explicit_sector_agnostic_not_blank():
    result = classify({"master_id": "5", "scheme_name": "General Startup Support", "record_kind": "SCHEME_OR_PROGRAMME", "eligibility": "startups from all sectors"})
    assert result.primary_sector == "Sector Agnostic / Multi-sector"
    assert result.all_sectors


def test_validation_preserves_identity_and_has_no_missing_sector():
    tax = taxonomy()
    before = [
        {"master_id": "a", "scheme_name": "NIDHI PRAYAS", "record_kind": "INCUBATION_SUPPORT", "sector": ""},
        {"master_id": "b", "scheme_name": "Agri Challenge", "record_kind": "GRANT", "sector": ""},
    ]
    results = [classify(row) for row in before]
    after = []
    for row, result in zip(before, results):
        copy = dict(row)
        copy["sector"] = module.list_cell(result.all_sectors)
        after.append(copy)
    validation = module.validate(before, after, results, tax)
    assert validation["validation_passed"] is True
    assert validation["counts"]["records_missing_sector"] == 0
