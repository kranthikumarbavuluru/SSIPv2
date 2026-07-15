from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.meity_temporal_parent_safety_v3_4_3_8_0_3 import (  # noqa: E402
    run_safety_gate,
)
from services.meity_url_integrity_v3_4_3_8_0_4 import (  # noqa: E402
    run_url_integrity,
)


def main() -> int:
    safety = run_safety_gate(PROJECT_ROOT)
    integrity = run_url_integrity(PROJECT_ROOT)

    if integrity["historical_application_links_exposed"]:
        raise RuntimeError("Historical application links were exposed.")
    if integrity["about_page_application_links_exposed"]:
        raise RuntimeError("About-page links were exposed as application routes.")
    if integrity["cross_entity_link_contamination_count"]:
        raise RuntimeError("Cross-entity application contamination survived.")
    if integrity["current_status_evidence_complete_count"] == 0:
        if integrity["verified_application_routes"] != 0:
            raise RuntimeError(
                "Application routes were exposed while global current "
                "evidence remained incomplete."
            )
    if integrity["database_write_performed"]:
        raise RuntimeError("Database write reported.")
    if integrity["publication_performed"]:
        raise RuntimeError("Publication action reported.")

    print(
        json.dumps(
            {
                "safety": safety,
                "integrity": integrity,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
