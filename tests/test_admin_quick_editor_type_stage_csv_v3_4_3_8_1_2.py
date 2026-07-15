from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.admin_quick_editor_v3_4_3_8_1 import (
    AdminQuickEditorService,
    QuickEditorPaths,
)


class QuickEditorTypeStageCsvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.config = json.loads(
            (
                cls.root
                / "config/admin_quick_editor_v3_4_3_8_1.json"
            ).read_text(encoding="utf-8")
        )

    def test_config_has_requested_type_and_stage_values(self) -> None:
        self.assertEqual(
            self.config["applicant_types"],
            ["INDIVIDUAL", "STARTUP"],
        )
        self.assertEqual(
            self.config["startup_stages"],
            ["IDEATION", "VALIDATION", "SCALING", "EARLY_TRACTION"],
        )

    def test_preview_stores_selected_type_and_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            preview = service.preview(
                master_id="m1",
                source_table="admin_review_queue",
                selected_categories=["PROGRAMME"],
                selected_statuses=["OPEN"],
                selected_applicant_types=["STARTUP"],
                selected_startup_stages=["IDEATION", "EARLY_TRACTION"],
                funding_minimum=None,
                funding_maximum=5000000,
                editor="Admin",
                note="Verified for startups at two stages.",
            )
            self.assertEqual(preview["applicant_types"], ["STARTUP"])
            self.assertEqual(
                preview["startup_stages"],
                ["IDEATION", "EARLY_TRACTION"],
            )
            result = service.apply(
                preview,
                confirmation="SAVE QUICK EDIT",
            )
            self.assertEqual(result["publication_action"], "NONE")

            connection = sqlite3.connect(
                project / "database/ssip_staging_v1.db"
            )
            try:
                raw = connection.execute(
                    "SELECT validated_record_json FROM admin_review_queue WHERE master_id='m1'"
                ).fetchone()[0]
                record = json.loads(raw)
                self.assertEqual(record["applicant_types"], ["STARTUP"])
                self.assertEqual(
                    record["startup_stages"],
                    ["IDEATION", "EARLY_TRACTION"],
                )
            finally:
                connection.close()

    def test_all_type_and_all_stage_mean_every_option(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            preview = service.preview(
                master_id="m1",
                source_table="admin_review_queue",
                selected_categories=["PROGRAMME"],
                selected_statuses=["OPEN"],
                selected_applicant_types=self.config["applicant_types"],
                selected_startup_stages=self.config["startup_stages"],
                editor="Admin",
                note="All types and stages.",
            )
            self.assertEqual(
                preview["after"]["applicant_type_scope"],
                "ALL",
            )
            self.assertEqual(
                preview["after"]["startup_stage_scope"],
                "ALL",
            )

    def test_empty_type_or_stage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            with self.assertRaisesRegex(ValueError, "under Type"):
                service.preview(
                    master_id="m1",
                    source_table="admin_review_queue",
                    selected_categories=["PROGRAMME"],
                    selected_statuses=["OPEN"],
                    selected_applicant_types=[],
                    selected_startup_stages=["IDEATION"],
                    editor="Admin",
                    note="",
                )
            with self.assertRaisesRegex(ValueError, "startup stage"):
                service.preview(
                    master_id="m1",
                    source_table="admin_review_queue",
                    selected_categories=["PROGRAMME"],
                    selected_statuses=["OPEN"],
                    selected_applicant_types=["STARTUP"],
                    selected_startup_stages=[],
                    editor="Admin",
                    note="",
                )

    def test_filtered_csv_contains_requested_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            service = AdminQuickEditorService(
                QuickEditorPaths.defaults(project),
                self.config,
            )
            data = service.export_csv(service.list_records())
            text = data.decode("utf-8-sig")
            rows = list(csv.DictReader(text.splitlines()))
            self.assertEqual(len(rows), 1)
            self.assertIn("applicant_types", rows[0])
            self.assertIn("startup_stages", rows[0])
            self.assertEqual(rows[0]["scheme_name"], "Test Programme")

    def test_ui_has_type_stage_and_csv_controls(self) -> None:
        text = (
            self.root
            / "ui/components/admin_quick_editor_v3_4_3_8_1.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Download filtered CSV", text)
        self.assertIn('title="TYPE"', text)
        self.assertIn('title="STAGE"', text)
        self.assertIn("Individual", json.dumps(self.config))
        self.assertIn("Early Traction", json.dumps(self.config))

    def _fixture_project(self, project: Path) -> Path:
        (project / "database").mkdir(parents=True)
        (project / "config").mkdir()
        (
            project / "config/admin_quick_editor_v3_4_3_8_1.json"
        ).write_text(json.dumps(self.config), encoding="utf-8")
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
            "applicant_types": ["INDIVIDUAL", "STARTUP"],
            "startup_stages": [
                "IDEATION",
                "VALIDATION",
                "SCALING",
                "EARLY_TRACTION",
            ],
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
                'PENDING',?,?,?
            )
            """,
            (raw, "hash", "now"),
        )
        connection.commit()
        connection.close()
        return project


if __name__ == "__main__":
    unittest.main()
