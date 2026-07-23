from __future__ import annotations

import ast
import unittest
from pathlib import Path


class MeitYLinkIntegrityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_link_integrity_review_v3_4_3_8_0_4.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_only_verified_application_url_is_clickable(self) -> None:
        self.assertIn('app_url = child.get("verified_application_url"', self.text)
        self.assertIn('"Open verified application route"', self.text)
        self.assertNotIn(
            'st.link_button(\n            "Inspect official application route",\n            application_url',
            self.text,
        )

    def test_withheld_application_route_is_disabled(self) -> None:
        self.assertIn('"Application route withheld"', self.text)
        self.assertIn("disabled=True", self.text)
        self.assertIn("application_route_withheld_reason", self.text)

    def test_provenance_fields_are_visible(self) -> None:
        for marker in (
            "Final page role",
            "Final redirected URL",
            "Source child",
            "Source field",
            "Last checked",
            "Entity match",
        ):
            self.assertIn(marker, self.text)

    def test_positive_decision_requires_link_integrity(self) -> None:
        self.assertIn("safe_positive_decision_allowed", self.text)
        self.assertIn("positive_ready", self.text)
        self.assertIn("disabled=not save_ready", self.text)

    def test_session_invalidates_on_link_signature_change(self) -> None:
        self.assertIn("session_state_signature", self.text)
        self.assertIn("Earlier session decisions were cleared", self.text)
        self.assertIn("link_integrity_signature", self.text)

    def test_raw_application_url_only_appears_in_audit_tab(self) -> None:
        self.assertIn("Withheld Application Routes", self.text)
        self.assertIn(
            "These raw URLs are visible only for audit",
            self.text,
        )
        self.assertIn(
            "as public or Admin application buttons.",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
