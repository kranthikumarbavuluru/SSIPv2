from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ssip_agents.coverage_audit_agent_v2_6 import (
    AuditPaths,
    FINAL_CATEGORIES,
    run_audit,
    write_outputs,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CoverageAuditV26Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "database").mkdir()

        discovery = []
        classified = []
        masters = []
        source_cycle = ["Startup India", "BIRAC", "DST", "DST", "BIRAC", "MeitY Startup Hub"]
        for index, source in enumerate(source_cycle, start=1):
            url = f"https://example{index}.gov.in/scheme/{index}"
            discovery.append(
                {
                    "url": url,
                    "source": source,
                    "status": "PENDING",
                    "content_kind": "html",
                    "discovery_method": "test",
                    "title": f"Scheme {index}",
                }
            )
            classified.append(
                {
                    "url": url,
                    "canonical_url": url,
                    "source": source,
                    "classification": "SCHEME",
                    "classification_reasons": ["scheme marker"],
                    "review_decision": "PRIORITY_REVIEW",
                }
            )
            masters.append(
                {
                    "master_id": f"m{index}",
                    "canonical_name": f"Scheme {index}",
                    "source": source,
                    "best_available_url": url,
                    "all_member_urls": [url],
                }
            )

        # A classified non-scheme URL with no master.
        discovery.append(
            {
                "url": "https://example.gov.in/directory",
                "source": "DST",
                "status": "PENDING",
                "content_kind": "html",
                "discovery_method": "test",
                "title": "Directory",
            }
        )
        classified.append(
            {
                "url": "https://example.gov.in/directory",
                "canonical_url": "https://example.gov.in/directory",
                "source": "DST",
                "classification": "DIRECTORY_PAGE",
                "classification_reasons": ["directory marker"],
                "review_decision": "USE_FOR_FURTHER_DISCOVERY",
            }
        )

        write_json(self.root / "data" / "discovery_results_v2.json", discovery)
        write_json(self.root / "data" / "classified_candidates_v1.json", classified)
        write_json(self.root / "data" / "scheme_master_candidates_v1.json", masters)
        write_json(
            self.root / "data" / "extracted_scheme_records_v2_3.json",
            [
                {"master_id": "m1", "scheme_name": "Scheme 1", "source": "Startup India"},
                {"master_id": "m3", "scheme_name": "Scheme 3", "source": "DST"},
                {"master_id": "m4", "scheme_name": "Scheme 4", "source": "DST"},
                {"master_id": "m5", "scheme_name": "Scheme 5", "source": "BIRAC"},
                {"master_id": "m6", "scheme_name": "Scheme 6", "source": "MeitY Startup Hub"},
            ],
        )
        write_json(self.root / "data" / "extracted_scheme_records_v1.json", [])
        write_json(
            self.root / "data" / "validated_scheme_records_v2_4.json",
            [
                {"master_id": "m1", "scheme_name": "Scheme 1", "source": "Startup India", "decision": "APPROVED_FOR_DATABASE"},
                {"master_id": "m4", "scheme_name": "Scheme 4", "source": "DST", "decision": "APPROVED_FOR_DATABASE"},
                {"master_id": "m5", "scheme_name": "Scheme 5", "source": "BIRAC", "decision": "NEEDS_ADMIN_REVIEW"},
                {"master_id": "m6", "scheme_name": "Scheme 6", "source": "MeitY Startup Hub", "decision": "REJECTED"},
            ],
        )
        write_json(self.root / "data" / "validated_scheme_records_v1.json", [])
        write_json(self.root / "data" / "meity_discovery_summary_v2_1.json", {})

        self.staging_db = self.root / "database" / "ssip_staging_v1.db"
        connection = sqlite3.connect(self.staging_db)
        connection.executescript(
            """
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                source TEXT,
                publication_status TEXT,
                raw_record_json TEXT
            );
            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                source TEXT,
                review_status TEXT,
                validated_record_json TEXT
            );
            CREATE TABLE rejected_scheme_records (
                master_id TEXT PRIMARY KEY,
                source TEXT,
                raw_record_json TEXT
            );
            CREATE TABLE scheme_sources (
                master_id TEXT,
                source_url TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO scheme_staging VALUES (?, ?, ?, ?)",
            ("m1", "Startup India", "STAGED", "{}"),
        )
        connection.execute(
            "INSERT INTO admin_review_queue VALUES (?, ?, ?, ?)",
            ("m5", "BIRAC", "PENDING", "{}"),
        )
        connection.execute(
            "INSERT INTO rejected_scheme_records VALUES (?, ?, ?)",
            ("m6", "MeitY Startup Hub", "{}"),
        )
        connection.commit()
        connection.close()

        legacy_db = self.root / "database" / "ssip.db"
        connection = sqlite3.connect(legacy_db)
        connection.execute(
            """
            CREATE TABLE discovered_links (
                id INTEGER PRIMARY KEY,
                url TEXT,
                title TEXT,
                page_type TEXT,
                crawl_status TEXT,
                classification_status TEXT,
                source_url TEXT,
                discovered_date TEXT
            )
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_full_category_reconciliation_and_read_only_database(self) -> None:
        before_hash = sha256(self.staging_db)
        paths = AuditPaths.from_project_root(self.root)
        result = run_audit(paths, include_legacy=False)
        after_hash = sha256(self.staging_db)

        self.assertEqual(before_hash, after_hash, "Audit must not modify the staging database")
        categories = {row.master_id: row.final_category for row in result.rows if row.master_id}
        self.assertEqual(categories["m1"], "FULLY_PROCESSED")
        self.assertEqual(categories["m2"], "AWAITING_EXTRACTION")
        self.assertEqual(categories["m3"], "AWAITING_VALIDATION")
        self.assertEqual(categories["m4"], "MISSING_FROM_STAGING")
        self.assertEqual(categories["m5"], "AWAITING_ADMIN_REVIEW")
        self.assertEqual(categories["m6"], "REJECTED")
        self.assertIn("NON_SCHEME_CONTENT", {row.final_category for row in result.rows})
        self.assertTrue({row.final_category for row in result.rows}.issubset(FINAL_CATEGORIES))

        summary_by_source = {row["source"]: row for row in result.source_summary}
        self.assertEqual(summary_by_source["MSME"]["coverage_status"], "SOURCE_NOT_DISCOVERED")
        self.assertEqual(result.overall_summary["master_candidate_count"], 6)
        self.assertEqual(result.overall_summary["terminal_master_count"], 2)
        self.assertAlmostEqual(result.overall_summary["overall_coverage_percentage"], 33.33, places=2)

    def test_output_files_are_created(self) -> None:
        paths = AuditPaths.from_project_root(self.root)
        result = run_audit(paths, include_legacy=False)
        written = write_outputs(result, paths.output_dir)
        for output_path in written.values():
            self.assertTrue(Path(output_path).exists(), output_path)
        summary = json.loads((paths.output_dir / "coverage_audit_summary_v2_6.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["read_only"])
        self.assertEqual(summary["audit_version"], "2.6.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
