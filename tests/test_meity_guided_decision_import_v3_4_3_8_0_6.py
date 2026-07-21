from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_guided_decision_import_v3_4_3_8_0_6 import (
    DecisionImportPaths,
    GuidedDecisionImporter,
    load_config,
)


class MeitYGuidedDecisionImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
        )

    def test_valid_signed_decisions_create_preview_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            self._write_worksheet(
                worksheet,
                [
                    {
                        "bundle_id": "bundle_programme",
                        "bundle_title": "Programme family — SAMRIDH",
                        "link_integrity_signature": "sig_programme",
                        "admin_decision": "CONFIRM_PROGRAMME_IDENTITY",
                        "admin_decision_label": "Confirm the programme identity",
                        "selected_child_ids": "child_programme",
                        "admin_note": "",
                    },
                    {
                        "bundle_id": "bundle_evidence",
                        "bundle_title": "Historical evidence — GENESIS",
                        "link_integrity_signature": "sig_evidence",
                        "admin_decision": "NEEDS_MORE_EVIDENCE",
                        "admin_decision_label": "Needs more official evidence",
                        "selected_child_ids": "child_evidence",
                        "admin_note": "The official page role remains unclear.",
                    },
                ],
            )
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            after = hashlib.sha256(database.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(result["plan_status"], "READY_FOR_REVIEW")
            self.assertEqual(result["accepted_decision_count"], 2)
            self.assertEqual(result["rejected_decision_count"], 0)
            self.assertFalse(result["database_write_performed"])
            self.assertFalse(result["publication_performed"])
            self.assertFalse(result["admin_bridge_applied"])

            preview = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_admin_bridge_preview_v3_4_3_8_0_6.csv"
            )
            self.assertEqual(
                preview[0]["bridge_action"],
                "PROPOSE_PROGRAMME_IDENTITY",
            )
            self.assertEqual(preview[0]["database_action"], "NONE")
            self.assertEqual(preview[0]["publication_action"], "NONE")

    def test_stale_signature_blocks_strict_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            self._write_worksheet(
                worksheet,
                [
                    {
                        "bundle_id": "bundle_programme",
                        "bundle_title": "Programme family — SAMRIDH",
                        "link_integrity_signature": "old_signature",
                        "admin_decision": "CONFIRM_PROGRAMME_IDENTITY",
                        "admin_decision_label": "Confirm the programme identity",
                        "selected_child_ids": "child_programme",
                        "admin_note": "",
                    }
                ],
            )
            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            self.assertEqual(result["plan_status"], "BLOCKED")
            self.assertEqual(result["accepted_decision_count"], 0)
            self.assertEqual(result["rejected_decision_count"], 1)
            rejected = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
            )
            self.assertIn(
                "STALE_OR_TAMPERED_LINK_SIGNATURE",
                rejected[0]["rejection_codes"],
            )

    def test_positive_decision_is_blocked_when_link_safety_disallows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            self._write_worksheet(
                worksheet,
                [
                    {
                        "bundle_id": "bundle_evidence",
                        "bundle_title": "Historical evidence — GENESIS",
                        "link_integrity_signature": "sig_evidence",
                        "admin_decision": "CONFIRM_HISTORICAL",
                        "admin_decision_label": "Confirm as a historical reference",
                        "selected_child_ids": "child_evidence",
                        "admin_note": "",
                    }
                ],
            )
            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            self.assertEqual(result["plan_status"], "BLOCKED")
            rejected = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
            )
            self.assertIn(
                "POSITIVE_DECISION_BLOCKED_BY_LINK_SAFETY",
                rejected[0]["rejection_codes"],
            )

    def test_required_note_and_child_selection_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            self._write_worksheet(
                worksheet,
                [
                    {
                        "bundle_id": "bundle_deep",
                        "bundle_title": "Current opportunity evidence review",
                        "link_integrity_signature": "sig_deep",
                        "admin_decision": "NEEDS_MORE_EVIDENCE",
                        "admin_decision_label": "Needs more official evidence",
                        "selected_child_ids": "",
                        "admin_note": "",
                    }
                ],
            )
            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            self.assertEqual(result["plan_status"], "BLOCKED")
            rejected = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
            )
            codes = rejected[0]["rejection_codes"]
            self.assertIn("CHILD_SELECTION_REQUIRED", codes)
            self.assertIn("ADMIN_NOTE_REQUIRED", codes)

    def test_current_call_confirmation_requires_complete_application_integrity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            self._write_worksheet(
                worksheet,
                [
                    {
                        "bundle_id": "bundle_deep",
                        "bundle_title": "Current opportunity evidence review",
                        "link_integrity_signature": "sig_deep",
                        "admin_decision": (
                            "CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE"
                        ),
                        "admin_decision_label": (
                            "Confirm the current opportunity evidence"
                        ),
                        "selected_child_ids": "child_deep",
                        "admin_note": "Deadline checked.",
                    }
                ],
            )
            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            self.assertEqual(result["plan_status"], "BLOCKED")
            rejected = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
            )
            self.assertIn(
                "CURRENT_APPLICATION_INTEGRITY_INCOMPLETE",
                rejected[0]["rejection_codes"],
            )

    def test_unknown_child_and_duplicate_bundle_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            worksheet = project / "guided.csv"
            row = {
                "bundle_id": "bundle_programme",
                "bundle_title": "Programme family — SAMRIDH",
                "link_integrity_signature": "sig_programme",
                "admin_decision": "CONFIRM_PROGRAMME_IDENTITY",
                "admin_decision_label": "Confirm the programme identity",
                "selected_child_ids": "unknown_child",
                "admin_note": "",
            }
            self._write_worksheet(worksheet, [row, row])
            importer = GuidedDecisionImporter(
                DecisionImportPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
                ),
            )
            result = importer.validate_and_plan(worksheet, strict=True)
            self.assertEqual(result["plan_status"], "BLOCKED")
            rejected = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_6/"
                "meity_rejected_decision_rows_v3_4_3_8_0_6.csv"
            )
            all_codes = ";".join(row["rejection_codes"] for row in rejected)
            self.assertIn("UNKNOWN_SELECTED_CHILD", all_codes)
            self.assertIn("DUPLICATE_BUNDLE_DECISION", all_codes)

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_4"
        source.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project
            / "config/meity_guided_decision_import_v3_4_3_8_0_6.json"
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
            "bundle_title",
            "link_integrity_signature",
            "allowed_decisions",
            "requires_child_selection",
            "requires_admin_note",
            "safe_positive_decision_allowed",
            "current_application_integrity_complete",
        ]
        bundles = [
            {
                "bundle_id": "bundle_programme",
                "bundle_title": "Programme family — SAMRIDH",
                "link_integrity_signature": "sig_programme",
                "allowed_decisions": (
                    "PENDING;CONFIRM_PROGRAMME_IDENTITY;"
                    "NEEDS_MORE_EVIDENCE;DEFER;REJECT_CLASSIFICATION"
                ),
                "requires_child_selection": "False",
                "requires_admin_note": "False",
                "safe_positive_decision_allowed": "True",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_evidence",
                "bundle_title": "Historical evidence — GENESIS",
                "link_integrity_signature": "sig_evidence",
                "allowed_decisions": (
                    "PENDING;CONFIRM_HISTORICAL;"
                    "NEEDS_MORE_EVIDENCE;DEFER;REJECT_CLASSIFICATION"
                ),
                "requires_child_selection": "False",
                "requires_admin_note": "False",
                "safe_positive_decision_allowed": "False",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_deep",
                "bundle_title": "Current opportunity evidence review",
                "link_integrity_signature": "sig_deep",
                "allowed_decisions": (
                    "PENDING;CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE;"
                    "NEEDS_MORE_EVIDENCE;DEFER;REJECT_CLASSIFICATION"
                ),
                "requires_child_selection": "True",
                "requires_admin_note": "True",
                "safe_positive_decision_allowed": "True",
                "current_application_integrity_complete": "False",
            },
        ]
        self._write_csv(
            source
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv",
            bundles,
            bundle_fields,
        )

        child_fields = [
            "bundle_id",
            "child_id",
            "canonical_name",
            "entity_type",
        ]
        children = [
            {
                "bundle_id": "bundle_programme",
                "child_id": "child_programme",
                "canonical_name": "SAMRIDH",
                "entity_type": "ACCELERATOR_PROGRAMME",
            },
            {
                "bundle_id": "bundle_evidence",
                "child_id": "child_evidence",
                "canonical_name": "GENESIS Result",
                "entity_type": "RESULT_ANNOUNCEMENT",
            },
            {
                "bundle_id": "bundle_deep",
                "child_id": "child_deep",
                "canonical_name": "Current Challenge",
                "entity_type": "CHALLENGE_CALL",
            },
        ]
        self._write_csv(
            source
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv",
            children,
            child_fields,
        )

        (
            source / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        ).write_text(
            json.dumps(
                {
                    "version": "3.4.3.8.0.4",
                    "link_integrity_signature": "source_link_signature",
                    "session_state_signature": "source_session_signature",
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

    def _write_worksheet(
        self,
        path: Path,
        rows: list[dict[str, str]],
    ) -> None:
        fields = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )["required_headers"]
        self._write_csv(path, rows, fields)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
