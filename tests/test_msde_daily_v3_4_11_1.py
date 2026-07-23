from __future__ import annotations

from pathlib import Path
import unittest

from ssip_agents.discovery.msde_daily_v3_4_11_1 import build_msde_daily_report


ROOT = Path(__file__).resolve().parents[1]


class MSDEDailyDiscoveryTests(unittest.TestCase):
    def test_daily_report_is_read_only_and_uses_msde_batch(self) -> None:
        report = build_msde_daily_report(ROOT, "2026-07-23")
        self.assertEqual(report["version"], "3.4.11.1")
        self.assertEqual(report["batch_id"], "msde_scheme_sources")
        self.assertEqual(report["source_count"], 4)
        self.assertEqual(report["seed_url_count"], 4)
        self.assertEqual(report["network_requests_performed"], 0)
        self.assertEqual(report["database_writes_performed"], 0)
        self.assertFalse(report["publication_performed"])
        self.assertEqual(report["registry_audit"]["missing_authority_mappings"], [])
        self.assertEqual(report["registry_audit"]["missing_trusted_domain_mappings"], [])
        self.assertEqual(report["publication_snapshot"]["record_count"], 25)

    def test_fingerprint_is_stable_for_incremental_runs(self) -> None:
        first = build_msde_daily_report(ROOT, "2026-07-23")
        second = build_msde_daily_report(ROOT, "2026-07-23")
        self.assertEqual(first["incremental"]["fingerprint"], second["incremental"]["fingerprint"])


if __name__ == "__main__":
    unittest.main()
