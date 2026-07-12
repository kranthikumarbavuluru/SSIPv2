from pathlib import Path
from agents.v3420.role_agent import RecordRoleAgent
from agents.v3420.relevance_agent import StartupRelevanceAgent
from agents.v3420.sector_agent import EvidenceSectorAgent
from agents.v3420.governance import GovernancePolicy

ROOT = Path(__file__).resolve().parents[1]

def test_navigation_is_quarantined():
    r = RecordRoleAgent().classify("Sitemap.Xml", "", "")
    assert r.role == "NAVIGATION_OR_UTILITY"

def test_report_is_document():
    r = RecordRoleAgent().classify("Startup Ecosystem Report.Pdf", "", "")
    assert r.role == "SUPPORTING_DOCUMENT"

def test_nidhi_is_scheme():
    r = RecordRoleAgent().classify("NIDHI – PRAYAS", "startup prototype support", "")
    assert r.role == "SCHEME_OR_PROGRAMME"

def test_relevance():
    r = StartupRelevanceAgent().classify(
        "DPIIT startup may apply for prototype grant through an approved incubator application portal."
    )
    assert r.publishable

def test_sector_agritech():
    a = EvidenceSectorAgent(ROOT / "config/sector_taxonomy_v3_4_2_1.json")
    d = a.classify("AgriTech Challenge", "precision farming startup support", "", "prototype grant")
    assert d.primary == "Agriculture & AgriTech"

def test_sector_cross_finance():
    a = EvidenceSectorAgent(ROOT / "config/sector_taxonomy_v3_4_2_1.json")
    d = a.classify("Credit Guarantee Scheme for Startups", "", "DPIIT startups", "credit guarantee")
    assert d.primary == "Cross-sector MSME & Startup Finance"

def test_policy_blocks_navigation():
    d = GovernancePolicy().decide("NAVIGATION_OR_UTILITY", "NOT_STARTUP_RELEVANT", 0, False)
    assert d.decision == "QUARANTINE"


def test_pdf_is_supporting_document():
    r = RecordRoleAgent().classify("Startup Scheme Guidelines.Pdf", "startup grant", "")
    assert r.role == "SUPPORTING_DOCUMENT"

def test_generic_schemes_page_is_index():
    r = RecordRoleAgent().classify("Schemes", "", "")
    assert r.role == "CATEGORY_OR_INDEX_PAGE"
