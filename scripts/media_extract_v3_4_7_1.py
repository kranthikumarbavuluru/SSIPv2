from __future__ import annotations

"""Run the optional-engine media extraction stage for one dated inbox."""

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.media.extraction_v3_4_7_1 import extract_media_batch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract OCR, QR, links and field evidence from SSIP media.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--ingest-date", default=None, help="YYYY-MM-DD; defaults to today")
    args = parser.parse_args()
    print(json.dumps(extract_media_batch(args.project_root, args.ingest_date), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
