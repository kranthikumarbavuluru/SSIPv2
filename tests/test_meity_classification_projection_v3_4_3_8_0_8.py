from __future__ import annotations

import ast
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_classification_projection_v3_4_3_8_0_8 import (
    ClassificationProjectionService,
    ProjectionPaths,
    build_service,
    load_config,
)


class MeitYClassificationProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_classification_projection_v3_4_3_8_0_8.json"
        )

    def test_preview_applies_active_override_and_partitions_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            rows = service.effective_inventory()

            crest = next(
                row for row in rows
                if row["child_id"] == "child_crest"
            )
            challenge = next(
                row for row in rows
                if row["child_id"] == "child_challenge"
            )
            historical = next(
                row for row in rows
                if row["child_id"] == "child_history"
            )

            self.assertTrue(crest["override_applied"])
            self.assertEqual(
                crest["effective_entity_type"],
                "PERMANENT_PROGRAMME",
            )
            self.assertEqual(
                crest["dashboard_section"],
                "PROGRAMMES",
            )
            self.assertEqual(
                challenge["dashboard_section"],
                "CALLS_CHALLENGES",
            )
            self.assertEqual(
                historical["dashboard_section"],
                "HISTORICAL",
            )
            self.assertFalse(crest["public_visibility"])
            self.assertFalse(challenge["apply_action_allowed"])

    def test_call_without_parent_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            challenge = next(
                row for row in service.effective_inventory()
                if row["child_id"] == "child_challenge"
            )
            self.assertFalse(challenge["projection_eligible"])
            self.assertIn(
                "CALL_PARENT_PROGRAMME_REQUIRED",
                challenge["projection_errors"],
            )

    def test_historical_record_cannot_keep_application_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            source = (
                project
                / "data/departments/meity/v3_4_3_8_0_4/"
                "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
            )
            rows = self._read_csv(source)
            for row in rows:
                if row["child_id"] == "child_history":
                    row["verified_application_url"] = (
                        "https://msh.meity.gov.in/apply/history"
                    )
            self._write_csv(source, rows, list(rows[0]))

            service = build_service(project)
            history = next(
                row for row in service.effective_inventory()
                if row["child_id"] == "child_history"
            )
            self.assertFalse(history["projection_eligible"])
            self.assertIn(
                "HISTORICAL_APPLICATION_ROUTE_NOT_ALLOWED",
                history["projection_errors"],
            )

    def test_preview_generation_never_writes_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            service = build_service(project)
            summary = service.build_preview()

            after = hashlib.sha256(database.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(summary["override_count"], 1)
            self.assertEqual(summary["type_correction_count"], 1)
            self.assertFalse(summary["database_write_performed"])
            self.assertFalse(summary["publication_performed"])
            self.assertFalse(summary["public_visibility_changed"])
            self.assertEqual(summary["apply_action_allowed_count"], 0)

    def test_projection_requires_exact_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            summary = service.build_preview()
            with self.assertRaises(PermissionError):
                service.apply_projection(
                    expected_signature=summary["projection_signature"],
                    confirmation="PROJECT",
                    actor="Admin",
                )

    def test_projection_rejects_changed_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            service.build_preview()
            with self.assertRaisesRegex(
                RuntimeError,
                "plan changed after review",
            ):
                service.apply_projection(
                    expected_signature="stale",
                    confirmation="PROJECT TO STAGING",
                    actor="Admin",
                )

    def test_projection_write_uses_dedicated_layer_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            summary = service.build_preview()

            result = service.apply_projection(
                expected_signature=summary["projection_signature"],
                confirmation="PROJECT TO STAGING",
                actor="Projection Admin",
            )

            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertTrue(result["core_table_counts_preserved"])
            self.assertFalse(result["public_visibility_changed"])
            self.assertFalse(result["scheme_staging_modified"])
            self.assertFalse(result["admin_review_queue_modified"])
            self.assertFalse(result["public_schemes_modified"])
            self.assertEqual(result["publication_action"], "NONE")

            connection = sqlite3.connect(
                project / "database/ssip_staging_v1.db"
            )
            try:
                projection_table = service.config["projection_table"]
                audit_table = service.config[
                    "projection_audit_table"
                ]
                active_count = connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {projection_table}
                    WHERE is_active = 1
                    """
                ).fetchone()[0]
                self.assertGreaterEqual(active_count, 1)
                audit_count = connection.execute(
                    f"SELECT COUNT(*) FROM {audit_table}"
                ).fetchone()[0]
                self.assertGreaterEqual(audit_count, 1)
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

    def test_repeated_identical_projection_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = build_service(project)
            summary = service.build_preview()
            first = service.apply_projection(
                expected_signature=summary["projection_signature"],
                confirmation="PROJECT TO STAGING",
                actor="Admin",
            )
            second = service.apply_projection(
                expected_signature=summary["projection_signature"],
                confirmation="PROJECT TO STAGING",
                actor="Admin",
            )
            self.assertGreaterEqual(first["written_projection_rows"], 1)
            self.assertEqual(second["written_projection_rows"], 0)

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_4"
        source.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project
            / "config/meity_classification_projection_v3_4_3_8_0_8.json"
        ).write_text(
            self.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        database = project / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(database)
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
        connection.execute(
            """
            CREATE TABLE
            meity_entity_classification_overrides_v3_4_3_8_0_7 (
                action_id TEXT PRIMARY KEY,
                bundle_id TEXT,
                child_id TEXT,
                canonical_name TEXT,
                original_entity_type TEXT,
                corrected_entity_type TEXT,
                corrected_record_kind TEXT,
                original_parent_scheme_name TEXT,
                corrected_parent_scheme_name TEXT,
                original_parent_master_id TEXT,
                corrected_parent_master_id TEXT,
                correction_reason TEXT,
                admin_note TEXT,
                actor TEXT,
                source_link_integrity_signature TEXT,
                source_manifest_signature TEXT,
                created_at TEXT,
                supersedes_action_id TEXT,
                is_active INTEGER,
                publication_action TEXT,
                status TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO
            meity_entity_classification_overrides_v3_4_3_8_0_7 (
                action_id, bundle_id, child_id, canonical_name,
                original_entity_type, corrected_entity_type,
                corrected_record_kind, original_parent_scheme_name,
                corrected_parent_scheme_name, original_parent_master_id,
                corrected_parent_master_id, correction_reason,
                admin_note, actor, source_link_integrity_signature,
                source_manifest_signature, created_at,
                supersedes_action_id, is_active,
                publication_action, status
            ) VALUES (
                'override_crest','bundle_crest','child_crest',
                'CREST Semiconductor Accelerator',
                'ACCELERATOR_PROGRAMME','PERMANENT_PROGRAMME',
                'SCHEME_PROGRAMME','','','','',
                'ADMIN_TYPE_CONFIRMATION','Confirmed','Admin',
                'link_crest','manifest_sig','2026-07-15T10:00:00+00:00',
                '',1,'NONE','ACTIVE_OVERRIDE'
            )
            """
        )
        connection.commit()
        connection.close()

        child_fields = [
            "bundle_id",
            "child_id",
            "canonical_name",
            "entity_type",
            "record_kind",
            "temporal_validation",
            "safe_application_status",
            "verified_information_url",
            "verified_application_url",
            "repaired_parent_scheme_name",
            "repaired_parent_master_id",
        ]
        children = [
            {
                "bundle_id": "bundle_crest",
                "child_id": "child_crest",
                "canonical_name": "CREST Semiconductor Accelerator",
                "entity_type": "ACCELERATOR_PROGRAMME",
                "record_kind": "SCHEME_PROGRAMME",
                "temporal_validation": "NOT_APPLICABLE",
                "safe_application_status": "SCHEME_INFORMATION_AVAILABLE",
                "verified_information_url": (
                    "https://msh.meity.gov.in/crest"
                ),
                "verified_application_url": "",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
            {
                "bundle_id": "bundle_challenge",
                "child_id": "child_challenge",
                "canonical_name": "Agrienics Grand Challenge",
                "entity_type": "CHALLENGE_CALL",
                "record_kind": "CALL_INSTANCE",
                "temporal_validation": "CURRENT_STATUS_NOT_PROVEN",
                "safe_application_status": "VERIFICATION_REQUIRED",
                "verified_information_url": (
                    "https://msh.meity.gov.in/agrienics"
                ),
                "verified_application_url": "",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
            {
                "bundle_id": "bundle_history",
                "child_id": "child_history",
                "canonical_name": "Google Appscale Academy 2023",
                "entity_type": "HISTORICAL_REFERENCE",
                "record_kind": "HISTORICAL_REFERENCE",
                "temporal_validation": (
                    "HISTORICAL_BY_TITLE_OR_DEADLINE"
                ),
                "safe_application_status": "HISTORICAL_CLOSED",
                "verified_information_url": (
                    "https://msh.meity.gov.in/appscale-2023"
                ),
                "verified_application_url": "",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
            {
                "bundle_id": "bundle_document",
                "child_id": "child_document",
                "canonical_name": "CREST Brochure",
                "entity_type": "SUPPORTING_DOCUMENT",
                "record_kind": "SUPPORTING_DOCUMENT",
                "temporal_validation": "NOT_APPLICABLE",
                "safe_application_status": "SCHEME_INFORMATION_AVAILABLE",
                "verified_information_url": (
                    "https://msh.meity.gov.in/crest-brochure.pdf"
                ),
                "verified_application_url": "",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
        ]
        self._write_csv(
            source
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv",
            children,
            child_fields,
        )

        bundle_fields = [
            "bundle_id",
            "bundle_title",
            "link_integrity_complete",
            "current_application_integrity_complete",
        ]
        bundles = [
            {
                "bundle_id": "bundle_crest",
                "bundle_title": "Programme family — CREST",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_challenge",
                "bundle_title": "Calls/challenges — Agrienics",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "False",
            },
            {
                "bundle_id": "bundle_history",
                "bundle_title": "Historical/status review — Appscale",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_document",
                "bundle_title": "Supporting document — CREST",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "True",
            },
        ]
        self._write_csv(
            source
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv",
            bundles,
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


class MeitYClassificationDashboardPreviewUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_classification_dashboard_preview_v3_4_3_8_0_8.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_dashboard_tabs_show_effective_partitions(self) -> None:
        for marker in (
            "MeitY Programmes",
            "Calls & Challenges",
            "Historical Archive",
            "Excluded & Supporting",
            "Staging Projection Gate",
        ):
            self.assertIn(marker, self.text)

    def test_preview_is_not_presented_as_live_publication(self) -> None:
        self.assertIn("This view is not published", self.text)
        self.assertIn(
            "does not change the live public dashboard",
            self.text,
        )

    def test_projection_confirmation_is_explicit(self) -> None:
        self.assertIn("PROJECT TO STAGING", self.text)
        self.assertIn(
            "Write governed staging projection",
            self.text,
        )
        self.assertIn("disabled=not ready", self.text)

    def test_public_apply_action_is_not_exposed(self) -> None:
        self.assertIn("no public Apply action is enabled", self.text)
        self.assertNotIn(
            '"Apply now"',
            self.text,
        )

    def test_projection_scope_is_explained(self) -> None:
        self.assertIn(
            "It does not update scheme_staging, admin_review_queue or",
            self.text,
        )
        self.assertIn(
            "public_schemes.",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
