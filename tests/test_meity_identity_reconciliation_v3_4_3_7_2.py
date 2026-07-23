from __future__ import annotations

import copy
import csv
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.staging_loader_v1 import (
    open_database,
    upsert_review_item,
)
from services.admin_review_service_v3_4_3_7_2 import (
    AdminReviewService,
)
from services.meity_identity_reconciliation_v3_4_3_7_2 import (
    ACTION_RECONCILE_INSERT,
    ACTION_SKIP_SEMANTIC,
    GENESIS_ID,
    SASACT_ID,
    MeitYLegacyIdentityReconciliationBridge,
    MeitYReconciliationPaths,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_QUEUE = (
    ROOT
    / "data/departments/meity/v3_4_3_7/"
    "meity_admin_review_queue_v3_4_3_7.csv"
)
MAPPING = (
    ROOT
    / "data/departments/meity/v3_4_3_7_2/"
    "meity_legacy_identity_reconciliation_v3_4_3_7_2.csv"
)
MIGRATION = (
    ROOT
    / "database/migrations/"
    "20260714_meity_legacy_identity_reconciliation_v3_4_3_7_2.sql"
)


class MeitYIdentityReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(
            tempfile.mkdtemp(
                prefix="ssip-v34372-test-"
            )
        )
        self.database = self.directory / "test.db"
        connection = open_database(
            self.database,
            ROOT / "database/schema_staging_v1.sql",
        )
        connection.close()
        AdminReviewService(self.database)

        self.paths = MeitYReconciliationPaths(
            project_root=ROOT,
            source_queue_path=SOURCE_QUEUE,
            reconciliation_map_path=MAPPING,
            database_path=self.database,
            migration_path=MIGRATION,
            report_dir=self.directory / "reports",
        )
        self.bridge = (
            MeitYLegacyIdentityReconciliationBridge(
                self.paths
            )
        )
        self._seed_legacy_rejections()

    def tearDown(self) -> None:
        shutil.rmtree(self.directory)

    def _mapping_rows(
        self,
    ) -> dict[str, dict[str, str]]:
        with MAPPING.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            rows = list(csv.DictReader(handle))
        return {
            row["canonical_master_id"]: row
            for row in rows
        }

    def _seed_legacy_rejections(self) -> None:
        mapping = self._mapping_rows()
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO import_runs(
                run_id,started_at,status,
                approved_input_count,review_input_count,
                rejected_input_count
            ) VALUES (
                'legacy-fixture','2026-07-01',
                'COMPLETED',0,2,0
            )
            """
        )
        for item in self.bridge.build_items():
            legacy_id = mapping[
                item["master_id"]
            ]["legacy_master_id"]
            legacy = copy.deepcopy(item)
            legacy["master_id"] = legacy_id
            legacy["validated_record"][
                "master_id"
            ] = legacy_id
            upsert_review_item(
                connection,
                legacy,
                "legacy-fixture",
                "2026-07-01T00:00:00+00:00",
            )
            connection.execute(
                """
                UPDATE admin_review_queue
                SET review_status='REJECTED'
                WHERE master_id=?
                """,
                (legacy_id,),
            )
            connection.execute(
                """
                INSERT INTO admin_review_actions(
                    master_id,action,reviewer,notes,
                    before_json,after_json,
                    created_at,service_version
                ) VALUES (
                    ?,'REJECT','Legacy Admin',
                    'Original rejection',NULL,NULL,
                    '2026-07-01T00:00:00+00:00',
                    '1.0.1'
                )
                """,
                (legacy_id,),
            )
        connection.commit()
        connection.close()

    def test_mapping_is_exact(self) -> None:
        rows = self._mapping_rows()
        self.assertEqual(
            set(rows),
            {SASACT_ID, GENESIS_ID},
        )
        self.assertEqual(
            rows[GENESIS_ID]["legacy_master_id"],
            "190830c31088c57ffdbc",
        )
        self.assertEqual(
            rows[SASACT_ID]["legacy_master_id"],
            "e3abff4124f05a31f188",
        )

    def test_dry_run_proposes_two_reconciliations(self) -> None:
        before = self.database.read_bytes()
        report = self.bridge.run(apply=False)
        self.assertEqual(
            report["reconciliation_count"],
            2,
        )
        self.assertEqual(
            report["proposed_insert_count"],
            2,
        )
        self.assertEqual(
            report["skipped_semantic_duplicate_count"],
            0,
        )
        self.assertEqual(
            {
                action["action"]
                for action in report["actions"]
            },
            {ACTION_RECONCILE_INSERT},
        )
        self.assertEqual(
            before,
            self.database.read_bytes(),
        )

    def test_apply_preserves_old_and_inserts_new(self) -> None:
        report = self.bridge.run(apply=False)
        self.bridge.run(
            apply=True,
            expected_signature=report["plan_signature"],
        )
        connection = sqlite3.connect(self.database)
        rows = connection.execute(
            """
            SELECT master_id,review_status
            FROM admin_review_queue
            WHERE master_id IN (?,?,?,?)
            """,
            (
                SASACT_ID,
                GENESIS_ID,
                "190830c31088c57ffdbc",
                "e3abff4124f05a31f188",
            ),
        ).fetchall()
        statuses = dict(rows)
        self.assertEqual(
            statuses[SASACT_ID],
            "PENDING",
        )
        self.assertEqual(
            statuses[GENESIS_ID],
            "PENDING",
        )
        self.assertEqual(
            statuses["190830c31088c57ffdbc"],
            "REJECTED",
        )
        self.assertEqual(
            statuses["e3abff4124f05a31f188"],
            "REJECTED",
        )
        self.assertEqual(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM identity_reconciliations
                """
            ).fetchone()[0],
            2,
        )
        connection.close()

    def test_legacy_audit_history_is_unchanged(self) -> None:
        connection = sqlite3.connect(self.database)
        before = connection.execute(
            """
            SELECT COUNT(*)
            FROM admin_review_actions
            WHERE master_id IN (?,?)
            """,
            (
                "190830c31088c57ffdbc",
                "e3abff4124f05a31f188",
            ),
        ).fetchone()[0]
        connection.close()

        report = self.bridge.run(apply=False)
        self.bridge.run(
            apply=True,
            expected_signature=report["plan_signature"],
        )

        connection = sqlite3.connect(self.database)
        after = connection.execute(
            """
            SELECT COUNT(*)
            FROM admin_review_actions
            WHERE master_id IN (?,?)
            """,
            (
                "190830c31088c57ffdbc",
                "e3abff4124f05a31f188",
            ),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(before, after)

    def test_mapped_rejected_aliases_do_not_block(self) -> None:
        report = self.bridge.run(apply=False)
        self.bridge.run(
            apply=True,
            expected_signature=report["plan_signature"],
        )
        service = AdminReviewService(self.database)
        for master_id in (SASACT_ID, GENESIS_ID):
            review = service.get_review(master_id)
            self.assertEqual(
                service.duplicate_candidates(
                    master_id,
                    review["validated_record"],
                ),
                [],
            )
            self.assertEqual(
                len(
                    service.reconciled_aliases(
                        master_id
                    )
                ),
                1,
            )

    def test_non_rejected_legacy_status_aborts(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            UPDATE admin_review_queue
            SET review_status='APPROVED'
            WHERE master_id='190830c31088c57ffdbc'
            """
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(
            RuntimeError,
            "must remain REJECTED",
        ):
            self.bridge.plan()

    def test_unexpected_extra_duplicate_still_blocks(self) -> None:
        item = next(
            item
            for item in self.bridge.build_items()
            if item["master_id"] == GENESIS_ID
        )
        extra = copy.deepcopy(item)
        extra["master_id"] = "unexpected-genesis"
        extra["validated_record"][
            "master_id"
        ] = "unexpected-genesis"

        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys=ON")
        upsert_review_item(
            connection,
            extra,
            "legacy-fixture",
            "2026-07-01T00:00:00+00:00",
        )
        connection.commit()
        connection.close()

        report = self.bridge.plan()
        action = next(
            action
            for action in report["actions"]
            if action["master_id"] == GENESIS_ID
        )
        self.assertEqual(
            action["action"],
            ACTION_SKIP_SEMANTIC,
        )

    def test_apply_requires_signature(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "signature is required",
        ):
            self.bridge.run(apply=True)

    def test_no_calls_or_application_routes(self) -> None:
        items = self.bridge.build_items()
        self.assertTrue(
            all(
                item["record_kind"]
                == "SCHEME_OR_PROGRAMME"
                for item in items
            )
        )
        self.assertTrue(
            all(
                item["application_url"] is None
                for item in items
            )
        )
        report = self.bridge.plan()
        self.assertEqual(
            report["application_call_count"],
            0,
        )
        self.assertEqual(
            report["verified_current_call_count"],
            0,
        )

    def test_rerun_after_apply_updates_pending(self) -> None:
        report = self.bridge.run(apply=False)
        self.bridge.run(
            apply=True,
            expected_signature=report["plan_signature"],
        )
        rerun = self.bridge.plan()
        self.assertEqual(
            rerun["proposed_insert_count"],
            0,
        )
        self.assertEqual(
            rerun["proposed_update_count"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
