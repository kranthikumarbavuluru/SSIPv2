from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from services.meity_calls_admin_bridge_v3_4_3_7_5 import (
    MeitYCallsAdminBridge,
    MeitYCallsBridgePaths,
)
from services.meity_calls_recovery_v3_4_3_7_5 import (
    GENESIS_ID,
    MeitYCallsRecovery,
    RawCandidate,
    RecoveryPaths,
    official_url,
    resolve_parent,
    status_decision,
    usable_title,
)


class MeitYCallsRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        (self.root / "config").mkdir()
        (self.root / "data/departments/meity/v3_4_3_1").mkdir(
            parents=True
        )
        (self.root / "database").mkdir()

        (
            self.root
            / "config/meity_calls_official_seeds_v3_4_3_7_5.json"
        ).write_text(
            json.dumps(
                {
                    "entry_urls": [],
                    "timeout_seconds": 1,
                    "max_network_documents": 1,
                    "max_document_bytes": 1000,
                }
            ),
            encoding="utf-8",
        )

        self.database = self.root / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;

            CREATE TABLE import_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                approved_input_count INTEGER NOT NULL DEFAULT 0,
                review_input_count INTEGER NOT NULL DEFAULT 0,
                rejected_input_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT
            );

            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                source TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                official_page_url TEXT,
                application_url TEXT,
                decision TEXT NOT NULL,
                validation_score REAL,
                review_status TEXT NOT NULL DEFAULT 'PENDING',
                priority TEXT NOT NULL,
                decision_reasons_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                critical_flags_json TEXT NOT NULL,
                recommended_actions_json TEXT NOT NULL,
                validated_record_json TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                first_queued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_import_run_id TEXT,
                FOREIGN KEY(last_import_run_id)
                    REFERENCES import_runs(run_id)
            );

            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                official_page_url TEXT,
                publication_status TEXT,
                raw_record_json TEXT
            );
            """
        )
        connection.execute(
            """
            INSERT INTO scheme_staging(
                master_id,scheme_name,official_page_url,
                publication_status,raw_record_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                GENESIS_ID,
                "GENESIS",
                "https://msh.meity.gov.in/schemes/genesis",
                "STAGED",
                "{}",
            ),
        )
        connection.commit()
        connection.close()

        evidence = (
            self.root
            / "data/departments/meity/v3_4_3_1/"
            "meity_discovered_pages_v3_4_3_1.csv"
        )
        with evidence.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "title",
                    "canonical_url",
                    "discovered_from",
                    "status_code",
                    "text_excerpt",
                ),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "title": "SAMRIDH 2nd Cohort OM Final.pdf",
                    "canonical_url": (
                        "https://msh.meity.gov.in/assets/"
                        "samridh2ndcohrot/"
                        "SAMRIDH%202nd%20Cohort%20OM%20Final.pdf"
                    ),
                    "discovered_from": (
                        "https://msh.meity.gov.in/schemes/samridh"
                    ),
                    "status_code": "200",
                    "text_excerpt": "",
                }
            )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_off_domain_url_rejected(self) -> None:
        self.assertEqual(
            official_url("https://example.com/challenge"),
            "",
        )

    def test_generic_title_rejected(self) -> None:
        self.assertFalse(usable_title("View Challenge.Aspx"))

    def test_strict_open_requires_route(self) -> None:
        candidate = RawCandidate(
            title="GENESIS Startup Applications Cohort",
            evidence_url=(
                "https://msh.meity.gov.in/challenges/genesis"
            ),
            application_url=(
                "https://msh.meity.gov.in/register/genesis"
            ),
            closing_date="2026-08-31",
            status_text="Open",
            network_verified=True,
        )
        result = status_decision(
            candidate,
            today=date(2026, 7, 14),
        )
        self.assertEqual(result[0], "OPEN_VERIFIED")
        self.assertTrue(result[1])
        self.assertTrue(result[2])

    def test_open_without_route_suppressed(self) -> None:
        candidate = RawCandidate(
            title="SASACT Applications Invited",
            evidence_url=(
                "https://msh.meity.gov.in/challenges/sasact"
            ),
            closing_date="2026-08-31",
            status_text="Open",
            network_verified=True,
        )
        result = status_decision(
            candidate,
            today=date(2026, 7, 14),
        )
        self.assertEqual(
            result[0],
            "CURRENT_WINDOW_REQUIRES_ROUTE_VERIFICATION",
        )
        self.assertFalse(result[1])
        self.assertEqual(result[2], "")

    def test_parent_identity_preserved(self) -> None:
        candidate = RawCandidate(
            title="GENESIS Cohort 3",
            evidence_url=(
                "https://msh.meity.gov.in/challenges/genesis-3"
            ),
        )
        parent = resolve_parent(
            candidate,
            {"genesis": (GENESIS_ID, "GENESIS")},
        )
        self.assertEqual(parent[0], GENESIS_ID)

    def test_local_official_cohort_recovered(self) -> None:
        report = MeitYCallsRecovery(
            RecoveryPaths.defaults(self.root)
        ).run(
            network=False,
            today=date(2026, 7, 14),
        )
        self.assertGreaterEqual(report["admin_queue_count"], 1)
        self.assertEqual(report["off_domain_sources_accepted"], 0)
        self.assertFalse(report["database_modified"])

    def test_bridge_dry_run_non_writing(self) -> None:
        MeitYCallsRecovery(
            RecoveryPaths.defaults(self.root)
        ).run(
            network=False,
            today=date(2026, 7, 14),
        )
        bridge = MeitYCallsAdminBridge(
            MeitYCallsBridgePaths.defaults(
                self.root,
                self.database,
            )
        )
        before = self.database.read_bytes()
        report = bridge.run(apply=False)
        after = self.database.read_bytes()
        self.assertEqual(before, after)
        self.assertGreaterEqual(report["source_queue_count"], 1)
        self.assertFalse(report["database_modified"])
        self.assertFalse(report["publication_performed"])

    def test_bridge_imports_pending_calls_only(self) -> None:
        MeitYCallsRecovery(
            RecoveryPaths.defaults(self.root)
        ).run(
            network=False,
            today=date(2026, 7, 14),
        )
        bridge = MeitYCallsAdminBridge(
            MeitYCallsBridgePaths.defaults(
                self.root,
                self.database,
            )
        )
        plan = bridge.run(apply=False)
        bridge.run(
            apply=True,
            expected_signature=plan["plan_signature"],
        )
        connection = sqlite3.connect(self.database)
        rows = connection.execute(
            """
            SELECT review_status,record_kind,application_url
            FROM admin_review_queue
            """
        ).fetchall()
        connection.close()
        self.assertTrue(rows)
        self.assertTrue(
            all(row[0] == "PENDING" for row in rows)
        )
        self.assertTrue(
            all(row[1] == "APPLICATION_CALL" for row in rows)
        )
        self.assertTrue(
            all(row[2] in (None, "") for row in rows)
        )

    def test_permanent_scheme_unchanged(self) -> None:
        MeitYCallsRecovery(
            RecoveryPaths.defaults(self.root)
        ).run(
            network=False,
            today=date(2026, 7, 14),
        )
        bridge = MeitYCallsAdminBridge(
            MeitYCallsBridgePaths.defaults(
                self.root,
                self.database,
            )
        )
        plan = bridge.run(apply=False)
        bridge.run(
            apply=True,
            expected_signature=plan["plan_signature"],
        )
        connection = sqlite3.connect(self.database)
        row = connection.execute(
            """
            SELECT scheme_name,publication_status
            FROM scheme_staging
            WHERE master_id=?
            """,
            (GENESIS_ID,),
        ).fetchone()
        connection.close()
        self.assertEqual(row, ("GENESIS", "STAGED"))

    def test_publication_never_performed(self) -> None:
        report = MeitYCallsRecovery(
            RecoveryPaths.defaults(self.root)
        ).run(
            network=False,
            today=date(2026, 7, 14),
        )
        self.assertFalse(report["publication_performed"])


if __name__ == "__main__":
    unittest.main()
