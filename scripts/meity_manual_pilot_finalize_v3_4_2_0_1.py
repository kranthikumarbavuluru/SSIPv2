from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

VERSION = "3.4.2.0.1"
PHASE = "MeitY Manual Master Register Pilot - SAMRIDH and TIDE 2.0"
MODE = "MANUAL_PREVIEW_ONLY"
PHASE_DIR = ROOT / "data" / "departments" / "meity" / "v3_4_2_0_1"
AUDIT_DIR = ROOT / "data" / "audit"

P = {
    "baseline": AUDIT_DIR / "meity_v3_4_2_0_1_manual_prechange_sha256.json",
    "postchange": AUDIT_DIR / "meity_v3_4_2_0_1_manual_postchange_sha256.json",
    "lookup": PHASE_DIR / "meity_existing_identity_lookup_v3_4_2_0_1.csv",
    "master": PHASE_DIR / "meity_scheme_master_registry_v3_4_2_0_1.csv",
    "legacy": PHASE_DIR / "meity_legacy_status_adjudication_v3_4_2_0_1.csv",
    "calls": PHASE_DIR / "meity_call_instance_review_queue_v3_4_2_0_1.csv",
    "official": PHASE_DIR / "meity_official_evidence_registry_v3_4_2_0_1.csv",
    "statuses": PHASE_DIR / "meity_current_status_adjudication_v3_4_2_0_1.csv",
    "pilot": PHASE_DIR / "meity_extraction_pilot_records_v3_4_2_0_1.csv",
    "reviews": PHASE_DIR / "meity_extraction_review_queue_v3_4_2_0_1.csv",
    "field": PHASE_DIR / "meity_field_evidence_registry_v3_4_2_0_1.csv",
    "validation": PHASE_DIR / "meity_extraction_validation_v3_4_2_0_1.json",
    "summary": PHASE_DIR / "meity_extraction_summary_v3_4_2_0_1.json",
    "manifest": PHASE_DIR / "meity_extraction_manifest_v3_4_2_0_1.json",
    "active": ROOT / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv",
    "published": ROOT / "data" / "publication" / "20260710T162806+0000_f4936983" / "catalogue.csv",
}

EXPECTED_IDS = {"147173e17ea741687247", "6af79cf6c8a213dddce8"}
EXPECTED_CANONICAL_HASH = "838ca86cde4b2ceebd4325850c783823c931a3e42ef5c4ef74b7ae54a4596e4d"
ALLOWED_HOSTS = {"msh.meity.gov.in", "meity.gov.in", "www.meity.gov.in", "pib.gov.in", "www.pib.gov.in"}
PUBLIC_FIELDS = [
    "canonical_name", "official_abbreviation", "record_kind", "owning_ministry",
    "programme_owner", "implementing_agency", "platform_host", "programme_status",
    "application_status", "objective", "eligibility", "beneficiary_type", "startup_stage",
    "benefits", "funding_maximum", "currency", "funding_context", "application_process",
    "official_page_url", "guideline_url", "notification_url", "official_scheme_end_date",
]
PILOT_URL_FIELDS = [
    "official_page_url", "guideline_url", "notification_url", "identity_evidence_url",
    "ownership_evidence_url", "status_evidence_url",
]


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + os.linesep, encoding="utf-8", newline="")


def sha256_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root: Path) -> str:
    """Use the original PowerShell governed tree-hash algorithm."""
    if not root.exists():
        return "MISSING"

    import subprocess

    helper = (
        ROOT
        / "scripts"
        / "ssip_powershell_tree_hash_v1.ps1"
    )

    if not helper.exists():
        raise RuntimeError(
            f"Tree-hash helper is missing: {helper}"
        )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            str(root.resolve()),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    output_lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    if not output_lines:
        raise RuntimeError(
            "PowerShell tree-hash helper returned "
            f"no output for {root}"
        )

    value = output_lines[-1].lower()

    if value != "missing":
        valid = (
            len(value) == 64
            and all(
                character in "0123456789abcdef"
                for character in value
            )
        )

        if not valid:
            raise RuntimeError(
                f"Invalid tree hash returned for {root}: {value}"
            )

    return value


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def official_url(value: str) -> bool:
    if not value.strip():
        return True
    u = urlparse(value)
    return u.scheme.lower() == "https" and (u.hostname or "").lower() in ALLOWED_HOSTS


