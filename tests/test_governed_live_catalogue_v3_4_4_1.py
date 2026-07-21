from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish_governed_live_catalogue_v3_4_4_1.py"
SPEC = importlib.util.spec_from_file_location("governed_live_catalogue_v3_4_4_1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class GovernedLiveCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = MODULE.build_candidate()

    def test_signed_source_and_publication_safety_pass(self) -> None:
        self.assertTrue(self.result["passed"])
        self.assertTrue(self.result["checks"]["signed_source_package_passed"])
        self.assertTrue(self.result["checks"]["historical_apply_actions_suppressed"])
        self.assertTrue(self.result["checks"]["no_current_dpiit_call_claimed"])

    def test_complete_governed_dpiit_inventory_is_selected(self) -> None:
        self.assertEqual(self.result["counts"]["published_dpiit_permanent"], 12)
        self.assertEqual(self.result["counts"]["published_dpiit_historical"], 3)
        self.assertEqual(len(self.result["published_ids"]), 15)

    def test_legacy_dpiit_rows_are_reconciled(self) -> None:
        candidate_ids = {row["master_id"] for row in self.result["rows"]}
        self.assertFalse(candidate_ids & set(self.result["legacy_ids"]))
        self.assertGreater(self.result["counts"]["legacy_dpiit_rows_removed"], 0)

    def test_historical_records_are_closed_without_apply(self) -> None:
        historical = [
            row for row in self.result["rows"]
            if row["record_kind"] == "HISTORICAL_CALL"
        ]
        self.assertEqual(len(historical), 3)
        self.assertTrue(all(row["application_status"] == "CLOSED" for row in historical))
        self.assertTrue(all(not row["application_url"] for row in historical))


if __name__ == "__main__":
    unittest.main()
