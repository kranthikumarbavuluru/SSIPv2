#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

VERSION = "3.4.0.6b"
DEFAULT_INPUT = Path("data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv")
DEFAULT_RULES = Path("config/sector_rules_v3_4_0_6b.json")
DEFAULT_OUTPUT = Path("data/sector_verification/v3_4_0_6b")
BLANKS = {"", "none", "null", "unknown", "n/a", "na", "not specified", "sector not specified", "[]"}
CROSS_INNOVATION = "Cross-sector Innovation & Entrepreneurship"
CROSS_FINANCE = "Cross-sector MSME & Startup Finance"
SECTOR_AGNOSTIC = "Sector Agnostic / Multi-sector"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def key(v: Any) -> str:
    return clean(v).casefold()


def parse_list(v: Any) -> list[str]:
    text = clean(v)
    if key(text) in BLANKS:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [clean(x) for x in parsed if clean(x)]
        except Exception:
            pass
    return [clean(x) for x in re.split(r"\s*(?:;|\||\n)\s*", text) if clean(x)]


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent) as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({field: row.get(field, "") for field in fields})
        temp = f.name
    os.replace(temp, path)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return [dict(x) for x in r], list(r.fieldnames or [])


def phrase_present(text: str, phrase: str) -> bool:
    t = f" {key(text)} "
    p = key(phrase)
    if not p:
        return False
    if len(p) <= 3 and p.isalpha():
        return re.search(rf"\b{re.escape(p)}\b", t) is not None
    return p in t


def fetch_page(url: str, timeout: int = 20) -> tuple[str, str]:
    try:
        import requests
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": f"SSIP-Sector-Repair/{VERSION}"}, allow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").casefold()
        if "pdf" in ctype or urlparse(resp.url).path.casefold().endswith(".pdf"):
            return "", "PDF_SKIPPED"
        raw = resp.text[:1_500_000]
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        for node in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
            node.decompose()
        return clean(soup.get_text(" ", strip=True))[:60000], f"HTTP_{resp.status_code}"
    except Exception as exc:
        return "", f"FETCH_ERROR:{type(exc).__name__}"


def existing_valid_sector(row: Mapping[str, Any], allowed: set[str]) -> list[str]:
    candidates = parse_list(row.get("primary_sector")) + parse_list(row.get("sector"))
    out: list[str] = []
    for value in candidates:
        if value in allowed and value not in out:
            out.append(value)
    return out


def evidence_fields(row: Mapping[str, Any]) -> dict[str, str]:
    aliases = {
        "name": ["scheme_name", "canonical_name", "programme_name", "title"],
        "objective": ["objectives", "objective", "description", "summary"],
        "eligibility": ["eligibility", "target_beneficiaries", "beneficiaries", "who_can_apply"],
        "benefits": ["benefits", "support_details", "funding_details"],
        "type": ["scheme_type", "support_type", "normalized_record_kind", "record_kind", "current_record_kind"],
    }
    result: dict[str, str] = {}
    for group, fields in aliases.items():
        vals = [clean(row.get(f)) for f in fields if clean(row.get(f))]
        if vals:
            result[group] = " ".join(vals)
    return result


