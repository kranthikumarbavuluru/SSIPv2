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

from run_catalogue_discovery_v3_3 import main  # noqa: E402
from ssip_agents.discovery.source_registry_loader_v3_3 import write_dry_run_report  # noqa: E402


class CatalogueDiscoveryRunnerV33Test(unittest.TestCase):
    def test_runner_refuses_network_mode(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--allow-network"])

        self.assertIn("Network crawl is intentionally disabled", str(ctx.exception))

    def test_write_dry_run_report_uses_versioned_run_folder(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            run_id = "unit_test_dry_run"
            report_path = write_dry_run_report(project_root, run_id=run_id)
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report_path.name, "dry_run_report.json")
                self.assertIn("catalogue_discovery_v3_3", str(report_path))
                self.assertEqual(report["run_id"], run_id)
                self.assertTrue(report["dry_run"])
                self.assertEqual(report["network_requests_performed"], 0)
                self.assertEqual(report["database_writes_performed"], 0)
            finally:
                # Keep cleanup scoped to this test's run folder only.
                if report_path.exists():
                    report_path.unlink()
                if report_path.parent.exists():
                    report_path.parent.rmdir()

    def test_print_only_does_not_create_run_folder(self) -> None:
        with redirect_stdout(StringIO()):
            exit_code = main(["--print-only"])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
