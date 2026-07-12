import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.discovery.discovery_agent_v2 import (  # noqa: E402
    DiscoveryAgentV2,
    DiscoveryConfig,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)


SEED_SOURCES = [
    {
        "name": "Startup India",
        "url": "https://www.startupindia.gov.in/content/sih/en/government-schemes.html",
    },
    {
        "name": "MSME",
        "url": "https://msme.gov.in/",
    },
    {
        "name": "DST",
        "url": "https://dst.gov.in/",
    },
    {
        "name": "BIRAC",
        "url": "https://birac.nic.in/",
    },
    {
        "name": "MeitY Startup Hub",
        "url": "https://msh.meity.gov.in/",
    },
]


async def main() -> None:
    config = DiscoveryConfig(
        max_depth=3,
        max_pages_per_seed=120,
        workers_per_seed=4,
        candidate_threshold=9.0,
        document_threshold=6.5,
        crawl_threshold=1.5,
        discover_sitemaps=True,
        max_sitemap_urls_to_queue=250,
        use_browser_fallback=True,
        max_browser_pages_per_seed=6,
        request_delay=0.20,
    )

    agent = DiscoveryAgentV2(
        seed_sources=SEED_SOURCES,
        config=config,
    )

    results = await agent.run()

    output_dir = PROJECT_ROOT / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "discovery_results_v2.json"
    output_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 80)
    print("DISCOVERY COMPLETED")
    print("=" * 80)
    print(f"Total candidate URLs: {len(results)}")
    print(f"Saved to: {output_file}")

    for item in results:
        print(
            f"[{item['relevance_score']:>7.2f}] "
            f"{item['source']:<20} | "
            f"{item['content_kind']:<8} | "
            f"{item['title'] or item['anchor_text'] or '(untitled)'}"
        )
        print(f"           {item['url']}")

    print("\n" + "=" * 80)
    print("SOURCE STATISTICS")
    print("=" * 80)
    for source, stats in agent.last_run_stats.items():
        print(f"{source}: {json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(main())
