from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ssip_agents.validator.strict_validation_handoff_v2_7_2_1 import run_validation


FIELDS = [
    "master_id", "source", "canonical_name", "master_type", "final_url",
    "application_url", "http_status", "page_title", "document_type",
    "page_identity_score", "llm_status", "scheme_name", "ministry",
    "department", "programme_status", "eligibility", "benefits",
    "funding_text", "funding_min", "funding_max", "deadline",
    "documents_required", "application_process", "contact_details",
    "evidence_notes", "confidence", "quality_flags", "next_decision",
    "raw_evidence_path", "raw_html_path", "fetch_error", "parse_error",
]


class StrictValidationV2721Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "database").mkdir()
        (self.root / "evidence").mkdir()
        self.input_path = self.root / "data" / "manifest.csv"
        self.output_dir = self.root / "data" / "output"
        self.db_path = self.root / "database" / "ssip_staging_v1.db"

        con = sqlite3.connect(self.db_path)
        con.executescript(
            """
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,
                official_page_url TEXT,
                application_url TEXT
            );
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,
                official_page_url TEXT,
                application_url TEXT
            );
            CREATE TABLE admin_review_actions (
                action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id TEXT,
                action TEXT,
                reviewer TEXT,
                notes TEXT,
                created_at TEXT
            );
            CREATE TABLE scheme_sources (master_id TEXT, source_url TEXT);
            CREATE TABLE scheme_attributes (master_id TEXT, value TEXT);
            CREATE TABLE scheme_contacts (master_id TEXT, contact_value TEXT);
            """
        )
        con.execute(
            "INSERT INTO scheme_staging(master_id, scheme_name, official_page_url, application_url) VALUES (?, ?, ?, ?)",
            ("existing-id", "Existing Programme", "https://birac.nic.in/existing", ""),
        )
        con.execute(
            "INSERT INTO scheme_staging(master_id, scheme_name, official_page_url, application_url) VALUES (?, ?, ?, ?)",
            ("other-id", "Potential Duplicate Programme", "https://birac.nic.in/other", ""),
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_evidence(self, name: str, text: str) -> str:
        path = self.root / "evidence" / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.root))

    def strong_row(self, master_id: str, name: str, url: str) -> dict[str, str]:
        raw_path = self.write_evidence(
            master_id,
            (
                f"{name} is an official BIRAC scheme and programme. "
                "The programme provides grant funding, incubation support, and research support "
                "to eligible Indian startups and companies. Applicants submit an application "
                "through the official portal with the prescribed company documents. "
                "This official scheme information page describes the programme objectives, "
                "eligibility, benefits, and implementation arrangements."
            ),
        )
        return {
            "master_id": master_id,
            "source": "BIRAC",
            "canonical_name": name,
            "master_type": "SCHEME_OR_PROGRAMME",
            "final_url": url,
            "application_url": "https://birac.nic.in/apply/submit",
            "http_status": "200",
            "page_title": name,
            "document_type": "HTML",
            "page_identity_score": "0.90",
            "llm_status": "SUCCESS",
            "scheme_name": name,
            "ministry": "Ministry of Science and Technology",
            "department": "Department of Biotechnology",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "eligibility": "Indian startups and companies are eligible.",
            "benefits": "Grant funding and incubation support.",
            "funding_text": "",
            "funding_min": "",
            "funding_max": "",
            "deadline": "",
            "documents_required": "Application form and company documents.",
            "application_process": "Submit through the official portal.",
            "contact_details": "",
            "evidence_notes": "LLM-generated note must not be treated as independent proof.",
            "confidence": "0.90",
            "quality_flags": "[]",
            "next_decision": "READY_FOR_VALIDATION",
            "raw_evidence_path": raw_path,
            "raw_html_path": "",
            "fetch_error": "",
            "parse_error": "",
        }

    def write_rows(self, rows: list[dict[str, str]]) -> None:
        with self.input_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_hotfix_blocks_circular_and_historical_approval(self) -> None:
        approved = self.strong_row(
            "approved-id", "Strong Innovation Scheme", "https://birac.nic.in/strong"
        )

        historical = self.strong_row(
            "historical-id",
            "Historical Cyber Physical Systems Programme",
            "https://dst.gov.in/sites/default/files/old-call.pdf",
        )
        historical.update(
            {
                "source": "DST",
                "master_type": "PROGRAMME_FAMILY_FROM_HISTORICAL_EVIDENCE",
                "programme_status": "HISTORICAL_EVIDENCE_ONLY",
                "deadline": "31/03/2017",
                "funding_text": "Detailed call dated 2017 with closing date 31/03/2017.",
                "funding_min": "2017.0",
                "funding_max": "2017.0",
                "application_url": "",
                "next_decision": "READY_FOR_VALIDATION",
            }
        )
        Path(self.root / historical["raw_evidence_path"]).write_text(
            "Historical detailed call for proposals under the programme. "
            "The call closed on 31/03/2017. This archived call is not a current scheme page. "
            "The document was published in 2017 and contains no current application window.",
            encoding="utf-8",
        )

        self_claim_only = self.strong_row(
            "self-claim-id", "Self Claimed Scheme", "https://birac.nic.in/self-claim"
        )
        self_claim_only.update(
            {
                "raw_evidence_path": "",
                "page_title": "Self Claimed Scheme",
                "evidence_notes": (
                    "Self Claimed Scheme is definitely active with funding and applications open."
                ),
                "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                "confidence": "0.95",
            }
        )

        existing = self.strong_row(
            "existing-id", "Existing Programme", "https://birac.nic.in/existing"
        )

        potential = self.strong_row(
            "potential-id",
            "Potential Duplicate Programme",
            "https://birac.nic.in/new-potential",
        )

        news = self.strong_row("news-id", "News Article", "https://birac.nic.in/news/item")
        news.update(
            {
                "page_title": "Press Release",
                "page_identity_score": "0.05",
                "programme_status": "",
                "eligibility": "",
                "benefits": "",
                "documents_required": "",
                "application_process": "",
                "raw_evidence_path": self.write_evidence(
                    "news-id-replacement",
                    "Press release and news update about an event announcement. " * 8,
                ),
                "confidence": "0.20",
            }
        )

        self.write_rows([approved, historical, self_claim_only, existing, potential, news])

        before = self.db_path.read_bytes()
        summary = run_validation(
            project_root=self.root,
            input_path=self.input_path,
            database_path=self.db_path,
            output_directory=self.output_dir,
            as_of=date(2026, 7, 9),
            expected_count=6,
        )
        after = self.db_path.read_bytes()

        self.assertEqual(before, after)
        self.assertTrue(summary["database_counts_unchanged"])
        self.assertEqual(summary["records_by_decision"]["APPROVED_FOR_DATABASE"], 1)
        self.assertEqual(summary["records_by_decision"]["NEEDS_MORE_EVIDENCE"], 2)
        self.assertEqual(summary["records_by_decision"]["NEEDS_ADMIN_REVIEW"], 1)
        self.assertEqual(summary["records_by_decision"]["REJECTED"], 2)
        self.assertEqual(summary["handoff_candidate_count"], 1)

        with (self.output_dir / "validated_records_v2_7_2_1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            records = {row["master_id"]: row for row in csv.DictReader(handle)}

        self.assertEqual(records["approved-id"]["validation_decision"], "APPROVED_FOR_DATABASE")
        self.assertEqual(records["historical-id"]["validation_decision"], "NEEDS_MORE_EVIDENCE")
        self.assertEqual(records["historical-id"]["funding_year_contamination"], "YES")
        self.assertEqual(records["historical-id"]["normalized_funding_min"], "")
        self.assertEqual(records["historical-id"]["normalized_funding_max"], "")
        self.assertEqual(records["self-claim-id"]["validation_decision"], "NEEDS_MORE_EVIDENCE")
        self.assertEqual(records["existing-id"]["validation_decision"], "REJECTED")
        self.assertEqual(records["potential-id"]["validation_decision"], "NEEDS_ADMIN_REVIEW")
        self.assertEqual(records["news-id"]["validation_decision"], "REJECTED")

        with (self.output_dir / "database_handoff_v2_7_2_1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            handoff = list(csv.DictReader(handle))
        self.assertEqual([row["master_id"] for row in handoff], ["approved-id"])

        with (self.output_dir / "validation_summary_v2_7_2_1.json").open(
            "r", encoding="utf-8"
        ) as handle:
            saved_summary = json.load(handle)
        self.assertFalse(saved_summary["database_modified"])
        self.assertEqual(saved_summary["llm_validation_calls"], 0)
        self.assertEqual(saved_summary["validator_version"], "2.7.2.1")


if __name__ == "__main__":
    unittest.main()
