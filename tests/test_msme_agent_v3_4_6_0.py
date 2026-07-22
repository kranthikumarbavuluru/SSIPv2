from __future__ import annotations

import unittest
from pathlib import Path

from ssip_dashboard.msme_supplement import load_active_msme_supplement
from scripts.run_msme_agent_v3_4_6_0 import status


ROOT = Path(__file__).resolve().parents[1]


class MSMEAgentBundleTests(unittest.TestCase):
    def test_active_bundle_contains_all_verified_ap_directory_records(self) -> None:
        bundle = load_active_msme_supplement(ROOT)
        self.assertEqual(bundle.manifest["activation_status"], "ACTIVE")
        self.assertEqual(len(bundle.records), 31)
        self.assertEqual(len({row["master_id"] for row in bundle.records}), 31)
        self.assertTrue(all(row["official_page_url"].startswith("https://apmsmeone.ap.gov.in/schemes/") for row in bundle.records))
        self.assertTrue(all(row["application_status"] == "STATUS_UNVERIFIED" for row in bundle.records))

    def test_state_records_do_not_inherit_union_ministry(self) -> None:
        bundle = load_active_msme_supplement(ROOT)
        state = {row["scheme_name"]: row for row in bundle.records if row["implementation_role"] == "STATE_GOVERNMENT"}
        self.assertEqual(set(state), {"Andhra Pradesh Chief Minister's Entrepreneur Programme", "Andhra Pradesh Cluster Development Programme"})
        self.assertTrue(all(row["ministry"] == "Government of Andhra Pradesh" for row in state.values()))
        self.assertTrue(all(row["department"] == "MSME Department Government of Andhra Pradesh" for row in state.values()))

    def test_status_reports_active_bundle(self) -> None:
        report = status()
        self.assertEqual(report["active"]["activation_status"], "ACTIVE")
        self.assertEqual(report["active"]["record_count"], 31)


if __name__ == "__main__":
    unittest.main()
