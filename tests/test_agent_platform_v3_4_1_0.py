from pathlib import Path
from agents.taxonomy import SectorTaxonomy
from agents.sector_agent import SectorVerificationAgent
from agents.relevance_agent import StartupRelevanceAgent

ROOT = Path(__file__).resolve().parents[1]

def taxonomy():
    return SectorTaxonomy(ROOT / "config/sector_taxonomy_v3_4_1_0.json")

def test_taxonomy_unique():
    tx = taxonomy()
    assert len(tx.names) == len(set(tx.names))
    assert "Cross-sector Innovation & Entrepreneurship" in tx.names

def test_agritech_classification():
    agent = SectorVerificationAgent(taxonomy(), None)
    record = {
        "name": "AgriTech Innovation Challenge",
        "objective": "Support precision farming and agriculture startups.",
        "eligibility": "Startups",
        "benefits": "Prototype grant",
        "support_type": "Grant",
        "startup_stage": "Prototype"
    }
    d = agent.classify(record, "1", "precision farming agriculture startups", "https://example.gov.in")
    assert d.primary_sector == "Agriculture & AgriTech"

def test_cross_sector_finance():
    agent = SectorVerificationAgent(taxonomy(), None)
    record = {
        "name": "Credit Guarantee Scheme for Startups",
        "objective": "Credit guarantee and working capital support to startups across sectors.",
        "eligibility": "DPIIT startups",
        "benefits": "Guarantee",
        "support_type": "Credit",
        "startup_stage": ""
    }
    d = agent.classify(record, "2", "credit guarantee working capital startups across sectors", "")
    assert d.primary_sector == "Cross-sector MSME & Startup Finance"

def test_no_blank_fallback():
    agent = SectorVerificationAgent(taxonomy(), None)
    record = {k: "" for k in ("name","objective","eligibility","benefits","support_type","startup_stage")}
    d = agent.classify(record, "3", "", "")
    assert d.primary_sector == "Sector Agnostic / Multi-sector"
    assert d.review_required

def test_startup_relevance():
    d = StartupRelevanceAgent().classify(
        "DPIIT-recognised startup may apply through an approved incubator application portal."
    )
    assert d.publishable
    assert d.score >= 70
