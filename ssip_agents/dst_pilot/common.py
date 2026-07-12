from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def low(value: Any) -> str:
    return clean(value).casefold()


def stable_id(prefix: str, *parts: Any) -> str:
    material = "\x1f".join(clean(part).casefold() for part in parts if clean(part))
    return f"{prefix}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
