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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

VERSION = "3.4.2.0.2"
PHASE = "MeitY Governed Catalogue Promotion — SAMRIDH and TIDE 2.0"
EXPECTED_IDS = {
    "147173e17ea741687247",
    "6af79cf6c8a213dddce8",
}

ACTIVE = (
    ROOT
    / "data"
    / "catalogue_preview"
    / "v3_3_2"
    / "catalogue_preview_v3_3_2.csv"
)
CANDIDATE = (
    ROOT
    / "data"
    / "catalogue_preview"
    / "v3_4_2_0_2"
    / "catalogue_preview_v3_4_2_0_2.csv"
)
CANDIDATE_VALIDATION = (
    ROOT
    / "data"
    / "departments"
    / "meity"
    / "v3_4_2_0_2"
    / "meity_explicit_preview_validation_v3_4_2_0_2.json"
)
CURRENT_MANIFEST = ROOT / "data" / "publication" / "current_manifest.json"
PUBLICATION_ROOT = ROOT / "data" / "publication"
AUDIT_ROOT = ROOT / "data" / "audit"
LATEST_POINTER = PUBLICATION_ROOT / "meity_v3_4_2_0_2_latest_publication.json"
DASHBOARD_APP = ROOT / "apps" / "public_dashboard_app_v2_9.py"
DATABASE = ROOT / "database" / "ssip_staging_v1.db"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


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


def dashboard_snapshot(path: Path) -> dict[str, Any]:
    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    base = DashboardConfig.from_env(ROOT)
    config = replace(
        base,
        normalization_path=path.resolve(),
        preview_path_configured=True,
    )
    bundle = load_catalogue(config)
    populations = split_catalogue_populations(bundle.records)
    main_ids = {
        record.master_id
        for record in populations.main_scheme_records
        if record.master_id
    }
    loaded_ids = {record.master_id for record in bundle.records if record.master_id}
    return {
        "loaded_records": len(bundle.records),
        "main_visible_records": len(main_ids),
        "application_calls": len(populations.application_call_records),
        "evidence_only_records": len(populations.evidence_only_records),
        "archived_records": len(populations.archived_scheme_records),
        "verification_required_records": len(
            populations.verification_required_scheme_records
        ),
        "meity_loaded_ids": sorted(EXPECTED_IDS & loaded_ids),
        "meity_main_visible_ids": sorted(EXPECTED_IDS & main_ids),
    }


