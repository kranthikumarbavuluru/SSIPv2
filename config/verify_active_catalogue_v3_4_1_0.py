from __future__ import annotations
import csv, json, sys
from pathlib import Path

def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    path = root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
    taxonomy = json.loads((root / "config/sector_taxonomy_v3_4_1_0.json").read_text(encoding="utf-8"))
    allowed = {x["name"] for x in taxonomy["sectors"]}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    sector_col = "primary_sector" if rows and "primary_sector" in rows[0] else "sector"
    blank = [r for r in rows if not (r.get(sector_col) or "").strip()]
    invalid = [r for r in rows if (r.get(sector_col) or "").strip() not in allowed]
    review = [r for r in rows if (r.get("sector_review_required") or "").lower() == "true"]
    result = {
        "active_catalogue": str(path),
        "row_count": len(rows),
        "sector_column": sector_col,
        "blank_sector_rows": len(blank),
        "invalid_sector_rows": len(invalid),
        "review_rows": len(review),
        "dashboard_sector_ready": not blank and not invalid,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["dashboard_sector_ready"] else 2
if __name__ == "__main__":
    raise SystemExit(main())
