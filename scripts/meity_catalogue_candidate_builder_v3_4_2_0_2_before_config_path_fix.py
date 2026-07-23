from __future__ import annotations
import os

import csv, hashlib, json, os, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

VERSION = "3.4.2.0.2"
VERIFIED_DATE = "2026-07-13"
SRC = ROOT / "data/departments/meity/v3_4_2_0_1"
OUT = ROOT / "data/departments/meity/v3_4_2_0_2"
AUDIT = ROOT / "data/audit"
ACTIVE = ROOT / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
CURRENT_MANIFEST = ROOT / "data/publication/current_manifest.json"
IMMUTABLE = ROOT / "data/publication/20260710T162806+0000_f4936983/catalogue.csv"
DASHBOARD = ROOT / "apps/public_dashboard_app_v2_9.py"
PILOT = SRC / "meity_extraction_pilot_records_v3_4_2_0_1.csv"
REVIEWS = SRC / "meity_extraction_review_queue_v3_4_2_0_1.csv"
FIELD_EVIDENCE = SRC / "meity_field_evidence_registry_v3_4_2_0_1.csv"
SOURCE_VALIDATION = SRC / "meity_extraction_validation_v3_4_2_0_1.json"

READY = OUT / "meity_publication_ready_records_v3_4_2_0_2.csv"
RESOLVED = OUT / "meity_resolved_review_queue_v3_4_2_0_2.csv"
ADDITIONS = OUT / "meity_catalogue_additions_v3_4_2_0_2.csv"
CANDIDATE = OUT / "catalogue_candidate_v3_4_2_0_2.csv"
VALIDATION = OUT / "meity_publication_candidate_validation_v3_4_2_0_2.json"
SUMMARY = OUT / "meity_publication_candidate_summary_v3_4_2_0_2.json"
PREAUDIT = AUDIT / "meity_v3_4_2_0_2_prepublication_sha256.json"

EXPECTED_IDS = {"147173e17ea741687247", "6af79cf6c8a213dddce8"}
ALLOWED_HOSTS = {"msh.meity.gov.in", "meity.gov.in", "www.meity.gov.in", "pib.gov.in", "www.pib.gov.in"}
CALL_KINDS = {"APPLICATION_CALL", "CALL", "CHALLENGE", "APPLICATION_WINDOW", "COHORT_INSTANCE", "ROUND_INSTANCE"}


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


def write_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pick(row, *names):
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def mode(rows, field, fallback=""):
    vals = [str(r.get(field, "") or "").strip() for r in rows]
    vals = [v for v in vals if v]
    return Counter(vals).most_common(1)[0][0] if vals else fallback


def prefer(rows, field, preferred, fallback=""):
    vals = {str(r.get(field, "") or "").strip() for r in rows}
    lookup = {v.upper(): v for v in vals if v}
    for token in preferred:
        if token.upper() in lookup:
            return lookup[token.upper()]
    return mode(rows, field, fallback)


def official_url(value):
    text = str(value or "").strip()
    if not text:
        return True
    try:
        u = urlparse(text)
    except Exception:
        return False
    return u.scheme.lower() == "https" and (u.hostname or "").lower() in ALLOWED_HOSTS


def join_urls(*values):
    seen, out = set(), []
    for value in values:
        for item in str(value or "").replace("\n", ";").split(";"):
            item = item.strip()
            if item and item not in seen:
                seen.add(item); out.append(item)
    return "; ".join(out)


def field_evidence_json(p):
    page = pick(p, "official_page_url")
    guide = pick(p, "guideline_url")
    status = pick(p, "status_evidence_url", "official_page_url", "guideline_url")
    owner = pick(p, "ownership_evidence_url", "official_page_url")
    data = {
        "scheme_name": page,
        "ministry": owner,
        "department": owner,
        "implementing_agency": owner or guide or page,
        "programme_status": status,
        "application_status": status,
        "eligibility": guide or page,
        "benefits": guide or page,
        "application_process": guide or page,
        "funding_maximum": guide or page,
    }
    return json.dumps({k: v for k, v in data.items() if v}, ensure_ascii=False, sort_keys=True)


