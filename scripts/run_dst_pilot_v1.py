from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.dst_pilot import DSTPilotPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the evidence-first DST scheme/call curation pilot without modifying production data.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verification-date", type=date.fromisoformat)
    parser.add_argument("--live-refresh", action="store_true", help="Refresh the current official DST call index and linked official evidence before building the preview.")
    args = parser.parse_args()
    result = DSTPilotPipeline(
        args.project_root,
        profile_path=args.profile,
        output_dir=args.output_dir,
        today=args.verification_date,
        live_refresh=args.live_refresh,
    ).run()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
