from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from ssip_dashboard.analytics import build_public_analytics


ROOT = Path(__file__).resolve().parents[1]


def record(**overrides):
    defaults = {
        "master_id": "scheme-1",
        "scheme_name": "Governed Scheme",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "normalized_record_kind": "SCHEME_OR_PROGRAMME",
        "current_decision": "APPROVED",
        "ministry": "Ministry A",
        "department": "Department A",
        "implementing_agency": "Agency A",
        "source": "Official Source A",
        "government_level": "Central Government",
        "official_page_url": "https://example.gov.in/scheme",
        "sectors": ["Deep Technology"],
        "scheme_types": ["GRANT"],
        "application_status": "",
        "catalogue_section": "",
        "catalogue_inclusion": "",
        "opening_date": "",
        "closing_date": "",
        "funding_minimum": None,
        "funding_maximum": 1_000_000,
        "last_verified_at": "2026-07-10T10:30:00+05:30",
        "last_updated": "2026-07-09",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PublicDashboardAnalyticsTest(unittest.TestCase):
    def test_snapshot_separates_schemes_calls_and_statuses(self) -> None:
        records = [
            record(master_id="scheme-1"),
            record(
                master_id="scheme-2",
                scheme_name="Incomplete Scheme",
                ministry="",
                department="",
                sectors=[],
                scheme_types=[],
                funding_maximum=None,
                government_level="State Government",
            ),
            record(
                master_id="call-open",
                scheme_name="Open Challenge",
                record_kind="APPLICATION_CALL",
                normalized_record_kind="APPLICATION_CALL",
                application_status="OPEN",
                closing_date="",
            ),
            record(
                master_id="call-soon",
                scheme_name="Closing Challenge",
                record_kind="CHALLENGE",
                normalized_record_kind="CHALLENGE",
                application_status="OPEN",
                closing_date=(date.today() + timedelta(days=8)).isoformat(),
            ),
            record(
                master_id="call-review",
                scheme_name="Unverified Call",
                record_kind="APPLICATION_CALL",
                normalized_record_kind="APPLICATION_CALL",
                application_status="STATUS_UNVERIFIED",
                last_verified_at="2026-07-12T08:00:00+05:30",
            ),
        ]

        snapshot = build_public_analytics(records)

        self.assertEqual(snapshot.scheme_count, 2)
        self.assertEqual(snapshot.call_count, 3)
        self.assertEqual(snapshot.open_call_windows, 2)
        self.assertEqual(snapshot.closing_soon_calls, 1)
        self.assertEqual(snapshot.verification_required_calls, 1)
        self.assertEqual(snapshot.call_statuses["OPEN"], 1)
        self.assertEqual(snapshot.call_statuses["CLOSING_SOON"], 1)
        self.assertEqual(snapshot.call_statuses["VERIFICATION_REQUIRED"], 1)
        self.assertEqual(snapshot.latest_verification_signal, "2026-07-12")

    def test_snapshot_reports_readiness_without_inference(self) -> None:
        snapshot = build_public_analytics([
            record(master_id="complete"),
            record(
                master_id="incomplete",
                scheme_name="Incomplete Scheme",
                ministry="",
                department="",
                sectors=[],
                scheme_types=[],
                funding_maximum=None,
            ),
        ])
        readiness = {item.label: item for item in snapshot.readiness}

        self.assertEqual(readiness["Ministry mapped"].complete, 1)
        self.assertEqual(readiness["Department mapped"].complete, 1)
        self.assertEqual(readiness["Sector evidenced"].complete, 1)
        self.assertEqual(readiness["Funding structured"].complete, 1)
        self.assertEqual(readiness["Official page linked"].complete, 2)
        self.assertEqual(readiness["Sector evidenced"].percentage, 50)
        self.assertEqual(snapshot.structured_sectors, {"Deep Technology": 1})
        self.assertNotIn("Sector Not Specified", snapshot.structured_sectors)
        self.assertNotIn("SUPPORT_TYPE_NOT_SPECIFIED", snapshot.structured_support_types)

    def test_snapshot_includes_separately_published_department_verification_dates(self) -> None:
        snapshot = build_public_analytics(
            [record()],
            additional_verification_dates=("2026-07-21", "not-a-date", ""),
        )

        self.assertEqual(snapshot.latest_verification_signal, "2026-07-21")

    def test_dashboard_uses_accessible_non_donut_analytics(self) -> None:
        app = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        css = (ROOT / "assets" / "dashboard_theme.css").read_text(encoding="utf-8")

        self.assertIn('role="progressbar"', app)
        self.assertIn('role="img"', app)
        self.assertIn("Application Call Status", app)
        self.assertIn("Catalogue Data Readiness", app)
        self.assertIn("Verified Sector Coverage", app)
        self.assertNotIn("render_donut(", app)
        self.assertIn(".analytics-primary-grid", css)
        self.assertIn(".data-quality-callout", css)
        self.assertIn("@media (max-width: 920px)", css)


if __name__ == "__main__":
    unittest.main()
