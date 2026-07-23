from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from ssip_dashboard.meity_history import (
    load_meity_historical_archive,
)


class MeitYHistoryLoaderTests(unittest.TestCase):
    def test_loader_enforces_zero_apply_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = (
                root
                / "data/departments/meity/v3_4_3_7_8"
            )
            directory.mkdir(parents=True)

            archive_path = (
                directory
                / "meity_historical_archive_v3_4_3_7_8.csv"
            )
            fields = [
                "historical_id",
                "source_master_id",
                "canonical_title",
                "official_page_url",
                "historical_status",
                "historical_year",
                "programme_type",
                "sector",
                "applicant_layer",
                "startup_relevance",
                "parent_resolution",
                "historical_basis",
                "evidence_excerpt",
                "date_confidence",
                "quality_flags",
            ]
            with archive_path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=fields,
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "historical_id": "test",
                        "source_master_id": "source",
                        "canonical_title": "Historical Call",
                        "official_page_url": "https://example.gov",
                        "historical_status": "HISTORICAL_CLOSED",
                        "historical_year": "2023",
                        "programme_type": "HACKATHON",
                        "sector": "Digital",
                        "applicant_layer": "STARTUP",
                        "startup_relevance": "STARTUP_DIRECT",
                        "parent_resolution": "STANDALONE",
                        "historical_basis": "Past activity evidence.",
                        "evidence_excerpt": "Organized a hackathon.",
                        "date_confidence": "YEAR_EXPLICIT",
                        "quality_flags": "NO_ACTIVE_APPLY_ACTION",
                    }
                )

            manifest_path = (
                directory
                / "meity_historical_archive_manifest_v3_4_3_7_8.json"
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "qualified_historical_calls": 1,
                        "apply_actions_allowed": 0,
                    }
                ),
                encoding="utf-8",
            )

            archive = load_meity_historical_archive(root)
            self.assertEqual(len(archive.records), 1)
            self.assertEqual(
                archive.records[0].canonical_title,
                "Historical Call",
            )


if __name__ == "__main__":
    unittest.main()
