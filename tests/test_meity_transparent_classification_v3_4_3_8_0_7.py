from __future__ import annotations

import ast
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_transparent_classification_v3_4_3_8_0_7 import (
    AUDIT_TABLE,
    OVERRIDE_TABLE,
    ClassificationPaths,
    ClassificationWriteGate,
    load_config,
    transparent_classification,
)


class TransparentClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
        )
        self.config = load_config(self.config_path)

    def test_permanent_programme_is_explained(self) -> None:
        result = transparent_classification(
            {
                "canonical_name": "CREST Semiconductor Accelerator",
                "entity_type": "ACCELERATOR_PROGRAMME",
                "verified_information_role": "SCHEME_INFORMATION_PAGE",
                "temporal_validation": "NOT_APPLICABLE",
                "verified_application_url": "",
                "closing_date": "",
            },
            self.config,
        )
        self.assertEqual(
            result["suggested_entity_type"],
            "PERMANENT_PROGRAMME",
        )
        labels = [row["label"] for row in result["classification_reasons"]]
        self.assertTrue(
            any("upstream identity is a programme" in label for label in labels)
        )
        self.assertTrue(
            any("No call closing date" in label for label in labels)
        )

    def test_grand_challenge_is_separate_call_type(self) -> None:
        result = transparent_classification(
            {
                "canonical_name": "Inviting Applications Agrienics Grand Challenge",
                "entity_type": "GRAND_CHALLENGE",
                "verified_information_role": "CALL_INFORMATION_PAGE",
                "temporal_validation": "CURRENT_STATUS_NOT_PROVEN",
                "verified_application_url": "",
                "closing_date": "",
            },
            self.config,
        )
        self.assertEqual(
            result["suggested_entity_type"],
            "CHALLENGE_CALL",
        )
        self.assertIn(
            "grand challenge",
            result["challenge_markers"].casefold(),
        )

    def test_historical_title_is_not_current_call(self) -> None:
        result = transparent_classification(
            {
                "canonical_name": "Google Appscale Academy 2023",
                "entity_type": "ACCELERATOR_COHORT",
                "temporal_validation": "HISTORICAL_BY_TITLE_OR_DEADLINE",
                "verified_application_url": "",
            },
            self.config,
        )
        self.assertEqual(
            result["suggested_entity_type"],
            "HISTORICAL_REFERENCE",
        )

    def test_preview_does_not_write_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = ClassificationWriteGate(
                ClassificationPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
                ),
            )
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            preview = service.preview(
                child_id="child_crest",
                corrected_entity_type="PERMANENT_PROGRAMME",
                corrected_parent_scheme_name="",
                corrected_parent_master_id="",
                admin_note="",
                actor="Test Admin",
            )
            after = hashlib.sha256(database.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(
                preview["publication_action"],
                "NONE",
            )

    def test_type_change_requires_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = ClassificationWriteGate(
                ClassificationPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
                ),
            )
            with self.assertRaisesRegex(ValueError, "Admin note is required"):
                service.preview(
                    child_id="child_crest",
                    corrected_entity_type="CHALLENGE_CALL",
                    corrected_parent_scheme_name="CREST",
                    corrected_parent_master_id="child_crest",
                    admin_note="",
                    actor="Test Admin",
                )

    def test_write_requires_exact_confirmation_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = ClassificationWriteGate(
                ClassificationPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
                ),
            )
            preview = service.preview(
                child_id="child_crest",
                corrected_entity_type="PERMANENT_PROGRAMME",
                corrected_parent_scheme_name="",
                corrected_parent_master_id="",
                admin_note="Official programme identity confirmed.",
                actor="Test Admin",
            )
            with self.assertRaises(PermissionError):
                service.apply(preview, "WRITE")

            result = service.apply(preview, "WRITE CLASSIFICATION")
            self.assertTrue(result["written"])
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertTrue(result["core_table_counts_preserved"])
            self.assertFalse(result["public_visibility_changed"])
            self.assertEqual(result["publication_action"], "NONE")

            connection = sqlite3.connect(
                project / "database/ssip_staging_v1.db"
            )
            try:
                override = connection.execute(
                    f"""
                    SELECT corrected_entity_type, is_active, publication_action
                    FROM {OVERRIDE_TABLE}
                    WHERE child_id = ?
                    """,
                    ("child_crest",),
                ).fetchone()
                self.assertEqual(override[0], "PERMANENT_PROGRAMME")
                self.assertEqual(override[1], 1)
                self.assertEqual(override[2], "NONE")
                audit_count = connection.execute(
                    f"SELECT COUNT(*) FROM {AUDIT_TABLE}"
                ).fetchone()[0]
                self.assertEqual(audit_count, 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM scheme_staging"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM public_schemes"
                    ).fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_second_write_supersedes_first(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = ClassificationWriteGate(
                ClassificationPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
                ),
            )
            first = service.preview(
                "child_crest",
                "PERMANENT_PROGRAMME",
                "",
                "",
                "Programme confirmed.",
                "Admin A",
            )
            service.apply(first, "WRITE CLASSIFICATION")
            second = service.preview(
                "child_crest",
                "PERMANENT_SCHEME",
                "",
                "",
                "Official source uses scheme identity.",
                "Admin B",
            )
            service.apply(second, "WRITE CLASSIFICATION")

            connection = sqlite3.connect(
                project / "database/ssip_staging_v1.db"
            )
            try:
                active = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM {OVERRIDE_TABLE}
                    WHERE child_id = ? AND is_active = 1
                    """,
                    ("child_crest",),
                ).fetchone()[0]
                superseded = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM {OVERRIDE_TABLE}
                    WHERE child_id = ? AND status = 'SUPERSEDED'
                    """,
                    ("child_crest",),
                ).fetchone()[0]
                self.assertEqual(active, 1)
                self.assertEqual(superseded, 1)
            finally:
                connection.close()

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_4"
        source.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project
            / "config/meity_transparent_classification_v3_4_3_8_0_7.json"
        ).write_text(
            self.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        connection = sqlite3.connect(
            project / "database/ssip_staging_v1.db"
        )
        connection.execute(
            "CREATE TABLE scheme_staging (master_id TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO scheme_staging VALUES ('scheme_1')"
        )
        connection.execute(
            "CREATE TABLE admin_review_queue (master_id TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO admin_review_queue VALUES ('review_1')"
        )
        connection.execute(
            "CREATE TABLE public_schemes (master_id TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO public_schemes VALUES ('public_1')"
        )
        connection.commit()
        connection.close()

        children_fields = [
            "bundle_id",
            "child_id",
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "temporal_validation",
            "verified_information_title",
            "verified_information_role",
            "verified_information_url",
            "verified_application_url",
            "closing_date",
            "status_evidence",
            "evidence_excerpt",
            "safe_application_status",
            "repaired_parent_scheme_name",
            "repaired_parent_master_id",
            "parent_link_resolution",
        ]
        self._write_csv(
            source
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv",
            [
                {
                    "bundle_id": "bundle_crest",
                    "child_id": "child_crest",
                    "canonical_name": "CREST Semiconductor Accelerator",
                    "original_canonical_name": "CREST Semiconductor Accelerator",
                    "entity_type": "ACCELERATOR_PROGRAMME",
                    "temporal_validation": "NOT_APPLICABLE",
                    "verified_information_title": "CREST Semiconductor Accelerator",
                    "verified_information_role": "SCHEME_INFORMATION_PAGE",
                    "verified_information_url": "https://msh.meity.gov.in/crest",
                    "verified_application_url": "",
                    "closing_date": "",
                    "status_evidence": "Permanent accelerator programme.",
                    "evidence_excerpt": "Startup accelerator support.",
                    "safe_application_status": "SCHEME_INFORMATION_AVAILABLE",
                    "repaired_parent_scheme_name": "",
                    "repaired_parent_master_id": "",
                    "parent_link_resolution": "NOT_APPLICABLE",
                }
            ],
            children_fields,
        )
        bundle_fields = [
            "bundle_id",
            "bundle_title",
            "link_integrity_signature",
            "safe_positive_decision_allowed",
        ]
        self._write_csv(
            source
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv",
            [
                {
                    "bundle_id": "bundle_crest",
                    "bundle_title": "Programme family — CREST",
                    "link_integrity_signature": "link_sig_crest",
                    "safe_positive_decision_allowed": "True",
                }
            ],
            bundle_fields,
        )
        (
            source / "meity_url_integrity_manifest_v3_4_3_8_0_4.json"
        ).write_text(
            json.dumps(
                {
                    "version": "3.4.3.8.0.4",
                    "link_integrity_signature": "manifest_sig",
                    "database_write_performed": False,
                    "publication_performed": False,
                }
            ),
            encoding="utf-8",
        )
        return project

    @staticmethod
    def _write_csv(path, rows, fields):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


class TransparentClassificationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_transparent_classification_review_v3_4_3_8_0_7.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_reasoning_is_visible(self) -> None:
        self.assertIn(
            "Why the system classified it this way",
            self.text,
        )
        self.assertIn("Programme or call distinction", self.text)

    def test_admin_can_correct_record_type(self) -> None:
        self.assertIn("Correct record type", self.text)
        self.assertIn("Parent programme", self.text)
        self.assertIn("Admin reason", self.text)

    def test_preview_and_governed_write_modes_exist(self) -> None:
        self.assertIn("Preview only", self.text)
        self.assertIn("Governed database write", self.text)
        self.assertIn("WRITE CLASSIFICATION", self.text)

    def test_write_is_never_publication(self) -> None:
        self.assertIn("does not publish records", self.text)
        self.assertIn("Publication action", self.text)
        self.assertIn("public visibility", self.text.casefold())


if __name__ == "__main__":
    unittest.main()
