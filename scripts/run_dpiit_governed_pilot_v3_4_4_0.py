from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.dpiit_governed_pilot_v3_4_4_0 import DPIITGovernedPilot, PipelinePaths, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the governed DPIIT department-page package.")
    parser.add_argument("--live-network", action="store_true", help="Fetch only bounded registered official sources.")
    args = parser.parse_args()
    paths = PipelinePaths.defaults(PROJECT_ROOT)
    result = DPIITGovernedPilot(paths, load_config(paths.config_path)).run(live_network=args.live_network)
    print(json.dumps({"manifest": result["manifest"], "crawl": result["crawl"]}, indent=2))
    return 0 if result["validation"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
