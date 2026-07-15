from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_review_compression_v3_4_3_8_0_2 import (  # noqa: E402
    run_compression,
)
from services.meity_temporal_parent_safety_v3_4_3_8_0_3 import (  # noqa: E402
    run_safety_gate,
)


def main() -> int:
    compression = run_compression(PROJECT_ROOT)
    safety = run_safety_gate(PROJECT_ROOT)

    if safety["source_decision_bundle_count"] != safety["safe_decision_bundle_count"]:
        raise RuntimeError("Decision bundles did not reconcile.")
    if safety["unsafe_current_status_count"]:
        raise RuntimeError("Unsafe current status survived.")
    if safety["ambiguous_decision_label_count"]:
        raise RuntimeError("Ambiguous Admin decision wording survived.")
    if safety["database_write_performed"]:
        raise RuntimeError("Database write reported.")
    if safety["publication_performed"]:
        raise RuntimeError("Publication action reported.")

    print(
        json.dumps(
            {
                "compression": compression,
                "safety": safety,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
