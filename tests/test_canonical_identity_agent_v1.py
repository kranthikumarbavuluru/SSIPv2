import unittest

from agents.governed_v1.canonical_identity_agent import CanonicalIdentityAgent


class CanonicalIdentityAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = CanonicalIdentityAgent()

    def test_nidhi_prayas_is_a_permanent_programme_identity(self) -> None:
        identity = self.agent.create_master({"master_id": "nidhi-prayas", "scheme_name": "NIDHI - PRAYAS", "official_page_url": "https://dst.gov.in/nidhi-prayas"})
        self.assertEqual(identity.scheme_master_id, "nidhi-prayas")
        self.assertEqual(identity.canonical_name, "NIDHI-PRAYAS")

    def test_nidhi_application_round_maps_to_parent(self) -> None:
        masters = [{"scheme_master_id": "nidhi-prayas", "canonical_name": "NIDHI-PRAYAS"}]
        parent, reason = self.agent.resolve_call_parent({"scheme_name": "NIDHI-PRAYAS Application Round 2026"}, masters)
        self.assertEqual(parent, "nidhi-prayas")
        self.assertIn("permanent", reason)

    def test_call_does_not_replace_parent_identity(self) -> None:
        masters = [{"scheme_master_id": "nidhi-prayas", "canonical_name": "NIDHI-PRAYAS"}]
        parent, _ = self.agent.resolve_call_parent({"scheme_name": "NIDHI-PRAYAS Cohort 4", "master_id": "temporary-call"}, masters)
        self.assertEqual(parent, "nidhi-prayas")
        self.assertNotEqual(parent, "temporary-call")


if __name__ == "__main__":
    unittest.main()
