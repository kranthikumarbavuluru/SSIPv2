from __future__ import annotations

import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from services.admin_auth_v1 import (
    ADMIN_PASSWORD_ENV,
    ADMIN_PASSWORD_HASH_ENV,
    admin_auth_config,
    make_pbkdf2_password_hash,
    verify_admin_password,
)


ROOT = Path(__file__).resolve().parents[1]


class AdminAuthV1Tests(TestCase):
    def test_plaintext_secret_is_external_and_constant_time_verified(self) -> None:
        with patch.dict(os.environ, {ADMIN_PASSWORD_ENV: "local-test-secret"}, clear=False):
            os.environ.pop(ADMIN_PASSWORD_HASH_ENV, None)
            self.assertTrue(admin_auth_config().secret_configured)
            self.assertTrue(verify_admin_password("local-test-secret"))
            self.assertFalse(verify_admin_password("wrong-secret"))

    def test_pbkdf2_secret_is_supported_without_plaintext(self) -> None:
        encoded = make_pbkdf2_password_hash("hashed-test-secret", iterations=100_000)
        with patch.dict(os.environ, {ADMIN_PASSWORD_HASH_ENV: encoded}, clear=False):
            os.environ.pop(ADMIN_PASSWORD_ENV, None)
            self.assertTrue(verify_admin_password("hashed-test-secret"))
            self.assertFalse(verify_admin_password("wrong-secret"))

    def test_missing_secret_disables_login(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(admin_auth_config().secret_configured)
            self.assertFalse(verify_admin_password("anything"))

    def test_public_and_operational_entry_points_are_gated(self) -> None:
        public = (ROOT / "apps/public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        admin = (ROOT / "ui/admin_review_app_v1.py").read_text(encoding="utf-8-sig")
        self.assertIn('"Admin Login"', public)
        self.assertIn('"admin/login"', public)
        self.assertIn('href="?page=admin/login"', public)
        self.assertIn("verify_admin_password", public)
        self.assertIn("verify_admin_password", admin)
        self.assertNotIn("local-test-secret", public)
        self.assertNotIn("local-test-secret", admin)


if __name__ == "__main__":
    import unittest

    unittest.main()
