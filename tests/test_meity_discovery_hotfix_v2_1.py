import asyncio
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.meity_discovery_hotfix_v2_1 import (  # noqa: E402
    MeityDiscoveryHotfixV21,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.INFO)


async def main() -> None:
    dry_run = os.getenv("SSIP_MEITY_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    hotfix = MeityDiscoveryHotfixV21(PROJECT_ROOT)
    summary = await hotfix.run(dry_run=dry_run)

    print("\n" + "=" * 92)
    print("MEITY DISCOVERY HOTFIX V2.1 COMPLETED")
    print("=" * 92)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if dry_run:
        print("\nDry run completed. No files were changed.")
        return

    results = json.loads(
        hotfix.meity_output_path.read_text(encoding="utf-8")
    )

    print("\n" + "=" * 92)
    print("MEITY CANDIDATES")
    print("=" * 92)
    for item in results:
        print(
            f"[{float(item.get('relevance_score') or 0):>7.2f}] "
            f"{item.get('content_kind', ''):<8} | "
            f"{item.get('title') or item.get('anchor_text') or '(untitled)'}"
        )
        print(f"           {item.get('url')}")

    print("\nFiles created/updated:")
    print(hotfix.meity_output_path)
    print(hotfix.discovery_path)
    print(hotfix.summary_path)
    if summary.get("backup_path"):
        print(summary["backup_path"])


if __name__ == "__main__":
    asyncio.run(main())