def resolve_review(row):
    key = (pick(row, "master_id"), pick(row, "field_name"))
    resolutions = {
        ("147173e17ea741687247", "application_url"): ("APPROVED_OMISSION_NO_CURRENT_ROUTE", "No current official application route was verified. application_url remains blank and OPEN is not claimed."),
        ("147173e17ea741687247", "required_documents"): ("APPROVED_OMISSION_NOT_VERIFIED", "No governed scheme-wide document checklist was verified; the field remains blank."),
        ("147173e17ea741687247", "official_scheme_end_date"): ("APPROVED_OMISSION_NO_OFFICIAL_END_DATE", "No permanent-scheme end date was established; cohort dates are not reused."),
        ("147173e17ea741687247", "contact_details"): ("APPROVED_OMISSION_NOT_VERIFIED", "No scheme-specific public contact was verified; the field remains blank."),
        ("6af79cf6c8a213dddce8", "programme_status"): ("HISTORICAL_STATUS_CONFIRMED_NO_EXTENSION", "The official approval period ended on 2024-01-31 and no extension evidence was located."),
        ("6af79cf6c8a213dddce8", "required_documents"): ("APPROVED_OMISSION_HISTORICAL_NOT_CONSOLIDATED", "Historical application documents are not represented as current requirements."),
        ("6af79cf6c8a213dddce8", "contact_details"): ("APPROVED_OMISSION_NOT_APPLICABLE_OR_UNVERIFIED", "No current scheme-specific contact is represented for the completed historical programme."),
    }
    if key not in resolutions:
        raise RuntimeError(f"Unexpected review item: {key}")
    decision, basis = resolutions[key]
    out = dict(row)
    out.update({"review_status": "RESOLVED", "review_decision": decision, "resolution_basis": basis, "resolved_at": VERIFIED_DATE, "publication_effect": "PUBLICATION_ALLOWED_WITH_GOVERNED_OMISSION"})
    return out


