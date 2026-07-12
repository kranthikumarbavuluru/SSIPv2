from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ssip_agents.master_backlog_executor_v2_7_1 import (
    BacklogRow,
    FetchResult,
    build_llm_evidence,
    classify_document,
    evaluate_record,
    inspect_db_master_ids,
    is_actionable,
    is_generic_destination,
    name_similarity,
    page_identity_score,
    parse_money_values,
    read_backlog,
    selection_report,
)


class TestMasterBacklogExecutorV271(unittest.TestCase):
    def make_row(self, **updates):
        data = dict(
            master_id="abc123",
            source="BIRAC",
            canonical_name="AMRIT Grand Challenge – JanCare",
            master_type="PROGRAMME_FAMILY_FROM_HISTORICAL_EVIDENCE",
            current_status="HISTORICAL_EVIDENCE_ONLY",
            readiness="NEEDS_OFFICIAL_SCHEME_PAGE_DISCOVERY",
            best_available_url="https://example.gov.in/cfp_view.php?id=70",
            extraction_status="NOT_EXTRACTED",
            database_status="NOT_PRESENT",
            recommended_action="Run incremental extraction for this master_id.",
        )
        data.update(updates)
        return BacklogRow(**data)

    def test_actionable_row(self):
        ok, reason = is_actionable(self.make_row())
        self.assertTrue(ok)
        self.assertEqual(reason, "ACTIONABLE")

    def test_approved_row_is_not_actionable(self):
        row = self.make_row(
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
        row = self.make_row(master_id="protected-id")
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

    def test_pdf_classification(self):
        self.assertEqual(
            classify_document("application/pdf", "https://x.gov/a", b"%PDF-1.7"),
            "PDF",
        )
        self.assertEqual(
            classify_document("text/html", "https://x.gov/a", b"<html>"),
            "HTML",
        )

    def test_llm_evidence_is_context_bounded(self):
        row = self.make_row()
        evidence = build_llm_evidence(
            row,
            ("AMRIT JanCare eligibility benefits funding deadline documents " * 3000),
        )
        self.assertLessEqual(len(evidence), 6000)
        self.assertLessEqual(len(evidence.split()), 1400)

    def test_generic_home_page_is_not_ready_even_if_llm_echoes_name(self):
        row = self.make_row()
        fetch = FetchResult(
            requested_url=row.best_available_url,
            final_url="https://birac.nic.in/grandchallengesindia/",
            status_code=200,
            document_type="HTML",
            title="Home | Grand Challenges India",
            text="Welcome to Grand Challenges India. Browse programmes and news.",
        )
        extracted = {
            "scheme_name": row.canonical_name,  # Simulates an LLM echo.
            "eligibility": "Some eligibility",
            "benefits": "Some benefits",
            "funding_text": "Rs. 1 crore",
            "deadline": "31 December 2026",
            "application_process": "Apply online",
            "application_url": "https://example.gov.in/apply",
            "documents_required": "Proposal",
        }
        confidence, flags, decision, identity = evaluate_record(
            row, fetch, extracted, fetch.title, fetch.text
        )
        self.assertTrue(is_generic_destination(fetch.final_url, fetch.title))
        self.assertIn("GENERIC_DESTINATION_PAGE", flags)
        self.assertEqual(decision, "NEEDS_MORE_EVIDENCE")
        self.assertLess(identity, 0.45)
        self.assertLess(confidence, 0.72)

    def test_specific_entity_page_scores_above_generic_home(self):
        row = self.make_row()
        generic = page_identity_score(
            row,
            "https://birac.nic.in/grandchallengesindia/",
            "Home | Grand Challenges India",
            "Welcome to Grand Challenges India.",
        )
        specific = page_identity_score(
            row,
            "https://birac.nic.in/cfp_view.php?id=70&scheme_type=40",
            "AMRIT Grand Challenge - JanCare",
            "AMRIT JanCare eligibility, funding support and application details.",
        )
        self.assertGreater(specific, generic)
        self.assertGreaterEqual(specific, 0.75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
