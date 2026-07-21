from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from services.meity_complete_intelligence_v3_4_3_8_0 import (
    BrowserRenderer,
    MeitYCompleteIntelligence,
    PipelinePaths,
    classify_entity,
    determine_status,
    extract_js_urls,
    load_config,
)


class MeitYCompleteIntelligenceTests(
    unittest.TestCase
):
    def test_javascript_api_and_document_urls_are_discovered(
        self,
    ) -> None:
        script = (
            'fetch("/api/v1/challenges"); '
            'const file="/uploads/code-for-consent.pdf"; '
            'const x="https://msh.meity.gov.in/schemes/samridh";'
        )
        urls = extract_js_urls(
            script,
            "https://msh.meity.gov.in/main.js",
        )
        self.assertIn(
            "https://msh.meity.gov.in/api/v1/challenges",
            urls,
        )
        self.assertIn(
            "https://msh.meity.gov.in/uploads/code-for-consent.pdf",
            urls,
        )
        self.assertIn(
            "https://msh.meity.gov.in/schemes/samridh",
            urls,
        )

    def test_result_notice_is_not_classified_as_open_call(
        self,
    ) -> None:
        entity_type, _, _ = classify_entity(
            "Results of Code for Consent: "
            "The DPDP Innovation Challenge",
            (
                "Winner Baldor Technologies. "
                "Runner-up Jio Platforms Limited."
            ),
            "https://msh.meity.gov.in/result.pdf",
            "application/pdf",
        )
        self.assertEqual(
            entity_type,
            "RESULT_ANNOUNCEMENT",
        )
        status, _, _ = determine_status(
            entity_type,
            "Winner and runner-up announced.",
            "",
            "",
            "",
            date(2026, 7, 14),
        )
        self.assertEqual(
            status,
            "HISTORICAL_CLOSED",
        )

    def test_open_requires_deadline_and_application_route(
        self,
    ) -> None:
        status, _, flags = determine_status(
            "CHALLENGE_CALL",
            "Applications are invited. Apply now.",
            "",
            "",
            "",
            date(2026, 7, 14),
        )
        self.assertEqual(
            status,
            "VERIFICATION_REQUIRED",
        )
        self.assertIn(
            "OPEN_DEADLINE_NOT_VERIFIED",
            flags,
        )
        self.assertIn(
            "OPEN_APPLICATION_ROUTE_NOT_VERIFIED",
            flags,
        )

        status, _, flags = determine_status(
            "CHALLENGE_CALL",
            (
                "Applications are invited. "
                "Apply now. Last date to apply "
                "31 December 2026."
            ),
            "https://msh.meity.gov.in/apply/challenge",
            "",
            "2026-12-31",
            date(2026, 7, 14),
        )
        self.assertEqual(status, "OPEN")
        self.assertEqual(flags, [])

    def test_programme_and_call_are_distinct_entities(
        self,
    ) -> None:
        programme, _, _ = classify_entity(
            "SAMRIDH",
            (
                "A permanent startup accelerator "
                "programme providing growth support."
            ),
            "https://msh.meity.gov.in/schemes/samridh",
            "text/html",
        )
        cohort, _, _ = classify_entity(
            "SAMRIDH Cohort 2",
            (
                "Call for applications for Cohort 2. "
                "Applications are invited."
            ),
            "https://msh.meity.gov.in/whatsnew/samridh-cohort-2",
            "text/html",
        )
        self.assertIn(
            programme,
            {
                "ACCELERATOR_PROGRAMME",
                "PERMANENT_PROGRAMME",
            },
        )
        self.assertEqual(
            cohort,
            "ACCELERATOR_COHORT",
        )

    def test_repository_only_end_to_end_never_writes_database(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "config").mkdir()
            (project / "database").mkdir()
            evidence_dir = (
                project
                / "data/departments/meity/v3_4_3_7_5"
            )
            evidence_dir.mkdir(parents=True)

            source_config = (
                Path(__file__).resolve().parents[1]
                / "config/meity_complete_intelligence_v3_4_3_8_0.json"
            )
            config_path = (
                project
                / "config/meity_complete_intelligence_v3_4_3_8_0.json"
            )
            config_path.write_text(
                source_config.read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )

            database_path = (
                project
                / "database/ssip_staging_v1.db"
            )
            connection = sqlite3.connect(
                database_path
            )
            connection.execute(
                """
                CREATE TABLE scheme_staging (
                    master_id TEXT PRIMARY KEY,
                    scheme_name TEXT,
                    source TEXT,
                    ministry TEXT,
                    record_kind TEXT,
                    programme_status TEXT,
                    application_status TEXT,
                    publication_status TEXT,
                    is_public INTEGER,
                    official_page_url TEXT,
                    application_url TEXT,
                    raw_record_json TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO scheme_staging
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "genesis_master",
                    "GENESIS",
                    "MeitY Startup Hub",
                    (
                        "Ministry of Electronics and "
                        "Information Technology (MeitY)"
                    ),
                    "SCHEME_PROGRAMME",
                    "SCHEME_INFORMATION_AVAILABLE",
                    "NOT_APPLICABLE",
                    "PUBLISHED",
                    1,
                    "https://msh.meity.gov.in/schemes/genesis",
                    "",
                    "{}",
                ),
            )
            connection.commit()
            connection.close()

            prior_path = (
                evidence_dir
                / "fixture_candidates.csv"
            )
            with prior_path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "master_id",
                        "canonical_name",
                        "official_source_url",
                        "evidence_excerpt",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "master_id": "fixture_genesis",
                        "canonical_name": "GENESIS",
                        "official_source_url": (
                            "https://msh.meity.gov.in/schemes/genesis"
                        ),
                        "evidence_excerpt": (
                            "Permanent startup support scheme."
                        ),
                    }
                )
                writer.writerow(
                    {
                        "master_id": "fixture_samridh",
                        "canonical_name": "SAMRIDH",
                        "official_source_url": (
                            "https://msh.meity.gov.in/schemes/samridh"
                        ),
                        "evidence_excerpt": (
                            "Permanent startup accelerator programme "
                            "providing funding support."
                        ),
                    }
                )
                writer.writerow(
                    {
                        "master_id": "fixture_result",
                        "canonical_name": (
                            "Results of Code for Consent: "
                            "The DPDP Innovation Challenge"
                        ),
                        "official_source_url": (
                            "https://msh.meity.gov.in/uploads/result.pdf"
                        ),
                        "evidence_excerpt": (
                            "Winner Baldor Technologies. "
                            "Runner-up Jio Platforms Limited."
                        ),
                    }
                )

            before = hashlib.sha256(
                database_path.read_bytes()
            ).hexdigest()
            paths = PipelinePaths.defaults(
                project
            )
            service = MeitYCompleteIntelligence(
                paths,
                load_config(
                    paths.config_path
                ),
            )
            manifest = service.run(
                live_network=False
            )
            after = hashlib.sha256(
                database_path.read_bytes()
            ).hexdigest()

            self.assertEqual(before, after)
            self.assertFalse(
                manifest[
                    "database_write_performed"
                ]
            )
            self.assertFalse(
                manifest[
                    "publication_performed"
                ]
            )
            self.assertGreaterEqual(
                manifest[
                    "programme_candidate_count"
                ],
                2,
            )
            self.assertGreaterEqual(
                manifest[
                    "historical_call_result_count"
                ],
                1,
            )
            self.assertTrue(
                (
                    project
                    / "data/departments/meity/v3_4_3_8_0/"
                    "meity_admin_review_preview_v3_4_3_8_0.csv"
                ).exists()
            )

    def test_browser_capability_is_detectable(
        self,
    ) -> None:
        renderer = BrowserRenderer(10)
        self.assertIsInstance(
            renderer.executable,
            str,
        )


if __name__ == "__main__":
    unittest.main()
