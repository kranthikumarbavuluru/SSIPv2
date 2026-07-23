from __future__ import annotations

import ast
import unittest
from datetime import date, timedelta
from pathlib import Path

from ssip_dashboard.catalogue import CatalogueRecord, load_catalogue
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.msme_public import (
    build_msme_public_bundle,
    filter_msme_records,
    is_official_msme_url,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/public_dashboard_app_v2_9.py"


def record(**overrides: object) -> CatalogueRecord:
    defaults: dict[str, object] = {
        "master_id": "msme-1",
        "scheme_name": "Governed MSME Support",
        "ministry": "Ministry of Micro, Small and Medium Enterprises",
        "department": "Ministry of Micro, Small and Medium Enterprises",
        "implementing_agency": "NSIC",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "application_status": "VERIFICATION_REQUIRED",
        "official_page_url": "https://www.nsic.co.in/Schemes/GovernedSupport",
        "application_url": "https://www.nsic.co.in/apply",
        "status_evidence": "",
    }
    defaults.update(overrides)
    return CatalogueRecord(**defaults)


class MSMEPublicProjectionTests(unittest.TestCase):
    def test_projection_separates_public_roles_and_fails_closed(self) -> None:
        records = [
            record(),
            record(
                master_id="current",
                scheme_name="Verified current challenge",
                record_kind="APPLICATION_CALL",
                application_status="OPEN",
                status_evidence="Official page states that applications are open.",
            ),
            record(
                master_id="unverified-call",
                scheme_name="Unverified challenge",
                record_kind="APPLICATION_CALL",
            ),
            record(
                master_id="expired-open-call",
                scheme_name="Expired open challenge",
                record_kind="APPLICATION_CALL",
                application_status="OPEN",
                closing_date=(date.today() - timedelta(days=1)).isoformat(),
                status_evidence="Official page once stated that applications were open.",
            ),
            record(
                master_id="historical",
                scheme_name="Historical credit support",
                record_kind="CREDIT_SUPPORT",
                application_status="CLOSED_OR_HISTORICAL",
            ),
            record(
                master_id="document",
                scheme_name="Operational Guidelines.Pdf",
                official_page_url="https://www.nsic.co.in/documents/guidelines.pdf",
            ),
            record(
                master_id="index",
                scheme_name="Schemes",
                official_page_url="https://www.msme.gov.in/schemes",
            ),
        ]

        bundle = build_msme_public_bundle(records)

        self.assertEqual([item.master_id for item in bundle.permanent_records], ["msme-1"])
        self.assertEqual([item.master_id for item in bundle.current_calls], ["current"])
        self.assertEqual([item.master_id for item in bundle.historical_records], ["historical"])
        self.assertEqual([item.master_id for item in bundle.documents], ["document"])
        self.assertEqual(bundle.excluded_count, 3)
        self.assertEqual(bundle.permanent_records[0].application_url, "")
        self.assertEqual(bundle.historical_records[0].application_url, "")
        self.assertEqual(bundle.current_calls[0].application_url, "https://www.nsic.co.in/apply")

    def test_official_host_matching_does_not_accept_lookalikes(self) -> None:
        self.assertTrue(is_official_msme_url("https://www.nsic.co.in/Schemes/Test"))
        self.assertTrue(is_official_msme_url("https://champions.gov.in/test"))
        self.assertTrue(is_official_msme_url("https://my.msme.gov.in/MyMsmeMob/MsmeScheme/MSME_Scheme.htm"))
        self.assertFalse(is_official_msme_url("https://nsic.co.in.example.com/test"))
        self.assertFalse(is_official_msme_url("javascript:alert(1)"))

    def test_filter_uses_keyword_agency_and_support_type(self) -> None:
        records = [
            record(master_id="credit", scheme_name="Credit Support", record_kind="CREDIT_SUPPORT"),
            record(master_id="marketing", scheme_name="Marketing Support", implementing_agency="MSME Ministry"),
        ]
        visible = filter_msme_records(
            records,
            keyword="credit",
            agency="NSIC",
            support_type="CREDIT_SUPPORT",
        )
        self.assertEqual([item.master_id for item in visible], ["credit"])

    def test_current_catalogue_projection_reconciles_all_msme_records(self) -> None:
        catalogue = load_catalogue(DashboardConfig.from_env(ROOT))
        bundle = build_msme_public_bundle(catalogue.records)

        self.assertGreaterEqual(len(bundle.permanent_records), 45)
        self.assertEqual(len(bundle.current_calls), 0)
        self.assertEqual(len(bundle.historical_records), 2)
        self.assertEqual(len(bundle.documents), 21)
        self.assertEqual(bundle.excluded_count, 16)
        self.assertEqual(
            len(bundle.public_records) + len(bundle.documents) + bundle.excluded_count,
            100,
        )
        self.assertEqual(bundle.latest_verification_date, "2026-07-22")
        self.assertEqual(sum(item.source == "AP MSME ONE" for item in bundle.permanent_records), 31)
        self.assertEqual(sum(item.source == "MyMSME Portal" for item in bundle.permanent_records), 16)


class MSMEDashboardSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8-sig")
        ast.parse(cls.source)

    def test_route_and_top_level_navigation_are_wired(self) -> None:
        self.assertIn('"MSME": "msme-schemes"', self.source)
        self.assertIn('PAGE_SLUG_ALIASES = {"msme-programmes": "MSME"}', self.source)
        self.assertIn('elif page == "MSME":', self.source)
        header = self.source[self.source.index("def site_header"):self.source.index("def page_intro")]
        primary = header[header.index("primary_pages"):header.index("links = []")]
        self.assertIn('"MSME"', primary)

    def test_page_uses_three_governed_public_views_without_admin_review(self) -> None:
        section = self.source[
            self.source.index("def render_msme_page"):
            self.source.index("def main()")
        ]
        for label in ("Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"):
            self.assertIn(label, section)
        self.assertNotIn("Admin Review", section)
        self.assertIn("build_msme_public_bundle", section)
        self.assertIn("Latest scheme verification", section)

    def test_documents_are_moved_to_shared_resources(self) -> None:
        resources = self.source[
            self.source.index("def render_resources"):
            self.source.index("def _dst_preview_notice")
        ]
        self.assertIn("msme_bundle.documents", resources)
        self.assertIn("msme_document_ids", resources)
        self.assertIn("Ministry of Micro, Small and Medium Enterprises", resources)

    def test_cards_use_safe_new_tab_links_and_no_historical_apply_action(self) -> None:
        card = self.source[
            self.source.index("def _msme_record_card"):
            self.source.index("def _render_msme_record_group")
        ]
        self.assertIn('target="_blank" rel="noopener noreferrer"', card)
        self.assertIn('record.application_url and status in {"OPEN", "UPCOMING"}', card)
        self.assertIn("No active application action", card)


if __name__ == "__main__":
    unittest.main()
