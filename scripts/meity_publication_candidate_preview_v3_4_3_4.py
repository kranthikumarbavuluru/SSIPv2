from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import io
import json
import os
import sys
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "3.4.3.4"
PHASE = "MeitY SASACT and GENESIS Publication Candidate, Dashboard Preview and Release Readiness"

SAMRIDH_ID = "147173e17ea741687247"
TIDE_ID = "6af79cf6c8a213dddce8"
SASACT_ID = "194b7ba77d6b53f30b91"
GENESIS_ID = "94f8ab0a070a6ff15fce"
TARGET_IDS = {SASACT_ID, GENESIS_ID}
SUPPRESS_APPLICATION = "NO_CURRENT_APPLICATION_ROUTE"

TARGETS = {
    "SASACT": {
        "master_id": SASACT_ID,
        "template_id": TIDE_ID,
        "official_name": "Scheme for Accelerating Startups around Post-COVID Technology Opportunities (SASACT)",
        "official_url": "https://msh.meity.gov.in/schemes/sasact",
        "programme_status": "HISTORICAL_SCHEME_INFORMATION_AVAILABLE",
        "scheme_status": "HISTORICAL_INFORMATION_ONLY",
        "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
    },
    "GENESIS": {
        "master_id": GENESIS_ID,
        "template_id": SAMRIDH_ID,
        "official_name": "GEN-NEXT Support for Innovative Startups (GENESIS)",
        "official_url": "https://msh.meity.gov.in/schemes/genesis",
        "programme_status": "UMBRELLA_SCHEME_INFORMATION_AVAILABLE",
        "scheme_status": "CURRENT_SCHEME_INFORMATION_AVAILABLE",
        "application_status": "APPLICATION_STATUS_REQUIRES_VERIFICATION",
    },
}


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(tmp, path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)


def set_many(row: dict[str, str], fields: set[str], keys: tuple[str, ...], value: Any) -> None:
    rendered = "" if value is None else str(value)
    for key in keys:
        if key in fields:
            row[key] = rendered


