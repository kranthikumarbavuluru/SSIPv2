from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


PUBLIC_RELEVANCE_CLASSES = {
    "DIRECT_STARTUP_SCHEME",
    "STARTUP_ACCESS_PROGRAMME",
    "MSME_SUPPORT_RELEVANT",
}
MASTER_ROLES = {"SCHEME_MASTER", "PROGRAMME_MASTER"}
DOCUMENT_ROLES = {"SUPPORTING_DOCUMENT", "GUIDELINE_OR_NOTIFICATION"}
MAIN_RECORD_KINDS = {
    "SCHEME_OR_PROGRAMME", "GRANT", "FUND", "CREDIT_SUPPORT",
    "CREDIT_GUARANTEE", "SUBSIDY", "INCENTIVE", "FELLOWSHIP",
    "INCUBATION_SUPPORT", "ACCELERATOR_SUPPORT", "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT", "PROCUREMENT_SUPPORT", "INDIRECT_FINANCIAL_SUPPORT",
    "UMBRELLA_PROGRAMME",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{os.urandom(4).hex()}"


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unquote(str(value))).strip()


def low(value: Any) -> str:
    return clean(value).casefold()


def split_values(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[;|]", text) if item.strip()]


def first(row: dict[str, Any], *names: str) -> str:
    folded = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        value = clean(folded.get(name.casefold(), ""))
        if value:
            return value
    return ""


def row_text(row: dict[str, Any]) -> str:
    fields = (
        "scheme_name", "canonical_name", "title", "objectives", "objective",
        "eligibility", "benefits", "application_process", "target_beneficiaries",
        "scheme_type", "record_kind", "sector_evidence", "status_evidence",
    )
    return " ".join(first(row, field) for field in fields if first(row, field))


def hostname(url: str) -> str:
    try:
        return (urlparse(clean(url)).hostname or "").casefold().strip(".")
    except ValueError:
        return ""


def trusted_hostname(host: str, allowed_domains: Iterable[str]) -> bool:
    value = host.casefold().strip(".")
    return any(
        value == domain.casefold().strip(".")
        or value.endswith("." + domain.casefold().strip("."))
        for domain in allowed_domains
    )


def canonical_key(value: str) -> str:
    text = low(value)
    text = re.sub(r"\.(?:pdf|docx?|xlsx?|html?|aspx?|xml)$", "", text)
    text = re.sub(r"\b(?:landing|official page|homepage)\b", "", text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(canonical_key(part) for part in parts if clean(part))
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def union_fields(base: list[str], rows: Iterable[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    known: set[str] = set()
    for key in base:
        if key not in known:
            known.add(key)
            fields.append(key)
    for row in rows:
        for key in row:
            if key not in known:
                known.add(key)
                fields.append(key)
    return fields


def dashboard_public_ids(project_root: Path, active_path: Path) -> set[str]:
    """Return the same main-scheme population used by the existing dashboard."""
    expected = (project_root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv").resolve()
    if active_path.resolve() == expected and (project_root / "ssip_dashboard").is_dir():
        from ssip_dashboard.catalogue import load_catalogue
        from ssip_dashboard.catalogue_populations import split_catalogue_populations
        from ssip_dashboard.config import DashboardConfig

        config = DashboardConfig.from_env(project_root)
        populations = split_catalogue_populations(load_catalogue(config).records)
        return {record.master_id for record in populations.main_scheme_records if record.master_id}

    rows, _ = read_csv(active_path)
    return {
        first(row, "master_id", "scheme_master_id")
        for row in rows
        if first(row, "master_id", "scheme_master_id")
        and first(row, "normalized_record_kind", "record_kind").upper() in MAIN_RECORD_KINDS
        and first(row, "current_decision").upper() != "REJECTED"
    }
