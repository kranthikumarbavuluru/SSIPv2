from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VERSION = "3.4.4.1"
SOURCE_ACTIVE = ROOT / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
LIVE_ACTIVE = ROOT / "data/catalogue_preview/v3_4_4_1/catalogue_preview_v3_4_4_1.csv"
SOURCE_DIR = ROOT / "data/departments/dpiit/v3_4_4_0"
OUTPUT_DIR = ROOT / "data/departments/dpiit/v3_4_4_1"
CURRENT_MANIFEST = ROOT / "data/publication/current_manifest.json"
DATABASE = ROOT / "database/ssip_staging_v1.db"

PERMANENT_FILE = SOURCE_DIR / "dpiit_permanent_inventory_v3_4_4_0.csv"
HISTORICAL_FILE = SOURCE_DIR / "dpiit_historical_call_inventory_v3_4_4_0.csv"
DOCUMENT_FILE = SOURCE_DIR / "dpiit_supporting_document_index_v3_4_4_0.csv"
SOURCE_REGISTRY_FILE = SOURCE_DIR / "dpiit_official_source_registry_v3_4_4_0.csv"
SOURCE_MANIFEST_FILE = SOURCE_DIR / "dpiit_signed_dry_run_manifest_v3_4_4_0.json"
SOURCE_VALIDATION_FILE = SOURCE_DIR / "dpiit_validation_report_v3_4_4_0.json"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(path: Path) -> str:
    from agents.publication_agent import content_hash

    return content_hash(path.read_bytes()).lower()


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    shutil.copy2(source, temp)
    os.replace(temp, destination)


def official_domains() -> set[str]:
    _, rows = read_csv(SOURCE_REGISTRY_FILE)
    return {
        str(row.get("official_domain", "")).casefold().strip().lstrip(".")
        for row in rows
        if str(row.get("official_domain", "")).strip()
    }


def allowed_official_url(url: str, domains: set[str]) -> bool:
    host = (urlparse(str(url)).hostname or "").casefold()
    return bool(host and any(host == domain or host.endswith("." + domain) for domain in domains))


