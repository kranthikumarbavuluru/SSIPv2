from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_review_compression_v3_4_3_8_0_2 import (
    ACTION_REVIEW_CURRENT_CALL,
    LANE_AUTO,
    LANE_DEEP,
    CompressionPaths,
    ReviewCompressor,
    load_config,
    obvious_non_catalogue,
    row_weight,
)


class MeitYReviewCompressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_review_compression_v3_4_3_8_0_2.json"
        )
        self.config = load_config(self.config_path)

    def test_source_candidate_weight_uses_consolidated_count(self) -> None:
        self.assertEqual(row_weight({"source_candidate_count": "4"}), 4)
        self.assertEqual(row_weight({"source_candidate_count": ""}), 1)

    def test_event_or_conference_is_auto_resolved(self) -> None:
        row = {
            "canonical_name": "Brussels",
            "entity_type": "EVENT_OR_CONFERENCE",
        }
        self.assertTrue(obvious_non_catalogue(row, self.config))

    def test_current_call_is_deep_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            compressor = ReviewCompressor(
                CompressionPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_review_compression_v3_4_3_8_0_2.json"
                ),
            )
            result = compressor.run()

            decision_rows = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_2/"
                "meity_admin_decision_bundles_v3_4_3_8_0_2.csv"
            )
            current = [
                row
                for row in decision_rows
                if row["recommended_action"] == ACTION_REVIEW_CURRENT_CALL
            ]
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["lane"], LANE_DEEP)
            self.assertEqual(current[0]["allow_batch_all"], "False")
            self.assertLessEqual(
                result["admin_decision_bundle_count"],
                result["max_admin_decision_bundles"],
            )

    def test_auto_resolved_rows_do_not_enter_admin_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            compressor = ReviewCompressor(
                CompressionPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_review_compression_v3_4_3_8_0_2.json"
                ),
            )
            result = compressor.run()

            auto_rows = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_2/"
                "meity_auto_resolved_groups_v3_4_3_8_0_2.csv"
            )
            decision_rows = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_2/"
                "meity_admin_decision_bundles_v3_4_3_8_0_2.csv"
            )

            self.assertTrue(auto_rows)
            self.assertTrue(
                all(row["lane"] == LANE_AUTO for row in auto_rows)
            )
            self.assertTrue(
                all(row["lane"] != LANE_AUTO for row in decision_rows)
            )
            self.assertGreater(result["auto_resolved_evidence_weight"], 0)

    def test_end_to_end_reconciles_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            compressor = ReviewCompressor(
                CompressionPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_review_compression_v3_4_3_8_0_2.json"
                ),
            )
            result = compressor.run()
            after = hashlib.sha256(database.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertTrue(result["row_reconciliation"])
            self.assertTrue(result["evidence_weight_reconciliation"])
            self.assertEqual(result["source_evidence_weight"], 11)
            self.assertEqual(result["apply_action_allowed_count"], 0)
            self.assertEqual(result["publication_eligible_count"], 0)
            self.assertFalse(result["database_write_performed"])
            self.assertFalse(result["publication_performed"])

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_1"
        source.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project
            / "config/meity_review_compression_v3_4_3_8_0_2.json"
        ).write_text(
            self.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        database = project / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('unchanged')")
        connection.commit()
        connection.close()

        common_fields = [
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "record_kind",
            "application_status",
            "programme_status",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "startup_relevance",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "existing_master_id",
            "existing_public_record",
            "identity_family",
            "disposition",
            "decision_reason",
            "document_role",
            "source_candidate_id",
            "source_candidate_ids",
            "source_candidate_count",
            "source_evidence_id",
            "evidence_ids",
            "source_titles",
            "source_urls",
            "evidence_excerpt",
            "status_evidence",
            "quality_flags",
            "publication_eligible",
            "apply_action_allowed",
        ]

        programmes = [
            {
                "canonical_name": "GENESIS",
                "entity_type": "ACCELERATOR_PROGRAMME",
                "source_entity_type": "PERMANENT_SCHEME",
                "record_kind": "SCHEME_PROGRAMME",
                "application_status": "SCHEME_INFORMATION_AVAILABLE",
                "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                "official_page_url": "https://msh.meity.gov.in/schemes/genesis",
                "existing_master_id": "genesis_master",
                "existing_public_record": "True",
                "identity_family": "GENESIS",
                "disposition": "PURIFIED_PROGRAMME_FAMILY",
                "source_candidate_id": "p1",
                "source_candidate_count": "2",
                "evidence_excerpt": "GENESIS startup support programme.",
            },
            {
                "canonical_name": "New Innovation Programme",
                "entity_type": "PERMANENT_PROGRAMME",
                "source_entity_type": "PERMANENT_PROGRAMME",
                "record_kind": "SCHEME_PROGRAMME",
                "application_status": "SCHEME_INFORMATION_AVAILABLE",
                "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                "official_page_url": "https://msh.meity.gov.in/program/new",
                "existing_public_record": "False",
                "identity_family": "New Innovation Programme",
                "disposition": "PURIFIED_PROGRAMME_FAMILY",
                "source_candidate_id": "p2",
                "evidence_excerpt": "Possible new permanent programme.",
            },
        ]
        calls = [
            {
                "canonical_name": "Current Startup Challenge",
                "entity_type": "CHALLENGE_CALL",
                "source_entity_type": "CHALLENGE_CALL",
                "record_kind": "APPLICATION_CALL",
                "application_status": "OPEN",
                "programme_status": "OPEN",
                "closing_date": "2026-12-31",
                "official_page_url": "https://msh.meity.gov.in/challenges/current",
                "application_url": "https://msh.meity.gov.in/apply/current",
                "parent_scheme_name": "GENESIS",
                "parent_resolution": "MATCHED_EXISTING_PROGRAMME",
                "disposition": "PURIFIED_CALL_OR_CHALLENGE",
                "source_candidate_id": "c1",
                "evidence_excerpt": "Applications open until 31 December 2026.",
            },
            {
                "canonical_name": "Historical Hackathon",
                "entity_type": "HACKATHON",
                "source_entity_type": "HACKATHON",
                "record_kind": "APPLICATION_CALL",
                "application_status": "VERIFICATION_REQUIRED",
                "programme_status": "VERIFICATION_REQUIRED",
                "official_page_url": "https://msh.meity.gov.in/challenges/history",
                "parent_scheme_name": "GENESIS",
                "parent_resolution": "MATCHED_EXISTING_PROGRAMME",
                "disposition": "PURIFIED_CALL_OR_CHALLENGE",
                "source_candidate_id": "c2",
                "evidence_excerpt": "Past hackathon reference.",
            },
        ]
        historical = [
            {
                "canonical_name": "GENESIS Result Notice",
                "entity_type": "RESULT_ANNOUNCEMENT",
                "source_entity_type": "RESULT_ANNOUNCEMENT",
                "record_kind": "CALL_EVENT",
                "application_status": "HISTORICAL_CLOSED",
                "programme_status": "HISTORICAL_CLOSED",
                "official_page_url": "https://msh.meity.gov.in/results/genesis",
                "parent_scheme_name": "GENESIS",
                "parent_resolution": "LINKED_TO_CALL_CANDIDATE",
                "disposition": "PURIFIED_HISTORICAL_EVENT",
                "source_candidate_id": "h1",
                "evidence_excerpt": "Winner announced.",
            }
        ]
        documents = [
            {
                "canonical_name": "",
                "original_canonical_name": "brochure_genesis.pdf",
                "entity_type": "PERMANENT_SCHEME",
                "source_entity_type": "PERMANENT_SCHEME",
                "record_kind": "SCHEME_PROGRAMME",
                "official_page_url": "https://msh.meity.gov.in/files/brochure_genesis.pdf",
                "disposition": "SUPPORTING_DOCUMENT",
                "document_role": "BROCHURE",
                "source_candidate_id": "d1",
                "evidence_excerpt": "GENESIS brochure.",
            },
            {
                "canonical_name": "",
                "original_canonical_name": "tide_guidelines.pdf",
                "entity_type": "PERMANENT_SCHEME",
                "source_entity_type": "PERMANENT_SCHEME",
                "record_kind": "SCHEME_PROGRAMME",
                "official_page_url": "https://msh.meity.gov.in/files/tide_guidelines.pdf",
                "disposition": "SUPPORTING_DOCUMENT",
                "document_role": "PROGRAMME_GUIDELINE",
                "source_candidate_id": "d2",
                "evidence_excerpt": "TIDE 2.0 guidelines.",
            },
        ]
        excluded = [
            {
                "canonical_name": "MeityStartupHub",
                "entity_type": "PERMANENT_PROGRAMME",
                "source_entity_type": "PERMANENT_PROGRAMME",
                "record_kind": "SCHEME_PROGRAMME",
                "official_page_url": "https://msh.meity.gov.in/",
                "disposition": "EXCLUDED_ERROR_OR_NAVIGATION",
                "decision_reason": "GENERIC_OR_PORTAL_TITLE",
                "source_candidate_id": "e1",
                "evidence_excerpt": "Generic portal page.",
            },
            {
                "canonical_name": "Page Not Found",
                "entity_type": "PERMANENT_SCHEME",
                "source_entity_type": "PERMANENT_SCHEME",
                "record_kind": "SCHEME_PROGRAMME",
                "official_page_url": "https://msh.meity.gov.in/missing",
                "disposition": "EXCLUDED_ERROR_OR_NAVIGATION",
                "decision_reason": "ERROR_OR_NOT_FOUND_PAGE",
                "source_candidate_id": "e2",
                "evidence_excerpt": "Page Not Found.",
            },
        ]
        identity = [
            {
                "canonical_name": "Brussels",
                "entity_type": "EVENT_OR_CONFERENCE",
                "source_entity_type": "EVENT_OR_CONFERENCE",
                "record_kind": "EVIDENCE_ONLY",
                "application_status": "NOT_APPLICABLE",
                "programme_status": "NOT_APPLICABLE",
                "official_page_url": "https://msh.meity.gov.in/program/brussels",
                "parent_resolution": "UNRESOLVED",
                "disposition": "IDENTITY_OR_ROLE_REVIEW",
                "source_candidate_id": "i1",
                "evidence_excerpt": "Startup delegation to Brussels.",
            }
        ]

        self._write_csv(
            source / "meity_purified_programme_families_v3_4_3_8_0_1.csv",
            programmes,
            common_fields,
        )
        self._write_csv(
            source / "meity_purified_calls_challenges_v3_4_3_8_0_1.csv",
            calls,
            common_fields,
        )
        self._write_csv(
            source / "meity_purified_historical_events_v3_4_3_8_0_1.csv",
            historical,
            common_fields,
        )
        self._write_csv(
            source / "meity_supporting_documents_v3_4_3_8_0_1.csv",
            documents,
            common_fields,
        )
        self._write_csv(
            source / "meity_excluded_error_pages_v3_4_3_8_0_1.csv",
            excluded,
            common_fields,
        )
        self._write_csv(
            source / "meity_identity_role_review_v3_4_3_8_0_1.csv",
            identity,
            common_fields,
        )
        (
            source
            / "meity_candidate_purification_manifest_v3_4_3_8_0_1.json"
        ).write_text(
            json.dumps(
                {
                    "version": "3.4.3.8.0.1",
                    "signature": "fixture-purification-signature",
                    "source_candidate_count": 11,
                    "database_write_performed": False,
                    "publication_performed": False,
                }
            ),
            encoding="utf-8",
        )
        return project

    @staticmethod
    def _write_csv(
        path: Path,
        rows: list[dict[str, str]],
        fields: list[str],
    ) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
