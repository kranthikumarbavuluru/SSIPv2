from __future__ import annotations

import unittest
from pathlib import Path
from urllib.robotparser import RobotFileParser

from scripts.run_mymsme_agent_v3_4_6_0 import LegalCrawlPolicy, classify_division, configured_source, normalise_key
from ssip_dashboard.msme_supplement import load_active_mymsme_supplement


ROOT = Path(__file__).resolve().parents[1]


class MyMSMEAgentPolicyTests(unittest.TestCase):
    def test_adapter_uses_governed_source_registry(self) -> None:
        source = configured_source()
        self.assertEqual(source["source_id"], "my_msme_mobile_directory")
        self.assertEqual(source["domain"], "my.msme.gov.in")

    def test_directory_identity_normalisation_reconciles_known_aliases(self) -> None:
        self.assertEqual(normalise_key("Credit Guarantee"), "credit guarantee micro small enterprises")
        self.assertEqual(normalise_key("Bank Credit Facilitation"), "credit facilitation through bank")
        self.assertEqual(normalise_key("Single Point Registration"), "single point registration")

    def test_division_classification_is_source_specific(self) -> None:
        self.assertEqual(classify_division("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/NSIC.htm")[0], "NSIC")
        self.assertEqual(classify_division("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/Pages/1_3_4.html")[0], "ARI Division")
        self.assertEqual(classify_division("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/Pages/0_2_4.html")[0], "Development Commissioner (MSME)")

    def test_robots_policy_blocks_disallowed_or_out_of_scope_urls(self) -> None:
        policy = LegalCrawlPolicy(min_delay_seconds=0)
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /MyMsmeMob/MsmeScheme/private"])
        policy.robots_parser = parser
        policy.robots_state = "PUBLISHED"
        policy.permit("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/MSME_Scheme.htm")
        with self.assertRaises(RuntimeError):
            policy.permit("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/private.htm")
        with self.assertRaises(RuntimeError):
            policy.permit("https://example.com/MyMsmeMob/MsmeScheme/MSME_Scheme.htm")


class MyMSMEActiveBundleTests(unittest.TestCase):
    def test_active_bundle_is_hash_verified_and_public_only(self) -> None:
        bundle = load_active_mymsme_supplement(ROOT)
        self.assertEqual(bundle.manifest["activation_status"], "ACTIVE")
        self.assertEqual(len(bundle.records), 16)
        self.assertTrue(all(row["official_page_url"].startswith("https://my.msme.gov.in/") for row in bundle.records))
        self.assertTrue(all(not row["application_url"] for row in bundle.records))


if __name__ == "__main__":
    unittest.main()
