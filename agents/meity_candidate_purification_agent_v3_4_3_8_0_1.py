from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_complete_intelligence_v3_4_3_8_0 import (  # noqa: E402
    run_pipeline,
)
from services.meity_candidate_purification_v3_4_3_8_0_1 import (  # noqa: E402
    run_purification,
)


def main() -> int:
    source = run_pipeline(PROJECT_ROOT, live_network=True)
    parse_errors = [
        item
        for item in source.get("errors", [])
        if str(item).startswith("HTML_PARSE:")
    ]
    if parse_errors:
        raise RuntimeError(
            "HTML parse errors remain: " + " | ".join(parse_errors)
        )

    result = run_purification(PROJECT_ROOT)
    if not result["partition_complete"]:
        raise RuntimeError("Candidate partition is incomplete.")
    if result["unsafe_programme_identity_count"]:
        raise RuntimeError("Unsafe programme identities survived.")
    if result["database_write_performed"]:
        raise RuntimeError("Database write reported.")
    if result["publication_performed"]:
        raise RuntimeError("Publication action reported.")

    print(
        json.dumps(
            {
                "source": source,
                "purification": result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
