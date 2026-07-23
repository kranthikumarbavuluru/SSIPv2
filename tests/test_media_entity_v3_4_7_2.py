from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ssip_agents.media.entity_v3_4_7_2 import (
    build_entity_candidate,
    classify_record_kind,
    map_department,
)


class MediaEntityTests(unittest.TestCase):
    def test_classifies_calls_and_challenges_from_evidence(self) -> None:
        self.assertEqual(classify_record_kind("Applications open until 5 August")[0], "APPLICATION_CALL")
        self.assertEqual(classify_record_kind("Grand Challenge competition")[0], "CHALLENGE")

    def test_maps_known_departments_and_falls_back_to_others(self) -> None:
        dst = map_department("DST NIDHI grant")[0]
        self.assertEqual(dst.department, "Department of Science and Technology (DST)")
        self.assertIsNone(map_department("A private foundation fellowship"))
        candidate = build_entity_candidate({
            "asset_id": "asset-1",
            "relative_path": "media/inbox/2026-07-22/notice.jpg",
            "source_sha256": "abc",
            "raw_text": "RTIH MedTech Catalyst applications open",
            "links": [],
            "qr_values": [],
            "language": "en",
            "warnings": [],
            "evidence_ids": ["evidence-1"],
        })
        self.assertEqual(candidate["record_kind"], "APPLICATION_CALL")
        self.assertIn("ITE&C", candidate["department"])
        self.assertEqual(candidate["publication_status"], "UNPUBLISHED")

    def test_unknown_department_is_explicitly_unmapped(self) -> None:
        candidate = build_entity_candidate({
            "asset_id": "asset-2",
            "relative_path": "media/inbox/2026-07-22/unknown.png",
            "source_sha256": "def",
            "raw_text": "Innovation fellowship",
            "links": [],
            "qr_values": [],
            "language": "en",
            "warnings": [],
            "evidence_ids": [],
        })
        self.assertEqual(candidate["department"], "Others / Unmapped")
        self.assertIn("DEPARTMENT_UNMAPPED", candidate["warnings"])

    def test_funding_fields_are_carried_into_entity_candidate(self) -> None:
        candidate = build_entity_candidate({
            "asset_id": "asset-funding",
            "relative_path": "media/inbox/2026-07-22/funding.jpg",
            "source_sha256": "ghi",
            "raw_text": "DST grant support up to INR 10 lakh",
            "links": [],
            "qr_values": [],
            "language": "en",
            "warnings": [],
            "evidence_ids": [],
            "funding_minimum": None,
            "funding_maximum": 1_000_000,
            "funding_currency": "INR",
            "funding_amount_status": "RECORDED",
            "funding_amount_optional": True,
            "funding_mentions": [{"mention": "INR 10 lakh", "value": 1_000_000}],
        })
        self.assertIsNone(candidate["funding_minimum"])
        self.assertEqual(candidate["funding_maximum"], 1_000_000)
        self.assertTrue(candidate["funding_amount_optional"])


if __name__ == "__main__":
    unittest.main()
