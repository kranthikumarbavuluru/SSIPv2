from pathlib import Path
import unittest

from agents.governed_v1.record_role_agent import RecordRoleAgent


ROOT = Path(__file__).resolve().parents[1]


class RecordRoleAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = RecordRoleAgent(ROOT / "config/record_role_rules_v1.json")

    def test_sitemap_is_never_a_scheme(self) -> None:
        decision = self.agent.classify({"scheme_name": "Sitemap.xml", "official_page_url": "https://dst.gov.in/sitemap.xml"})
        self.assertEqual(decision.role, "NAVIGATION_OR_UTILITY")

    def test_contact_page_is_never_a_scheme(self) -> None:
        decision = self.agent.classify({"scheme_name": "Contact Us", "official_page_url": "https://msme.gov.in/contact"})
        self.assertEqual(decision.role, "NAVIGATION_OR_UTILITY")

    def test_report_pdf_is_never_a_scheme(self) -> None:
        decision = self.agent.classify({"scheme_name": "Annual Research Report.pdf", "official_page_url": "https://dst.gov.in/report.pdf"})
        self.assertIn(decision.role, {"REPORT_OR_PUBLICATION", "SUPPORTING_DOCUMENT"})


if __name__ == "__main__":
    unittest.main()
