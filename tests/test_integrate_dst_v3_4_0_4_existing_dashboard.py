from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.integrate_dst_v3_4_0_4_into_existing_dashboard import adapt_dst_row, integrate, is_existing_dst_row


class IntegrationTests(unittest.TestCase):
    def test_dst_detection(self) -> None:
        self.assertTrue(is_existing_dst_row({"source": "DST"}))
        self.assertTrue(is_existing_dst_row({"official_page_url": "https://dst.gov.in/test"}))
        self.assertFalse(is_existing_dst_row({"source": "BIRAC", "official_page_url": "https://birac.nic.in/test"}))

    def test_adaptation(self) -> None:
        fields = ["master_id", "scheme_name", "source", "record_kind", "catalogue_inclusion", "official_page_url"]
        row = adapt_dst_row({"master_id": "x", "scheme_name": "Y", "entity_type": "SCHEME", "official_page_url": "https://dst.gov.in/y"}, fields)
        self.assertEqual(row["source"], "DST")
        self.assertEqual(row["record_kind"], "SCHEME_OR_PROGRAMME")
        self.assertEqual(row["catalogue_inclusion"], "INCLUDED")

    def test_full_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
            dst = root / "data/departments/dst/v3_4_0_4/dst_publication_catalogue_v3_4_0_4.csv"
            app = root / "apps/public_dashboard_app_v2_9.py"
            base.parent.mkdir(parents=True)
            dst.parent.mkdir(parents=True)
            app.parent.mkdir(parents=True)
            fields = ["master_id", "scheme_name", "source", "ministry", "department", "normalized_record_kind", "record_kind", "programme_status", "application_status", "catalogue_inclusion", "current_decision", "official_page_url", "last_verified_date"]
            with base.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    {"master_id": "old_dst", "scheme_name": "Old DST", "source": "DST", "official_page_url": "https://dst.gov.in/old"},
                    {"master_id": "other", "scheme_name": "Other", "source": "BIRAC", "official_page_url": "https://birac.nic.in/other"},
                ])
            pub_fields = ["master_id", "scheme_name", "entity_type", "ministry", "department", "programme_status", "application_status", "official_page_url", "last_verified_date"]
            with dst.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=pub_fields)
                writer.writeheader()
                for i in range(23):
                    writer.writerow({"master_id": f"dst_{i}", "scheme_name": f"DST {i}", "entity_type": "SCHEME" if i < 3 else "PROGRAMME", "ministry": "Ministry of Science and Technology", "department": "Department of Science and Technology", "programme_status": "SCHEME_INFORMATION_AVAILABLE", "application_status": "REFERENCE", "official_page_url": f"https://dst.gov.in/{i}", "last_verified_date": "2026-07-10"})
            app.write_text('APP_VERSION = "3.2.0"\n', encoding="utf-8")
            summary = integrate(root, Path("data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"), Path("data/departments/dst/v3_4_0_4/dst_publication_catalogue_v3_4_0_4.csv"), Path("data/catalogue_preview/v3_4_0_4/catalogue_preview_v3_4_0_4.csv"), Path("apps/public_dashboard_app_v2_9.py"))
            self.assertTrue(summary["integration_passed"])
            self.assertEqual(summary["counts"]["old_dst_rows_removed"], 1)
            self.assertEqual(summary["counts"]["dst_rows_added"], 23)
            self.assertEqual(summary["counts"]["merged_rows_after"], 24)
            self.assertIn('APP_VERSION = "3.4.0.4"', app.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
