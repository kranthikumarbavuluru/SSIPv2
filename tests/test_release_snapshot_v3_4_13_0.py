from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "data" / "releases" / "v3_4_13_0"


class ReleaseSnapshotV34130Tests(unittest.TestCase):
    def test_manifest_hash_and_counts(self) -> None:
        manifest = json.loads((RELEASE_DIR / "release_manifest_v3_4_13_0.json").read_text(encoding="utf-8"))
        snapshot = RELEASE_DIR / manifest["snapshot_file"].split("data/releases/v3_4_13_0/", 1)[-1]
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), manifest["snapshot_sha256"])
        with snapshot.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 341)
        self.assertEqual(manifest["counts"], {
            "loaded_records": 341,
            "schemes_and_programmes": 158,
            "application_calls": 89,
            "evidence_or_excluded": 94,
        })
        self.assertFalse(manifest["database_modified"])

    def test_department_manifests_are_versioned_inputs(self) -> None:
        manifest = json.loads((RELEASE_DIR / "release_manifest_v3_4_13_0.json").read_text(encoding="utf-8"))
        self.assertIn("moe", manifest["department_publication_manifests"])
        self.assertIn("msde", manifest["department_publication_manifests"])
        for item in manifest["department_publication_manifests"].values():
            self.assertTrue((ROOT / item["path"]).exists())

    def test_dashboard_version_marker(self) -> None:
        source = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        self.assertIn('APP_VERSION = "3.4.14.0-visual-foundation"', source)


if __name__ == "__main__":
    unittest.main()
