#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, re
from collections import Counter
from pathlib import Path

VERSION="3.4.0.6b"

def clean(v): return re.sub(r"\s+"," ",str(v or "")).strip()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--project-root",default="."); args=p.parse_args()
    root=Path(args.project_root).resolve()
    cat=root/"data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
    with cat.open("r",encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    dist=Counter(clean(r.get("primary_sector") or r.get("sector")) for r in rows)
    unspecified=sum(c for s,c in dist.items() if not s or s.casefold()=="sector not specified")
    result={"service_version":VERSION,"active_catalogue":str(cat),"row_count":len(rows),"sector_not_specified_or_blank":unspecified,"distribution":dict(dist),"dashboard_ready":unspecified==0}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["dashboard_ready"] else 2
if __name__=="__main__": raise SystemExit(main())
