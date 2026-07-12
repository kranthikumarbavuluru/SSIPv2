from pathlib import Path
import unittest

from agents.governed_v1.startup_relevance_agent import StartupRelevanceAgent


ROOT = Path(__file__).resolve().parents[1]


class StartupRelevanceAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = StartupRelevanceAgent(ROOT / "config/startup_relevance_rules_v1.json")

    def test_startup_india_seed_fund_is_startup_relevant(self) -> None:
        row = {
            "scheme_name": "Startup India Seed Fund Scheme",
            "eligibility": "DPIIT-recognised startup",
            "benefits": "Seed funding and proof of concept support",
            "application_process": "Apply through the application portal",
        }
        decision = self.agent.classify(row, "SCHEME_MASTER")
        self.assertEqual(decision.classification, "DIRECT_STARTUP_SCHEME")
        self.assertFalse(decision.review_required)

    def test_university_only_infrastructure_is_excluded(self) -> None:
        row = {
            "scheme_name": "University Research Infrastructure Support",
            "eligibility": "Universities only and academic institutions only",
            "benefits": "Research infrastructure grant",
        }
        decision = self.agent.classify(row, "SCHEME_MASTER")
        self.assertEqual(decision.classification, "INSTITUTION_ONLY")


if __name__ == "__main__":
    unittest.main()