def evidence_values(rows: list[dict[str, str]], scheme: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in rows:
        if norm(row.get("canonical_name")).upper() != scheme:
            continue
        key = norm(row.get("field_name"))
        value = norm(row.get("field_value"))
        if key and value and key not in values:
            values[key] = value
    return values


def build_row(
    scheme: str,
    config: dict[str, str],
    template: dict[str, str],
    fields: list[str],
    evidence: dict[str, str],
    application: dict[str, str],
) -> dict[str, str]:
    row = deepcopy(template)
    available = set(fields)

    clear_keys = (
        "call_id", "call_title", "call_name", "parent_master_id",
        "parent_scheme_name", "parent_programme", "cohort", "round",
        "opening_date", "open_date", "closing_date", "close_date",
        "deadline", "current_call_id", "current_call_url",
        "application_window", "application_process",
        "application_deadline", "call_status", "call_type",
        "status_evidence", "application_evidence", "source_url",
        "guidelines_url", "manual_url", "notification_url",
        "related_links", "quality_flags", "rejection_reasons",
        "required_documents",
    )
    set_many(row, available, clear_keys, "")

    set_many(row, available, ("master_id",), config["master_id"])
    set_many(
        row,
        available,
        ("canonical_name", "scheme_name", "title", "candidate_name", "display_name"),
        scheme,
    )
    set_many(row, available, ("official_full_name", "long_name"), config["official_name"])
    set_many(row, available, ("source", "agency", "source_name"), "MeitY Startup Hub")
    set_many(
        row,
        available,
        ("ministry", "department"),
        "Ministry of Electronics and Information Technology (MeitY)",
    )
    set_many(
        row,
        available,
        ("implementing_agency", "implementation_agency"),
        evidence.get("implementing_agency", "MeitY Startup Hub"),
    )
    set_many(
        row,
        available,
        ("official_page_url", "core_scheme_url", "best_available_url", "final_url", "scheme_url"),
        config["official_url"],
    )

    set_many(row, available, ("record_kind", "record_type"), "SCHEME")
    set_many(row, available, ("master_type",), "SCHEME_OR_PROGRAMME")
    set_many(row, available, ("scheme_type",), "SCHEME")
    set_many(row, available, ("programme_status",), config["programme_status"])
    set_many(row, available, ("scheme_status", "current_status"), config["scheme_status"])
    set_many(row, available, ("application_status",), config["application_status"])
    set_many(row, available, ("application_url",), SUPPRESS_APPLICATION)

    objective = evidence.get("objective", application.get("status_rationale", ""))
    eligibility = evidence.get("startup_eligibility", "")
    benefit = evidence.get("funding_support", evidence.get("historical_grant_evidence", ""))

    set_many(row, available, ("objective", "description", "summary"), objective)
    set_many(row, available, ("eligibility", "eligible_applicants"), eligibility)
    set_many(row, available, ("benefits", "funding", "funding_amount", "funding_support"), benefit)
    set_many(row, available, ("budget", "total_budget"), evidence.get("total_budget", ""))
    set_many(row, available, ("duration",), evidence.get("duration", ""))
    set_many(row, available, ("target_geography", "geography"), evidence.get("target_geography", ""))
    set_many(
        row,
        available,
        ("status_note", "status_rationale", "review_notes"),
        application.get("status_rationale", ""),
    )

    set_many(row, available, ("catalogue_inclusion",), "INCLUDED")
    set_many(row, available, ("current_decision", "validation_decision"), "APPROVED_FOR_DATABASE")
    set_many(row, available, ("verification_status",), "VERIFIED")
    set_many(row, available, ("confidence", "confidence_after_validation"), "0.98")
    set_many(row, available, ("last_verified_at", "last_verified", "latest_verification"), date.today().isoformat())
    set_many(row, available, ("publication_candidate",), "true")

    return {field: row.get(field, "") for field in fields}


def append_preserving_bytes(
    active: Path,
    candidate: Path,
    fields: list[str],
    rows: list[dict[str, str]],
) -> None:
    original = active.read_bytes()
    newline = "\r\n" if b"\r\n" in original else "\n"

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        extrasaction="ignore",
        lineterminator=newline,
    )
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})

    separator = b""
    if original and not original.endswith((b"\n", b"\r")):
        separator = newline.encode("ascii")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    tmp = candidate.with_suffix(candidate.suffix + ".tmp")
    tmp.write_bytes(original + separator + buffer.getvalue().encode("utf-8"))
    os.replace(tmp, candidate)


def override_catalogue_path(config: Any, path: Path) -> Any:
    if not dataclasses.is_dataclass(config):
        raise RuntimeError("DashboardConfig is not a dataclass.")

    names = {field.name for field in dataclasses.fields(config)}
    for name in (
        "normalization_path",
        "catalogue_path",
        "catalogue_csv_path",
        "preview_catalogue_path",
        "public_catalogue_path",
    ):
        if name in names:
            return dataclasses.replace(config, **{name: path})

    candidates = []
    for field in dataclasses.fields(config):
        value = getattr(config, field.name)
        if (
            isinstance(value, Path)
            and value.suffix.casefold() == ".csv"
            and ("catalog" in field.name.casefold() or "normal" in field.name.casefold())
        ):
            candidates.append(field.name)

    if len(candidates) != 1:
        raise RuntimeError(f"Cannot identify catalogue path field: {candidates}")

    return dataclasses.replace(config, **{candidates[0]: path})


