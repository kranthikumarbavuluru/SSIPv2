from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.meity_calls_admin_bridge_v3_4_3_7_5 import (
    MeitYCallsAdminBridge,
    MeitYCallsBridgePaths,
    utc_now,
)


class MeitYCallsPlanSignatureHotfixTests(unittest.TestCase):
    def test_build_item_contains_no_runtime_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = MeitYCallsBridgePaths(
                project_root=root,
                source_queue_path=root / "unused.csv",
                database_path=root / "unused.db",
                report_dir=root / "reports",
            )
            bridge = MeitYCallsAdminBridge(paths)
            row = {
                "master_id": "meitycall_12345678901234567890",
                "canonical_name": "Example MeitY Challenge 2026",
                "record_kind": "APPLICATION_CALL",
                "permanent_scheme_or_call": "CALL_INSTANCE",
                "official_source_url": (
                    "https://msh.meity.gov.in/challenges/example-2026"
                ),
                "application_url": "",
                "opening_date": "",
                "deadline": "",
                "application_status": "VERIFICATION_REQUIRED",
                "status_basis": (
                    "INSUFFICIENT_CURRENT_STATUS_EVIDENCE"
                ),
                "status_evidence": "No verified current deadline.",
                "eligible_applicants": "",
                "applicant_layer": "REQUIRES_ADMIN_VERIFICATION",
                "startup_relevance": "DIRECT_OR_REVIEW_REQUIRED",
                "sector_scope": "UNKNOWN",
                "confidence": "0.750",
                "network_verified": "True",
                "verified_current": "False",
                "evidence_title": "Example MeitY Challenge 2026",
                "evidence_excerpt": "Official challenge evidence.",
                "parent_master_id": "",
                "parent_scheme_name": "",
                "parent_resolution": "STANDALONE_OFFICIAL_CALL",
                "quality_flags": "NO_PUBLIC_APPLY_ROUTE",
                "evidence_hash": "abc123",
            }

            first = bridge.build_item(row)
            second = bridge.build_item(row)

            self.assertIsNone(
                first["validated_record"]["last_verified_at"]
            )
            self.assertEqual(first, second)

    def test_runtime_clock_still_available_for_import_audit(self) -> None:
        self.assertTrue(utc_now())


if __name__ == "__main__":
    unittest.main()
