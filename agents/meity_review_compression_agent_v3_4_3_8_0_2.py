from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_candidate_purification_v3_4_3_8_0_1 import (  # noqa: E402
    run_purification,
)
from services.meity_review_compression_v3_4_3_8_0_2 import (  # noqa: E402
    run_compression,
)


def main() -> int:
    purification = run_purification(PROJECT_ROOT)
    compression = run_compression(PROJECT_ROOT)

    if not compression["row_reconciliation"]:
        raise RuntimeError("Review rows did not reconcile.")
    if not compression["evidence_weight_reconciliation"]:
        raise RuntimeError("Evidence weight did not reconcile.")
    if (
        compression["admin_decision_bundle_count"]
        > compression["max_admin_decision_bundles"]
    ):
        raise RuntimeError("Admin decision bundle limit exceeded.")
    if compression["database_write_performed"]:
        raise RuntimeError("Database write reported.")
    if compression["publication_performed"]:
        raise RuntimeError("Publication action reported.")

    print(
        json.dumps(
            {
                "purification": purification,
                "compression": compression,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
