from __future__ import annotations

import json
import sqlite3
import unittest

from scripts.publication_control_service_v2_7_3_4 import write_audit


class MeitYWithdrawalAuditCompatibilityTests(unittest.TestCase):
    def test_withdrawal_uses_schema_compatible_unpublish_action(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE publication_audit_log (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN (
                        'LOAD',
                        'MARK_READY',
                        'PUBLISH',
                        'UNPUBLISH',
                        'ARCHIVE',
                        'RESTORE',
                        'UPDATE'
                    )
                ),
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                previous_is_public INTEGER NOT NULL,
                new_is_public INTEGER NOT NULL,
                action_by TEXT NOT NULL,
                action_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                source_run_id TEXT,
                record_version INTEGER NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )

        write_audit(
            connection,
            master_id="meitycall_test",
            action="withdraw-publication",
            previous_status="PUBLISHED",
            new_status="UNPUBLISHED",
            previous_is_public=1,
            new_is_public=0,
            actor="Admin",
            now="2026-07-14T08:30:00+00:00",
            reason=(
                "Emergency withdrawal of an unverified MeitY call."
            ),
            source_run_id="test_run",
            record_version=2,
            metadata={
                "service_version": "3.4.3.7.7.1",
                "governance_action": "WITHDRAW_PUBLICATION",
                "emergency_scope": "MEITY_APPLICATION_CALLS",
            },
        )
        connection.commit()

        row = connection.execute(
            """
            SELECT action,reason,metadata_json
            FROM publication_audit_log
            """
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "UNPUBLISH")
        self.assertIn("Emergency withdrawal", row[1])

        metadata = json.loads(row[2])
        self.assertEqual(
            metadata["governance_action"],
            "WITHDRAW_PUBLICATION",
        )
        self.assertEqual(
            metadata["emergency_scope"],
            "MEITY_APPLICATION_CALLS",
        )


if __name__ == "__main__":
    unittest.main()
