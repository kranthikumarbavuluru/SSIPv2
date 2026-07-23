from __future__ import annotations

import json
import sqlite3
import unittest

from scripts.publication_control_service_v2_7_3_4 import (
    call_specific_quality_gate,
    transition_for,
)


class MeitYPublicationControlsTests(unittest.TestCase):
    def _row(
        self,
        *,
        title: str,
        application_status: str,
        raw_record: dict,
        application_url: str = "",
        official_page_url: str = "https://msh.meity.gov.in/call/example",
    ) -> sqlite3.Row:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT
              'APPLICATION_CALL' AS record_kind,
              ? AS scheme_name,
              ? AS official_page_url,
              ? AS application_url,
              ? AS application_status,
              '' AS opening_date,
              '' AS closing_date,
              ? AS raw_record_json
            """,
            (
                title,
                official_page_url,
                application_url,
                application_status,
                json.dumps(raw_record),
            ),
        ).fetchone()

    def test_withdraw_transition_is_auditable(self) -> None:
        self.assertEqual(
            transition_for("withdraw-publication", "PUBLISHED"),
            ("UNPUBLISHED", 0),
        )

    def test_verification_required_call_is_blocked(self) -> None:
        row = self._row(
            title="DRISHTI",
            application_status="VERIFICATION_REQUIRED",
            raw_record={
                "parent_master_id": "parent",
                "parent_resolution": "CURATED_OFFICIAL_RELATIONSHIP",
                "applicant_layer": "STARTUP",
                "status_basis": "OFFICIAL_PAGE",
                "status_evidence": "Evidence",
            },
        )
        result = call_specific_quality_gate(row)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("status is not sufficiently verified" in item for item in result.blockers)
        )

    def test_generic_title_is_blocked(self) -> None:
        row = self._row(
            title="Challenges",
            application_status="CLOSED",
            official_page_url="https://msh.meity.gov.in/challenges",
            raw_record={
                "parent_resolution": "STANDALONE_OFFICIAL_CALL",
                "applicant_layer": "STARTUP",
                "status_basis": "HISTORICAL_DEADLINE",
                "status_evidence": "Closed historical call.",
                "closing_date": "2025-01-01",
            },
        )
        result = call_specific_quality_gate(row)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("identity is generic" in item for item in result.blockers)
        )


if __name__ == "__main__":
    unittest.main()
