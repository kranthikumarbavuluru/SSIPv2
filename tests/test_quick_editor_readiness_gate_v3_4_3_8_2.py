from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.admin_quick_editor_v3_4_3_8_1 import (
    AUDIT_TABLE,
    AdminQuickEditorService,
    QuickEditorPaths,
    completeness,
)


class QuickEditorReadinessGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.config = json.loads(
            (cls.root / "config/admin_quick_editor_v3_4_3_8_1.json").read_text(encoding="utf-8")
        )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = self._fixture(Path(self.temporary.name))
        self.service = AdminQuickEditorService(QuickEditorPaths.defaults(self.project), self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_only_three_representative_records_are_loaded(self) -> None:
        rows = self.service.list_records()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["master_id"] for row in rows}, {"nonpublic", "call", "published"})
        published = next(row for row in rows if row["master_id"] == "published")
        self.assertEqual(published["publication_status"], "PUBLISHED")
        self.assertEqual(published["is_public"], 1)

    def test_non_public_updates_staging_and_creates_audit(self) -> None:
        preview = self._preview("nonpublic", "PROGRAMME", "OPEN")
        result = self.service.apply(preview, confirmation="SAVE QUICK EDIT")
        self.assertEqual(result["write_result"], "STAGING_UPDATED")
        connection = sqlite3.connect(self.project / "database/ssip_staging_v1.db")
        try:
            row = connection.execute(
                "SELECT funding_maximum,is_public,publication_status FROM scheme_staging WHERE master_id='nonpublic'"
            ).fetchone()
            self.assertEqual(row, (5000000.0, 0, "STAGED"))
            self.assertEqual(connection.execute(f"SELECT count(*) FROM {AUDIT_TABLE}").fetchone()[0], 1)
        finally:
            connection.close()

    def test_published_record_is_unchanged_and_pending_publication_review(self) -> None:
        database = self.project / "database/ssip_staging_v1.db"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        connection = sqlite3.connect(database)
        original = connection.execute(
            "SELECT raw_record_json,funding_maximum,record_hash FROM scheme_staging WHERE master_id='published'"
        ).fetchone()
        connection.close()
        result = self.service.apply(self._preview("published", "SCHEME", "OPEN"), confirmation="SAVE QUICK EDIT")
        self.assertEqual(result["write_result"], "PENDING_PUBLICATION_REVIEW")
        connection = sqlite3.connect(database)
        try:
            current = connection.execute(
                "SELECT raw_record_json,funding_maximum,record_hash FROM scheme_staging WHERE master_id='published'"
            ).fetchone()
            self.assertEqual(current, original)
            pending = connection.execute(
                "SELECT write_result,publication_action FROM admin_quick_edit_requests_v3_4_3_8_1 WHERE master_id='published'"
            ).fetchone()
            self.assertEqual(pending, ("PENDING_PUBLICATION_REVIEW", "NONE"))
        finally:
            connection.close()
        self.assertNotEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())

    def test_call_accepts_governed_call_status_and_requires_parent(self) -> None:
        preview = self._preview("call", "CHALLENGE", "VERIFICATION_REQUIRED")
        result = self.service.apply(preview, confirmation="SAVE QUICK EDIT")
        self.assertIn(result["write_result"], {"REVIEW_QUEUE_UPDATED", "STAGING_UPDATED"})
        row = next(row for row in self.service.list_records() if row["master_id"] == "call")
        self.assertEqual(row["application_status"], "VERIFICATION_REQUIRED")
        self.assertEqual(row["readiness_status"], "NEEDS_PARENT_PROGRAMME")

    def test_completeness_dashboard_and_public_preview_fail_closed(self) -> None:
        rows = self.service.list_records()
        counters = self.service.completeness_dashboard(rows)
        self.assertEqual(counters["total_records"], 3)
        self.assertEqual(counters["parent_programme_missing"], 1)
        ready = completeness(next(row for row in rows if row["master_id"] == "published"))
        self.assertTrue(ready["ready_for_publication_review"])
        call = next(row for row in rows if row["master_id"] == "call")
        projected = self.service.public_dashboard_preview(call)
        self.assertTrue(projected["preview_only"])
        self.assertFalse(projected["apply_button_eligible"])
        self.assertEqual(projected["publication_action"], "NONE")

    def test_unspecified_type_stage_and_funding_are_non_blocking(self) -> None:
        record = self._record(
            "optional-blanks",
            "Officially Verified Scheme",
            "SCHEME",
            "CLOSED",
            approved=True,
        )
        record["applicant_types"] = []
        record["startup_stages"] = []
        record["funding_minimum"] = None
        record["funding_maximum"] = None
        record["funding_reviewed"] = False

        assessment = completeness(record)

        self.assertTrue(assessment["type_missing"])
        self.assertTrue(assessment["stage_missing"])
        self.assertTrue(assessment["funding_missing"])
        self.assertTrue(assessment["ready_for_publication_review"])
        self.assertEqual(assessment["blockers"], [])

    def test_csv_rejects_immutable_change(self) -> None:
        exported = self.service.export_csv(self.service.list_records())
        rows = list(csv.DictReader(io.StringIO(exported.decode("utf-8-sig"))))
        rows[0]["scheme_name"] = "Renamed illegally"
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        result = self.service.preview_csv_import(output.getvalue().encode("utf-8-sig"))
        self.assertFalse(result["valid"])
        self.assertTrue(any("immutable field changed" in error for error in result["errors"]))

    def _preview(self, master_id: str, category: str, status: str):
        row = next(row for row in self.service.list_records() if row["master_id"] == master_id)
        return self.service.preview(
            master_id=master_id,
            source_table=row["source_table"],
            selected_categories=[category],
            selected_statuses=[status],
            selected_applicant_types=["STARTUP"],
            selected_startup_stages=["IDEATION", "VALIDATION"],
            funding_minimum=100000,
            funding_maximum=5000000,
            editor="Three-record test",
            note="SSIP v3.4.3.8.2 governed representative test.",
        )

    def _fixture(self, project: Path) -> Path:
        (project / "database").mkdir(parents=True)
        (project / "config").mkdir()
        (project / "config/admin_quick_editor_v3_4_3_8_1.json").write_text(json.dumps(self.config), encoding="utf-8")
        connection = sqlite3.connect(project / "database/ssip_staging_v1.db")
        connection.executescript(
            """
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY, scheme_name TEXT, source TEXT, record_kind TEXT,
                programme_status TEXT, application_status TEXT, review_status TEXT,
                validated_record_json TEXT, record_hash TEXT, updated_at TEXT
            );
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY, scheme_name TEXT, source TEXT, ministry TEXT,
                department TEXT, implementing_agency TEXT, record_kind TEXT,
                programme_status TEXT, application_status TEXT, scheme_status TEXT,
                funding_minimum REAL, funding_maximum REAL, currency TEXT,
                publication_status TEXT, is_public INTEGER, raw_record_json TEXT,
                record_hash TEXT, last_loaded_at TEXT
            );
            """
        )
        records = [
            self._record("nonpublic", "Non-public Programme", "PROGRAMME", "OPEN", approved=False),
            self._record("call", "Representative Challenge", "CHALLENGE", "VERIFICATION_REQUIRED", approved=True),
            self._record("published", "Already Published Scheme", "SCHEME", "OPEN", approved=True),
        ]
        for record in records:
            raw = json.dumps(record, sort_keys=True)
            connection.execute(
                "INSERT INTO admin_review_queue VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record["master_id"], record["scheme_name"], "MeitY", record["record_kind"], record["programme_status"], record["application_status"], record["review_status"], raw, "queue-hash", "now"),
            )
            if record["master_id"] != "call":
                published = record["master_id"] == "published"
                connection.execute(
                    "INSERT INTO scheme_staging VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (record["master_id"], record["scheme_name"], "MeitY", "MeitY", "MeitY Startup Hub", "MeitY", record["record_kind"], record["programme_status"], record["application_status"], record["scheme_status"], None, None, "INR", "PUBLISHED" if published else "STAGED", 1 if published else 0, raw, "live-hash", "before"),
                )
        connection.commit()
        connection.close()
        return project

    @staticmethod
    def _record(master_id: str, name: str, kind: str, status: str, *, approved: bool) -> dict:
        return {
            "master_id": master_id,
            "scheme_name": name,
            "record_kind": kind,
            "admin_category": kind,
            "programme_status": status if kind in {"SCHEME", "PROGRAMME"} else "NOT_APPLICABLE",
            "application_status": status if kind not in {"SCHEME", "PROGRAMME"} else "NOT_APPLICABLE",
            "scheme_status": status if kind in {"SCHEME", "PROGRAMME"} else "",
            "review_status": "APPROVED" if approved else "PENDING",
            "admin_approval_complete": approved,
            "applicant_types": ["STARTUP"],
            "startup_stages": ["IDEATION"],
            "funding_reviewed": True,
            "official_page_url": "https://msh.meity.gov.in/schemes/example",
            "deadline_verified": kind == "CHALLENGE",
            "application_url": "",
            "critical_flags": [],
        }


if __name__ == "__main__":
    unittest.main()