def classify(row: Mapping[str, Any], rules: dict[str, Any], allow_network: bool, delay: float) -> dict[str, Any]:
    sectors = [x["name"] for x in rules["sectors"]]
    allowed = set(sectors + [CROSS_INNOVATION, CROSS_FINANCE, SECTOR_AGNOSTIC])
    existing = existing_valid_sector(row, allowed)
    ev = evidence_fields(row)
    fetched: list[str] = []
    notes: list[str] = []
    if allow_network:
        urls: list[str] = []
        for field in ("official_page_url", "application_url", "source_url", "final_url"):
            u = clean(row.get(field))
            if u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)
        for u in urls[:2]:
            text, note = fetch_page(u)
            fetched.append(u)
            notes.append(f"{u}::{note}")
            if text:
                ev["official"] = (ev.get("official", "") + " " + text)[:70000]
            if delay:
                time.sleep(delay)

    weights = {"name": 8.0, "objective": 4.0, "eligibility": 4.0, "benefits": 3.0, "type": 2.0, "official": 2.0}
    scores: defaultdict[str, float] = defaultdict(float)
    reasons: defaultdict[str, list[str]] = defaultdict(list)
    for item in rules["sectors"]:
        sector = item["name"]
        for field, text in ev.items():
            hits = [p for p in item["patterns"] if phrase_present(text, p)]
            if hits:
                scores[sector] += weights.get(field, 1.0) * min(3, len(hits))
                reasons[sector].append(f"{field}: {', '.join(hits[:4])}")

    combined = " ".join(ev.values())
    cross_innov = [p for p in rules["cross_sector_innovation_patterns"] if phrase_present(combined, p)]
    cross_fin = [p for p in rules["cross_sector_finance_patterns"] if phrase_present(combined, p)]
    agnostic = [p for p in rules["sector_agnostic_patterns"] if phrase_present(combined, p)]
    if cross_innov:
        scores[CROSS_INNOVATION] += 18 + min(6, 2 * len(cross_innov))
        reasons[CROSS_INNOVATION].append("broad innovation evidence: " + ", ".join(cross_innov[:4]))
    if cross_fin:
        scores[CROSS_FINANCE] += 20 + min(6, 2 * len(cross_fin))
        reasons[CROSS_FINANCE].append("broad finance evidence: " + ", ".join(cross_fin[:4]))
    if agnostic:
        scores[SECTOR_AGNOSTIC] += 12
        reasons[SECTOR_AGNOSTIC].append("explicit multi-sector evidence: " + ", ".join(agnostic[:4]))

    if existing:
        scores[existing[0]] += 6
        reasons[existing[0]].append("preserved existing controlled sector")

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    if ranked and ranked[0][1] >= 6:
        primary, top = ranked[0]
        secondary = [s for s, sc in ranked[1:] if sc >= 6 and sc >= top * 0.58][:2]
        method = "EVIDENCE_RULES_WITH_OFFICIAL_FETCH" if ev.get("official") else "EVIDENCE_RULES"
        confidence = min(0.97, 0.58 + min(top, 24) / 60 + (0.05 if ev.get("official") else 0))
        review = confidence < 0.72 or primary in {SECTOR_AGNOSTIC}
    else:
        kind_text = key(ev.get("type"))
        name_text = key(ev.get("name"))
        if any(x in combined.casefold() for x in ["incubat", "accelerat", "entrepreneur", "startup", "innovation", "prototype", "nidhi", "prayas"]):
            primary = CROSS_INNOVATION
            reason = "fallback from startup/incubation/innovation support context"
        elif any(x in combined.casefold() for x in ["credit", "loan", "finance", "fund", "guarantee", "working capital", "bill discount"]):
            primary = CROSS_FINANCE
            reason = "fallback from broad finance/support context"
        else:
            primary = SECTOR_AGNOSTIC
            reason = "no defensible industry restriction found; explicit multi-sector fallback"
        secondary = []
        method = "CONTROLLED_FALLBACK"
        confidence = 0.62
        review = True
        reasons[primary].append(reason)

    all_sectors = [primary] + [s for s in secondary if s != primary]
    evidence = "; ".join(reasons.get(primary, [])[:4]) or "controlled fallback"
    return {
        "primary_sector": primary,
        "secondary_sectors": secondary,
        "all_sectors": all_sectors,
        "confidence": round(confidence, 3),
        "method": method,
        "review_required": review,
        "evidence": evidence[:1000],
        "fetched_urls": fetched,
        "fetch_notes": notes,
        "scores": dict(sorted(scores.items(), key=lambda x: -x[1])[:8]),
    }


