from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from ssip_agents.media.review_v3_4_7_3 import (
    MediaReviewStore,
    build_review_workspace,
    project_validated_records,
)


def _candidate() -> dict[str, object]:
    return {
        "candidate_id": "media-candidate-1",
        "asset_id": "asset-1",
        "source_asset_path": "media/inbox/2026-07-22/call.jpg",
        "source_asset_sha256": "abc",
        "canonical_name": "DST grant call",
        "record_kind": "APPLICATION_CALL",
        "department": "Department of Science and Technology (DST)",
        "ministry": "Ministry of Science and Technology",
        "implementing_agency": "DST",
        "department_confidence": 0.9,
        "official_links": ["https://dst.gov.in/call"],
        "warnings": [],
        "evidence_ids": ["evidence-1"],
        "review_status": "REVIEW_REQUIRED",
    }


class MediaReviewTests(unittest.TestCase):
    def test_corrections_and_decisions_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ssip-media-review-") as temporary:
            project = Path(temporary)
            batch = project / "data/media_runs/2026-07-22"
            batch.mkdir(parents=True)
            (batch / "entity_candidates.jsonl").write_text(__import__("json").dumps(_candidate()) + "\n", encoding="utf-8")
            store = MediaReviewStore(project, "2026-07-22")
            store.record_correction("media-candidate-1", {"canonical_name": "Corrected DST grant call"}, "reviewer")
            store.record_decision("media-candidate-1", "APPROVE", "reviewer", "official page checked")
            effective = store.effective_candidate(_candidate())
            self.assertEqual(effective["canonical_name"], "Corrected DST grant call")
            self.assertEqual(effective["review_status"], "APPROVE")
            self.assertEqual(len(store.candidates()), 1)

    def test_projection_requires_approval_and_creates_hash_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ssip-media-publication-") as temporary:
            project = Path(temporary)
            batch = project / "data/media_runs/2026-07-22"
            batch.mkdir(parents=True)
            import json

            (batch / "entity_candidates.jsonl").write_text(json.dumps(_candidate()) + "\n", encoding="utf-8")
            store = MediaReviewStore(project, "2026-07-22")
            before = project_validated_records(project, "2026-07-22", "test-run-hold")
            self.assertEqual(before["published_count"], 0)
            store.record_decision("media-candidate-1", "APPROVE", "reviewer", "approved")
            after = project_validated_records(project, "2026-07-22", "test-run-approved")
            self.assertEqual(after["published_count"], 1)
            manifest = project / after["manifest_path"]
            inventory = project / after["inventory_path"]
            self.assertEqual(manifest.exists(), True)
            self.assertEqual(inventory.exists(), True)
            with inventory.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)

    def test_workspace_is_read_only_projection_of_candidates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ssip-media-workspace-") as temporary:
            project = Path(temporary)
            batch = project / "data/media_runs/2026-07-22"
            batch.mkdir(parents=True)
            import json

            (batch / "entity_candidates.jsonl").write_text(json.dumps(_candidate()) + "\n", encoding="utf-8")
            workspace = build_review_workspace(project, "2026-07-22")
            self.assertEqual(workspace.candidate_count, 1)
            self.assertTrue((project / workspace.workspace_path).exists())


if __name__ == "__main__":
    unittest.main()
