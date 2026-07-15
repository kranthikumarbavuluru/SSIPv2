from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from services.meity_temporal_parent_safety_v3_4_3_8_0_3 import (
    PARENT_UNRESOLVED,
    SAFE_HISTORICAL_ACTION,
    TEMPORAL_CURRENT,
    TEMPORAL_HISTORICAL,
    TEMPORAL_UNVERIFIED,
    DecisionSafetyGate,
    SafetyPaths,
    load_config,
    parent_link_repair,
    safe_decision_options,
    safe_recommended_action,
    temporal_validation,
)


class MeitYTemporalParentSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_temporal_parent_safety_v3_4_3_8_0_3.json"
        )
        self.config = load_config(self.config_path)
        self.today = date(2026, 7, 14)

    def test_2023_title_is_historical_without_reopen_evidence(self) -> None:
        row = {
            "canonical_name": "Google Appscale Academy 2023",
            "application_status": "OPEN",
            "closing_date": "2026-12-31",
            "application_url": "https://msh.meity.gov.in/apply/appscale",
            "evidence_excerpt": (
                "Applications are invited. Last date to apply "
                "31 December 2026."
            ),
            "last_verified_at": "2026-07-10T10:00:00+00:00",
        }
        result = temporal_validation(row, self.config, self.today)
        self.assertEqual(result["temporal_validation"], TEMPORAL_HISTORICAL)
        self.assertEqual(result["safe_application_status"], "HISTORICAL_CLOSED")
        self.assertIn(
            "HISTORICAL_TITLE_WITHOUT_REOPEN_EVIDENCE",
            result["temporal_flags"],
        )

    def test_current_call_requires_complete_fresh_evidence(self) -> None:
        complete = {
            "canonical_name": "Current Innovation Challenge",
            "application_status": "OPEN",
            "closing_date": "2026-12-31",
            "application_url": "https://msh.meity.gov.in/apply/current",
            "evidence_excerpt": (
                "Applications are invited. Last date to apply "
                "31 December 2026."
            ),
            "last_verified_at": "2026-07-10T10:00:00+00:00",
        }
        result = temporal_validation(complete, self.config, self.today)
        self.assertEqual(result["temporal_validation"], TEMPORAL_CURRENT)
        self.assertEqual(result["safe_application_status"], "OPEN")

        incomplete = dict(complete)
        incomplete["last_verified_at"] = ""
        result = temporal_validation(incomplete, self.config, self.today)
        self.assertEqual(result["temporal_validation"], TEMPORAL_UNVERIFIED)
        self.assertEqual(result["safe_application_status"], "VERIFICATION_REQUIRED")

    def test_google_appscale_false_genesis_parent_is_removed(self) -> None:
        row = {
            "canonical_name": "Google Appscale Academy 2023",
            "official_page_url": (
                "https://msh.meity.gov.in/program/googleappscale"
            ),
            "parent_scheme_name": "",
            "parent_master_id": "",
            "inferred_family": "GENESIS",
        }
        result = parent_link_repair(row, self.config)
        self.assertEqual(
            result["parent_link_resolution"],
            PARENT_UNRESOLVED,
        )
        self.assertEqual(result["repaired_parent_scheme_name"], "")
        self.assertIn(
            "INCIDENTAL_PARENT_LINK_REMOVED",
            result["parent_link_flags"],
        )

    def test_direct_samridh_parent_is_retained(self) -> None:
        row = {
            "canonical_name": "SAMRIDH Cohort 3",
            "official_page_url": (
                "https://msh.meity.gov.in/program/samridh/cohort-3"
            ),
            "parent_scheme_name": "SAMRIDH",
            "parent_master_id": "samridh_master",
            "inferred_family": "SAMRIDH",
        }
        result = parent_link_repair(row, self.config)
        self.assertEqual(result["repaired_parent_scheme_name"], "SAMRIDH")
        self.assertEqual(result["repaired_parent_master_id"], "samridh_master")

    def test_ambiguous_accept_recommendation_is_never_allowed(self) -> None:
        actions = [
            "CONFIRM_EXISTING_PROGRAMME_FAMILY",
            "REVIEW_NEW_PROGRAMME_FAMILY",
            "CONFIRM_CALL_OR_CHALLENGE_GROUP",
            "REVIEW_CURRENT_CALL",
            "CONFIRM_HISTORICAL_GROUP",
            "REVIEW_IDENTITY_OR_ROLE",
        ]
        for original in actions:
            safe = safe_recommended_action(
                original,
                TEMPORAL_UNVERIFIED,
                self.config,
            )
            options = safe_decision_options(safe)
            self.assertNotIn("ACCEPT_RECOMMENDATION", options)

    def test_historical_temporal_state_forces_historical_action(self) -> None:
        safe = safe_recommended_action(
            "REVIEW_CURRENT_CALL",
            TEMPORAL_HISTORICAL,
            self.config,
        )
        self.assertEqual(safe, SAFE_HISTORICAL_ACTION)

    def test_end_to_end_repairs_bundle_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            gate = DecisionSafetyGate(
                SafetyPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_temporal_parent_safety_v3_4_3_8_0_3.json"
                ),
                today=self.today,
            )
            result = gate.run()
            after = hashlib.sha256(database.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(result["source_decision_bundle_count"], 2)
            self.assertEqual(result["safe_decision_bundle_count"], 2)
            self.assertEqual(result["temporal_downgrade_count"], 1)
            self.assertEqual(result["parent_link_repair_count"], 1)
            self.assertEqual(result["unsafe_current_status_count"], 0)
            self.assertEqual(result["ambiguous_decision_label_count"], 0)
            self.assertTrue(result["deep_review_requires_child_selection"])
            self.assertTrue(result["session_decisions_invalidated_on_signature_change"])
            self.assertFalse(result["database_write_performed"])
            self.assertFalse(result["publication_performed"])

            bundles = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_3/"
                "meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv"
            )
            appscale = next(
                row
                for row in bundles
                if "Google Appscale" in row["bundle_title"]
            )
            self.assertEqual(
                appscale["recommended_action"],
                SAFE_HISTORICAL_ACTION,
            )
            self.assertNotIn(
                "ACCEPT_RECOMMENDATION",
                appscale["allowed_decisions"],
            )

            children = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_3/"
                "meity_safe_decision_children_v3_4_3_8_0_3.csv"
            )
            appscale_child = next(
                row
                for row in children
                if row["canonical_name"] == "Google Appscale Academy 2023"
            )
            self.assertEqual(
                appscale_child["safe_application_status"],
                "HISTORICAL_CLOSED",
            )
            self.assertEqual(
                appscale_child["repaired_parent_scheme_name"],
                "",
            )

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_2"
        purified = project / "data/departments/meity/v3_4_3_8_0_1"
        source.mkdir(parents=True)
        purified.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project
            / "config/meity_temporal_parent_safety_v3_4_3_8_0_3.json"
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

        bundle_fields = [
            "bundle_id",
            "lane",
            "priority",
            "risk_score",
            "bundle_title",
            "recommended_action",
            "rationale",
            "child_record_count",
            "source_evidence_weight",
            "families",
            "entity_types",
            "allow_batch_all",
            "reversible",
            "requires_individual_child_selection",
            "publication_eligible",
            "apply_action_allowed",
            "database_action",
            "publication_action",
        ]
        bundles = [
            {
                "bundle_id": "bundle_appscale",
                "lane": "DEEP_REVIEW",
                "priority": "HIGH",
                "risk_score": "65",
                "bundle_title": (
                    "Potential current call — Google Appscale Academy 2023"
                ),
                "recommended_action": "REVIEW_CURRENT_CALL",
                "rationale": "Potential current call.",
                "child_record_count": "1",
                "source_evidence_weight": "4",
                "families": "GENESIS",
                "entity_types": "ACCELERATOR_COHORT",
                "allow_batch_all": "False",
                "reversible": "True",
                "requires_individual_child_selection": "True",
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "database_action": "NONE",
                "publication_action": "NONE",
            },
            {
                "bundle_id": "bundle_samridh",
                "lane": "BATCH_CONFIRMATION",
                "priority": "LOW",
                "risk_score": "5",
                "bundle_title": "Programme family — SAMRIDH",
                "recommended_action": "CONFIRM_EXISTING_PROGRAMME_FAMILY",
                "rationale": "Confirm programme family.",
                "child_record_count": "1",
                "source_evidence_weight": "1",
                "families": "SAMRIDH",
                "entity_types": "ACCELERATOR_PROGRAMME",
                "allow_batch_all": "True",
                "reversible": "True",
                "requires_individual_child_selection": "False",
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "database_action": "NONE",
                "publication_action": "NONE",
            },
        ]
        self._write_csv(
            source / "meity_admin_decision_bundles_v3_4_3_8_0_2.csv",
            bundles,
            bundle_fields,
        )

        child_fields = [
            "bundle_id",
            "bundle_lane",
            "bundle_action",
            "bundle_title",
            "bundle_child_order",
            "child_id",
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "application_status",
            "programme_status",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "inferred_family",
            "parent_scheme_name",
            "parent_master_id",
            "parent_resolution",
            "evidence_excerpt",
            "status_evidence",
            "source_urls",
            "quality_flags",
            "publication_eligible",
            "apply_action_allowed",
            "source_candidate_id",
        ]
        children = [
            {
                "bundle_id": "bundle_appscale",
                "bundle_lane": "DEEP_REVIEW",
                "bundle_action": "REVIEW_CURRENT_CALL",
                "bundle_title": (
                    "Potential current call — Google Appscale Academy 2023"
                ),
                "bundle_child_order": "1",
                "child_id": "child_appscale",
                "canonical_name": "Google Appscale Academy 2023",
                "entity_type": "ACCELERATOR_COHORT",
                "source_entity_type": "ACCELERATOR_COHORT",
                "application_status": "OPEN",
                "programme_status": "OPEN",
                "closing_date": "2026-12-31",
                "official_page_url": (
                    "https://msh.meity.gov.in/program/googleappscale"
                ),
                "application_url": (
                    "https://msh.meity.gov.in/apply/googleappscale"
                ),
                "inferred_family": "GENESIS",
                "parent_scheme_name": "",
                "parent_master_id": "",
                "parent_resolution": "UNRESOLVED",
                "evidence_excerpt": (
                    "Applications are invited. Last date to apply "
                    "31 December 2026."
                ),
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "source_candidate_id": "appscale_candidate",
            },
            {
                "bundle_id": "bundle_samridh",
                "bundle_lane": "BATCH_CONFIRMATION",
                "bundle_action": "CONFIRM_EXISTING_PROGRAMME_FAMILY",
                "bundle_title": "Programme family — SAMRIDH",
                "bundle_child_order": "1",
                "child_id": "child_samridh",
                "canonical_name": "SAMRIDH",
                "entity_type": "ACCELERATOR_PROGRAMME",
                "source_entity_type": "ACCELERATOR_PROGRAMME",
                "application_status": "SCHEME_INFORMATION_AVAILABLE",
                "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                "official_page_url": (
                    "https://msh.meity.gov.in/schemes/samridh"
                ),
                "inferred_family": "SAMRIDH",
                "parent_scheme_name": "",
                "parent_master_id": "",
                "parent_resolution": "NOT_APPLICABLE",
                "evidence_excerpt": "SAMRIDH permanent accelerator programme.",
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "source_candidate_id": "samridh_candidate",
            },
        ]
        self._write_csv(
            source / "meity_decision_bundle_children_v3_4_3_8_0_2.csv",
            children,
            child_fields,
        )
        (
            source / "meity_review_compression_manifest_v3_4_3_8_0_2.json"
        ).write_text(
            json.dumps(
                {
                    "version": "3.4.3.8.0.2",
                    "signature": "fixture-compression-signature",
                    "admin_decision_bundle_count": 2,
                    "database_write_performed": False,
                    "publication_performed": False,
                }
            ),
            encoding="utf-8",
        )

        purified_fields = [
            "source_candidate_id",
            "last_verified_at",
        ]
        purified_rows = [
            {
                "source_candidate_id": "appscale_candidate",
                "last_verified_at": "2026-07-10T10:00:00+00:00",
            },
            {
                "source_candidate_id": "samridh_candidate",
                "last_verified_at": "2026-07-10T10:00:00+00:00",
            },
        ]
        self._write_csv(
            purified
            / "meity_purified_calls_challenges_v3_4_3_8_0_1.csv",
            [purified_rows[0]],
            purified_fields,
        )
        self._write_csv(
            purified
            / "meity_purified_programme_families_v3_4_3_8_0_1.csv",
            [purified_rows[1]],
            purified_fields,
        )
        for filename in (
            "meity_purified_historical_events_v3_4_3_8_0_1.csv",
            "meity_identity_role_review_v3_4_3_8_0_1.csv",
        ):
            self._write_csv(
                purified / filename,
                [],
                purified_fields,
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
