from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any
from .common import atomic_write_csv, atomic_write_json, content_hash, utc_now

class AtomicPublicationAgent:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def publish(
        self,
        run_id: str,
        rows: list[dict[str, Any]],
        fieldnames: list[str],
        active_catalogue: Path,
        validation: dict[str, Any],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        if not validation.get("passed"):
            raise RuntimeError("Publication blocked: validation did not pass.")
        publication_dir = self.project_root / "data" / "publication" / run_id
        publication_dir.mkdir(parents=True, exist_ok=True)
        versioned_csv = publication_dir / "catalogue.csv"
        atomic_write_csv(versioned_csv, rows, fieldnames)

        backup_dir = self.project_root / "backups" / "agent_platform" / run_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        if active_catalogue.exists():
            shutil.copy2(active_catalogue, backup_dir / active_catalogue.name)

        atomic_write_csv(active_catalogue, rows, fieldnames)
        manifest = {
            "run_id": run_id,
            "published_at": utc_now(),
            "catalogue_path": str(active_catalogue),
            "versioned_catalogue_path": str(versioned_csv),
            "row_count": len(rows),
            "catalogue_sha256": content_hash(versioned_csv.read_bytes()),
            "validation": validation,
            "summary": summary,
        }
        atomic_write_json(publication_dir / "manifest.json", manifest)
        atomic_write_json(
            self.project_root / "data" / "publication" / "current_manifest.json",
            manifest
        )
        return manifest
