from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.common import load_json, read_csv, sha256_file


def verify(root: Path) -> dict:
    config = load_json(root / "config/governed_agents_v1.json")
    current_dir = root / config["publication_root"] / "current"
    current_catalogue = current_dir / "public_catalogue.csv"
    current_manifest = current_dir / "publication_manifest.json"
    fallback = root / config["active_catalogue"]
    if current_catalogue.exists() and current_manifest.exists():
        manifest = load_json(current_manifest)
        expected = manifest.get("public_catalogue_sha256", "")
        actual = sha256_file(current_catalogue)
        valid = expected == actual and bool(manifest.get("validation_passed"))
        if valid:
            rows, _ = read_csv(current_catalogue)
            return {"source_status": "APPROVED_PUBLICATION_AVAILABLE", "valid": True, "path": str(current_catalogue), "row_count": len(rows), "sha256": actual}
    rows, _ = read_csv(fallback)
    return {"source_status": "FALLBACK_ACTIVE_CATALOGUE", "valid": True, "path": str(fallback), "row_count": len(rows), "sha256": sha256_file(fallback)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    print(json.dumps(verify(args.project_root.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
