from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.core_resolution_runner_v3_3_2 import run_resolution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SSIP v3.3.2 core programme resolution from Batch 1 review candidates.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--allow-network", action="store_true", help="Allow bounded same-domain resolution requests.")
    args = parser.parse_args(argv)
    output_dir = run_resolution(PROJECT_ROOT, run_id=args.run_id, allow_network=args.allow_network)
    print(f"v3.3.2 resolution output: {output_dir}")
    print("Database writes performed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
