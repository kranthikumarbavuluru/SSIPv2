from pathlib import Path
import unittest

from agents.governed_v1.sector_verification_agent import SectorVerificationAgent


ROOT = Path(__file__).resolve().parents[1]


class SectorVerificationAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = SectorVerificationAgent(ROOT / "config/sector_taxonomy_v1.json")

    def test_credit_guarantee_maps_to_cross_sector_finance(self) -> None:
        decision = self.agent.classify({"scheme_name": "Credit Guarantee Scheme for Startups", "benefits": "Credit guarantee for startup loans", "official_page_url": "https://startupindia.gov.in/cgss"})
        self.assertEqual(decision.primary_sector, "Cross-sector MSME & Startup Finance")

    def test_agritech_maps_to_agriculture(self) -> None:
        decision = self.agent.classify({"scheme_name": "AgriTech Innovation Grant", "eligibility": "AgriTech startups working in precision farming", "official_page_url": "https://myscheme.gov.in/agritech"})
        self.assertEqual(decision.primary_sector, "Agriculture & AgriTech")

    def test_bio_ai_has_biotech_primary_and_ai_secondary(self) -> None:
        decision = self.agent.classify({"scheme_name": "Bio-AI Programme", "objectives": "Biotechnology startups using artificial intelligence and machine learning", "official_page_url": "https://birac.nic.in/bio-ai"})
        self.assertEqual(decision.primary_sector, "Biotechnology & Life Sciences")
        self.assertIn("Artificial Intelligence & Data", decision.secondary_sectors)


if __name__ == "__main__":
    unittest.main()
