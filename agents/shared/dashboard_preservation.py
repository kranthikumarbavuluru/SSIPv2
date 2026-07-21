from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation_core import sha256_file


def dpiit_preview_preserves_home(project_root: Path, baseline: dict[str, Any]) -> bool:
    """Allow the governed DPIIT route while retaining legacy Home/CSS safety."""
    app_path = project_root / "apps/public_dashboard_app_v2_9.py"
    text = app_path.read_text(encoding="utf-8-sig")
    start = text.find("def render_home(")
    end = text.find("\ndef ", start + 1)
    home_block = text[start:end] if start >= 0 and end > start else ""
    css_files = [
        path for path in baseline.get("frozen_files", {})
        if path.endswith(".css")
    ]
    css_unchanged = all(
        sha256_file(project_root / path) == baseline["frozen_files"][path]
        for path in css_files
    )
    return bool(
        home_block
        and "dpiit" not in home_block.casefold()
        and '"DPIIT": "dpiit-programmes"' in text
        and "render_dpiit_page()" in text
        and css_unchanged
    )
