from __future__ import annotations
import csv, json, sys
from pathlib import Path

def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    active = root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
    with active.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    bad = [r for r in rows if not (r.get("sector") or "").strip()]
    mismatch = [r for r in rows if (r.get("sector") or "") != (r.get("primary_sector") or "")]
    nonpublic = [r for r in rows if r.get("governance_decision") != "PUBLISH_SCHEME"]
    result = {
        "active_catalogue": str(active),
        "public_rows": len(rows),
        "blank_sector_rows": len(bad),
        "sector_field_mismatches": len(mismatch),
        "nonpublic_rows_in_active_catalogue": len(nonpublic),
        "dashboard_ready": not bad and not mismatch and not nonpublic and len(rows) >= 5
    }
    print(json.dumps(result, indent=2))
    return 0 if result["dashboard_ready"] else 2
if __name__ == "__main__":
    raise SystemExit(main())
