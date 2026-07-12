from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def clean(value: Any) -> str:
    if value is None:
        return ""
    value = unquote(str(value))
    return re.sub(r"\s+", " ", value).strip()

def low(value: Any) -> str:
    return clean(value).casefold()

ALIASES = {
    "id": ["master_id", "scheme_master_id", "record_id", "id"],
    "name": ["canonical_name", "scheme_name", "programme_name", "name", "title"],
    "objective": ["objective", "objectives", "description", "summary", "scheme_objective"],
    "eligibility": ["eligibility", "eligible_beneficiaries", "who_can_apply"],
    "benefits": ["benefits", "benefit", "support", "funding_details"],
    "official_url": ["official_url", "official_page", "source_url", "final_url", "best_available_url"],
    "application_url": ["application_url", "apply_url", "application_portal"],
    "department": ["department", "source", "agency"],
    "ministry": ["ministry", "ministry_name"],
    "record_type": ["record_type", "master_type", "programme_type"],
    "status": ["publication_status", "database_status", "status"],
    "sector": ["sector", "primary_sector", "sectors", "sector_name"],
    "support_type": ["support_type", "grant_support_type", "scheme_type"],
}

def find_column(fieldnames: Iterable[str], key: str) -> str | None:
    mapping = {x.casefold(): x for x in fieldnames}
    for alias in ALIASES[key]:
        if alias.casefold() in mapping:
            return mapping[alias.casefold()]
    return None

def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(r) for r in reader], list(reader.fieldnames or [])

def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

def ensure_fields(fieldnames: list[str], names: list[str]) -> None:
    for name in names:
        if name not in fieldnames:
            fieldnames.append(name)

def backup_file(source: Path, backup_dir: Path) -> Path | None:
    if not source.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / source.name
    shutil.copy2(source, dest)
    return dest

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def normalized_identity(name: str) -> str:
    value = clean(name)
    value = re.sub(r"\.(pdf|html?|aspx?|xml)$", "", value, flags=re.I)
    value = re.sub(r"\b(landing|official page|homepage)\b", "", value, flags=re.I)
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).casefold()
    return re.sub(r"\s+", " ", value).strip()

def hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").casefold()
    except Exception:
        return ""