def validate_source_package() -> dict[str, Any]:
    manifest = read_json(SOURCE_MANIFEST_FILE)
    validation = read_json(SOURCE_VALIDATION_FILE)
    file_checks: dict[str, bool] = {}
    for item in manifest.get("files", []):
        path = ROOT / str(item.get("relative_path", ""))
        file_checks[str(item.get("relative_path", ""))] = (
            path.is_file() and sha256_file(path) == str(item.get("sha256", ""))
        )
    checks = {
        "source_manifest_passed": manifest.get("validation_status") == "PASS",
        "source_validation_passed": validation.get("status") == "PASS",
        "source_was_preview_only": manifest.get("publication_performed") is False,
        "database_was_not_written": manifest.get("database_write_performed") is False,
        "source_files_match_signed_manifest": bool(file_checks) and all(file_checks.values()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "source_file_checks": file_checks,
        "source_manifest": manifest,
    }


def existing_dpiit_ids() -> set[str]:
    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    base = DashboardConfig.from_env(ROOT)
    bundle = load_catalogue(
        replace(
            base,
            normalization_path=SOURCE_ACTIVE,
            preview_path_configured=True,
        )
    )
    result = set()
    for record in split_catalogue_populations(bundle.records).main_scheme_records:
        haystack = " ".join(
            (
                record.source,
                record.ministry,
                record.department,
                record.implementing_agency,
            )
        ).casefold()
        if "dpiit" in haystack or "promotion of industry and internal trade" in haystack:
            result.add(record.master_id)
    return result


def supporting_documents_by_parent() -> dict[str, list[dict[str, str]]]:
    _, documents = read_csv(DOCUMENT_FILE)
    grouped: dict[str, list[dict[str, str]]] = {}
    for document in documents:
        grouped.setdefault(document.get("parent_record_id", ""), []).append(document)
    return grouped


def candidate_row(
    record: dict[str, str],
    fields: list[str],
    documents: dict[str, list[dict[str, str]]],
) -> dict[str, str]:
    record_id = record.get("record_id", "")
    record_type = record.get("record_type", "")
    is_historical = record_type == "HISTORICAL_CALL"
    evidence_documents = [
        item
        for item in documents.get(record_id, [])
        if item.get("document_type") in {"FAQ", "GUIDELINE"}
    ]
    guideline_urls = ";".join(
        item.get("official_url", "") for item in evidence_documents
        if item.get("official_url", "")
    )
    sector = record.get("sector", "")
    if sector.casefold() == "not verified":
        sector = ""
    field_evidence = json.dumps(
        {
            "source_record_type": record_type,
            "parent_record_id": record.get("parent_record_id", ""),
            "evidence_status": record.get("evidence_status", ""),
            "publication_authority": "USER_CONFIRMED_2026_07_21",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    values: dict[str, str] = {
        "master_id": record_id,
        "scheme_name": record.get("canonical_name", ""),
        "source": "DPIIT governed official-source inventory",
        "ministry": record.get("ministry", ""),
        "department": record.get("department", ""),
        "implementing_agency": record.get("implementing_agency", ""),
        "normalized_record_kind": record_type,
        "record_kind": record_type,
        "programme_status": "HISTORICAL_REFERENCE" if is_historical else "CURRENT_PROGRAMME_IDENTITY",
        "application_status": "CLOSED" if is_historical else "NOT_APPLICABLE_TO_PROGRAMME_IDENTITY",
        "status_evidence": (
            "Official evidence confirms this call is closed; no Apply action is published."
            if is_historical
            else "Permanent identity; application status is evaluated only on dated calls."
        ),
        "sector": sector,
        "scheme_type": record_type,
        "target_beneficiaries": record.get("direct_applicant_layer", ""),
        "startup_stage": "",
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "HISTORICAL_ARCHIVE" if is_historical else "SCHEMES_AND_PROGRAMMES",
        "current_decision": "APPROVED_FOR_PUBLICATION",
        "official_page_url": record.get("official_url", ""),
        "application_url": "",
        "guideline_urls": guideline_urls or record.get("guideline_url", ""),
        "opening_date": record.get("opening_date", ""),
        "closing_date": record.get("closing_date", ""),
        "eligibility": "",
        "benefits": record.get("summary", ""),
        "application_process": "Refer to the official evidence; no unverified application action is published.",
        "last_verified_date": record.get("last_verified_date", ""),
        "field_evidence": field_evidence,
        "primary_sector": sector,
        "secondary_sectors": "",
        "sector_confidence": "1.0" if sector else "",
        "sector_classification_method": "OFFICIAL_EVIDENCE" if sector else "NOT_VERIFIED",
        "sector_evidence": record.get("summary", "") if sector else "",
        "sector_review_required": "0" if sector else "1",
        "sector_verified_at": record.get("last_verified_date", "") if sector else "",
        "sector_agent_version": VERSION,
        "sector_evidence_url": record.get("official_url", "") if sector else "",
        "sector_reason": "Official source supports the displayed sector scope." if sector else "Sector evidence not verified.",
        "startup_relevance_classification": record.get("startup_relevance", ""),
        "startup_relevance_score": "",
        "startup_beneficiary_evidence": record.get("summary", ""),
        "startup_access_evidence": record.get("direct_applicant_layer", ""),
    }
    return {field: values.get(field, "") for field in fields}


def build_candidate() -> dict[str, Any]:
    source_validation = validate_source_package()
    if not source_validation["passed"]:
        raise RuntimeError("The signed DPIIT source package failed validation.")

    fields, active_rows = read_csv(SOURCE_ACTIVE)
    _, permanent = read_csv(PERMANENT_FILE)
    _, historical = read_csv(HISTORICAL_FILE)
    documents = supporting_documents_by_parent()
    legacy_ids = existing_dpiit_ids()
    retained = [row for row in active_rows if row.get("master_id", "") not in legacy_ids]
    publication_rows = [
        candidate_row(row, fields, documents) for row in [*permanent, *historical]
    ]
    candidate = [*retained, *publication_rows]
    candidate.sort(key=lambda row: (row.get("catalogue_section", ""), row.get("scheme_name", "").casefold()))

    ids = [row.get("master_id", "") for row in candidate]
    domains = official_domains()
    dpiit_urls_valid = all(
        allowed_official_url(row.get("official_page_url", ""), domains)
        for row in publication_rows
    )
    historical_safe = all(
        not row.get("application_url", "")
        and row.get("application_status", "") == "CLOSED"
        for row in publication_rows
        if row.get("record_kind", "") == "HISTORICAL_CALL"
    )
    current_manifest = read_json(CURRENT_MANIFEST)
    current_version = str(
        current_manifest.get("summary", {}).get("service_version", "")
    )
    manifest_catalogue = LIVE_ACTIVE if current_version == VERSION else SOURCE_ACTIVE
    checks = {
        "signed_source_package_passed": source_validation["passed"],
        "active_manifest_matches_source": (
            manifest_catalogue.exists()
            and canonical_hash(manifest_catalogue)
            == str(current_manifest.get("catalogue_sha256", "")).lower()
        ),
        "candidate_master_ids_unique": len(ids) == len(set(ids)) and all(ids),
        "legacy_dpiit_rows_reconciled": not (legacy_ids & set(ids)),
        "twelve_permanent_records_included": len(permanent) == 12,
        "three_historical_records_included": len(historical) == 3,
        "official_domains_enforced": dpiit_urls_valid,
        "historical_apply_actions_suppressed": historical_safe,
        "no_current_dpiit_call_claimed": not any(
            row.get("application_status", "") in {"OPEN", "UPCOMING"}
            for row in publication_rows
        ),
    }
    return {
        "fields": fields,
        "rows": candidate,
        "legacy_ids": sorted(legacy_ids),
        "published_ids": sorted(row["master_id"] for row in publication_rows),
        "source_validation": source_validation,
        "checks": checks,
        "passed": all(checks.values()),
        "counts": {
            "source_rows": len(active_rows),
            "retained_rows": len(retained),
            "legacy_dpiit_rows_removed": len(active_rows) - len(retained),
            "published_dpiit_permanent": len(permanent),
            "published_dpiit_historical": len(historical),
            "candidate_rows": len(candidate),
            "supporting_documents_linked": sum(
                item.get("document_type") in {"FAQ", "GUIDELINE"}
                for items in documents.values() for item in items
            ),
            "inactive_application_portals_suppressed": sum(
                item.get("document_type") == "APPLICATION_PORTAL"
                for items in documents.values() for item in items
            ),
        },
    }


def dashboard_snapshot(path: Path) -> dict[str, Any]:
    from ssip_dashboard.analytics import build_public_analytics
    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig
    from ssip_dashboard.meity_public_integrated_v3_4_3_8_1 import partition_meity_department_view
    from ssip_dashboard.metrics import compute_metrics

    base = DashboardConfig.from_env(ROOT)
    bundle = load_catalogue(
        replace(base, normalization_path=path.resolve(), preview_path_configured=True)
    )
    populations = split_catalogue_populations(bundle.records)
    analytics = build_public_analytics(bundle.records)
    metrics = compute_metrics(bundle.records)
    meity = partition_meity_department_view(bundle.records)
    return {
        "loaded_records": len(bundle.records),
        "scheme_count": analytics.scheme_count,
        "call_count": analytics.call_count,
        "open_call_windows": analytics.open_call_windows,
        "department_count": metrics.total_explicit_departments,
        "latest_verification": analytics.latest_verification_signal,
        "main_ids": sorted(row.master_id for row in populations.main_scheme_records),
        "call_ids": sorted(row.master_id for row in populations.application_call_records),
        "meity_programmes": len(meity["programmes"]),
        "meity_calls": len(meity["calls"]),
        "meity_names": [row.scheme_name for row in meity["programmes"]],
    }


def write_candidate(result: dict[str, Any]) -> tuple[Path, Path]:
    from agents.common import atomic_write_csv, atomic_write_json

    candidate_path = (
        ROOT
        / "data/catalogue_preview/v3_4_4_1"
        / "catalogue_preview_candidate_v3_4_4_1.csv"
    )
    validation_path = OUTPUT_DIR / "governed_publication_validation_v3_4_4_1.json"
    atomic_write_csv(candidate_path, result["rows"], result["fields"])
    snapshot = dashboard_snapshot(candidate_path)
    published_ids = set(result["published_ids"])
    projection_checks = {
        "all_dpiit_permanent_visible": len(published_ids & set(snapshot["main_ids"])) == 12,
        "all_dpiit_historical_classified_as_calls": len(published_ids & set(snapshot["call_ids"])) == 3,
        "latest_verification_is_2026_07_21": snapshot["latest_verification"] == "2026-07-21",
        "meity_utility_pages_removed": not any(
            name in {
                "About", "Accessibility Statement", "Contact", "Dashboard",
                "Disclaimer", "Screen Reader", "Sitemap 0.Xml", "Sitemap.Xml",
                "Terms Conditions",
            }
            for name in snapshot["meity_names"]
        ),
    }
    result["checks"].update(projection_checks)
    result["passed"] = all(result["checks"].values())
    result["dashboard_snapshot"] = snapshot
    atomic_write_json(
        validation_path,
        {
            "version": VERSION,
            "status": "PASS" if result["passed"] else "FAIL",
            "publication_performed": False,
            "checks": result["checks"],
            "counts": result["counts"],
            "dashboard_snapshot": snapshot,
            "legacy_dpiit_master_ids_removed": result["legacy_ids"],
            "candidate_sha256": sha256_file(candidate_path),
            "database_sha256": sha256_file(DATABASE),
        },
    )
    if not result["passed"]:
        raise RuntimeError("Candidate projection validation failed.")
    return candidate_path, validation_path


def publish(result: dict[str, Any], candidate_path: Path, validation_path: Path) -> dict[str, Any]:
    from agents.common import atomic_write_json, utc_now

    if not result["passed"] or read_json(validation_path).get("status") != "PASS":
        raise RuntimeError("Publication blocked because candidate validation did not pass.")

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S+0000")
        + "_dpiit_v3_4_4_1_"
        + uuid.uuid4().hex[:8]
    )
    release_dir = ROOT / "data/publication" / run_id
    rollback_dir = ROOT / "data/publication/rollback" / f"{run_id}_pre_publish"
    audit_path = ROOT / "data/audit" / f"governed_live_publication_{run_id}.json"
    release_dir.mkdir(parents=True, exist_ok=False)
    rollback_dir.mkdir(parents=True, exist_ok=False)
    atomic_copy(SOURCE_ACTIVE, rollback_dir / SOURCE_ACTIVE.name)
    atomic_copy(CURRENT_MANIFEST, rollback_dir / CURRENT_MANIFEST.name)
    atomic_copy(candidate_path, release_dir / "catalogue.csv")
    atomic_copy(validation_path, release_dir / validation_path.name)

    before = {
        "source_active_sha256": sha256_file(SOURCE_ACTIVE),
        "current_manifest_sha256": sha256_file(CURRENT_MANIFEST),
        "database_sha256": sha256_file(DATABASE),
    }
    try:
        atomic_copy(candidate_path, LIVE_ACTIVE)
        snapshot = dashboard_snapshot(LIVE_ACTIVE)
        published_ids = set(result["published_ids"])
        post_checks = {
            "live_matches_candidate": sha256_file(LIVE_ACTIVE) == sha256_file(candidate_path),
            "database_unchanged": sha256_file(DATABASE) == before["database_sha256"],
            "all_published_dpiit_ids_live": published_ids <= (
                set(snapshot["main_ids"]) | set(snapshot["call_ids"])
            ),
            "latest_verification_updated": snapshot["latest_verification"] == "2026-07-21",
            "meity_projection_clean": snapshot["meity_programmes"] == 4,
        }
        if not all(post_checks.values()):
            raise RuntimeError(
                "Post-publication validation failed: "
                + ", ".join(name for name, passed in post_checks.items() if not passed)
            )
        summary = {
            "service_version": VERSION,
            "publication_mode": "GOVERNED_LIVE_CATALOGUE_PROMOTION",
            "published_dpiit_record_ids": result["published_ids"],
            "published_dpiit_permanent": 12,
            "published_dpiit_historical": 3,
            "published_supporting_documents": result["counts"]["supporting_documents_linked"],
            "suppressed_inactive_application_portals": result["counts"]["inactive_application_portals_suppressed"],
            "legacy_dpiit_rows_removed": result["counts"]["legacy_dpiit_rows_removed"],
            "home_scheme_count": snapshot["scheme_count"],
            "home_open_call_windows": snapshot["open_call_windows"],
            "home_department_count": snapshot["department_count"],
            "latest_verification": snapshot["latest_verification"],
            "database_modified": False,
        }
        manifest = {
            "run_id": run_id,
            "published_at": utc_now(),
            "catalogue_path": str(LIVE_ACTIVE),
            "versioned_catalogue_path": str(release_dir / "catalogue.csv"),
            "row_count": result["counts"]["candidate_rows"],
            "catalogue_sha256": canonical_hash(LIVE_ACTIVE),
            "validation": {"passed": True, "checks": post_checks, "errors": []},
            "summary": summary,
            "rollback_directory": str(rollback_dir),
        }
        atomic_write_json(release_dir / "manifest.json", manifest)
        atomic_write_json(CURRENT_MANIFEST, manifest)
        atomic_write_json(
            release_dir / "publication_summary.json",
            {"publication_status": "PUBLISHED", **summary},
        )
        atomic_write_json(
            audit_path,
            {
                "version": VERSION,
                "run_id": run_id,
                "status": "PASS",
                "before": before,
                "after": {
                    "live_catalogue_sha256": sha256_file(LIVE_ACTIVE),
                    "current_manifest_sha256": sha256_file(CURRENT_MANIFEST),
                    "database_sha256": sha256_file(DATABASE),
                    "dashboard_snapshot": snapshot,
                },
                "checks": post_checks,
                "rollback_directory": str(rollback_dir),
            },
        )
        return manifest
    except Exception:
        if LIVE_ACTIVE.exists():
            LIVE_ACTIVE.unlink()
        atomic_copy(rollback_dir / CURRENT_MANIFEST.name, CURRENT_MANIFEST)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and publish the reconciled SSIP v3.4.4.1 live catalogue."
    )
    parser.add_argument("--confirm-publish", action="store_true")
    args = parser.parse_args()

    result = build_candidate()
    candidate_path, validation_path = write_candidate(result)
    print(f"Candidate: {candidate_path}")
    print(f"Validation: {validation_path}")
    print(json.dumps(result["counts"], indent=2))
    print(json.dumps(result["dashboard_snapshot"], indent=2))
    if not args.confirm_publish:
        print("Publication not performed. Candidate validation: PASS")
        return 0

    manifest = publish(result, candidate_path, validation_path)
    print("Publication status: PASS")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
