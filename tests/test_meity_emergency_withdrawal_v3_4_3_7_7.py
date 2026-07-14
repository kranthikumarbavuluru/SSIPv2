from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_emergency_withdrawal_v3_4_3_7_7 import (
    TARGET_IDS,
    MeitYEmergencyWithdrawal,
    WithdrawalPaths,
    classify,
)


class MeitYEmergencyWithdrawalTests(unittest.TestCase):
    def test_exact_target_population_is_frozen(self) -> None:
        self.assertEqual(len(TARGET_IDS), 16)
        self.assertEqual(len(set(TARGET_IDS)), 16)

    def test_raw_document_is_detected(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
              'samridh%202nd%20cohort%20om%20final.pdf'
                AS scheme_name,
              'https://msh.meity.gov.in/a.pdf'
                AS official_page_url,
              'VERIFICATION_REQUIRED' AS application_status,
              '{}' AS raw_record_json
            """
        ).fetchone()
        result = classify(row)
        self.assertEqual(result[0], "RAW_DOCUMENT")

    def test_directory_is_detected(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
              'Challenges' AS scheme_name,
              'https://msh.meity.gov.in/challenges'
                AS official_page_url,
              'VERIFICATION_REQUIRED' AS application_status,
              '{}' AS raw_record_json
            """
        ).fetchone()
        result = classify(row)
        self.assertEqual(result[0], "NAVIGATION_OR_DIRECTORY")

    def test_call_identity_is_not_republication_approval(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        payload = json.dumps(
            {
                "evidence_excerpt": (
                    "A grand challenge and hackathon for startups."
                )
            }
        )
        row = connection.execute(
            """
            SELECT
              'DRISHTI' AS scheme_name,
              'https://msh.meity.gov.in/program/drishti'
                AS official_page_url,
              'VERIFICATION_REQUIRED' AS application_status,
              ? AS raw_record_json
            """,
            (payload,),
        ).fetchone()
        result = classify(row)
        self.assertEqual(result[0], "VALID_CALL_INSTANCE")
        self.assertIn("status and dates remain unverified", result[1])


if __name__ == "__main__":
    unittest.main()
