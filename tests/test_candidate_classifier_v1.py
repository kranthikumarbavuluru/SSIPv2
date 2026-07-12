from __future__ import annotations

import json
import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.classifier.candidate_classifier_v1 import CandidateClassifierV1


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


def main() -> None:
    input_file = PROJECT_ROOT / "data" / "discovery_results_v2.json"
    output_dir = PROJECT_ROOT / "data"

    if not input_file.exists():
        raise FileNotFoundError(
            f"Discovery result not found: {input_file}\n"
            "Run Discovery Agent v2 first."
        )

    classifier = CandidateClassifierV1()
    result = classifier.run(
        input_path=input_file,
        output_dir=output_dir,
    )

    print("\n" + "=" * 88)
    print("CANDIDATE CLASSIFICATION COMPLETED")
    print("=" * 88)
    print(json.dumps(result.summary, indent=2, ensure_ascii=False))

    print("\n" + "=" * 88)
    print("SCHEME MASTER CANDIDATES")
    print("=" * 88)

    for master in result.scheme_master_candidates:
        print(
            f"[{master['current_status']:<28}] "
            f"[{master['readiness']:<40}] "
            f"{master['source']:<16} | {master['canonical_name']}"
        )
        print(f"    Best URL: {master['best_available_url']}")
        print(
            f"    Records: {master['source_records_count']} | "
            f"Active calls: {master['active_call_count']} | "
            f"Closed calls: {master['closed_call_count']} | "
            f"Supporting docs: {master['supporting_document_count']}"
        )

    print("\nFiles saved:")
    print(output_dir / "classified_candidates_v1.json")
    print(output_dir / "scheme_master_candidates_v1.json")
    print(output_dir / "classification_summary_v1.json")


if __name__ == "__main__":
    main()