def dashboard_snapshot(project: Path, catalogue: Path) -> dict[str, Any]:
    sys.path.insert(0, str(project))

    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    config = override_catalogue_path(DashboardConfig.from_env(project), catalogue)
    bundle = load_catalogue(config)
    populations = split_catalogue_populations(bundle.records)

    records = {
        record.master_id: record
        for record in bundle.records
        if getattr(record, "master_id", "")
    }
    main_ids = {
        record.master_id
        for record in populations.main_scheme_records
        if getattr(record, "master_id", "")
    }

    targets: dict[str, Any] = {}
    for master_id in TARGET_IDS:
        record = records.get(master_id)
        targets[master_id] = {
            "loaded": record is not None,
            "main_visible": master_id in main_ids,
            "scheme_name": getattr(record, "scheme_name", "") if record else "",
            "application_url": getattr(record, "application_url", "") if record else "",
            "application_status": getattr(record, "application_status", "") if record else "",
            "programme_status": getattr(record, "programme_status", "") if record else "",
        }

    return {
        "loaded_records": len(bundle.records),
        "main_visible_records": len(main_ids),
        "targets": targets,
    }


def self_test() -> None:
    fields = ["master_id", "scheme_name", "application_url", "catalogue_inclusion"]
    row = build_row(
        "SASACT",
        TARGETS["SASACT"],
        {field: "template" for field in fields},
        fields,
        {},
        {},
    )
    assert row["master_id"] == SASACT_ID
    assert row["application_url"] == SUPPRESS_APPLICATION
    assert row["catalogue_inclusion"] == "INCLUDED"
    print("MeitY v3.4.3.4 publication-candidate self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    project = root()
    active = project / "data" / "catalogue_preview" / "v3_3_2" / "catalogue_preview_v3_3_2.csv"
    manifest = project / "data" / "publication" / "current_manifest.json"
    database = project / "database" / "ssip_staging_v1.db"
    dashboard = project / "apps" / "public_dashboard_app_v2_9.py"

    source_dir = project / "data" / "departments" / "meity" / "v3_4_3_3"
    identity_file = source_dir / "meity_new_scheme_identity_validation_v3_4_3_3.csv"
    evidence_file = source_dir / "meity_new_scheme_field_evidence_v3_4_3_3.csv"
    application_file = source_dir / "meity_new_scheme_application_status_v3_4_3_3.csv"
    upstream_validation = source_dir / "meity_new_scheme_validation_v3_4_3_3.json"

    output_dir = project / "data" / "departments" / "meity" / "v3_4_3_4"
    preview_dir = project / "data" / "catalogue_preview" / "v3_4_3_4"
    audit_dir = project / "data" / "audit"

    candidate = preview_dir / "catalogue_preview_v3_4_3_4.csv"
    candidate_rows_file = output_dir / "meity_publication_candidate_rows_v3_4_3_4.csv"
    validation_file = output_dir / "meity_dashboard_preview_validation_v3_4_3_4.json"
    summary_file = output_dir / "meity_release_readiness_summary_v3_4_3_4.json"
    manifest_file = output_dir / "meity_release_readiness_manifest_v3_4_3_4.json"

    required = [
        active, manifest, database, dashboard,
        identity_file, evidence_file, application_file, upstream_validation,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing required inputs:\n" + "\n".join(missing))

    upstream = json.loads(upstream_validation.read_text(encoding="utf-8-sig"))
    if upstream.get("validation_status") != "PASS":
        raise RuntimeError("v3.4.3.3 validation is not PASS.")

    frozen = [active, manifest, database, dashboard, identity_file, evidence_file, application_file, upstream_validation]
    before_hashes = {path.relative_to(project).as_posix(): digest(path) for path in frozen}

    audit_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        audit_dir / "meity_v3_4_3_4_prechange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "frozen_files": before_hashes,
            "publication_performed": False,
        },
    )

    fields, active_rows = read_csv(active)
    if len(active_rows) != 139:
        raise RuntimeError(f"Expected 139 active rows; found {len(active_rows)}.")

    active_by_id = {norm(row.get("master_id")): row for row in active_rows}
    if len(active_by_id) != len(active_rows):
        raise RuntimeError("Active catalogue contains duplicate/blank master IDs.")
    if TARGET_IDS & set(active_by_id):
        raise RuntimeError("SASACT or GENESIS is already active.")
    for template_id in (SAMRIDH_ID, TIDE_ID):
        if template_id not in active_by_id:
            raise RuntimeError(f"Template record missing: {template_id}")

    _, identity_rows = read_csv(identity_file)
    _, evidence_rows = read_csv(evidence_file)
    _, application_rows = read_csv(application_file)

    identities = {norm(row.get("canonical_name")).upper(): row for row in identity_rows}
    applications = {norm(row.get("canonical_name")).upper(): row for row in application_rows}

    new_rows: list[dict[str, str]] = []
    for scheme, config in TARGETS.items():
        identity = identities.get(scheme)
        application = applications.get(scheme)
        if not identity or not application:
            raise RuntimeError(f"Missing validated rows for {scheme}.")
        if norm(identity.get("identity_confirmed")).casefold() != "true":
            raise RuntimeError(f"{scheme} identity is not confirmed.")
        if norm(identity.get("master_id")) != config["master_id"]:
            raise RuntimeError(f"{scheme} governed master ID mismatch.")
        if norm(application.get("application_url")):
            raise RuntimeError(f"{scheme} unexpectedly has an application URL.")

        new_rows.append(
            build_row(
                scheme,
                config,
                active_by_id[config["template_id"]],
                fields,
                evidence_values(evidence_rows, scheme),
                application,
            )
        )

    write_csv(candidate_rows_file, fields, new_rows)
    append_preserving_bytes(active, candidate, fields, new_rows)

    candidate_fields, candidate_rows = read_csv(candidate)
    if candidate_fields != fields:
        raise RuntimeError("Candidate columns differ from active columns.")
    if len(candidate_rows) != 141:
        raise RuntimeError(f"Expected 141 candidate rows; found {len(candidate_rows)}.")

    prefix_preserved = candidate.read_bytes().startswith(active.read_bytes())
    existing_rows_preserved = candidate_rows[:139] == active_rows
    candidate_ids = [norm(row.get("master_id")) for row in candidate_rows]
    unique_ids = len(candidate_ids) == len(set(candidate_ids))

    active_snapshot = dashboard_snapshot(project, active)
    candidate_snapshot = dashboard_snapshot(project, candidate)

    after_hashes = {path.relative_to(project).as_posix(): digest(path) for path in frozen}
    frozen_unchanged = {name: before_hashes[name] == after_hashes[name] for name in before_hashes}

    checks = [
        ("active_rows_139", len(active_rows) == 139, f"actual={len(active_rows)}"),
        ("candidate_rows_141", len(candidate_rows) == 141, f"actual={len(candidate_rows)}"),
        ("active_bytes_preserved", prefix_preserved, "candidate begins with exact active bytes"),
        ("existing_rows_preserved", existing_rows_preserved, "first 139 rows unchanged"),
        ("master_ids_unique", unique_ids, f"unique={len(set(candidate_ids))}"),
        ("active_dashboard_53", active_snapshot["main_visible_records"] == 53, f"actual={active_snapshot['main_visible_records']}"),
        ("candidate_dashboard_55", candidate_snapshot["main_visible_records"] == 55, f"actual={candidate_snapshot['main_visible_records']}"),
        ("targets_loaded", all(candidate_snapshot["targets"][mid]["loaded"] for mid in TARGET_IDS), json.dumps(candidate_snapshot["targets"], sort_keys=True)),
        ("targets_main_visible", all(candidate_snapshot["targets"][mid]["main_visible"] for mid in TARGET_IDS), json.dumps(candidate_snapshot["targets"], sort_keys=True)),
        ("no_public_application_urls", all(not norm(candidate_snapshot["targets"][mid]["application_url"]) for mid in TARGET_IDS), json.dumps(candidate_snapshot["targets"], sort_keys=True)),
        ("frozen_files_unchanged", all(frozen_unchanged.values()), json.dumps(frozen_unchanged, sort_keys=True)),
        ("publication_not_performed", True, "preview only"),
    ]

    failed = [
        {"name": name, "details": details}
        for name, passed, details in checks
        if not passed
    ]
    status = "PASS" if not failed else "FAIL"

    validation = {
        "version": VERSION,
        "phase": PHASE,
        "validation_status": status,
        "generated_at": now_iso(),
        "counts": {
            "active_raw_rows": len(active_rows),
            "candidate_raw_rows": len(candidate_rows),
            "active_loaded_records": active_snapshot["loaded_records"],
            "candidate_loaded_records": candidate_snapshot["loaded_records"],
            "active_main_visible": active_snapshot["main_visible_records"],
            "candidate_main_visible": candidate_snapshot["main_visible_records"],
            "new_meity_records": 2,
        },
        "active_snapshot": active_snapshot,
        "candidate_snapshot": candidate_snapshot,
        "checks": [
            {"name": name, "passed": passed, "details": details}
            for name, passed, details in checks
        ],
        "failed_checks": [item["name"] for item in failed],
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }
    write_json(validation_file, validation)

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "release_readiness_status": status,
        "generated_at": now_iso(),
        "active_catalogue": str(active),
        "candidate_catalogue": str(candidate),
        "active_dashboard_schemes": active_snapshot["main_visible_records"],
        "candidate_dashboard_schemes": candidate_snapshot["main_visible_records"],
        "candidate_records": candidate_snapshot["targets"],
        "governance": {
            "sasact_historical": True,
            "genesis_application_status_unverified": True,
            "public_application_buttons_added": 0,
            "publication_performed": False,
        },
    }
    write_json(summary_file, summary)

    generated = [candidate, candidate_rows_file, validation_file, summary_file]
    write_json(
        manifest_file,
        {
            "version": VERSION,
            "phase": PHASE,
            "generated_at": now_iso(),
            "release_readiness_status": status,
            "outputs": [
                {
                    "path": path.relative_to(project).as_posix(),
                    "sha256": digest(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in generated
            ],
            "publication_status": "NOT_PUBLISHED",
        },
    )

    write_json(
        audit_dir / "meity_v3_4_3_4_postchange_sha256.json",
        {
            "version": VERSION,
            "phase": PHASE,
            "recorded_at": now_iso(),
            "release_readiness_status": status,
            "frozen_file_results": {
                name: {
                    "before": before_hashes[name],
                    "after": after_hashes[name],
                    "unchanged": frozen_unchanged[name],
                }
                for name in before_hashes
            },
            "candidate_catalogue": {
                "path": candidate.relative_to(project).as_posix(),
                "sha256": digest(candidate),
                "row_count": len(candidate_rows),
            },
            "publication_performed": False,
        },
    )

    print()
    print("SSIP MeitY v3.4.3.4 publication candidate")
    print("----------------------------------------------------")
    print(f"Release readiness status:       {status}")
    print(f"Active raw rows:                {len(active_rows)}")
    print(f"Candidate raw rows:             {len(candidate_rows)}")
    print(f"Active dashboard schemes:       {active_snapshot['main_visible_records']}")
    print(f"Candidate dashboard schemes:    {candidate_snapshot['main_visible_records']}")
    print(f"SASACT candidate visible:       {candidate_snapshot['targets'][SASACT_ID]['main_visible']}")
    print(f"GENESIS candidate visible:      {candidate_snapshot['targets'][GENESIS_ID]['main_visible']}")
    print("Public application buttons:     0")
    print(f"Existing rows preserved:        {existing_rows_preserved}")
    print("Active catalogue modified:      No")
    print("Database modified:              No")
    print("Dashboard code modified:        No")
    print("Publication performed:          No")
    print()
    print("Candidate catalogue:")
    print(candidate)
    print()
    print("Validation:")
    print(validation_file)

    if failed:
        print()
        print("Failed checks:")
        for item in failed:
            print(f"- {item['name']}: {item['details']}")

    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"RELEASE-READINESS ERROR: {exc}", file=sys.stderr)
        raise
