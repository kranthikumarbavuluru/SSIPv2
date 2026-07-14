from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.staging_loader_v1 import (
    open_database,
    upsert_approved_scheme,
    upsert_review_item,
)
from services.admin_review_service_v3_4_3_7_4 import AdminReviewService
from services.organization_canonicalization_v3_4_3_7_4 import (
    DEPARTMENT_DST,
    MINISTRY_LEVEL_LABEL,
    MINISTRY_MEITY,
    MINISTRY_SCIENCE_TECH,
    OrganizationCanonicalizationService,
    canonical_payload_hash,
    canonicalize_organization_record,
)


ROOT = Path(__file__).resolve().parents[1]


class OrganizationCanonicalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ssip-v34374-"))
        self.database = self.temp_dir / "test.db"
        connection = open_database(
            self.database,
            ROOT / "database/schema_staging_v1.sql",
        )
        connection.close()
        AdminReviewService(self.database)
        self._seed_alias_records()
        self.service = OrganizationCanonicalizationService(self.database)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _record(
        master_id: str,
        name: str,
        source: str,
        ministry: str | None,
        department: str | None,
    ) -> dict:
        return {
            "master_id": master_id,
            "scheme_name": name,
            "source": source,
            "ministry": ministry,
            "department": department,
            "implementing_agency": source,
            "record_kind": "SCHEME_OR_PROGRAMME",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
            "official_page_url": f"https://example.gov.in/{master_id}",
            "application_url": None,
            "validation": {
                "decision": "APPROVED_FOR_DATABASE",
                "validation_score": 1.0,
            },
        }

    def _seed_alias_records(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO import_runs(
                run_id,started_at,status,approved_input_count,
                review_input_count,rejected_input_count
            ) VALUES ('fixture','2026-07-14T00:00:00Z','COMPLETED',2,2,0)
            """
        )

        records = [
            self._record(
                "dst-admin",
                "DST Admin Record",
                "DST",
                "Department of Science and Technology",
                "Department of Science and Technology",
            ),
            self._record(
                "meity-admin",
                "MeitY Admin Record",
                "MeitY Startup Hub",
                "Ministry of Electronics and Information Technology",
                "Ministry of Electronics and Information Technology (MeitY)",
            ),
        ]
        for record in records:
            payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
            connection.execute(
                """
                INSERT INTO admin_review_queue(
                    master_id,scheme_name,source,record_kind,programme_status,
                    application_status,official_page_url,application_url,decision,
                    validation_score,review_status,priority,decision_reasons_json,
                    warnings_json,critical_flags_json,recommended_actions_json,
                    validated_record_json,record_hash,first_queued_at,updated_at,
                    last_import_run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,'APPROVED','NORMAL','[]','[]','[]','[]',?,?,?,?,?)
                """,
                (
                    record["master_id"],
                    record["scheme_name"],
                    record["source"],
                    record["record_kind"],
                    record["programme_status"],
                    record["application_status"],
                    record["official_page_url"],
                    record["application_url"],
                    "APPROVED_FOR_DATABASE",
                    1.0,
                    payload,
                    canonical_payload_hash(record),
                    "2026-07-14T00:00:00Z",
                    "2026-07-14T00:00:00Z",
                    "fixture",
                ),
            )

        staging_records = [
            self._record(
                "dst-stage",
                "DST Staging Record",
                "Department of Science and Technology",
                "Ministry of Science & Technology",
                "Department of Science and Technology",
            ),
            self._record(
                "meity-stage",
                "MeitY Staging Record",
                "MeitY Startup Hub",
                "Ministry of Electronics and Information Technology",
                "Ministry of Electronics and Information Technology",
            ),
        ]
        for record in staging_records:
            payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
            connection.execute(
                """
                INSERT INTO scheme_staging(
                    master_id,scheme_name,source,ministry,department,
                    record_kind,programme_status,application_status,
                    official_page_url,application_url,validation_score,
                    validation_decision,publication_status,record_hash,
                    raw_record_json,first_loaded_at,last_loaded_at,last_import_run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,1.0,'APPROVED_FOR_DATABASE','STAGED',?,?,?,?,?)
                """,
                (
                    record["master_id"],
                    record["scheme_name"],
                    record["source"],
                    record["ministry"],
                    record["department"],
                    record["record_kind"],
                    record["programme_status"],
                    record["application_status"],
                    record["official_page_url"],
                    record["application_url"],
                    canonical_payload_hash(record),
                    payload,
                    "2026-07-14T00:00:00Z",
                    "2026-07-14T00:00:00Z",
                    "fixture",
                ),
            )
        connection.commit()
        connection.close()

    def test_canonicalizer_maps_dst(self) -> None:
        result = canonicalize_organization_record(
            self._record(
                "dst",
                "DST",
                "DST",
                "Department of Science and Technology",
                "Department of Science and Technology",
            )
        )
        self.assertEqual(result["ministry"], MINISTRY_SCIENCE_TECH)
        self.assertEqual(result["department"], DEPARTMENT_DST)
        self.assertEqual(result["organization_level"], "DEPARTMENT")

    def test_canonicalizer_maps_meity_to_ministry_level(self) -> None:
        result = canonicalize_organization_record(
            self._record(
                "meity",
                "MeitY",
                "MeitY Startup Hub",
                "Ministry of Electronics and Information Technology",
                "Ministry of Electronics and Information Technology (MeitY)",
            )
        )
        self.assertEqual(result["ministry"], MINISTRY_MEITY)
        self.assertIsNone(result["department"])
        self.assertEqual(result["organization_level"], "MINISTRY")

    def test_unknown_organization_is_not_inferred(self) -> None:
        original = self._record(
            "unknown",
            "Unknown",
            "Unknown Agency",
            "Example Ministry",
            "Example Department",
        )
        result = canonicalize_organization_record(original)
        self.assertEqual(result["ministry"], "Example Ministry")
        self.assertEqual(result["department"], "Example Department")

    def test_dry_run_does_not_modify_database(self) -> None:
        before = self.database.read_bytes()
        report = self.service.plan()
        self.assertEqual(report["change_count"], 4)
        self.assertFalse(report["database_modified"])
        self.assertEqual(before, self.database.read_bytes())

    def test_apply_preserves_identity_and_governance_fields(self) -> None:
        before_connection = sqlite3.connect(self.database)
        before = before_connection.execute(
            """
            SELECT master_id,review_status,application_url
            FROM admin_review_queue ORDER BY master_id
            """
        ).fetchall()
        staged_before = before_connection.execute(
            """
            SELECT master_id,publication_status,application_url
            FROM scheme_staging ORDER BY master_id
            """
        ).fetchall()
        before_connection.close()

        plan = self.service.plan()
        result = self.service.apply(plan["plan_signature"])
        self.assertEqual(result["applied_change_count"], 4)

        connection = sqlite3.connect(self.database)
        after = connection.execute(
            """
            SELECT master_id,review_status,application_url
            FROM admin_review_queue ORDER BY master_id
            """
        ).fetchall()
        staged_after = connection.execute(
            """
            SELECT master_id,publication_status,application_url
            FROM scheme_staging ORDER BY master_id
            """
        ).fetchall()
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM organization_canonicalization_audit"
        ).fetchone()[0]
        connection.close()

        self.assertEqual(before, after)
        self.assertEqual(staged_before, staged_after)
        self.assertEqual(audit_count, 4)

    def test_apply_is_idempotent(self) -> None:
        plan = self.service.plan()
        self.service.apply(plan["plan_signature"])
        rerun = self.service.plan()
        self.assertEqual(rerun["change_count"], 0)

    def test_filter_options_are_deduplicated(self) -> None:
        plan = self.service.plan()
        self.service.apply(plan["plan_signature"])
        service = AdminReviewService(self.database)
        options = service.filter_options()
        self.assertIn(DEPARTMENT_DST, options["departments"])
        self.assertIn(MINISTRY_LEVEL_LABEL, options["departments"])
        self.assertNotIn("Department of Science and Technology", options["departments"])
        self.assertNotIn(
            "Ministry of Electronics and Information Technology",
            options["departments"],
        )

    def test_ministry_level_filter_returns_meity(self) -> None:
        plan = self.service.plan()
        self.service.apply(plan["plan_signature"])
        service = AdminReviewService(self.database)
        rows = service.list_reviews(
            review_status="ALL",
            department=MINISTRY_LEVEL_LABEL,
        )
        self.assertEqual([row["master_id"] for row in rows], ["meity-admin"])

    def test_future_review_import_is_normalized(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys=ON")
        item = {
            "master_id": "future-meity",
            "scheme_name": "Future MeitY",
            "source": "MeitY Startup Hub",
            "record_kind": "SCHEME_OR_PROGRAMME",
            "programme_status": "SCHEME_INFORMATION_AVAILABLE",
            "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
            "official_page_url": "https://msh.meity.gov.in/schemes/future",
            "application_url": None,
            "decision": "NEEDS_ADMIN_REVIEW",
            "validated_record": self._record(
                "future-meity",
                "Future MeitY",
                "MeitY Startup Hub",
                "Ministry of Electronics and Information Technology",
                "Ministry of Electronics and Information Technology",
            ),
        }
        upsert_review_item(
            connection,
            item,
            "fixture",
            "2026-07-14T01:00:00Z",
        )
        connection.commit()
        payload = json.loads(
            connection.execute(
                "SELECT validated_record_json FROM admin_review_queue WHERE master_id='future-meity'"
            ).fetchone()[0]
        )
        connection.close()
        self.assertEqual(payload["ministry"], MINISTRY_MEITY)
        self.assertIsNone(payload["department"])

    def test_future_staging_import_is_normalized(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys=ON")
        record = self._record(
            "future-dst",
            "Future DST",
            "DST",
            "Department of Science and Technology",
            "Department of Science and Technology",
        )
        upsert_approved_scheme(
            connection,
            record,
            "fixture",
            "2026-07-14T01:00:00Z",
        )
        connection.commit()
        row = connection.execute(
            "SELECT ministry,department FROM scheme_staging WHERE master_id='future-dst'"
        ).fetchone()
        connection.close()
        self.assertEqual(row, (MINISTRY_SCIENCE_TECH, DEPARTMENT_DST))


if __name__ == "__main__":
    unittest.main()
