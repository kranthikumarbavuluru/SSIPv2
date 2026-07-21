from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_candidate_purification_v3_4_3_8_0_1 import (
    CandidatePurifier,
    PurificationPaths,
    date_role_repair,
    hard_error_reason,
    load_config,
    raw_filename_title,
)


class MeitYCandidatePurificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_candidate_purification_v3_4_3_8_0_1.json"
        )
        self.config = load_config(self.config_path)

    def test_page_not_found_is_hard_excluded(self) -> None:
        row = {
            "canonical_name": "MeityStartupHub",
            "official_page_url": "https://msh.meity.gov.in/successtoryview",
            "evidence_excerpt": "Page Not Found GENERIC_OR_NAVIGATION_PAGE",
        }
        reason = hard_error_reason(row, None, self.config)
        self.assertTrue(reason)

    def test_footer_date_is_not_a_closing_date(self) -> None:
        row = {
            "canonical_name": "MeityStartupHub",
            "closing_date": "2026-07-13",
            "opening_date": "",
            "evidence_excerpt": (
                "Page Not Found. Last Updated On : 13/07/2026. "
                "All Rights Reserved."
            ),
        }
        opening, closing, flags = date_role_repair(
            row,
            None,
            self.config,
        )
        self.assertEqual(opening, "")
        self.assertEqual(closing, "")
        self.assertIn("CLOSING_DATE_CONTEXT_NOT_PROVEN", flags)
        self.assertIn("FOOTER_DATE_REMOVED", flags)

    def test_real_deadline_is_retained(self) -> None:
        row = {
            "canonical_name": "Official Challenge",
            "closing_date": "2026-12-31",
            "opening_date": "",
            "evidence_excerpt": (
                "Applications are invited. Last date to apply: "
                "31 December 2026."
            ),
        }
        _, closing, flags = date_role_repair(
            row,
            None,
            self.config,
        )
        self.assertEqual(closing, "2026-12-31")
        self.assertNotIn("FOOTER_DATE_REMOVED", flags)

    def test_raw_pdf_filename_is_never_a_canonical_title(self) -> None:
        self.assertTrue(
            raw_filename_title(
                "administrative%20approval_tide%202.0.pdf"
            )
        )
        self.assertTrue(
            raw_filename_title("brochure_genesis.pdf")
        )

    def test_end_to_end_partitions_and_consolidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            source_dir = (
                project
                / "data/departments/meity/v3_4_3_8_0"
            )
            output_dir = (
                project
                / "data/departments/meity/v3_4_3_8_0_1"
            )
            config_dir = project / "config"
            database_dir = project / "database"
            source_dir.mkdir(parents=True)
            config_dir.mkdir()
            database_dir.mkdir()

            config_target = (
                config_dir
                / "meity_candidate_purification_v3_4_3_8_0_1.json"
            )
            config_target.write_text(
                self.config_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            database_path = database_dir / "ssip_staging_v1.db"
            connection = sqlite3.connect(database_path)
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('unchanged')")
            connection.commit()
            connection.close()

            fields = [
                "candidate_id",
                "canonical_name",
                "entity_type",
                "record_kind",
                "programme_status",
                "application_status",
                "opening_date",
                "closing_date",
                "official_page_url",
                "application_url",
                "source",
                "ministry",
                "implementing_agency",
                "startup_relevance",
                "parent_master_id",
                "parent_scheme_name",
                "parent_resolution",
                "existing_master_id",
                "existing_public_record",
                "evidence_id",
                "evidence_excerpt",
                "status_evidence",
                "quality_flags",
                "admin_queue",
                "publication_eligible",
                "apply_action_allowed",
            ]

            programme_rows = [
                {
                    "candidate_id": "p1",
                    "canonical_name": "GENESIS",
                    "entity_type": "PERMANENT_SCHEME",
                    "record_kind": "SCHEME_PROGRAMME",
                    "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "SCHEME_INFORMATION_AVAILABLE",
                    "official_page_url": "https://msh.meity.gov.in/schemes/genesis",
                    "source": "MeitY Startup Hub",
                    "existing_master_id": "genesis_master",
                    "existing_public_record": "True",
                    "evidence_id": "e1",
                    "evidence_excerpt": "GENESIS startup support programme",
                },
                {
                    "candidate_id": "p2",
                    "canonical_name": "Genesis",
                    "entity_type": "PERMANENT_PROGRAMME",
                    "record_kind": "SCHEME_PROGRAMME",
                    "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "SCHEME_INFORMATION_AVAILABLE",
                    "official_page_url": "https://msh.meity.gov.in/schemes/genesis",
                    "source": "MeitY Startup Hub",
                    "evidence_id": "e2",
                    "evidence_excerpt": "Gen-next support for innovative startups",
                },
                {
                    "candidate_id": "bad1",
                    "canonical_name": "MeityStartupHub",
                    "entity_type": "PERMANENT_SCHEME",
                    "record_kind": "SCHEME_PROGRAMME",
                    "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "SCHEME_INFORMATION_AVAILABLE",
                    "closing_date": "2026-07-13",
                    "official_page_url": "https://msh.meity.gov.in/successtoryview",
                    "source": "MeitY Startup Hub",
                    "evidence_id": "e3",
                    "evidence_excerpt": "Page Not Found Last Updated On 13/07/2026",
                },
                {
                    "candidate_id": "doc1",
                    "canonical_name": "brochure_genesis.pdf",
                    "entity_type": "PERMANENT_SCHEME",
                    "record_kind": "SCHEME_PROGRAMME",
                    "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "SCHEME_INFORMATION_AVAILABLE",
                    "official_page_url": "https://msh.meity.gov.in/uploads/brochure_genesis.pdf",
                    "source": "MeitY Startup Hub",
                    "evidence_id": "e4",
                    "evidence_excerpt": "GENESIS brochure",
                },
            ]
            call_rows = [
                {
                    "candidate_id": "c1",
                    "canonical_name": "Bhumi",
                    "entity_type": "HACKATHON",
                    "record_kind": "APPLICATION_CALL",
                    "programme_status": "VERIFICATION_REQUIRED",
                    "application_status": "VERIFICATION_REQUIRED",
                    "official_page_url": "https://msh.meity.gov.in/program/mshcorporate/bhumi",
                    "source": "MeitY Startup Hub",
                    "evidence_id": "e5",
                    "evidence_excerpt": "BHUMI BSF hackathon with Indian startups",
                }
            ]

            def write_fixture(name: str, rows: list[dict[str, str]]) -> None:
                with (source_dir / name).open(
                    "w",
                    encoding="utf-8-sig",
                    newline="",
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(row)

            write_fixture(
                "meity_programme_inventory_v3_4_3_8_0.csv",
                programme_rows,
            )
            write_fixture(
                "meity_current_calls_challenges_v3_4_3_8_0.csv",
                call_rows,
            )
            write_fixture(
                "meity_historical_calls_results_v3_4_3_8_0.csv",
                [],
            )
            write_fixture(
                "meity_exclusions_v3_4_3_8_0.csv",
                [],
            )

            evidence_fields = [
                "evidence_id",
                "title",
                "text",
                "url",
                "final_url",
                "source_kind",
                "status_code",
                "quality_flags",
                "error",
            ]
            evidence_rows = [
                {
                    "evidence_id": "e1",
                    "title": "GENESIS",
                    "text": "GENESIS startup support programme",
                    "url": "https://msh.meity.gov.in/schemes/genesis",
                    "final_url": "https://msh.meity.gov.in/schemes/genesis",
                    "source_kind": "HTML_BROWSER_RENDERED",
                    "status_code": "200",
                },
                {
                    "evidence_id": "e2",
                    "title": "Genesis",
                    "text": "Gen-next support for innovative startups",
                    "url": "https://msh.meity.gov.in/schemes/genesis",
                    "final_url": "https://msh.meity.gov.in/schemes/genesis",
                    "source_kind": "PRIOR_CSV_RECORD",
                    "status_code": "200",
                },
                {
                    "evidence_id": "e3",
                    "title": "MeityStartupHub",
                    "text": "Page Not Found Last Updated On 13/07/2026",
                    "url": "https://msh.meity.gov.in/successtoryview",
                    "final_url": "https://msh.meity.gov.in/successtoryview",
                    "source_kind": "HTML_BROWSER_RENDERED",
                    "status_code": "200",
                },
                {
                    "evidence_id": "e4",
                    "title": "brochure_genesis.pdf",
                    "text": "GENESIS brochure",
                    "url": "https://msh.meity.gov.in/uploads/brochure_genesis.pdf",
                    "final_url": "https://msh.meity.gov.in/uploads/brochure_genesis.pdf",
                    "source_kind": "PDF_DOCUMENT",
                    "status_code": "200",
                },
                {
                    "evidence_id": "e5",
                    "title": "BHUMI – BSF",
                    "text": "BHUMI BSF hackathon with Indian startups",
                    "url": "https://msh.meity.gov.in/program/mshcorporate/bhumi",
                    "final_url": "https://msh.meity.gov.in/program/mshcorporate/bhumi",
                    "source_kind": "HTML_BROWSER_RENDERED",
                    "status_code": "200",
                },
            ]
            with (
                source_dir
                / "meity_document_and_page_evidence_v3_4_3_8_0.csv"
            ).open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=evidence_fields)
                writer.writeheader()
                writer.writerows(evidence_rows)

            (
                source_dir
                / "meity_complete_intelligence_manifest_v3_4_3_8_0.json"
            ).write_text(
                json.dumps(
                    {
                        "version": "3.4.3.8.0",
                        "signature": "fixture-signature",
                        "candidate_count": 5,
                        "evidence_count": 5,
                        "database_write_performed": False,
                        "publication_performed": False,
                    }
                ),
                encoding="utf-8",
            )

            before = hashlib.sha256(database_path.read_bytes()).hexdigest()
            purifier = CandidatePurifier(
                PurificationPaths.defaults(project),
                load_config(config_target),
            )
            manifest = purifier.purify()
            after = hashlib.sha256(database_path.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(manifest["source_candidate_count"], 5)
            self.assertEqual(manifest["partition_total"], 5)
            self.assertTrue(manifest["partition_complete"])
            self.assertEqual(manifest["purified_programme_family_count"], 1)
            self.assertEqual(manifest["purified_call_challenge_count"], 1)
            self.assertEqual(manifest["supporting_document_count"], 1)
            self.assertEqual(manifest["excluded_error_page_count"], 1)
            self.assertEqual(manifest["unsafe_programme_identity_count"], 0)
            self.assertFalse(manifest["database_write_performed"])
            self.assertFalse(manifest["publication_performed"])

            with (
                output_dir
                / "meity_purified_programme_families_v3_4_3_8_0_1.csv"
            ).open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                programme_rows_out = list(csv.DictReader(handle))
            self.assertEqual(programme_rows_out[0]["canonical_name"], "GENESIS")
            self.assertEqual(programme_rows_out[0]["source_candidate_count"], "2")


if __name__ == "__main__":
    unittest.main()
