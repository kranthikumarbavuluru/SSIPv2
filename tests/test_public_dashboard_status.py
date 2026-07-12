from __future__ import annotations

from datetime import date
import unittest
from types import SimpleNamespace

from ssip_dashboard.status import status_bucket


class PublicDashboardStatusTest(unittest.TestCase):
    def test_open_excludes_closed_and_historical(self) -> None:
        open_record = SimpleNamespace(application_status="OPEN", catalogue_section="", catalogue_inclusion="", opening_date="")
        closed_record = SimpleNamespace(application_status="CLOSED", catalogue_section="CLOSED_OPPORTUNITIES", catalogue_inclusion="ARCHIVED", opening_date="")
        historical_record = SimpleNamespace(application_status="CLOSED_OR_DEADLINE_PASSED", catalogue_section="HISTORICAL_PROGRAMMES", catalogue_inclusion="ARCHIVED", opening_date="")
        self.assertEqual(status_bucket(open_record), "OPEN")
        self.assertEqual(status_bucket(closed_record), "CLOSED")
        self.assertEqual(status_bucket(historical_record), "HISTORICAL")

    def test_pending_revalidation_requires_verification(self) -> None:
        record = SimpleNamespace(application_status="", catalogue_section="", catalogue_inclusion="PENDING_REVALIDATION", opening_date="")
        self.assertEqual(status_bucket(record), "VERIFICATION_REQUIRED")

    def test_future_opening_date_is_upcoming(self) -> None:
        record = SimpleNamespace(application_status="", catalogue_section="", catalogue_inclusion="", opening_date="2026-08-01")
        self.assertEqual(status_bucket(record, today=date(2026, 7, 9)), "UPCOMING")

    def test_closing_soon_is_separate_from_open(self) -> None:
        record = SimpleNamespace(
            application_status="OPEN",
            catalogue_section="",
            catalogue_inclusion="",
            opening_date="",
            closing_date="2026-07-20",
        )
        self.assertEqual(status_bucket(record, today=date(2026, 7, 9), closing_soon_days=30), "CLOSING_SOON")

    def test_expired_deadline_is_not_open(self) -> None:
        record = SimpleNamespace(
            application_status="OPEN",
            catalogue_section="",
            catalogue_inclusion="",
            opening_date="",
            closing_date="2026-07-01",
        )
        self.assertEqual(status_bucket(record, today=date(2026, 7, 9)), "CLOSED")


if __name__ == "__main__":
    unittest.main()
