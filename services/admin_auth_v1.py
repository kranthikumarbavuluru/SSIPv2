"""Small, dependency-free authentication helpers for the SSIP admin surface.

The public catalogue remains read-only.  Admin credentials are deliberately
loaded from process configuration instead of the repository so deployments can
provide a secret without changing code or committing credentials.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass


ADMIN_SESSION_KEY = "ssip_admin_authenticated"
ADMIN_FAILURE_COUNT_KEY = "ssip_admin_failed_attempts"
ADMIN_PASSWORD_ENV = "SSIP_ADMIN_PASSWORD"
ADMIN_PASSWORD_HASH_ENV = "SSIP_ADMIN_PASSWORD_HASH"
ADMIN_WORKSPACE_URL_ENV = "SSIP_ADMIN_WORKSPACE_URL"
DEFAULT_ADMIN_WORKSPACE_URL = "http://localhost:8505"


@dataclass(frozen=True)
class AdminAuthConfig:
    """Non-sensitive admin-auth configuration exposed to the UI."""

    secret_configured: bool
    workspace_url: str


def _configured_password() -> str:
    return os.environ.get(ADMIN_PASSWORD_ENV, "").strip()


def _configured_password_hash() -> str:
    return os.environ.get(ADMIN_PASSWORD_HASH_ENV, "").strip()


def admin_auth_config() -> AdminAuthConfig:
    """Return safe-to-display configuration state without exposing secrets."""

    workspace_url = os.environ.get(
        ADMIN_WORKSPACE_URL_ENV,
        DEFAULT_ADMIN_WORKSPACE_URL,
    ).strip() or DEFAULT_ADMIN_WORKSPACE_URL
    return AdminAuthConfig(
        secret_configured=bool(_configured_password() or _configured_password_hash()),
        workspace_url=workspace_url,
    )


def _verify_pbkdf2(candidate: str, encoded: str) -> bool:
    """Verify ``pbkdf2_sha256$iterations$salt$checksum`` values.

    The hash format is intentionally simple to generate with Python's standard
    library and keeps plaintext credentials out of deployment configuration.
    """

    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = base64.urlsafe_b64decode(parts[2] + "===")
        expected = base64.urlsafe_b64decode(parts[3] + "===")
    except (binascii.Error, ValueError, TypeError):
        return False
    if iterations < 100_000 or not salt or not expected:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        candidate.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def verify_admin_password(candidate: str) -> bool:
    """Verify a submitted password using a configured process secret."""

    value = str(candidate or "")
    configured_hash = _configured_password_hash()
    if configured_hash:
        return _verify_pbkdf2(value, configured_hash)

    configured_password = _configured_password()
    if not configured_password:
        return False
    return hmac.compare_digest(value, configured_password)


def mark_authenticated(session_state: object) -> None:
    """Mark the current Streamlit session as authenticated."""

    session_state[ADMIN_SESSION_KEY] = True
    session_state[ADMIN_FAILURE_COUNT_KEY] = 0


def clear_authenticated(session_state: object) -> None:
    """Clear the current Streamlit admin session."""

    session_state.pop(ADMIN_SESSION_KEY, None)
    session_state.pop(ADMIN_FAILURE_COUNT_KEY, None)


def is_authenticated(session_state: object) -> bool:
    return bool(session_state.get(ADMIN_SESSION_KEY, False))


def register_failed_attempt(session_state: object) -> int:
    """Increment and return the current session's failed-attempt count."""

    count = int(session_state.get(ADMIN_FAILURE_COUNT_KEY, 0) or 0) + 1
    session_state[ADMIN_FAILURE_COUNT_KEY] = count
    return count


def make_pbkdf2_password_hash(password: str, *, iterations: int = 600_000) -> str:
    """Create a deployable PBKDF2 hash for an admin password.

    This helper is intended for one-time local setup; callers should store only
    its return value in ``SSIP_ADMIN_PASSWORD_HASH``.
    """

    if not password:
        raise ValueError("Password cannot be empty")
    if iterations < 100_000:
        raise ValueError("PBKDF2 iterations must be at least 100000")
    salt = os.urandom(16)
    checksum = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${iterations}${encode(salt)}${encode(checksum)}"