def main() -> int:
    required = [P[k] for k in ("baseline", "lookup", "master", "legacy", "calls", "official", "statuses", "pilot", "reviews", "field", "active", "published")]
    missing = [str(x) for x in required if not x.exists()]
    if missing:
        raise RuntimeError("Required files are missing:\n" + "\n".join(missing))

    baseline = read_json(P["baseline"])
    masters = read_csv(P["master"])
    legacy = read_csv(P["legacy"])
    calls = read_csv(P["calls"])
    official = read_csv(P["official"])
    statuses = read_csv(P["statuses"])
    pilot = read_csv(P["pilot"])
    reviews = read_csv(P["reviews"])
    field = read_csv(P["field"])
    active = read_csv(P["active"])
    published = read_csv(P["published"])

    checks = []
    def add(name, passed, details):
        checks.append({"name": name, "passed": bool(passed), "details": details})

    add("exactly_two_master_records", len(masters) == 2, f"Actual master records: {len(masters)}")
    add("exactly_two_pilot_records", len(pilot) == 2, f"Actual pilot records: {len(pilot)}")
    add("existing_master_ids_preserved", {r.get("master_id") for r in masters} == EXPECTED_IDS and {r.get("master_id") for r in pilot} == EXPECTED_IDS, "Existing IDs retained")

    all_groups = [masters, legacy, calls, official, statuses, pilot, reviews, field]
    all_rows = [r for g in all_groups for r in g]
    unexpected = [r for r in all_rows if r.get("master_id", "").strip() and r.get("master_id") not in EXPECTED_IDS]
    add("no_new_permanent_identity", not unexpected, f"Unexpected governed IDs: {len(unexpected)}")

    for name, actual, expected in [
        ("legacy_adjudication_count", len(legacy), 2),
        ("call_review_count", len(calls), 4),
        ("official_evidence_count", len(official), 13),
        ("current_status_adjudication_count", len(statuses), 2),
        ("extraction_review_count", len(reviews), 7),
        ("field_evidence_count", len(field), 42),
    ]:
        add(name, actual == expected, f"Actual: {actual}; expected: {expected}")

    add("both_identities_are_schemes", all(r.get("record_kind") == "SCHEME" for r in masters), "Both master records are SCHEME")
    add("existing_identity_decisions_retained", all(r.get("identity_decision") == "EXISTING_MASTER_ID_RETAINED" for r in masters), "Existing IDs retained")

    mb = {r["master_id"]: r for r in masters}
    pb = {r["master_id"]: r for r in pilot}
    sam = pb.get("147173e17ea741687247", {})
    tide = pb.get("6af79cf6c8a213dddce8", {})

    add("master_statuses_governed", mb.get("147173e17ea741687247", {}).get("current_scheme_status") == "CURRENT_SCHEME_INFORMATION_AVAILABLE" and mb.get("6af79cf6c8a213dddce8", {}).get("current_scheme_status") == "HISTORICAL_INFORMATION_ONLY", "SAMRIDH current information; TIDE 2.0 historical")
    add("pilot_statuses_governed", sam.get("programme_status") == "CURRENT_SCHEME_INFORMATION_AVAILABLE" and sam.get("application_status") == "APPLICATION_STATUS_REQUIRES_VERIFICATION" and tide.get("programme_status") == "HISTORICAL_INFORMATION_ONLY" and tide.get("application_status") == "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED" and tide.get("official_scheme_end_date") == "2024-01-31", "No open application asserted")

    invalid_open = [r for r in statuses if r.get("current_open_call_confirmed", "").lower() != "false"]
    invalid_app = [r for r in pilot if r.get("application_url", "").strip() or r.get("application_status", "").startswith("OPEN")]
    add("no_open_application_asserted", not invalid_open and not invalid_app, f"Open-call violations: {len(invalid_open)}; application violations: {len(invalid_app)}")

    public_rows = masters + official + statuses + pilot + field
    contaminated = [r for r in public_rows if "applyforthelogo" in " ".join(r.values()).lower() or "2023-03-29" in " ".join(r.values())]
    add("legacy_contamination_excluded", not contaminated, f"Contaminated public/governed rows: {len(contaminated)}")

    legacy_ok = all(r.get("adjudication_decision") == "LEGACY_STATUS_REJECTED_AS_CONTAMINATED" and r.get("application_url_disposition") == "REJECT_AS_UNRELATED_MSH_LOGO_LINK" and r.get("closing_date_disposition") == "REJECT_AS_UNRELATED_PAGE_DEADLINE" and r.get("permanent_identity_disposition") == "PRESERVE_EXISTING_MASTER_ID" for r in legacy)
    add("legacy_contamination_adjudicated", legacy_ok, "Legacy contamination preserved only as adjudication evidence")

    calls_ok = all(r.get("create_permanent_master", "").lower() == "false" for r in calls) and sum(r.get("candidate_type") == "COHORT_INSTANCE" for r in calls) == 2 and sum(r.get("candidate_type") == "UNRELATED_PAGE_DEADLINE" for r in calls) == 2
    add("calls_and_cohorts_separate_from_scheme_masters", calls_ok, "No call or cohort creates a master")

    coverage_failures = []
    for r in pilot:
        for f in PUBLIC_FIELDS:
            v = r.get(f, "")
            if not v.strip():
                continue
            m = [e for e in field if e.get("master_id") == r.get("master_id") and e.get("field_name") == f and e.get("field_value") == v]
            if len(m) != 1:
                coverage_failures.append((r.get("master_id"), f, len(m)))
    groups = {}
    for e in field:
        key = (e.get("master_id", ""), e.get("field_name", ""))
        groups[key] = groups.get(key, 0) + 1
    duplicate_groups = [k for k, c in groups.items() if c != 1]
    add("every_populated_public_field_has_exact_evidence", not coverage_failures and not duplicate_groups, f"Coverage failures: {len(coverage_failures)}; duplicate groups: {len(duplicate_groups)}")

    bad_evidence_urls = [r for r in official + field if not official_url(r.get("evidence_url", ""))]
    add("all_evidence_urls_are_official", not bad_evidence_urls, f"Invalid evidence URLs: {len(bad_evidence_urls)}")
    bad_pilot_urls = [(r.get("master_id"), f) for r in pilot for f in PILOT_URL_FIELDS if r.get(f, "").strip() and not official_url(r.get(f, ""))]
    add("all_pilot_urls_are_official", not bad_pilot_urls, f"Invalid pilot URLs: {len(bad_pilot_urls)}")

    publication_violations = [r for r in all_rows if "publication_status" in r and r.get("publication_status") != "NOT_PUBLISHED"]
    add("all_phase_outputs_not_published", not publication_violations, f"Publication-state violations: {len(publication_violations)}")
    add("field_completeness_scores_valid", sam.get("field_completeness") == "0.77" and tide.get("field_completeness") == "0.85", "Expected SAMRIDH=0.77 and TIDE 2.0=0.85")

    frozen_files = []
    for rp, expected in baseline.get("frozen_files", {}).items():
        full = ROOT.joinpath(*rp.split("/"))
        actual = sha256_file(full)
        frozen_files.append({"path": rp, "expected_sha256": expected, "actual_sha256": actual, "unchanged": expected == actual})
    changed_files = [x for x in frozen_files if not x["unchanged"]]
    add("frozen_files_unchanged", not changed_files, f"Changed frozen files: {len(changed_files)}")

    frozen_trees = []
    for rp, expected in baseline.get("frozen_trees", {}).items():
        full = ROOT.joinpath(*rp.split("/"))
        actual = tree_hash(full)
        frozen_trees.append({"path": rp, "expected_sha256": expected, "actual_sha256": actual, "unchanged": expected == actual})
    changed_trees = [x for x in frozen_trees if not x["unchanged"]]
    add("frozen_department_trees_unchanged", not changed_trees, f"Changed frozen trees: {len(changed_trees)}")

    active_rows, published_rows = len(active), len(published)
    add("active_catalogue_row_count_unchanged", active_rows == 137, f"Active catalogue rows: {active_rows}")
    add("immutable_publication_row_count_unchanged", published_rows == 137, f"Immutable published rows: {published_rows}")

    from agents.governed_v1.common import dashboard_public_ids
    from agents.publication_agent import content_hash
    visible = len(dashboard_public_ids(ROOT, P["active"]))
    canonical = content_hash(P["published"].read_bytes()).lower()
    add("dashboard_visible_baseline_unchanged", visible == 51, f"Dashboard-visible records: {visible}")
    add("canonical_publication_hash_unchanged", canonical == EXPECTED_CANONICAL_HASH, f"Canonical publication hash: {canonical}")
    active_matches = [r for r in active if r.get("master_id") in EXPECTED_IDS]
    add("pilot_records_absent_from_active_catalogue", not active_matches, f"Pilot IDs in active catalogue: {len(active_matches)}")

    failed = [x for x in checks if not x["passed"]]
    status = "PASS" if not failed else "FAIL"

    validation = {
        "version": VERSION, "phase": PHASE, "execution_mode": MODE,
        "baseline_recorded_at": baseline.get("recorded_at"), "validation_status": status,
        "counts": {
            "master_records": len(masters), "legacy_adjudications": len(legacy),
            "call_instance_reviews": len(calls), "official_evidence_rows": len(official),
            "status_adjudications": len(statuses), "extraction_pilot_records": len(pilot),
            "extraction_review_rows": len(reviews), "field_evidence_rows": len(field),
            "active_catalogue_rows": active_rows, "dashboard_visible_records": visible,
            "immutable_published_rows": published_rows,
        },
        "governed_master_ids": sorted(EXPECTED_IDS),
        "canonical_publication_hash": canonical,
        "checks": checks,
        "failed_checks": [x["name"] for x in failed],
    }
    write_json(P["validation"], validation)

    summary = {
        "version": VERSION, "phase": PHASE, "execution_mode": MODE,
        "validation_status": status, "publication_status": "NOT_PUBLISHED",
        "scope": {"permanent_scheme_count": 2, "permanent_scheme_names": ["SAMRIDH", "TIDE 2.0"], "new_permanent_identities_created": 0, "open_calls_created": 0},
        "output_counts": {"master_records": len(masters), "legacy_adjudications": len(legacy), "call_instance_reviews": len(calls), "official_evidence_rows": len(official), "status_adjudications": len(statuses), "extraction_pilot_records": len(pilot), "extraction_review_rows": len(reviews), "field_evidence_rows": len(field)},
        "catalogue_baseline": {"active_rows": active_rows, "visible_records": visible, "immutable_published_rows": published_rows, "canonical_publication_hash": canonical},
        "decisions": [
            {"master_id": "147173e17ea741687247", "canonical_name": "SAMRIDH", "identity_decision": "EXISTING_MASTER_ID_RETAINED", "programme_status": "CURRENT_SCHEME_INFORMATION_AVAILABLE", "application_status": "APPLICATION_STATUS_REQUIRES_VERIFICATION", "field_completeness": "0.77", "confidence": "0.95", "review_decision": "NEEDS_MANUAL_REVIEW"},
            {"master_id": "6af79cf6c8a213dddce8", "canonical_name": "TIDE 2.0", "identity_decision": "EXISTING_MASTER_ID_RETAINED", "programme_status": "HISTORICAL_INFORMATION_ONLY", "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED", "official_scheme_end_date": "2024-01-31", "field_completeness": "0.85", "confidence": "0.99", "review_decision": "NEEDS_MANUAL_REVIEW"},
        ],
        "unresolved_review_count": sum(r.get("review_status") == "OPEN" for r in reviews),
        "governance_notes": [
            "Existing SAMRIDH and TIDE 2.0 master IDs are retained.",
            "Cohorts, rounds and application windows are not permanent scheme masters.",
            "The unrelated MSH logo URL and 29 March 2023 date are excluded from public fields.",
            "No publication, database update or dashboard update was performed.",
        ],
    }
    write_json(P["summary"], summary)

    governed_outputs = [P[k] for k in ("master", "legacy", "calls", "official", "statuses", "pilot", "reviews", "field", "validation", "summary")]
    manifest_entries = [{"path": rel(x), "sha256": sha256_file(x), "row_count": len(read_csv(x)) if x.suffix.lower() == ".csv" else None} for x in governed_outputs]
    manifest = {
        "version": VERSION, "phase": PHASE, "execution_mode": MODE,
        "baseline_recorded_at": baseline.get("recorded_at"), "validation_status": status,
        "publication_status": "NOT_PUBLISHED", "governed_output_count": 11,
        "governed_outputs": manifest_entries,
        "auxiliary_outputs": [{"path": rel(P["lookup"]), "sha256": sha256_file(P["lookup"]), "purpose": "Working identity lookup used to confirm existing master IDs."}],
        "frozen_source_audit": "data/audit/meity_v3_4_2_0_1_manual_prechange_sha256.json",
        "postchange_audit": "data/audit/meity_v3_4_2_0_1_manual_postchange_sha256.json",
    }
    write_json(P["manifest"], manifest)

    postchange = {
        "version": VERSION, "phase": PHASE, "execution_mode": MODE,
        "baseline_recorded_at": baseline.get("recorded_at"), "validation_status": status,
        "frozen_files": frozen_files, "frozen_trees": frozen_trees,
        "phase_output_tree_sha256": tree_hash(PHASE_DIR),
        "generated_output_hashes": {"validation": sha256_file(P["validation"]), "summary": sha256_file(P["summary"]), "manifest": sha256_file(P["manifest"])},
        "catalogue_baseline": {"active_rows": active_rows, "visible_records": visible, "immutable_published_rows": published_rows, "canonical_publication_hash": canonical},
        "publication_performed": False, "database_modified": False, "dashboard_modified": False,
    }
    write_json(P["postchange"], postchange)

    print("\nMeitY v3.4.2.0.1 finalization")
    print("----------------------------------------")
    print(f"Validation status: {status}")
    print(f"Master records:    {len(masters)}")
    print(f"Pilot records:     {len(pilot)}")
    print(f"Field evidence:    {len(field)}")
    print(f"Review rows:       {len(reviews)}")
    print(f"Catalogue rows:    {active_rows}")
    print(f"Visible records:   {visible}")
    print(f"Published rows:    {published_rows}")
    print(f"\nValidation:\n{P['validation']}")
    print(f"\nSummary:\n{P['summary']}")
    print(f"\nManifest:\n{P['manifest']}")
    print(f"\nPost-change audit:\n{P['postchange']}")

    if failed:
        print("\nFailed checks:")
        for x in failed:
            print(f"- {x['name']}: {x['details']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
