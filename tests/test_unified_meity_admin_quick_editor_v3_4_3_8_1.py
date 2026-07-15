from __future__ import annotations

import ast
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from services.admin_quick_editor_v3_4_3_8_1 import (
    AUDIT_TABLE,
    EDIT_TABLE,
    AdminQuickEditorService,
    QuickEditorPaths,
)
from services.meity_unified_workflow_v3_4_3_8_1 import (
    PROJECTION_AUDIT_TABLE,
    PROJECTION_TABLE,
    MeitYUnifiedWorkflowService,
    UnifiedMeitYPaths,
)
from ssip_dashboard.meity_public_integrated_v3_4_3_8_1 import (
    partition_published_meity,
)


@dataclass
class Record:
    master_id: str
    scheme_name: str
    source: str
    ministry: str
    department: str
    implementing_agency: str
    record_kind: str
    application_status: str
    application_url: str
    publication_status: str
    is_public: int


class PublicMeitYIntegrationTests(unittest.TestCase):
    def test_public_partition_uses_only_published_meity(self) -> None:
        records = [
            Record(
                "p1",
                "Permanent Programme",
                "MeitY Startup Hub",
                "MeitY",
                "",
                "MeitY Startup Hub",
                "PROGRAMME",
                "NOT_APPLICABLE",
                "https://unsafe.example/apply",
                "PUBLISHED",
                1,
            ),
            Record(
                "c1",
                "Open Challenge",
                "MeitY Startup Hub",
                "MeitY",
                "",
                "MeitY Startup Hub",
                "CHALLENGE",
                "OPEN",
                "https://msh.meity.gov.in/apply",
                "PUBLISHED",
                1,
            ),
            Record(
                "c2",
                "Unverified Call",
                "MeitY Startup Hub",
                "MeitY",
                "",
                "MeitY Startup Hub",
                "APPLICATION_CALL",
                "VERIFICATION_REQUIRED",
                "https://msh.meity.gov.in/apply",
                "PUBLISHED",
                1,
            ),
            Record(
                "x1",
                "Unpublished",
                "MeitY Startup Hub",
                "MeitY",
                "",
                "MeitY Startup Hub",
                "PROGRAMME",
                "OPEN",
                "",
                "STAGED",
                0,
            ),
        ]
        parts = partition_published_meity(records)
        self.assertEqual(
            [row.scheme_name for row in parts["programmes"]],
            ["Permanent Programme"],
        )
        self.assertEqual(parts["programmes"][0].application_url, "")
        self.assertEqual(
            [row.scheme_name for row in parts["calls"]],
            ["Open Challenge"],
        )
        self.assertNotIn(
            "Unverified Call",
            [row.scheme_name for row in parts["calls"]],
        )


class QuickEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package_root = Path(__file__).resolve().parents[1]
        self.config = json.loads(
            (
                self.package_root
                / "config/admin_quick_editor_v3_4_3_8_1.json"
            ).read_text(encoding="utf-8")
        )

    def test_preview_requires_one_category_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            with self.assertRaisesRegex(
                ValueError,
                "exactly one category",
            ):
                service.preview(
                    master_id="m1",
                    source_table="admin_review_queue",
                    selected_categories=["SCHEME", "PROGRAMME"],
                    selected_statuses=["OPEN"],
                    funding_minimum=1,
                    funding_maximum=2,
                    editor="Admin",
                    note="",
                )
            with self.assertRaisesRegex(
                ValueError,
                "exactly one status",
            ):
                service.preview(
                    master_id="m1",
                    source_table="admin_review_queue",
                    selected_categories=["PROGRAMME"],
                    selected_statuses=["OPEN", "CLOSED"],
                    funding_minimum=1,
                    funding_maximum=2,
                    editor="Admin",
                    note="",
                )

    def test_funding_order_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            with self.assertRaisesRegex(
                ValueError,
                "minimum cannot be greater",
            ):
                service.preview(
                    master_id="m1",
                    source_table="admin_review_queue",
                    selected_categories=["PROGRAMME"],
                    selected_statuses=["OPEN"],
                    funding_minimum=100,
                    funding_maximum=10,
                    editor="Admin",
                    note="",
                )

    def test_non_public_approved_record_updates_queue_and_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            preview = service.preview(
                master_id="m1",
                source_table="admin_review_queue",
                selected_categories=["PROGRAMME"],
                selected_statuses=["CLOSED"],
                funding_minimum=1000,
                funding_maximum=5000,
                editor="Admin",
                note="Official page verified.",
            )
            result = service.apply(
                preview,
                confirmation="SAVE QUICK EDIT",
            )
            self.assertEqual(result["write_result"], "STAGING_UPDATED")
            self.assertTrue(Path(result["backup_path"]).exists())
            self.assertFalse(result["public_visibility_changed"])

            connection = sqlite3.connect(database)
            try:
                queue = connection.execute(
                    """
                    SELECT record_kind,programme_status,
                           application_status
                    FROM admin_review_queue
                    WHERE master_id='m1'
                    """
                ).fetchone()
                staged = connection.execute(
                    """
                    SELECT record_kind,programme_status,
                           funding_minimum,funding_maximum
                    FROM scheme_staging
                    WHERE master_id='m1'
                    """
                ).fetchone()
                self.assertEqual(queue, ("PROGRAMME", "CLOSED", "NOT_APPLICABLE"))
                self.assertEqual(staged, ("PROGRAMME", "CLOSED", 1000, 5000))
                self.assertEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {EDIT_TABLE}"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {AUDIT_TABLE}"
                    ).fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_published_record_becomes_pending_publication_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(
                Path(temporary),
                published=True,
            )
            database = project / "database/ssip_staging_v1.db"
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            connection = sqlite3.connect(database)
            try:
                before = connection.execute(
                    """
                    SELECT programme_status,funding_maximum
                    FROM scheme_staging WHERE master_id='m1'
                    """
                ).fetchone()
            finally:
                connection.close()
            preview = service.preview(
                master_id="m1",
                source_table="admin_review_queue",
                selected_categories=["PROGRAMME"],
                selected_statuses=["CLOSED"],
                funding_minimum=1000,
                funding_maximum=5000,
                editor="Admin",
                note="Requires republication.",
            )
            result = service.apply(
                preview,
                confirmation="SAVE QUICK EDIT",
            )
            connection = sqlite3.connect(database)
            try:
                after = connection.execute(
                    """
                    SELECT programme_status,funding_maximum
                    FROM scheme_staging WHERE master_id='m1'
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                result["write_result"],
                "PENDING_PUBLICATION_REVIEW",
            )
            self.assertEqual(before, after)

    def _fixture_project(
        self,
        project: Path,
        published: bool = False,
    ) -> Path:
        (project / "database").mkdir(parents=True)
        (project / "config").mkdir()
        (
            project / "config/admin_quick_editor_v3_4_3_8_1.json"
        ).write_text(
            json.dumps(self.config),
            encoding="utf-8",
        )
        database = project / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,
                source TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                review_status TEXT,
                validated_record_json TEXT,
                record_hash TEXT,
                updated_at TEXT
            );
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,
                source TEXT,
                ministry TEXT,
                department TEXT,
                implementing_agency TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                scheme_status TEXT,
                funding_minimum REAL,
                funding_maximum REAL,
                currency TEXT,
                publication_status TEXT,
                is_public INTEGER,
                raw_record_json TEXT,
                record_hash TEXT,
                last_loaded_at TEXT
            );
            """
        )
        record = {
            "master_id": "m1",
            "scheme_name": "Test Programme",
            "source": "MeitY Startup Hub",
            "ministry": "MeitY",
            "department": "",
            "record_kind": "PROGRAMME",
            "programme_status": "OPEN",
            "application_status": "NOT_APPLICABLE",
            "scheme_status": "OPEN",
            "funding_amount": {
                "minimum": None,
                "maximum": None,
                "currency": "INR",
            },
        }
        raw = json.dumps(record)
        connection.execute(
            """
            INSERT INTO admin_review_queue VALUES (
                'm1','Test Programme','MeitY Startup Hub',
                'PROGRAMME','OPEN','NOT_APPLICABLE',
                'APPROVED',?,?,?
            )
            """,
            (raw, "hash", "now"),
        )
        connection.execute(
            """
            INSERT INTO scheme_staging VALUES (
                'm1','Test Programme','MeitY Startup Hub',
                'MeitY','','MeitY Startup Hub',
                'PROGRAMME','OPEN','NOT_APPLICABLE','OPEN',
                NULL,NULL,'INR',?,?,?,?,'now'
            )
            """,
            (
                "PUBLISHED" if published else "STAGED",
                1 if published else 0,
                raw,
                "hash",
            ),
        )
        connection.commit()
        connection.close()
        return project


class UnifiedMeitYWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        package_root = Path(__file__).resolve().parents[1]
        self.config = json.loads(
            (
                package_root
                / "config/meity_unified_workflow_v3_4_3_8_1.json"
            ).read_text(encoding="utf-8")
        )

    def test_effective_inventory_applies_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = MeitYUnifiedWorkflowService(
                UnifiedMeitYPaths.defaults(project),
                self.config,
            )
            rows = service.effective_inventory()
            programme = next(
                row for row in rows if row["child_id"] == "child_programme"
            )
            challenge = next(
                row for row in rows if row["child_id"] == "child_challenge"
            )
            self.assertEqual(
                programme["effective_entity_type"],
                "PERMANENT_PROGRAMME",
            )
            self.assertTrue(programme["override_applied"])
            self.assertEqual(
                challenge["dashboard_section"],
                "CALLS_CHALLENGES",
            )
            self.assertFalse(challenge["projection_eligible"])
            self.assertIn(
                "CALL_PARENT_PROGRAMME_REQUIRED",
                challenge["projection_errors"],
            )
            self.assertFalse(challenge["apply_action_allowed"])

    def test_projection_imports_pending_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            service = MeitYUnifiedWorkflowService(
                UnifiedMeitYPaths.defaults(project),
                self.config,
            )
            plan = service.projection_plan()
            result = service.apply_projection(
                expected_signature=plan["plan_signature"],
                confirmation="PROJECT TO ADMIN REVIEW",
                actor="Admin",
            )
            self.assertGreaterEqual(result["inserted_pending"], 1)
            self.assertEqual(result["publication_action"], "NONE")
            self.assertFalse(result["public_visibility_changed"])
            self.assertTrue(Path(result["backup_path"]).exists())

            connection = sqlite3.connect(database)
            try:
                statuses = {
                    row[0]
                    for row in connection.execute(
                        "SELECT review_status FROM admin_review_queue"
                    )
                }
                self.assertEqual(statuses, {"PENDING"})
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM scheme_staging"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {PROJECTION_TABLE}"
                    ).fetchone()[0],
                    len(plan["rows"]),
                )
                self.assertGreaterEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {PROJECTION_AUDIT_TABLE}"
                    ).fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_projection_protects_existing_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            service = MeitYUnifiedWorkflowService(
                UnifiedMeitYPaths.defaults(project),
                self.config,
            )
            plan = service.projection_plan()
            target = plan["rows"][0]["master_id"]
            connection = sqlite3.connect(database)
            connection.execute(
                """
                INSERT INTO admin_review_queue(
                    master_id,scheme_name,source,record_kind,
                    programme_status,application_status,
                    official_page_url,application_url,decision,
                    validation_score,review_status,priority,
                    decision_reasons_json,warnings_json,
                    critical_flags_json,recommended_actions_json,
                    validated_record_json,record_hash,
                    first_queued_at,updated_at,last_import_run_id
                ) VALUES (
                    ?,'Protected','MeitY','PROGRAMME',
                    'SCHEME_INFORMATION_AVAILABLE','NOT_APPLICABLE',
                    'https://msh.meity.gov.in/protected','',
                    'APPROVED_FOR_DATABASE',1.0,'APPROVED','NORMAL',
                    '[]','[]','[]','[]','{}','hash','now','now','run'
                )
                """,
                (target,),
            )
            connection.commit()
            connection.close()

            result = service.apply_projection(
                expected_signature=plan["plan_signature"],
                confirmation="PROJECT TO ADMIN REVIEW",
                actor="Admin",
            )
            self.assertGreaterEqual(
                result["skipped_existing_decisions"],
                1,
            )

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_4"
        source.mkdir(parents=True)
        (project / "database").mkdir()
        (project / "config").mkdir()
        (
            project / "config/meity_unified_workflow_v3_4_3_8_1.json"
        ).write_text(
            json.dumps(self.config),
            encoding="utf-8",
        )

        children = [
            {
                "bundle_id": "bundle_programme",
                "child_id": "child_programme",
                "canonical_name": "CREST Accelerator",
                "entity_type": "ACCELERATOR_PROGRAMME",
                "verified_information_url": (
                    "https://msh.meity.gov.in/crest"
                ),
                "verified_application_url": "",
                "temporal_validation": "NOT_APPLICABLE",
                "safe_application_status": (
                    "SCHEME_INFORMATION_AVAILABLE"
                ),
                "link_integrity_complete": "True",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
            {
                "bundle_id": "bundle_history",
                "child_id": "child_history",
                "canonical_name": "Appscale 2023",
                "entity_type": "HISTORICAL_REFERENCE",
                "verified_information_url": (
                    "https://msh.meity.gov.in/appscale-2023"
                ),
                "verified_application_url": "",
                "temporal_validation": (
                    "HISTORICAL_BY_TITLE_OR_DEADLINE"
                ),
                "safe_application_status": "CLOSED",
                "link_integrity_complete": "True",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
            {
                "bundle_id": "bundle_challenge",
                "child_id": "child_challenge",
                "canonical_name": "Agrienics Challenge",
                "entity_type": "CHALLENGE_CALL",
                "verified_information_url": (
                    "https://msh.meity.gov.in/agrienics"
                ),
                "verified_application_url": "",
                "temporal_validation": "CURRENT_STATUS_NOT_PROVEN",
                "safe_application_status": "VERIFICATION_REQUIRED",
                "link_integrity_complete": "True",
                "repaired_parent_scheme_name": "",
                "repaired_parent_master_id": "",
            },
        ]
        child_fields = sorted(
            {key for row in children for key in row}
        )
        self._write_csv(
            source
            / "meity_link_safe_decision_children_v3_4_3_8_0_4.csv",
            children,
            child_fields,
        )
        bundles = [
            {
                "bundle_id": "bundle_programme",
                "bundle_title": "Programme — CREST",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_history",
                "bundle_title": "Historical — Appscale",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "True",
            },
            {
                "bundle_id": "bundle_challenge",
                "bundle_title": "Challenge — Agrienics",
                "link_integrity_complete": "True",
                "current_application_integrity_complete": "False",
            },
        ]
        bundle_fields = sorted(
            {key for row in bundles for key in row}
        )
        self._write_csv(
            source
            / "meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv",
            bundles,
            bundle_fields,
        )

        database = project / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,source TEXT,record_kind TEXT,
                programme_status TEXT,application_status TEXT,
                official_page_url TEXT,application_url TEXT,
                decision TEXT,validation_score REAL,
                review_status TEXT,priority TEXT,
                decision_reasons_json TEXT,warnings_json TEXT,
                critical_flags_json TEXT,
                recommended_actions_json TEXT,
                validated_record_json TEXT,record_hash TEXT,
                first_queued_at TEXT,updated_at TEXT,
                last_import_run_id TEXT
            );
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY
            );
            CREATE TABLE import_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT,completed_at TEXT,status TEXT,
                approved_input_count INTEGER,
                review_input_count INTEGER,
                rejected_input_count INTEGER,
                summary_json TEXT
            );
            CREATE TABLE
            meity_entity_classification_overrides_v3_4_3_8_0_7 (
                action_id TEXT PRIMARY KEY,bundle_id TEXT,
                child_id TEXT,canonical_name TEXT,
                original_entity_type TEXT,
                corrected_entity_type TEXT,
                corrected_record_kind TEXT,
                original_parent_scheme_name TEXT,
                corrected_parent_scheme_name TEXT,
                original_parent_master_id TEXT,
                corrected_parent_master_id TEXT,
                correction_reason TEXT,admin_note TEXT,
                actor TEXT,source_link_integrity_signature TEXT,
                source_manifest_signature TEXT,created_at TEXT,
                supersedes_action_id TEXT,is_active INTEGER,
                publication_action TEXT,status TEXT
            );
            """
        )
        connection.execute(
            """
            INSERT INTO
            meity_entity_classification_overrides_v3_4_3_8_0_7 (
                action_id,bundle_id,child_id,canonical_name,
                original_entity_type,corrected_entity_type,
                corrected_record_kind,actor,created_at,
                is_active,publication_action,status
            ) VALUES (
                'override1','bundle_programme','child_programme',
                'CREST Accelerator','ACCELERATOR_PROGRAMME',
                'PERMANENT_PROGRAMME','SCHEME_PROGRAMME',
                'Admin','now',1,'NONE','ACTIVE_OVERRIDE'
            )
            """
        )
        connection.commit()
        connection.close()
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


class IntegrationSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_admin_component_has_quick_editor_checkboxes(self) -> None:
        text = (
            self.root
            / "ui/components/admin_quick_editor_v3_4_3_8_1.py"
        ).read_text(encoding="utf-8")
        ast.parse(text)
        self.assertIn("Select exactly one category checkbox", text)
        self.assertIn("Minimum fund value (INR)", text)
        self.assertIn("Maximum fund value (INR)", text)
        self.assertIn("Save governed quick edit", text)

    def test_meity_admin_is_embedded_with_tabs(self) -> None:
        text = (
            self.root
            / "ui/components/meity_admin_intelligence_v3_4_3_8_1.py"
        ).read_text(encoding="utf-8")
        ast.parse(text)
        for marker in (
            "Overview",
            "Classification & Type Correction",
            "Links, Dates & Parent",
            "Dashboard & Projection",
            "Audit",
        ):
            self.assertIn(marker, text)
        self.assertIn("PROJECT TO ADMIN REVIEW", text)

    def test_navigation_contains_both_new_workspaces(self) -> None:
        text = (
            self.root
            / "services/admin_workflow_navigation_v3_4_3_8_1.py"
        ).read_text(encoding="utf-8")
        self.assertIn("3. Quick Editor", text)
        self.assertIn("4. MeitY Intelligence Review", text)

    def test_patcher_integrates_existing_apps(self) -> None:
        text = (
            self.root
            / "scripts/apply_unified_meity_admin_public_v3_4_3_8_1.py"
        ).read_text(encoding="utf-8")
        ast.parse(text)
        self.assertIn('workspace == "Quick Editor"', text)
        self.assertIn(
            'workspace == "MeitY Intelligence Review"',
            text,
        )
        self.assertIn(
            "return render_integrated_meity_public_page",
            text,
        )


if __name__ == "__main__":
    unittest.main()