def visible(row: Mapping[str, Any]) -> bool:
    if key(row.get("current_decision")) in {"rejected", "do_not_publish"}:
        return False
    if key(row.get("catalogue_inclusion")) in {"excluded", "rejected", "evidence_only"}:
        return False
    return bool(clean(row.get("scheme_name") or row.get("canonical_name")))


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.project_root).resolve()
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = root / input_path
    rules_path = Path(args.rules)
    if not rules_path.is_absolute():
        rules_path = root / rules_path
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    if not input_path.exists():
        raise FileNotFoundError(f"Active dashboard catalogue not found: {input_path}")

    rows, fields = read_csv(input_path)
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    enriched: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        result = classify(row, rules, args.allow_network, args.delay)
        updated = dict(row)
        updated["sector"] = "; ".join(result["all_sectors"])
        updated["primary_sector"] = result["primary_sector"]
        updated["secondary_sectors"] = "; ".join(result["secondary_sectors"])
        updated["sector_confidence"] = f'{result["confidence"]:.3f}'
        updated["sector_classification_method"] = result["method"]
        updated["sector_evidence"] = result["evidence"]
        updated["sector_review_required"] = "true" if result["review_required"] else "false"
        updated["sector_verified_at"] = now()
        updated["sector_agent_version"] = VERSION
        enriched.append(updated)
        name = clean(row.get("scheme_name") or row.get("canonical_name"))
        audits.append({
            "master_id": clean(row.get("master_id") or row.get("normalized_scheme_id")),
            "scheme_name": name,
            "primary_sector": result["primary_sector"],
            "secondary_sectors": "; ".join(result["secondary_sectors"]),
            "confidence": result["confidence"],
            "method": result["method"],
            "review_required": result["review_required"],
            "evidence": result["evidence"],
            "scores": json.dumps(result["scores"], ensure_ascii=False),
            "fetched_urls": json.dumps(result["fetched_urls"], ensure_ascii=False),
            "fetch_notes": json.dumps(result["fetch_notes"], ensure_ascii=False),
        })
        if args.progress:
            print(f"[{idx}/{len(rows)}] {name}: {result['primary_sector']} ({result['method']})", flush=True)

    for extra in ["sector", "primary_sector", "secondary_sectors", "sector_confidence", "sector_classification_method", "sector_evidence", "sector_review_required", "sector_verified_at", "sector_agent_version"]:
        if extra not in fields:
            fields.append(extra)

    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = out_dir / "catalogue_sector_repaired_v3_4_0_6b.csv"
    write_csv_atomic(enriched_path, enriched, fields)
    audit_fields = list(audits[0].keys()) if audits else ["master_id", "scheme_name", "primary_sector"]
    write_csv_atomic(out_dir / "sector_scheme_mapping_v3_4_0_6b.csv", audits, audit_fields)
    write_csv_atomic(out_dir / "sector_manual_review_queue_v3_4_0_6b.csv", [x for x in audits if x["review_required"]], audit_fields)

    visible_rows = [r for r in enriched if visible(r)]
    missing = [clean(r.get("scheme_name") or r.get("canonical_name")) for r in visible_rows if key(r.get("sector")) in BLANKS]
    unspecified = [clean(r.get("scheme_name") or r.get("canonical_name")) for r in visible_rows if key(r.get("sector")) == "sector not specified"]
    allowed = {x["name"] for x in rules["sectors"]} | {CROSS_INNOVATION, CROSS_FINANCE, SECTOR_AGNOSTIC}
    invalid = []
    for r in visible_rows:
        for s in parse_list(r.get("sector")):
            if s not in allowed:
                invalid.append({"scheme_name": clean(r.get("scheme_name")), "sector": s})
    before_ids = [clean(r.get("master_id") or r.get("normalized_scheme_id")) for r in rows]
    after_ids = [clean(r.get("master_id") or r.get("normalized_scheme_id")) for r in enriched]
    checks = {
        "active_catalogue_path_is_explicit": input_path == (root / DEFAULT_INPUT).resolve(),
        "row_count_preserved": len(rows) == len(enriched),
        "master_id_order_preserved": before_ids == after_ids,
        "zero_blank_sector_rows": len(missing) == 0,
        "zero_sector_not_specified_rows": len(unspecified) == 0,
        "all_sectors_in_controlled_taxonomy": len(invalid) == 0,
        "every_visible_row_has_primary_sector": all(clean(r.get("primary_sector")) for r in visible_rows),
    }
    validation = {
        "service_version": VERSION,
        "validated_at": now(),
        "input_catalogue": str(input_path),
        "counts": {
            "input_rows": len(rows),
            "visible_rows": len(visible_rows),
            "blank_sector_rows": len(missing),
            "sector_not_specified_rows": len(unspecified),
            "manual_review_rows": sum(1 for x in audits if x["review_required"]),
        },
        "checks": checks,
        "missing": missing,
        "unspecified": unspecified,
        "invalid": invalid,
        "validation_passed": all(checks.values()),
    }
    (out_dir / "sector_validation_v3_4_0_6b.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    applied = False
    backup = ""
    if args.apply:
        if not validation["validation_passed"]:
            raise RuntimeError("Validation failed; active dashboard catalogue was not replaced")
        backup_dir = root / "backups" / "sector_verification_v3_4_0_6b"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{input_path.stem}_before_sector_repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        shutil.copy2(input_path, backup_path)
        shutil.copy2(enriched_path, input_path)
        backup = str(backup_path)
        applied = True

    distribution = Counter(clean(r.get("primary_sector")) for r in visible_rows)
    dist_rows = [{"sector": s, "record_count": c, "percentage": round(c * 100 / max(1, len(visible_rows)), 2)} for s, c in distribution.most_common()]
    write_csv_atomic(out_dir / "sector_distribution_v3_4_0_6b.csv", dist_rows, ["sector", "record_count", "percentage"])
    summary = {
        "service_version": VERSION,
        "generated_at": now(),
        "input_catalogue": str(input_path),
        "applied_to_active_dashboard_catalogue": applied,
        "backup": backup,
        "counts": validation["counts"],
        "distribution": dict(distribution),
        "validation_passed": validation["validation_passed"],
        "outputs": {
            "mapping": "sector_scheme_mapping_v3_4_0_6b.csv",
            "review_queue": "sector_manual_review_queue_v3_4_0_6b.csv",
            "distribution": "sector_distribution_v3_4_0_6b.csv",
            "validation": "sector_validation_v3_4_0_6b.json"
        }
    }
    (out_dir / "sector_summary_v3_4_0_6b.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def self_test(root: Path) -> int:
    rules = json.loads((root / "config" / "sector_rules_v3_4_0_6b.json").read_text(encoding="utf-8"))
    samples = [
        ({"scheme_name":"NIDHI PRAYAS","objectives":"prototype support for innovators and startups"}, CROSS_INNOVATION),
        ({"scheme_name":"Credit Guarantee Scheme for Startups","benefits":"credit guarantee across sectors"}, CROSS_FINANCE),
        ({"scheme_name":"Bio-AI Innovation Challenge","objectives":"biotechnology genomics artificial intelligence"}, "Biotechnology & Life Sciences"),
        ({"scheme_name":"AgriTech Fund","objectives":"farm mechanisation and agriculture technology"}, "Agriculture & AgriTech"),
        ({"scheme_name":"General Startup Scheme","eligibility":"startups from all sectors"}, SECTOR_AGNOSTIC),
    ]
    checks = {}
    for i, (row, expected) in enumerate(samples, 1):
        result = classify(row, rules, False, 0)
        checks[f"sample_{i}"] = result["primary_sector"] == expected
    checks["no_blank_fallback"] = bool(classify({"scheme_name":"Unknown General Support"}, rules, False, 0)["primary_sector"])
    ok = all(checks.values())
    print(json.dumps({"service_version": VERSION, "checks": checks, "self_test_passed": ok}, indent=2))
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", default=".")
    p.add_argument("--input", default=str(DEFAULT_INPUT))
    p.add_argument("--rules", default=str(DEFAULT_RULES))
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--allow-network", action="store_true")
    p.add_argument("--delay", type=float, default=0.15)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--progress", action="store_true")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    root = Path(args.project_root).resolve()
    if args.self_test:
        return self_test(root)
    try:
        summary = run(args)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["validation_passed"] else 2
    except Exception as exc:
        print(json.dumps({"service_version": VERSION, "error": str(exc), "error_type": type(exc).__name__}, indent=2), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
