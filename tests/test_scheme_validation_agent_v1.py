from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.validator.scheme_validation_agent_v1 import SchemeValidationAgentV1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


def main() -> None:
    input_path = PROJECT_ROOT / "data" / "extracted_scheme_records_v1.json"
    failure_path = PROJECT_ROOT / "data" / "extraction_failures_v1.json"
    output_dir = PROJECT_ROOT / "data"
    config_path = PROJECT_ROOT / "config" / "validator_config.json"

    if not input_path.exists():
        raise FileNotFoundError(f"Missing extractor output: {input_path}")

    limit_text = os.getenv("SSIP_VALIDATION_LIMIT", "").strip()
    limit = int(limit_text) if limit_text else None

    agent = SchemeValidationAgentV1(config_path=config_path)
    result = agent.run(
        input_path=input_path,
        failure_path=failure_path if failure_path.exists() else None,
        output_dir=output_dir,
        limit=limit,
    )

    print("\n" + "=" * 92)
    print("SCHEME VALIDATION COMPLETED")
    print("=" * 92)
    print(json.dumps(result.summary, indent=2, ensure_ascii=False))

    print("\n" + "=" * 92)
    print("VALIDATION DECISIONS")
    print("=" * 92)
    for record in result.audit_records:
        validation = record["validation"]
        print(
            f"[{validation['decision']:<24}] "
            f"[{validation['validation_score']:.3f}] "
            f"{record.get('source', ''):<14} | {record.get('scheme_name', '')}"
        )
        print(
            f"    Kind: {record.get('record_kind')} | "
            f"Programme: {record.get('programme_status')} | "
            f"Application: {record.get('application_status')}"
        )
        print(
            f"    Deadline: {record.get('closing_date')} | "
            f"Funding max: {record.get('funding_amount', {}).get('maximum')} | "
            f"Corpus: {record.get('funding_amount', {}).get('scheme_corpus')}"
        )
        print(
            f"    Corrections: {len(validation['corrections'])} | "
            f"Warnings: {len(validation['warnings'])}"
        )

    print("\nFiles saved:")
    for filename in (
        "validated_scheme_records_v1.json",
        "admin_review_queue_v1.json",
        "rejected_scheme_records_v1.json",
        "validation_audit_v1.json",
        "validation_summary_v1.json",
    ):
        print(output_dir / filename)


if __name__ == "__main__":
    main()
