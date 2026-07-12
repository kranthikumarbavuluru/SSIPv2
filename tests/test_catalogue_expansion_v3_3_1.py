from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_catalogue_expansion_v3_3_1 import main  # noqa: E402
from ssip_agents.discovery.catalogue_expansion_planner_v3_3_1 import (  # noqa: E402
    load_policy,
    planned_batch_report,
    summarize_catalogue_count,
    validate_batches,
)
from ssip_agents.discovery.source_registry_loader_v3_3 import load_registry_sources  # noqa: E402


class CatalogueExpansionV331Test(unittest.TestCase):
    def test_counting_policy_excludes_calls_and_directories_from_scheme_total(self) -> None:
        policy = load_policy(PROJECT_ROOT)
        rows = [
            {"master_id": "m1", "normalized_record_kind": "SCHEME_OR_PROGRAMME", "application_status": "OPEN"},
            {"master_id": "m2", "normalized_record_kind": "GRANT", "catalogue_section": "CLOSED_OPPORTUNITIES"},
            {"master_id": "m3", "normalized_record_kind": "APPLICATION_CALL", "application_status": "OPEN"},
            {"master_id": "m4", "normalized_record_kind": "DIRECTORY_PAGE"},
            {"master_id": "m1", "normalized_record_kind": "SCHEME_OR_PROGRAMME", "application_status": "OPEN"},
        ]

        summary = summarize_catalogue_count(rows, policy)

        self.assertEqual(summary.eligible_unique_master_records, 2)
        self.assertEqual(summary.application_calls, 1)
        self.assertEqual(summary.excluded_unique_master_records, 2)
        self.assertEqual(summary.duplicate_master_ids, 1)
        self.assertEqual(summary.open_schemes, 1)
        self.assertEqual(summary.closed_historical, 1)

    def test_all_v331_batch_sources_exist_in_v33_registry(self) -> None:
        policy = load_policy(PROJECT_ROOT)
        sources, _registry = load_registry_sources(PROJECT_ROOT)
        errors = validate_batches(policy, sources)

        self.assertEqual(errors, [])

    def test_batch_1_preflight_writes_report_and_checkpoint(self) -> None:
        run_id = "unit_test_batch_1_preflight"
        report, report_path = planned_batch_report(
            project_root=PROJECT_ROOT,
            batch_id="batch_1_enterprise_startup_indexes",
            run_id=run_id,
        )
        checkpoint_path = report_path.parent / "checkpoint.json"
        try:
            self.assertTrue(report_path.exists())
            self.assertTrue(checkpoint_path.exists())
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(report["run_id"], run_id)
            self.assertEqual(report["batch_id"], "batch_1_enterprise_startup_indexes")
            self.assertEqual(report["network_requests_performed"], 0)
            self.assertEqual(report["database_writes_performed"], 0)
            self.assertEqual(checkpoint["status"], "PREFLIGHT_COMPLETE_WAITING_FOR_APPROVAL")
            self.assertEqual(checkpoint["next_step"], "controlled_network_discovery_pilot")
            self.assertGreaterEqual(len(report["sources_processed"]), 8)
            self.assertGreater(report["seed_url_count"], 0)
        finally:
            if checkpoint_path.exists():
                checkpoint_path.unlink()
            if report_path.exists():
                report_path.unlink()
            if report_path.parent.exists():
                report_path.parent.rmdir()

    def test_runner_refuses_network_mode(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--allow-network"])
        self.assertIn("Network discovery is not enabled", str(ctx.exception))

    def test_runner_default_is_batch_1_preflight_only(self) -> None:
        run_id = "unit_test_runner_batch_1"
        with redirect_stdout(StringIO()):
            exit_code = main(["--run-id", run_id])
        output_root = PROJECT_ROOT / "outputs" / "catalogue_expansion_v3_3_1" / run_id
        try:
            self.assertEqual(exit_code, 0)
            self.assertTrue((output_root / "batch_report.json").exists())
            self.assertTrue((output_root / "checkpoint.json").exists())
        finally:
            for name in ("batch_report.json", "checkpoint.json"):
                path = output_root / name
                if path.exists():
                    path.unlink()
            if output_root.exists():
                output_root.rmdir()


if __name__ == "__main__":
    unittest.main()
