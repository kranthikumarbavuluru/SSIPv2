from __future__ import annotations

import ast
import unittest
from pathlib import Path

from ssip_dashboard.dst_history import (
    RELEVANCE_ORDER,
    load_dst_historical_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "apps/public_dashboard_app_v2_9.py"


class DSTDepartmentAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = APP_PATH.read_text(encoding="utf-8-sig")
        cls.tree = ast.parse(cls.text)
        cls.archive = load_dst_historical_archive(PROJECT_ROOT)

    def test_dashboard_is_valid_python(self) -> None:
        self.assertIsNotNone(self.tree)

    def test_dst_page_has_three_department_tabs(self) -> None:
        for marker in (
            '"DST Schemes"',
            '"Current DST Calls"',
            '"DST Historical Archive"',
        ):
            self.assertIn(marker, self.text)

    def test_dst_hero_matches_meity_department_pattern(self) -> None:
        for marker in (
            '"DST Schemes & Calls"',
            '"Permanent programmes"',
            '"Open calls"',
            '"Upcoming"',
            '"Historical calls"',
        ):
            self.assertIn(marker, self.text)

    def test_historical_relevance_categories_reconcile(self) -> None:
        manifest = self.archive.manifest
        records = self.archive.historical_records
        counts = manifest["relevance_counts"]
        self.assertEqual(
            tuple(counts),
            RELEVANCE_ORDER,
        )
        self.assertEqual(
            sum(counts.values()),
            len(records),
        )
        self.assertEqual(
            manifest["qualified_historical_calls"],
            len(records),
        )
        self.assertGreaterEqual(len(records), 300)

    def test_review_required_is_visible_in_archive_metrics(self) -> None:
        for marker in (
            '"Relevance Review"',
            'relevance_counts["REVIEW_REQUIRED"]',
            "Category reconciliation:",
        ):
            self.assertIn(marker, self.text)

    def test_live_calls_no_longer_embeds_dst_archive(self) -> None:
        start = self.text.index(
            "def render_calls_and_opportunities() -> None:"
        )
        end = self.text.index(
            "def render_startup_ecosystem() -> None:",
            start,
        )
        block = self.text[start:end]
        self.assertNotIn('"HISTORICAL_ARCHIVE"', block)
        self.assertNotIn(
            "render_dst_historical_archive()",
            block,
        )
        self.assertIn(
            '["OPEN_CURRENT", "CLOSED_STARTUP"]',
            block,
        )

    def test_live_calls_links_to_department_archives(self) -> None:
        self.assertIn(
            'href="?page=dst-programmes"',
            self.text,
        )
        self.assertIn(
            'href="?page=meity-programmes"',
            self.text,
        )

    def test_historical_cards_do_not_show_apply(self) -> None:
        start = self.text.index(
            "def _historical_call_card("
        )
        end = self.text.index(
            "def render_dst_historical_archive() -> None:",
            start,
        )
        block = self.text[start:end]
        self.assertNotIn("Apply now", block)
        self.assertNotIn("application_url", block)
        self.assertIn(
            "Official historical call",
            block,
        )


if __name__ == "__main__":
    unittest.main()
