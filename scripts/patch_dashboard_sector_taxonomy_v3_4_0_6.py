#!/usr/bin/env python3
"""Patch SSIP dashboard sector normalization so verified taxonomy is preserved."""
from __future__ import annotations

import argparse
import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path

VERSION = "3.4.0.6"

REPLACEMENT = '''def normalize_sector(text: str) -> str:
    """Preserve verified SSIP taxonomy values; normalize only legacy aliases."""
    value_text = str(text or "").strip().strip('[]').strip().strip('"').strip("'")
    value_text = re.sub(r"\\s+", " ", value_text)
    key = value_text.casefold()
    if not key or key in {"none", "null", "unknown", "not specified", "sector not specified", "n/a", "na"}:
        return "Sector Not Specified"

    legacy_aliases = {
        "biotechnology": "Biotechnology & Life Sciences",
        "healthcare": "Healthcare & MedTech",
        "digital technology": "Digital Technology & Software",
        "it & electronics": "Electronics & Semiconductors",
        "startup / innovation": "Cross-sector Innovation & Entrepreneurship",
        "msme / entrepreneurship": "Sector Agnostic / Multi-sector",
        "science & technology": "Deep Technology",
        "agriculture": "Agriculture & AgriTech",
    }
    return legacy_aliases.get(key, value_text)
'''


def patch(path: Path, backup_dir: Path) -> tuple[bool, Path | None]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"def normalize_sector\(text: str\) -> str:\n.*?(?=\ndef primary_sector\()", re.S)
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Could not locate normalize_sector() in {path}")
    current = match.group(0).strip()
    if "Preserve verified SSIP taxonomy values" in current:
        py_compile.compile(str(path), doraise=True)
        return False, None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{path.stem}_before_sector_taxonomy_{stamp}{path.suffix}"
    shutil.copy2(path, backup)
    updated = pattern.sub(lambda _match: REPLACEMENT.rstrip(), text, count=1)
    path.write_text(updated, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return True, backup


def self_test() -> int:
    sample = '''import re\n\ndef normalize_sector(text: str) -> str:\n    value_text = text.strip()\n    if not value_text:\n        return "Sector Not Specified"\n    return "Science & Technology"\n\ndef primary_sector(record):\n    return normalize_sector(record)\n'''
    pattern = re.compile(r"def normalize_sector\(text: str\) -> str:\n.*?(?=\ndef primary_sector\()", re.S)
    updated, count = pattern.subn(lambda _match: REPLACEMENT.rstrip(), sample, count=1)
    passed = count == 1 and "Biotechnology & Life Sciences" in updated and "def primary_sector" in updated
    print({"service_version": VERSION, "self_test_passed": passed})
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    root = Path(args.project_root).resolve()
    target = root / "ssip_dashboard" / "catalogue_populations.py"
    if not target.exists():
        raise FileNotFoundError(target)
    changed, backup = patch(target, root / "backups" / "sector_verification_v3_4_0_6")
    print({
        "service_version": VERSION,
        "target": str(target),
        "patched": changed,
        "backup": str(backup) if backup else "",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
