from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from ssip_agents.media.intake_v3_4_7_0 import (
    MEDIA_SCHEMA_VERSION,
    MediaIntakePaths,
    parse_ingest_date,
    scan_media_batch,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = PROJECT_ROOT / ".test_tmp_public_dashboard"


class MediaIntakeFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = TEST_TEMP_ROOT / f"media_foundation_{uuid4().hex}"
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_parse_ingest_date_requires_iso_date(self) -> None:
        self.assertEqual(parse_ingest_date("2026-07-22").isoformat(), "2026-07-22")
        with self.assertRaises(ValueError):
            parse_ingest_date("22-07-2026")

    def test_scan_registers_supported_duplicate_and_unsupported_files(self) -> None:
        root = self.temp_root
        inbox = root / "media" / "inbox" / "2026-07-22"
        inbox.mkdir(parents=True)
        (inbox / "poster.png").write_bytes(b"same flyer")
        (inbox / "poster-copy.pdf").write_bytes(b"same flyer")
        (inbox / "notes.txt").write_text("not a flyer", encoding="utf-8")

        report = scan_media_batch(root, "2026-07-22")

        self.assertEqual(report["schema_version"], MEDIA_SCHEMA_VERSION)
        self.assertEqual(report["asset_count"], 3)
        self.assertEqual(report["supported_asset_count"], 2)
        self.assertEqual(report["unique_supported_asset_count"], 1)
        self.assertEqual(report["duplicate_count"], 1)
        self.assertEqual(report["unsupported_count"], 1)
        self.assertFalse(report["database_modified"])

        manifest = root / "data" / "media_runs" / "2026-07-22" / "asset_manifest.jsonl"
        rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["asset_id"] for row in rows}), 3)
        supported_hashes = {
            row["sha256"]
            for row in rows
            if row["status"] in {"READY_FOR_EXTRACTION", "DUPLICATE"}
        }
        self.assertEqual(len(supported_hashes), 1)
        self.assertIn("UNSUPPORTED_MEDIA", {row["status"] for row in rows})

    def test_same_day_rerun_is_idempotent_and_cross_day_hashes_are_duplicates(self) -> None:
        root = self.temp_root
        first = root / "media" / "inbox" / "2026-07-22"
        second = root / "media" / "inbox" / "2026-07-23"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "poster.png").write_bytes(b"identical")
        (second / "renamed-poster.jpg").write_bytes(b"identical")

        first_report = scan_media_batch(root, "2026-07-22")
        rerun_report = scan_media_batch(root, "2026-07-22")
        second_report = scan_media_batch(root, "2026-07-23")

        self.assertEqual(first_report["unique_supported_asset_count"], 1)
        self.assertEqual(rerun_report["unique_supported_asset_count"], 1)
        self.assertEqual(second_report["duplicate_count"], 1)

        second_manifest = (
            root / "data" / "media_runs" / "2026-07-23" / "asset_manifest.jsonl"
        )
        second_row = json.loads(second_manifest.read_text(encoding="utf-8").strip())
        self.assertTrue(second_row["duplicate_of"].startswith("asset-"))

    def test_paths_create_date_based_foundation_layout(self) -> None:
        paths = MediaIntakePaths(self.temp_root)
        paths.ensure_batch_layout("2026-07-22")
        for path in (
            paths.batch_inbox("2026-07-22"),
            paths.batch_processed("2026-07-22"),
            paths.batch_quarantine("2026-07-22"),
            paths.batch_run("2026-07-22"),
        ):
            self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
