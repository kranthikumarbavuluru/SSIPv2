from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path
import unittest
import uuid

from ssip_dashboard.config import CatalogueMode, DashboardConfig
from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.data_access import readonly_connection


class PublicDashboardDataAccessTest(unittest.TestCase):
    def temp_project(self) -> Path:
        scratch = Path.cwd() / ".test_tmp_public_dashboard"
        scratch.mkdir(exist_ok=True)
        path = scratch / f"case_{uuid.uuid4().hex}"
        path.mkdir()
        return path

    def cleanup_project(self, path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

    def make_project(self, temp_dir: str) -> Path:
        root = Path(temp_dir)
        (root / "database").mkdir()
        (root / "data" / "audit" / "v2_8_1_catalogue_normalization").mkdir(parents=True)
        db = root / "database" / "ssip_staging_v1.db"
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                source TEXT,
                ministry TEXT,
                department TEXT,
                implementing_agency TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                official_page_url TEXT,
                application_url TEXT,
                opening_date TEXT,
                closing_date TEXT,
                validation_score REAL,
                validation_decision TEXT,
                publication_status TEXT,
                funding_minimum INTEGER,
                funding_maximum INTEGER,
                currency TEXT,
                beneficiary_support_minimum INTEGER,
                beneficiary_support_maximum INTEGER,
                intermediary_support_maximum INTEGER,
                scheme_corpus INTEGER,
                record_hash TEXT,
                raw_record_json TEXT,
                first_loaded_at TEXT,
                last_loaded_at TEXT,
                last_import_run_id TEXT,
                is_public INTEGER DEFAULT 0,
                updated_at TEXT
            );
            CREATE VIEW public_schemes AS
            SELECT * FROM scheme_staging WHERE publication_status='PUBLISHED' AND is_public=1;
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                source TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                official_page_url TEXT,
                application_url TEXT,
                decision TEXT,
                validation_score REAL,
                review_status TEXT,
                priority TEXT,
                decision_reasons_json TEXT,
                warnings_json TEXT,
                critical_flags_json TEXT,
                recommended_actions_json TEXT,
                validated_record_json TEXT,
                record_hash TEXT,
                first_queued_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE rejected_scheme_records (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT,
                source TEXT,
                decision TEXT,
                validation_score REAL,
                rejection_reasons_json TEXT,
                raw_record_json TEXT,
                record_hash TEXT,
                first_rejected_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE scheme_attributes (master_id TEXT, attribute_group TEXT, sort_order INTEGER, value TEXT);
            CREATE TABLE scheme_contacts (master_id TEXT, sort_order INTEGER, contact_type TEXT, contact_value TEXT);
            CREATE TABLE scheme_sources (master_id TEXT, sort_order INTEGER, source_url TEXT);
            CREATE TABLE publication_audit_log (audit_id INTEGER PRIMARY KEY, master_id TEXT);
            """
        )
        con.execute(
            """
            INSERT INTO scheme_staging (
                master_id, scheme_name, source, ministry, department, implementing_agency,
                record_kind, programme_status, application_status, official_page_url,
                validation_decision, publication_status, funding_maximum, currency,
                record_hash, raw_record_json, first_loaded_at, last_loaded_at, is_public
            ) VALUES (
                'one', 'Open Grant', 'DST', 'Ministry A', 'Department A', 'Agency A',
                'SCHEME_OR_PROGRAMME', 'SCHEME_INFORMATION_AVAILABLE', 'OPEN',
                'https://example.gov/open', 'APPROVED_FOR_DATABASE', 'STAGED',
                1000000, 'INR', 'hash', '{}', '2026-07-09', '2026-07-09', 0
            )
            """
        )
        con.execute("INSERT INTO scheme_attributes VALUES ('one', 'sector', 1, 'Biotechnology')")
        con.commit()
        con.close()

        plan_path = root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv"
        with plan_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "master_id",
                    "source",
                    "scheme_name",
                    "current_location",
                    "current_review_status",
                    "current_decision",
                    "current_publication_status",
                    "current_is_public",
                    "normalized_record_kind",
                    "programme_status",
                    "application_status",
                    "catalogue_inclusion",
                    "catalogue_section",
                    "official_page_url",
                    "application_url",
                    "decision_reasons",
                    "warnings",
                    "recommended_actions",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "master_id": "one",
                    "source": "DST",
                    "scheme_name": "Open Grant",
                    "current_location": "SCHEME_STAGING",
                    "current_publication_status": "STAGED",
                    "current_is_public": "0",
                    "normalized_record_kind": "SCHEME_OR_PROGRAMME",
                    "programme_status": "SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "OPEN",
                    "catalogue_inclusion": "INCLUDED",
                    "catalogue_section": "SCHEMES_AND_PROGRAMMES",
                    "official_page_url": "https://example.gov/open",
                }
            )
        return root

    def test_readonly_connection_blocks_writes(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            with readonly_connection(root / "database" / "ssip_staging_v1.db") as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM scheme_staging").fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    con.execute("INSERT INTO scheme_staging(master_id, scheme_name) VALUES ('x', 'x')")
        finally:
            self.cleanup_project(temp_dir)

    def test_catalogue_preview_loads_normalized_record(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            config = DashboardConfig(
                project_root=root,
                database_path=root / "database" / "ssip_staging_v1.db",
                normalization_path=root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv",
                mode=CatalogueMode.CATALOGUE_PREVIEW,
            )
            bundle = load_catalogue(config)
            self.assertEqual(len(bundle.records), 1)
            self.assertEqual(bundle.records[0].scheme_name, "Open Grant")
            self.assertEqual(bundle.records[0].sectors, ["Biotechnology"])
        finally:
            self.cleanup_project(temp_dir)

    def test_published_only_uses_public_view(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            config = DashboardConfig(
                project_root=root,
                database_path=root / "database" / "ssip_staging_v1.db",
                normalization_path=root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv",
                mode=CatalogueMode.PUBLISHED_ONLY,
            )
            bundle = load_catalogue(config)
            self.assertEqual(bundle.records, [])
        finally:
            self.cleanup_project(temp_dir)

    def test_catalogue_preview_appends_published_records_missing_from_plan(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            payload = {
                "master_id": "published-call",
                "scheme_name": "Published RDIF Call",
                "record_kind": "APPLICATION_CALL",
                "application_status": "OPEN",
                "parent_master_id": "rdif-parent",
                "parent_scheme_name": "Research Development and Innovation Fund",
                "applicant_layer": "DIRECT_BENEFICIARY",
                "status_basis": "EXPLICIT_OFFICIAL_APPLY_ROUTE",
                "status_evidence": "Official Apply Now route verified",
                "last_verified_at": "2026-07-11",
            }
            con = sqlite3.connect(root / "database" / "ssip_staging_v1.db")
            try:
                con.execute(
                    """
                    INSERT INTO scheme_staging (
                        master_id, scheme_name, source, department, implementing_agency,
                        record_kind, application_status, official_page_url, application_url,
                        publication_status, is_public, raw_record_json, record_hash,
                        first_loaded_at, last_loaded_at
                    ) VALUES (?, ?, 'DST', 'Department of Science and Technology',
                              'Technology Development Board', 'APPLICATION_CALL', 'OPEN',
                              'https://tdb.gov.in/rdif', 'https://tdb.gov.in/apply',
                              'PUBLISHED', 1, ?, 'published-hash', '2026-07-11', '2026-07-11')
                    """,
                    ("published-call", "Published RDIF Call", json.dumps(payload)),
                )
                con.commit()
            finally:
                con.close()
            config = DashboardConfig(
                project_root=root,
                database_path=root / "database" / "ssip_staging_v1.db",
                normalization_path=root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv",
                mode=CatalogueMode.CATALOGUE_PREVIEW,
            )
            bundle = load_catalogue(config)
            self.assertEqual({record.master_id for record in bundle.records}, {"one", "published-call"})
            self.assertEqual(bundle.metadata["published_appended_count"], 1)
            call = next(record for record in bundle.records if record.master_id == "published-call")
            self.assertEqual(call.catalogue_section, "APPLICATION_CALLS")
            self.assertEqual(call.parent_master_id, "rdif-parent")
            self.assertEqual(call.applicant_layer, "DIRECT_BENEFICIARY")
            self.assertEqual(call.status_basis, "EXPLICIT_OFFICIAL_APPLY_ROUTE")
        finally:
            self.cleanup_project(temp_dir)

    def test_catalogue_preview_does_not_duplicate_published_plan_record(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            con = sqlite3.connect(root / "database" / "ssip_staging_v1.db")
            try:
                con.execute(
                    "UPDATE scheme_staging SET publication_status='PUBLISHED', is_public=1 WHERE master_id='one'"
                )
                con.commit()
            finally:
                con.close()
            config = DashboardConfig(
                project_root=root,
                database_path=root / "database" / "ssip_staging_v1.db",
                normalization_path=root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv",
                mode=CatalogueMode.CATALOGUE_PREVIEW,
            )
            bundle = load_catalogue(config)
            self.assertEqual([record.master_id for record in bundle.records], ["one"])
            self.assertEqual(bundle.metadata["published_appended_count"], 0)
        finally:
            self.cleanup_project(temp_dir)

    def test_published_record_supersedes_semantic_preview_duplicate(self) -> None:
        temp_dir = self.temp_project()
        try:
            root = self.make_project(str(temp_dir))
            con = sqlite3.connect(root / "database" / "ssip_staging_v1.db")
            try:
                con.execute(
                    """
                    INSERT INTO scheme_staging (
                        master_id, scheme_name, source, department, record_kind,
                        application_status, official_page_url, publication_status,
                        is_public, raw_record_json, record_hash, first_loaded_at, last_loaded_at
                    ) VALUES (
                        'published-one', 'Open Grant', 'DST', 'Department A',
                        'SCHEME_OR_PROGRAMME', 'NOT_APPLICABLE',
                        'https://example.gov/open/', 'PUBLISHED', 1, '{}',
                        'published-one-hash', '2026-07-11', '2026-07-11'
                    )
                    """
                )
                con.commit()
            finally:
                con.close()
            config = DashboardConfig(
                project_root=root,
                database_path=root / "database" / "ssip_staging_v1.db",
                normalization_path=root / "data" / "audit" / "v2_8_1_catalogue_normalization" / "catalogue_normalization_plan_v2_8_1.csv",
                mode=CatalogueMode.CATALOGUE_PREVIEW,
            )
            bundle = load_catalogue(config)
            self.assertEqual([record.master_id for record in bundle.records], ["published-one"])
            self.assertEqual(bundle.metadata["published_appended_count"], 0)
            self.assertEqual(bundle.metadata["published_merged_count"], 1)
        finally:
            self.cleanup_project(temp_dir)


if __name__ == "__main__":
    unittest.main()
