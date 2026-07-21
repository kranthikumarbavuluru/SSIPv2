from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from ssip_dashboard.meity_public_integrated_v3_4_3_8_1 import (
    partition_meity_department_view,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/public_dashboard_app_v2_9.py"


@dataclass
class Record:
    scheme_name: str
    source: str = "MeitY"
    ministry: str = ""
    department: str = ""
    implementing_agency: str = ""
    record_kind: str = "SCHEME_OR_PROGRAMME"
    application_status: str = ""
    application_url: str = ""
    publication_status: str = "STAGED"
    is_public: int = 0


class SeparatePageProjectionTests(unittest.TestCase):
    def test_meity_department_view_includes_preview_without_apply(self) -> None:
        preview = Record(
            scheme_name="Preview scheme",
            application_url="https://example.gov/apply",
        )
        published = Record(
            scheme_name="Published scheme",
            publication_status="PUBLISHED",
            is_public=1,
        )
        result = partition_meity_department_view([preview, published])
        self.assertEqual(len(result["programmes"]), 2)
        projected = next(
            item for item in result["programmes"]
            if item.scheme_name == "Preview scheme"
        )
        self.assertEqual(projected.application_url, "")

    def test_meity_department_view_keeps_closed_calls_visible(self) -> None:
        closed = Record(
            scheme_name="Historical challenge",
            record_kind="CHALLENGE",
            application_status="CLOSED",
        )
        result = partition_meity_department_view([closed])
        self.assertEqual([item.scheme_name for item in result["calls"]], [
            "Historical challenge"
        ])

    def test_home_route_is_unchanged_and_separate_pages_use_projection(self) -> None:
        text = APP.read_text(encoding="utf-8-sig")
        ast.parse(text)
        self.assertIn('if page == "Home":\n        render_home(bundle, official_sources)', text)
        self.assertIn("_calls_for_separate_verification_page(bundle)", text)
        self.assertIn("render_meity_page(bundle)", text)


if __name__ == "__main__":
    unittest.main()
