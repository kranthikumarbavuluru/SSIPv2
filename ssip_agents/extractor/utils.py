from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_WHITESPACE_RE = re.compile(r"\s+")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def unique_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = normalize_space(item)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def short_quote(value: str, limit: int = 420) -> str:
    value = normalize_space(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def sentence_chunks(text: str, min_chars: int = 20) -> list[str]:
    text = normalize_space(text)
    if not text:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
    return [
        normalize_space(chunk)
        for chunk in chunks
        if len(normalize_space(chunk)) >= min_chars
    ]


def slugify(value: str, max_length: int = 80) -> str:
    value = normalize_space(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:max_length] or "record"
