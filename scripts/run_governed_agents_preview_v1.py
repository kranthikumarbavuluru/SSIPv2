from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.governed_v1.orchestrator import GovernedAgentOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SSIP governed pipeline in preview-only mode.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    root = args.project_root.resolve()
    config = args.config.resolve() if args.config else root / "config/governed_agents_v1.json"
    result = GovernedAgentOrchestrator(root, config).run_preview(args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
