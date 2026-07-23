from __future__ import annotations

"""Save an immutable, read-only catalogue snapshot for v3.4.13.0."""

import csv
from dataclasses import asdict, fields
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ssip_dashboard.catalogue import CatalogueRecord, load_catalogue
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.config import DashboardConfig


VERSION = "3.4.13.0"
OUTPUT_DIR = ROOT / "data" / "releases" / "v3_4_13_0"
SNAPSHOT_NAME = "catalogue_snapshot_v3_4_13_0.csv"
MANIFEST_NAME = "release_manifest_v3_4_13_0.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_snapshot(records: list[CatalogueRecord], path: Path) -> None:
    fieldnames = [item.name for item in fields(CatalogueRecord)]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({key: csv_value(value) for key, value in asdict(record).items()})


def active_manifest_inventory() -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "data" / "departments").rglob("active_publication_manifest*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()
        department_path = path.parent.relative_to(ROOT / "data" / "departments")
        key = "_".join(department_path.parts[0::2])
        manifests[key] = {
            "path": relative,
            "version": payload.get("version", ""),
            "record_count": payload.get("record_count"),
            "sha256": sha256_file(path),
        }
    return manifests


def build_manifest() -> dict[str, Any]:
    bundle = load_catalogue(DashboardConfig.from_env(ROOT))
    populations = split_catalogue_populations(bundle.records)
    snapshot_path = OUTPUT_DIR / SNAPSHOT_NAME
    write_snapshot(bundle.records, snapshot_path)
    manifest = {
        "version": VERSION,
        "release_type": "GOVERNED_CATALOGUE_SNAPSHOT",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "snapshot_file": snapshot_path.relative_to(ROOT).as_posix(),
        "snapshot_sha256": sha256_file(snapshot_path),
        "catalogue_mode": bundle.mode.value,
        "counts": {
            "loaded_records": len(bundle.records),
            "schemes_and_programmes": len(populations.main_scheme_records),
            "application_calls": len(populations.application_call_records),
            "evidence_or_excluded": len(populations.evidence_only_records) + len(populations.excluded_records),
        },
        "latest_verification": max(
            (str(getattr(record, "last_verified_at", "") or getattr(record, "last_updated", ""))[:10]
             for record in bundle.records),
            default="",
        ),
        "department_publication_manifests": active_manifest_inventory(),
        "database_modified": False,
        "notes": "Immutable read-only snapshot. Existing department snapshots and the SQLite database were not modified.",
    }
    (OUTPUT_DIR / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = build_manifest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