def main():
    required = [ACTIVE, CURRENT_MANIFEST, IMMUTABLE, DASHBOARD, PILOT, REVIEWS, FIELD_EVIDENCE, SOURCE_VALIDATION]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Required files are missing:\n" + "\n".join(missing))

    src_validation = json.loads(SOURCE_VALIDATION.read_text(encoding="utf-8-sig"))
    if src_validation.get("validation_status") != "PASS":
        raise RuntimeError("Source MeitY pilot validation is not PASS.")

    active_fields, active_rows = read_csv(ACTIVE)
    pilot_fields, pilot_rows = read_csv(PILOT)
    review_fields, review_rows = read_csv(REVIEWS)
    _, evidence_rows = read_csv(FIELD_EVIDENCE)

    if len(active_rows) != 137 or len(pilot_rows) != 2 or len(review_rows) != 7 or len(evidence_rows) != 42:
        raise RuntimeError(f"Unexpected counts: active={len(active_rows)}, pilot={len(pilot_rows)}, reviews={len(review_rows)}, evidence={len(evidence_rows)}")
    if {pick(r, "master_id") for r in pilot_rows} != EXPECTED_IDS:
        raise RuntimeError("Pilot master IDs do not match the governed identities.")
    if any(r.get("master_id") in EXPECTED_IDS for r in active_rows):
        raise RuntimeError("A MeitY pilot ID already exists in the active catalogue.")

    from agents.governed_v1.common import dashboard_public_ids
    visible_before = set(dashboard_public_ids(ROOT, ACTIVE))
    visible_rows = [r for r in active_rows if r.get("master_id") in visible_before]
    templates = [r for r in visible_rows if pick(r, "normalized_record_kind", "record_kind").upper() not in CALL_KINDS]
    if not templates:
        raise RuntimeError("No visible scheme template rows were found.")

    defaults = {
        "normalized_record_kind": prefer(templates, "normalized_record_kind", ["SCHEME_OR_PROGRAMME", "SCHEME"], "SCHEME_OR_PROGRAMME"),
        "catalogue_inclusion": prefer(templates, "catalogue_inclusion", ["INCLUDED", "INCLUDE", "ACTIVE", "PUBLISHED"], mode(templates, "catalogue_inclusion", "INCLUDED")),
        "catalogue_section": prefer(templates, "catalogue_section", ["SCHEMES_AND_PROGRAMMES", "SCHEMES", "MAIN_CATALOGUE"], mode(templates, "catalogue_section", "SCHEMES")),
        "current_decision": prefer(templates, "current_decision", ["APPROVED_FOR_DATABASE", "APPROVED_FOR_PUBLICATION", "APPROVED", "VERIFIED_SCHEME"], mode(templates, "current_decision", "APPROVED")),
        "startup_relevance_classification": prefer(templates, "startup_relevance_classification", ["DIRECT_STARTUP_SUPPORT", "DIRECT_STARTUP_BENEFICIARY", "STARTUP_RELEVANT"], mode(templates, "startup_relevance_classification", "DIRECT_STARTUP_SUPPORT")),
        "sector_review_required": prefer(templates, "sector_review_required", ["false", "FALSE", "0", "NO"], "false"),
    }

    resolved = [resolve_review(r) for r in review_rows]
    resolved_fields = list(review_fields)
    for f in ["resolution_basis", "resolved_at", "publication_effect"]:
        if f not in resolved_fields: resolved_fields.append(f)

    ready_rows, additions = [], []
    for p in sorted(pilot_rows, key=lambda r: pick(r, "canonical_name")):
        mid = pick(p, "master_id")
        ready = dict(p)
        ready.update({
            "review_decision": "APPROVED_FOR_PUBLICATION_WITH_GOVERNED_OMISSIONS",
            "publication_status": "READY_FOR_GOVERNED_PROMOTION",
            "publication_readiness_version": VERSION,
            "publication_readiness_date": VERIFIED_DATE,
            "publication_notes": "Only verified permanent-scheme information is publishable. Unverified application routes, contacts, documents and unsupported dates remain blank.",
        })
        ready_rows.append(ready)

        row = {f: "" for f in active_fields}
        row.update({
            "master_id": mid,
            "scheme_name": pick(p, "canonical_name"),
            "source": pick(p, "platform_host") or "MeitY Startup Hub",
            "ministry": pick(p, "owning_ministry", "programme_owner") or "Ministry of Electronics and Information Technology",
            "department": "Innovation and IPR Division, MeitY" if mid == "6af79cf6c8a213dddce8" else "Ministry of Electronics and Information Technology (MeitY)",
            "implementing_agency": pick(p, "implementing_agency"),
            "normalized_record_kind": defaults["normalized_record_kind"],
            "record_kind": "SCHEME",
            "programme_status": pick(p, "programme_status"),
            "application_status": pick(p, "application_status"),
            "status_evidence": pick(p, "status_evidence_url", "guideline_url", "official_page_url"),
            "sector": "Cross-sector Innovation & Entrepreneurship",
            "scheme_type": "Accelerator Support; Funding Support" if mid == "147173e17ea741687247" else "Incubation Support; Funding Support",
            "target_beneficiaries": pick(p, "beneficiary_type"),
            "startup_stage": pick(p, "startup_stage"),
            "catalogue_inclusion": defaults["catalogue_inclusion"],
            "catalogue_section": defaults["catalogue_section"],
            "current_decision": defaults["current_decision"],
            "official_page_url": pick(p, "official_page_url"),
            "application_url": "",
            "guideline_urls": join_urls(pick(p, "guideline_url"), pick(p, "notification_url")),
            "opening_date": "",
            "closing_date": "",
            "funding_minimum": pick(p, "funding_minimum"),
            "funding_maximum": pick(p, "funding_maximum"),
            "currency": pick(p, "currency") or "INR",
            "eligibility": pick(p, "eligibility"),
            "benefits": pick(p, "benefits"),
            "application_process": pick(p, "application_process"),
            "required_documents": "",
            "contact_details": "",
            "last_verified_date": VERIFIED_DATE,
            "field_evidence": field_evidence_json(p),
            "primary_sector": "Cross-sector Innovation & Entrepreneurship",
            "secondary_sectors": "",
            "sector_confidence": pick(p, "confidence") or "0.95",
            "sector_classification_method": "MANUAL_OFFICIAL_EVIDENCE",
            "sector_evidence": "Official scheme material establishes startup acceleration, incubation, innovation and funding support.",
            "sector_review_required": defaults["sector_review_required"],
            "sector_verified_at": VERIFIED_DATE,
            "sector_agent_version": VERSION,
            "sector_evidence_url": pick(p, "guideline_url", "official_page_url"),
            "sector_reason": "The scheme supports technology startups through acceleration, incubation and structured financial or market support.",
            "startup_relevance_classification": defaults["startup_relevance_classification"],
            "startup_relevance_score": "1.00",
            "startup_beneficiary_evidence": pick(p, "beneficiary_type", "eligibility"),
            "startup_access_evidence": "Support is delivered through selected accelerators or incubation centres; no currently open central application route is asserted.",
        })
        if mid == "6af79cf6c8a213dddce8":
            row["startup_access_evidence"] = "Historical TIDE 2.0 support was delivered through participating incubation centres. The approved period ended on 2024-01-31; no current central application route is asserted."
        additions.append(row)

    ready_fields = list(pilot_fields)
    for f in ["publication_readiness_version", "publication_readiness_date", "publication_notes"]:
        if f not in ready_fields: ready_fields.append(f)

    OUT.mkdir(parents=True, exist_ok=True); AUDIT.mkdir(parents=True, exist_ok=True)
    write_csv(READY, ready_fields, ready_rows)
    write_csv(RESOLVED, resolved_fields, resolved)
    write_csv(ADDITIONS, active_fields, additions)
    candidate_rows = active_rows + additions
    write_csv(CANDIDATE, active_fields, candidate_rows)

    # Validate the candidate using the actual dashboard loader.
    # dashboard_public_ids() uses a broad fallback for non-active paths,
    # which incorrectly includes pending and review-only catalogue rows.
    previous_public_catalogue = os.environ.get(
        "SSIP_PUBLIC_CATALOGUE"
    )

    os.environ["SSIP_PUBLIC_CATALOGUE"] = str(
        CANDIDATE
    )

    try:
        from ssip_dashboard.catalogue import load_catalogue
        from ssip_dashboard.catalogue_populations import (
            split_catalogue_populations,
        )
        from ssip_dashboard.config import DashboardConfig

        candidate_config = DashboardConfig.from_env(
            ROOT
        )

        candidate_catalogue = load_catalogue(
            candidate_config
        )

        candidate_populations = (
            split_catalogue_populations(
                candidate_catalogue.records
            )
        )

        visible_after = {
            record.master_id
            for record in (
                candidate_populations.main_scheme_records
            )
            if record.master_id
        }
    finally:
        if previous_public_catalogue is None:
            os.environ.pop(
                "SSIP_PUBLIC_CATALOGUE",
                None,
            )
        else:
            os.environ[
                "SSIP_PUBLIC_CATALOGUE"
            ] = previous_public_catalogue

    new_visible = EXPECTED_IDS & visible_after
    checks = []
    def add(name, passed, details): checks.append({"name": name, "passed": bool(passed), "details": details})
    add("candidate_row_count", len(candidate_rows) == 139, f"rows={len(candidate_rows)}")
    add("candidate_master_ids_unique", len({r.get('master_id','') for r in candidate_rows}) == len(candidate_rows), "all master_id values must be unique")
    add("reviews_resolved", len(resolved) == 7 and all(r.get("review_status") == "RESOLVED" for r in resolved), f"resolved={sum(r.get('review_status') == 'RESOLVED' for r in resolved)}")
    add("no_open_application_claim", all(not r.get("application_url", "").strip() and not r.get("application_status", "").upper().startswith("OPEN") for r in additions), "application_url blank and no OPEN status")
    add("both_meity_ids_dashboard_visible", new_visible == EXPECTED_IDS, f"visible_ids={sorted(new_visible)}")
    add("dashboard_visible_count_increases_by_two", len(visible_after) == len(visible_before) + 2, f"before={len(visible_before)} after={len(visible_after)}")
    add("official_urls_only", all(official_url(r.get(f, "")) for r in additions for f in ["official_page_url", "application_url", "sector_evidence_url"]), "approved official hosts only")
    contaminated = [r for r in additions if "applyforthelogo" in " ".join(r.values()).lower() or "2023-03-29" in " ".join(r.values())]
    add("legacy_contamination_excluded", not contaminated, f"contaminated={len(contaminated)}")
    expected_statuses = {
        ("147173e17ea741687247", "CURRENT_SCHEME_INFORMATION_AVAILABLE", "APPLICATION_STATUS_REQUIRES_VERIFICATION"),
        ("6af79cf6c8a213dddce8", "HISTORICAL_INFORMATION_ONLY", "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED"),
    }
    add("governed_statuses_preserved", {(r['master_id'], r['programme_status'], r['application_status']) for r in additions} == expected_statuses, "exact status pairs required")

    failed = [c for c in checks if not c["passed"]]
    status = "PASS" if not failed else "FAIL"

    write_json(PREAUDIT, {
        "version": VERSION,
        "phase": "MeitY Publication Readiness and Governed Catalogue Promotion",
        "execution_mode": "CANDIDATE_BUILD_ONLY",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "active_catalogue": {"path": ACTIVE.relative_to(ROOT).as_posix(), "row_count": len(active_rows), "sha256": sha(ACTIVE)},
        "current_manifest_sha256": sha(CURRENT_MANIFEST),
        "immutable_catalogue": {"row_count": len(read_csv(IMMUTABLE)[1]), "sha256": sha(IMMUTABLE)},
        "dashboard_sha256": sha(DASHBOARD),
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    })
    write_json(VALIDATION, {
        "version": VERSION,
        "validation_status": status,
        "governance_defaults_derived_from_visible_catalogue": defaults,
        "counts": {"active_rows_before": len(active_rows), "candidate_rows": len(candidate_rows), "addition_rows": len(additions), "reviews_resolved": len(resolved), "visible_before": len(visible_before), "visible_after_candidate": len(visible_after)},
        "candidate_visible_meity_ids": sorted(new_visible),
        "checks": checks,
        "failed_checks": [c["name"] for c in failed],
        "publication_performed": False,
    })
    write_json(SUMMARY, {
        "version": VERSION,
        "validation_status": status,
        "active_catalogue_unchanged": True,
        "candidate_catalogue": CANDIDATE.relative_to(ROOT).as_posix(),
        "candidate_rows": len(candidate_rows),
        "dashboard_visible_before": len(visible_before),
        "dashboard_visible_after_candidate": len(visible_after),
        "next_action": "Run governed promotion only after PASS." if status == "PASS" else "Inspect failed checks before publication.",
    })

    print("\nSSIP MeitY v3.4.2.0.2 candidate build")
    print("-------------------------------------------")
    print(f"Validation status:       {status}")
    print(f"Active rows before:      {len(active_rows)}")
    print(f"Candidate rows:          {len(candidate_rows)}")
    print(f"Resolved review rows:    {len(resolved)}")
    print(f"Visible before:          {len(visible_before)}")
    print(f"Visible after candidate: {len(visible_after)}")
    print(f"MeitY IDs visible:       {len(new_visible)} of 2")
    print("Publication performed:   No")
    print(f"\nCandidate catalogue:\n{CANDIDATE}")
    print(f"\nValidation:\n{VALIDATION}")
    if failed:
        print("\nFailed checks:")
        for c in failed: print(f"- {c['name']}: {c['details']}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"CANDIDATE BUILD ERROR: {exc}", file=sys.stderr)
        raise
