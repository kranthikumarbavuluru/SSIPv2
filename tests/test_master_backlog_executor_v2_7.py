from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ssip_agents.master_backlog_executor_v2_7 import (
    BacklogRow,
    inspect_db_master_ids,
    is_actionable,
    name_similarity,
    parse_money_values,
    read_backlog,
    selection_report,
)


class TestMasterBacklogExecutorV27(unittest.TestCase):
    def test_actionable_row(self):
        row = BacklogRow(
            master_id="abc123",
            source="BIRAC",
            canonical_name="AMRIT Team Grants",
            master_type="PROGRAMME_FAMILY_FROM_HISTORICAL_EVIDENCE",
            current_status="HISTORICAL_EVIDENCE_ONLY",
            readiness="NEEDS_OFFICIAL_SCHEME_PAGE_DISCOVERY",
            best_available_url="https://example.gov.in/cfp_view.php?id=70",
            extraction_status="NOT_EXTRACTED",
            database_status="NOT_PRESENT",
            recommended_action="Run incremental extraction for this master_id.",
        )
        ok, reason = is_actionable(row)
        self.assertTrue(ok)
        self.assertEqual(reason, "ACTIONABLE")

    def test_approved_row_is_not_actionable(self):
        row = BacklogRow(
            master_id="done",
            source="DST",
            canonical_name="Example",
            master_type="SCHEME_OR_PROGRAMME",
            current_status="SCHEME_INFORMATION_AVAILABLE",
            readiness="READY",
            best_available_url="https://example.gov.in/scheme",
            extraction_status="EXTRACTED",
            validation_decision="APPROVED_FOR_DATABASE",
            database_status="PRESENT",
        )
        ok, _ = is_actionable(row)
        self.assertFalse(ok)

    def test_money_parser(self):
        low, high = parse_money_values(
            "Grant support ranges from Rs. 5 lakh to INR 2 crore."
        )
        self.assertEqual(low, 500000)
        self.assertEqual(high, 20000000)

    def test_name_similarity(self):
        score = name_similarity(
            "AMRIT Team Grants",
            "Applications invited for AMRIT Team Grant programme",
        )
        self.assertGreaterEqual(score, 0.5)

    def test_database_protection(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE scheme_staging "
                "(master_id TEXT PRIMARY KEY, scheme_name TEXT)"
            )
            con.execute(
                "INSERT INTO scheme_staging VALUES (?, ?)",
                ("protected-id", "Protected Scheme"),
            )
            con.commit()
            con.close()
            self.assertIn("protected-id", inspect_db_master_ids(db))

    def test_selection_report_skips_protected(self):
        row = BacklogRow(
            master_id="protected-id",
            source="BIRAC",
            canonical_name="Protected",
            master_type="SCHEME_OR_PROGRAMME",
            current_status="SCHEME_INFORMATION_AVAILABLE",
            readiness="READY",
            best_available_url="https://example.gov.in/protected",
            extraction_status="NOT_EXTRACTED",
            database_status="NOT_PRESENT",
        )
        selected, audit = selection_report(
            [row], {"protected-id"}, set(), force=False
        )
        self.assertEqual(selected, [])
        self.assertEqual(
            audit[0]["selection_reason"],
            "PROTECTED_BY_EXISTING_DATABASE_RECORD",
        )

    def test_backlog_header_alias_final_categ(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "backlog.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "master_id", "source", "canonical_name", "master_type",
                        "current_status", "readiness", "best_available_url",
                        "extraction_status", "validation_decision",
                        "database_status", "final_categ", "recommended_action",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "master_id": "1",
                        "source": "BIRAC",
                        "canonical_name": "Example",
                        "master_type": "SCHEME_OR_PROGRAMME",
                        "current_status": "HISTORICAL_EVIDENCE_ONLY",
                        "readiness": "NEEDS_EXTRACTION",
                        "best_available_url": "https://example.gov.in/x",
                        "extraction_status": "NOT_EXTRACTED",
                        "database_status": "NOT_PRESENT",
                        "final_categ": "AWAITING_EXTRACTION",
                        "recommended_action": "Run incremental extraction.",
                    }
                )
            rows = read_backlog(path)
            self.assertEqual(rows[0].final_category, "AWAITING_EXTRACTION")


if __name__ == "__main__":
    unittest.main(verbosity=2)