def restore_from_backup(
    backup_active: Path,
    backup_manifest: Path,
) -> None:
    if backup_active.exists():
        atomic_copy(backup_active, ACTIVE)
    if backup_manifest.exists():
        atomic_copy(backup_manifest, CURRENT_MANIFEST)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Governed publication of the validated MeitY 139-row catalogue."
    )
    parser.add_argument(
        "--confirm-publish",
        action="store_true",
        help="Required safety flag. Without it, no publication is performed.",
    )
    args = parser.parse_args()

    if not args.confirm_publish:
        print("Publication not performed: pass --confirm-publish to execute promotion.")
        return 2

    required = [
        ACTIVE,
        CANDIDATE,
        CANDIDATE_VALIDATION,
        CURRENT_MANIFEST,
        DASHBOARD_APP,
        DATABASE,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Required files are missing:\n" + "\n".join(missing))

    validation = read_json(CANDIDATE_VALIDATION)
    if validation.get("validation_status") != "PASS":
        raise RuntimeError("Explicit-preview candidate validation is not PASS.")
    if validation.get("publication_performed") is not False:
        raise RuntimeError("Candidate validation does not show publication_performed=false.")
    if validation.get("failed_checks"):
        raise RuntimeError(
            "Candidate validation contains failed checks: "
            + ", ".join(validation.get("failed_checks", []))
        )

    active_fields, active_rows = read_csv(ACTIVE)
    candidate_fields, candidate_rows = read_csv(CANDIDATE)
    current_manifest = read_json(CURRENT_MANIFEST)

    if len(active_rows) != 137:
        raise RuntimeError(f"Expected 137 active rows; found {len(active_rows)}.")
    if len(candidate_rows) != 139:
        raise RuntimeError(f"Expected 139 candidate rows; found {len(candidate_rows)}.")
    if active_fields != candidate_fields:
        raise RuntimeError("Candidate column order differs from the active catalogue.")
    if candidate_rows[: len(active_rows)] != active_rows:
        raise RuntimeError("The existing 137 catalogue rows are not byte-logically preserved.")

    candidate_ids = [row.get("master_id", "") for row in candidate_rows]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RuntimeError("Candidate master_id values are not unique.")
    if not EXPECTED_IDS <= set(candidate_ids):
        raise RuntimeError("Candidate does not contain both governed MeitY master IDs.")

    active_canonical = canonical_hash(ACTIVE)
    manifest_hash = str(current_manifest.get("catalogue_sha256", "")).lower()
    if manifest_hash and active_canonical != manifest_hash:
        raise RuntimeError(
            "Active catalogue canonical hash does not match current_manifest.json."
        )

    candidate_snapshot = dashboard_snapshot(CANDIDATE)
    if candidate_snapshot["main_visible_records"] != 53:
        raise RuntimeError(
            "Candidate dashboard-visible count is not 53: "
            f"{candidate_snapshot['main_visible_records']}"
        )
    if set(candidate_snapshot["meity_main_visible_ids"]) != EXPECTED_IDS:
        raise RuntimeError("Both MeitY records are not main-visible in the candidate.")

    published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S+0000")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    release_dir = PUBLICATION_ROOT / run_id
    release_catalogue = release_dir / "catalogue.csv"
    release_manifest = release_dir / "manifest.json"
    release_summary = release_dir / "publication_summary.json"
    rollback_dir = PUBLICATION_ROOT / "rollback" / f"{run_id}_pre_meity_v3_4_2_0_2"
    backup_active = rollback_dir / "catalogue_preview_v3_3_2.csv"
    backup_manifest = rollback_dir / "current_manifest.json"
    postchange_audit = AUDIT_ROOT / f"meity_v3_4_2_0_2_publication_{run_id}.json"

    release_dir.mkdir(parents=True, exist_ok=False)
    rollback_dir.mkdir(parents=True, exist_ok=False)
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ACTIVE, backup_active)
    shutil.copy2(CURRENT_MANIFEST, backup_manifest)
    shutil.copy2(CANDIDATE, release_catalogue)

    before = {
        "active_rows": len(active_rows),
        "active_raw_sha256": sha256_file(ACTIVE),
        "active_canonical_sha256": active_canonical,
        "current_manifest_sha256": sha256_file(CURRENT_MANIFEST),
        "dashboard_sha256": sha256_file(DASHBOARD_APP),
        "database_sha256": sha256_file(DATABASE),
        "dashboard_snapshot": dashboard_snapshot(ACTIVE),
    }

    try:
        atomic_copy(CANDIDATE, ACTIVE)

        promoted_fields, promoted_rows = read_csv(ACTIVE)
        if promoted_fields != candidate_fields or promoted_rows != candidate_rows:
            raise RuntimeError("Promoted active catalogue does not match the candidate.")

        promoted_snapshot = dashboard_snapshot(ACTIVE)
        if promoted_snapshot["main_visible_records"] != 53:
            raise RuntimeError(
                "Post-promotion dashboard-visible count is not 53: "
                f"{promoted_snapshot['main_visible_records']}"
            )
        if set(promoted_snapshot["meity_main_visible_ids"]) != EXPECTED_IDS:
            raise RuntimeError("Both MeitY records are not visible after promotion.")

        promoted_canonical = canonical_hash(ACTIVE)
        if promoted_canonical != canonical_hash(release_catalogue):
            raise RuntimeError("Active and immutable release canonical hashes differ.")

        checks = {
            "candidate_validation_passed": True,
            "active_row_count_before_137": True,
            "active_row_count_after_139": len(promoted_rows) == 139,
            "existing_137_rows_preserved": promoted_rows[:137] == active_rows,
            "identity_order_preserved_for_existing_rows": [
                row.get("master_id", "") for row in promoted_rows[:137]
            ]
            == [row.get("master_id", "") for row in active_rows],
            "master_ids_unique": len(
                {row.get("master_id", "") for row in promoted_rows}
            )
            == 139,
            "both_meity_ids_present": EXPECTED_IDS
            <= {row.get("master_id", "") for row in promoted_rows},
            "dashboard_visible_53": promoted_snapshot["main_visible_records"] == 53,
            "both_meity_ids_dashboard_visible": set(
                promoted_snapshot["meity_main_visible_ids"]
            )
            == EXPECTED_IDS,
            "dashboard_code_unchanged": sha256_file(DASHBOARD_APP)
            == before["dashboard_sha256"],
            "database_unchanged": sha256_file(DATABASE) == before["database_sha256"],
            "immutable_release_matches_active": sha256_file(release_catalogue)
            == sha256_file(ACTIVE),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError("Post-promotion checks failed: " + ", ".join(failed))

        manifest = {
            "run_id": run_id,
            "published_at": published_at,
            "catalogue_path": str(ACTIVE),
            "versioned_catalogue_path": str(release_catalogue),
            "row_count": 139,
            "catalogue_sha256": promoted_canonical,
            "validation": {
                "passed": True,
                "checks": checks,
                "errors": [],
            },
            "summary": {
                "service_version": VERSION,
                "phase": PHASE,
                "run_id": run_id,
                "input_rows": 137,
                "published_rows": 139,
                "added_rows": 2,
                "added_master_ids": sorted(EXPECTED_IDS),
                "dashboard_visible_before": before["dashboard_snapshot"][
                    "main_visible_records"
                ],
                "dashboard_visible_after": promoted_snapshot[
                    "main_visible_records"
                ],
                "publication_mode": "GOVERNED_EXPLICIT_PREVIEW_PROMOTION",
                "database_modified": False,
                "dashboard_modified": False,
                "active_catalogue": str(ACTIVE),
            },
        }
        write_json_atomic(release_manifest, manifest)
        write_json_atomic(CURRENT_MANIFEST, manifest)

        summary = {
            "version": VERSION,
            "phase": PHASE,
            "run_id": run_id,
            "published_at": published_at,
            "publication_status": "PUBLISHED",
            "active_catalogue_rows": 139,
            "dashboard_visible_records": 53,
            "added_records": [
                {
                    "master_id": "147173e17ea741687247",
                    "scheme_name": "SAMRIDH",
                    "programme_status": "CURRENT_SCHEME_INFORMATION_AVAILABLE",
                    "application_status": "APPLICATION_STATUS_REQUIRES_VERIFICATION",
                },
                {
                    "master_id": "6af79cf6c8a213dddce8",
                    "scheme_name": "TIDE 2.0",
                    "programme_status": "HISTORICAL_INFORMATION_ONLY",
                    "application_status": "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
                },
            ],
            "rollback_directory": str(rollback_dir),
            "database_modified": False,
            "dashboard_modified": False,
        }
        write_json_atomic(release_summary, summary)

        audit = {
            "version": VERSION,
            "phase": PHASE,
            "run_id": run_id,
            "published_at": published_at,
            "publication_status": "PASS",
            "before": before,
            "after": {
                "active_rows": 139,
                "active_raw_sha256": sha256_file(ACTIVE),
                "active_canonical_sha256": promoted_canonical,
                "current_manifest_sha256": sha256_file(CURRENT_MANIFEST),
                "release_catalogue_sha256": sha256_file(release_catalogue),
                "release_manifest_sha256": sha256_file(release_manifest),
                "dashboard_sha256": sha256_file(DASHBOARD_APP),
                "database_sha256": sha256_file(DATABASE),
                "dashboard_snapshot": promoted_snapshot,
            },
            "checks": checks,
            "rollback": {
                "directory": str(rollback_dir),
                "active_catalogue_backup": str(backup_active),
                "current_manifest_backup": str(backup_manifest),
            },
            "database_modified": False,
            "dashboard_modified": False,
        }
        write_json_atomic(postchange_audit, audit)
        write_json_atomic(
            LATEST_POINTER,
            {
                "version": VERSION,
                "run_id": run_id,
                "published_at": published_at,
                "release_directory": str(release_dir),
                "rollback_directory": str(rollback_dir),
                "publication_audit": str(postchange_audit),
            },
        )

    except Exception:
        restore_from_backup(backup_active, backup_manifest)
        raise

    print()
    print("SSIP MeitY v3.4.2.0.2 governed publication")
    print("------------------------------------------------")
    print("Publication status:      PASS")
    print(f"Run ID:                  {run_id}")
    print("Active catalogue rows:   139")
    print("Dashboard visible:       53")
    print("MeitY records visible:   2 of 2")
    print("Database modified:       No")
    print("Dashboard code modified: No")
    print()
    print("Active catalogue:")
    print(ACTIVE)
    print()
    print("Immutable release:")
    print(release_dir)
    print()
    print("Current manifest:")
    print(CURRENT_MANIFEST)
    print()
    print("Rollback backup:")
    print(rollback_dir)
    print()
    print("Publication audit:")
    print(postchange_audit)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PUBLICATION ERROR: {exc}", file=sys.stderr)
        raise
