import unittest

from agents.governed_v1.call_discovery_agent import CallDiscoveryAgent


class CallDiscoveryAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = CallDiscoveryAgent()

    def test_application_round_is_a_call_instance(self) -> None:
        decision = self.agent.classify({"scheme_name": "NIDHI-PRAYAS Application Round 2026"}, "CALL_INSTANCE")
        self.assertTrue(decision.is_call)
        self.assertEqual(decision.call_type, "CALL_FOR_APPLICATIONS")

    def test_selected_candidate_results_are_not_calls(self) -> None:
        decision = self.agent.classify({"scheme_name": "Challenge selected candidates results announced"}, "MANUAL_ROLE_REVIEW")
        self.assertFalse(decision.is_call)


if __name__ == "__main__":
    unittest.main()
