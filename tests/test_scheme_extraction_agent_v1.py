from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.extractor.scheme_extraction_agent_v1 import SchemeExtractionAgentV1


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


async def main() -> None:
    input_file = PROJECT_ROOT / "data" / "scheme_master_candidates_v1.json"

    if not input_file.exists():
        raise FileNotFoundError(
            f"Master candidate file not found: {input_file}\n"
            "Run Candidate Classifier v1 first."
        )

    limit_value = os.getenv("SSIP_EXTRACT_LIMIT", "").strip()
    limit = int(limit_value) if limit_value else None

    agent = SchemeExtractionAgentV1(project_root=PROJECT_ROOT)
    result = await agent.run(
        input_path=input_file,
        output_dir=PROJECT_ROOT / "data",
        limit=limit,
    )

    print("\n" + "=" * 92)
    print("SCHEME EXTRACTION COMPLETED")
    print("=" * 92)
    print(json.dumps(result.summary, indent=2, ensure_ascii=False))

    print("\n" + "=" * 92)
    print("EXTRACTED SCHEME RECORDS")
    print("=" * 92)

    for record in result.records:
        print(
            f"[{record['extraction_confidence']:.3f}] "
            f"{record['source']:<16} | {record['scheme_name']}"
        )
        print(f"    Status: {record['scheme_status']}")
        print(f"    Official URL: {record['official_page_url']}")
        print(
            f"    Eligibility: {len(record['eligibility'])} | "
            f"Benefits: {len(record['benefits'])} | "
            f"Funding mentions: {len(record['funding_amount']['amount_mentions'])} | "
            f"Flags: {len(record['quality_flags'])}"
        )

    print("\nFiles saved:")
    print(PROJECT_ROOT / "data" / "extracted_scheme_records_v1.json")
    print(PROJECT_ROOT / "data" / "extraction_failures_v1.json")
    print(PROJECT_ROOT / "data" / "extraction_summary_v1.json")
    print(PROJECT_ROOT / "data" / "extraction_cache_v1")


if __name__ == "__main__":
    asyncio.run(main())
