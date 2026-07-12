from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path


class CatalogueMode(str, Enum):
    CATALOGUE_PREVIEW = "CATALOGUE_PREVIEW"
    PUBLISHED_ONLY = "PUBLISHED_ONLY"


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        has_database = (candidate / "database" / "ssip_staging_v1.db").exists()
        has_project_markers = (
            (candidate / "ssip_dashboard").is_dir()
            and (candidate / "database").is_dir()
            and (candidate / "CODEX.md").is_file()
        )
        if has_database or has_project_markers:
            return candidate
    return Path.cwd()


@dataclass(frozen=True)
class DashboardConfig:
    project_root: Path
    database_path: Path
    normalization_path: Path
    normalization_fallback_path: Path | None = None
    preview_path_configured: bool = False
    mode: CatalogueMode = CatalogueMode.CATALOGUE_PREVIEW
    sqlite_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "DashboardConfig":
        root = find_project_root(project_root)
        mode_text = os.environ.get("SSIP_PUBLIC_CATALOGUE_MODE", "CATALOGUE_PREVIEW")
        try:
            mode = CatalogueMode(mode_text.strip().upper())
        except ValueError:
            mode = CatalogueMode.CATALOGUE_PREVIEW
        fallback_path = (
            root
            / "data"
            / "audit"
            / "v2_8_1_catalogue_normalization"
            / "catalogue_normalization_plan_v2_8_1.csv"
        )
        configured_preview = os.environ.get("SSIP_CATALOGUE_PREVIEW_PATH", "").strip()
        default_preview = root / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv"
        previous_preview = root / "data" / "catalogue_preview" / "v3_3_1" / "batch_1_catalogue_preview_v3_3_1.csv"
        preview_path_configured = bool(configured_preview)
        if configured_preview:
            normalization_path = Path(configured_preview)
            if not normalization_path.is_absolute():
                normalization_path = root / normalization_path
        elif mode == CatalogueMode.CATALOGUE_PREVIEW and default_preview.exists():
            normalization_path = default_preview
        elif mode == CatalogueMode.CATALOGUE_PREVIEW and previous_preview.exists():
            normalization_path = previous_preview
        else:
            normalization_path = fallback_path
        return cls(
            project_root=root,
            database_path=root / "database" / "ssip_staging_v1.db",
            normalization_path=normalization_path,
            normalization_fallback_path=fallback_path,
            preview_path_configured=preview_path_configured,
            mode=mode,
        )


DEFAULT_CONFIG = DashboardConfig.from_env()
