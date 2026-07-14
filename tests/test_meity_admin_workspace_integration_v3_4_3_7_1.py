from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from database.staging_loader_v1 import open_database, upsert_review_item
from services.admin_review_service_v1 import AdminReviewService
from services.department_review_intake_v1 import available_intakes, get_intake
from services.meity_admin_bridge_v3_4_3_7_1 import (
    ACTION_INSERT,
    ACTION_SKIP_DECIDED,
    ACTION_SKIP_SEMANTIC,
    ACTION_UPDATE,
    MeitYAdminBridge,
    MeitYBridgePaths,
)


class MeitYAdminWorkspaceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ssip-meity-admin-bridge-"))
        self.database_path = self.temp_dir / "bridge.db"
        connection = open_database(self.database_path, ROOT / "database/schema_staging_v1.sql")
        connection.close()
        self.bridge = MeitYAdminBridge(
            MeitYBridgePaths(
                project_root=ROOT,
                source_queue_path=(
                    ROOT
                    / "data/departments/meity/v3_4_3_7/meity_admin_review_queue_v3_4_3_7.csv"
                ),
                database_path=self.database_path,
                report_dir=self.temp_dir / "reports",
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_registry_exposes_dst_and_meity(self) -> None:
        ids = {
            item.provider_id
            for item in available_intakes(ROOT, self.database_path)
        }
        self.assertIn("dst_pilot_v1", ids)
        self.assertIn("meity_v3_4_3_7", ids)

    def test_get_intake_resolves_meity_provider(self) -> None:
        provider = get_intake("meity_v3_4_3_7", ROOT, self.database_path)
        self.assertIsInstance(provider, MeitYAdminBridge)

    def test_builds_only_sasact_and_genesis(self) -> None:
        items = self.bridge.build_items()
        self.assertEqual(len(items), 2)
        self.assertEqual(
            {item["master_id"] for item in items},
            {"194b7ba77d6b53f30b91", "94f8ab0a070a6ff15fce"},
        )
        self.assertEqual({item["scheme_name"] for item in items}, {"SASACT", "GENESIS"})

    def test_items_are_permanent_schemes_not_calls(self) -> None:
        for item in self.bridge.build_items():
            record = item["validated_record"]
            self.assertEqual(item["record_kind"], "SCHEME_OR_PROGRAMME")
            self.assertEqual(record["permanent_scheme_or_call"], "PERMANENT_SCHEME")
            self.assertNotIn(record["record_kind"], {"APPLICATION_CALL", "CHALLENGE"})
            self.assertIsNone(record["parent_master_id"])

    def test_no_public_application_route_is_imported(self) -> None:
        for item in self.bridge.build_items():
            self.assertIsNone(item["application_url"])
            self.assertIsNone(item["validated_record"]["application_url"])
            self.assertEqual(item["validated_record"]["application_process"], [])

    def test_evidence_is_restricted_to_official_meity_hosts(self) -> None:
        for item in self.bridge.build_items():
            evidence = item["validated_record"]["source_evidence"]
            self.assertTrue(evidence)
            self.assertTrue(all("meity.gov.in" in row["url"] for row in evidence))

    def test_empty_database_dry_run_proposes_two_inserts_without_writes(self) -> None:
        report = self.bridge.run(apply=False)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["proposed_insert_count"], 2)
        self.assertEqual(report["application_call_count"], 0)
        self.assertEqual(report["verified_current_call_count"], 0)
        self.assertFalse(report["database_modified"])
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM admin_review_queue").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scheme_staging").fetchone()[0], 0)

    def test_apply_imports_two_pending_reviews_only(self) -> None:
        dry_run = self.bridge.run(apply=False)
        result = self.bridge.run(apply=True, expected_signature=dry_run["plan_signature"])
        self.assertTrue(result["database_modified"])
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT master_id,scheme_name,source,review_status FROM admin_review_queue ORDER BY scheme_name"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row[2] == "MeitY Startup Hub" for row in rows))
            self.assertTrue(all(row[3] == "PENDING" for row in rows))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM scheme_staging").fetchone()[0], 0)

    def test_pending_records_are_updated_but_decisions_are_protected(self) -> None:
        dry_run = self.bridge.run(apply=False)
        self.bridge.run(apply=True, expected_signature=dry_run["plan_signature"])
        pending_plan = self.bridge.plan()
        self.assertEqual(
            sum(action["action"] == ACTION_UPDATE for action in pending_plan["actions"]),
            2,
        )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE admin_review_queue SET review_status='APPROVED' WHERE master_id='194b7ba77d6b53f30b91'"
            )
            connection.commit()
        protected_plan = self.bridge.plan()
        action = next(
            row for row in protected_plan["actions"] if row["master_id"] == "194b7ba77d6b53f30b91"
        )
        self.assertEqual(action["action"], ACTION_SKIP_DECIDED)
        self.assertEqual(protected_plan["skipped_existing_decision_count"], 1)

    def test_semantic_duplicate_is_skipped(self) -> None:
        target = next(item for item in self.bridge.build_items() if item["scheme_name"] == "GENESIS")
        duplicate = {
            **target,
            "master_id": "existing-genesis",
            "validated_record": {
                **target["validated_record"],
                "master_id": "existing-genesis",
            },
        }
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('fixture','2026-07-14','COMPLETED',1)"
            )
            upsert_review_item(connection, duplicate, "fixture", "2026-07-14T00:00:00+00:00")
            connection.commit()
        report = self.bridge.plan()
        action = next(row for row in report["actions"] if row["scheme_name"] == "GENESIS")
        self.assertEqual(action["action"], ACTION_SKIP_SEMANTIC)

    def test_changed_plan_rejects_old_signature(self) -> None:
        dry_run = self.bridge.run(apply=False)
        target = next(item for item in self.bridge.build_items() if item["scheme_name"] == "SASACT")
        duplicate = {
            **target,
            "master_id": "existing-sasact",
            "validated_record": {
                **target["validated_record"],
                "master_id": "existing-sasact",
            },
        }
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('changed','2026-07-14','COMPLETED',1)"
            )
            upsert_review_item(connection, duplicate, "changed", "2026-07-14T00:00:00+00:00")
            connection.commit()
        with self.assertRaisesRegex(RuntimeError, "plan changed"):
            self.bridge.run(apply=True, expected_signature=dry_run["plan_signature"])

    def test_admin_service_can_filter_imported_meity_records(self) -> None:
        dry_run = self.bridge.run(apply=False)
        self.bridge.run(apply=True, expected_signature=dry_run["plan_signature"])
        service = AdminReviewService(self.database_path)
        rows = service.list_reviews(source="MeitY Startup Hub")
        self.assertEqual({row["scheme_name"] for row in rows}, {"SASACT", "GENESIS"})
        self.assertTrue(all(row["review_status"] == "PENDING" for row in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
