from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ssip_agents.media.extraction_v3_4_7_1 import (
    detect_language,
    extract_links,
    extract_media_batch,
    parse_funding_amounts,
)
from ssip_agents.media.intake_v3_4_7_0 import scan_media_batch


ROOT = Path(__file__).resolve().parents[1]


class MediaExtractionTests(unittest.TestCase):
    def test_language_detection_is_conservative(self) -> None:
        self.assertEqual(detect_language(""), ("und", 0.0))
        self.assertEqual(detect_language("Government startup support")[0], "en")
        self.assertEqual(detect_language("తెలుగు కార్యక్రమం")[0], "te")

    def test_link_extraction_deduplicates_and_trims_punctuation(self) -> None:
        links = extract_links("See https://example.gov.in/call. and https://example.gov.in/call", ["https://pdf.gov.in/form"])
        self.assertEqual(links, ["https://example.gov.in/call", "https://pdf.gov.in/form"])

    def test_funding_amounts_keep_nullable_bounds_and_optional_flag(self) -> None:
        recorded = parse_funding_amounts("Grant support up to INR 10 lakh")
        self.assertIsNone(recorded["funding_minimum"])
        self.assertEqual(recorded["funding_maximum"], 1_000_000)
        self.assertEqual(recorded["funding_currency"], "INR")
        self.assertTrue(recorded["funding_amount_optional"])
        ranged = parse_funding_amounts("Funding support ₹5 lakh to ₹10 lakh")
        self.assertEqual(ranged["funding_minimum"], 500_000)
        self.assertEqual(ranged["funding_maximum"], 1_000_000)
        eligibility_cap = parse_funding_amounts("Grant support up to INR 10 lakh; turnover not above INR 25 lakh")
        self.assertIsNone(eligibility_cap["funding_minimum"])
        self.assertEqual(eligibility_cap["funding_maximum"], 1_000_000)

    def test_batch_writes_extraction_and_field_evidence_without_db(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ssip-media-extract-") as temporary:
            project = Path(temporary)
            inbox = project / "media" / "inbox" / "2026-07-22"
            inbox.mkdir(parents=True)
            (inbox / "notice.jpg").write_bytes((ROOT / "media/inbox/2026-07-22/1784627858692.jpg").read_bytes())
            intake = scan_media_batch(project, "2026-07-22")
            extraction = extract_media_batch(project, "2026-07-22")
            self.assertEqual(intake["database_modified"], False)
            self.assertEqual(extraction["database_modified"], False)
            self.assertEqual(extraction["extracted_count"], 1)
            self.assertTrue((project / "data/media_runs/2026-07-22/extraction_manifest.jsonl").exists())
            evidence_file = project / "data/media_runs/2026-07-22/field_evidence.jsonl"
            self.assertTrue(evidence_file.exists())
            extracted_row = json.loads((project / "data/media_runs/2026-07-22/extraction_manifest.jsonl").read_text().splitlines()[0])
            self.assertIn("qr_status", extracted_row)
            self.assertIn("barcode_status", extracted_row)


if __name__ == "__main__":
    unittest.main()
