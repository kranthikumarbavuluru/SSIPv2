from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ssip_agents.media.automation_v3_4_7_4 import run_incremental_media_pipeline


class MediaAutomationTests(unittest.TestCase):
    def test_daily_pipeline_is_incremental_and_writes_report_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ssip-media-automation-") as temporary:
            project = Path(temporary)
            result = run_incremental_media_pipeline(project, "2026-07-22")
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertTrue((project / "data/media_runs/2026-07-22/pipeline_report.json").exists())
            self.assertTrue((project / "data/media_runs/pipeline_state.json").exists())
            second = run_incremental_media_pipeline(project, "2026-07-22")
            self.assertEqual(second["status"], "SUCCEEDED")
            self.assertEqual(second["stages"]["extraction"]["skipped_unchanged_count"], 0)


if __name__ == "__main__":
    unittest.main()
