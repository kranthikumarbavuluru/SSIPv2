from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", default=".")
    args = p.parse_args()
    root = Path(args.project_root).resolve()
    required = [
        root / "agents" / "orchestrator.py",
        root / "config" / "agent_platform_v3_4_1_0.json",
        root / "config" / "sector_taxonomy_v3_4_1_0.json",
        root / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv",
        root / "apps" / "public_dashboard_app_v2_9.py",
    ]
    checks = {str(x.relative_to(root)): x.exists() for x in required}
    passed = all(checks.values())
    print(json.dumps({"preflight_passed": passed, "checks": checks}, indent=2))
    return 0 if passed else 2
if __name__ == "__main__":
    raise SystemExit(main())
