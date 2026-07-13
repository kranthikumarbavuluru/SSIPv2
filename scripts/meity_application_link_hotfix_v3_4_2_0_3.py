from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

VERSION = "3.4.2.0.3"
PHASE = "MeitY Invalid Application-Link Suppression Hotfix"

ACTIVE = (
    ROOT
    / "data"
    / "catalogue_preview"
    / "v3_3_2"
    / "catalogue_preview_v3_3_2.csv"
)
CURRENT_MANIFEST = ROOT / "data" / "publication" / "current_manifest.json"
PUBLICATION_ROOT = ROOT / "data" / "publication"
AUDIT_DIR = ROOT / "data" / "audit"
PHASE_DIR = ROOT / "data" / "departments" / "meity" / "v3_4_2_0_3"
PREVIEW_DIR = ROOT / "data" / "catalogue_preview" / "v3_4_2_0_3"

VALIDATION_PATH = PHASE_DIR / "meity_application_link_hotfix_validation_v3_4_2_0_3.json"
SUMMARY_PATH = PHASE_DIR / "meity_application_link_hotfix_summary_v3_4_2_0_3.json"
AUDIT_PATH = AUDIT_DIR / "meity_v3_4_2_0_3_application_link_hotfix.json"
PREVIEW_COPY = PREVIEW_DIR / "catalogue_preview_v3_4_2_0_3.csv"

SAMRIDH_ID = "147173e17ea741687247"
TIDE_ID = "6af79cf6c8a213dddce8"
TARGET_IDS = {SAMRIDH_ID, TIDE_ID}

INVALID_URL = "https://msh.meity.gov.in/about/applyforthelogo"
SUPPRESSION_VALUE = "NO_CURRENT_APPLICATION_ROUTE"

EXPECTED_OFFICIAL_PAGES = {
    SAMRIDH_ID: "https://msh.meity.gov.in/schemes/samridh",
    TIDE_ID: "https://msh.meity.gov.in/schemes/tide",
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dashboard_records():
    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import split_catalogue_populations
    from ssip_dashboard.config import DashboardConfig

    config = DashboardConfig.from_env(ROOT)
    bundle = load_catalogue(config)
    populations = split_catalogue_populations(bundle.records)
    records_by_id = {
        record.master_id: record
        for record in bundle.records
        if record.master_id
    }
    main_ids = {
        record.master_id
        for record in populations.main_scheme_records
        if record.master_id
    }
    return bundle, populations, records_by_id, main_ids


def main() -> int:
    required = [ACTIVE, CURRENT_MANIFEST]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Required files are missing:\n" + "\n".join(missing))

    fields, before_rows = read_csv(ACTIVE)
    before_manifest = read_json(CURRENT_MANIFEST)

    if len(before_rows) != 139:
        raise RuntimeError(
            f"Expected the published 139-row catalogue; found {len(before_rows)} rows."
        )

    target_rows = [
        row for row in before_rows if row.get("master_id", "").strip() in TARGET_IDS
    ]
    if {row.get("master_id", "").strip() for row in target_rows} != TARGET_IDS:
        raise RuntimeError("SAMRIDH and TIDE 2.0 were not both found exactly once.")

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S+0000")
        + "_meity_app_link_hotfix"
    )
    backup_dir = PUBLICATION_ROOT / "backups" / run_id
    release_dir = PUBLICATION_ROOT / run_id
    backup_dir.mkdir(parents=True, exist_ok=False)
    release_dir.mkdir(parents=True, exist_ok=False)

    active_backup = backup_dir / "catalogue_before.csv"
    manifest_backup = backup_dir / "current_manifest_before.json"
    shutil.copy2(ACTIVE, active_backup)
    shutil.copy2(CURRENT_MANIFEST, manifest_backup)

    before_active_raw_sha = raw_sha256(ACTIVE)
    before_manifest_raw_sha = raw_sha256(CURRENT_MANIFEST)

    after_rows = deepcopy(before_rows)

    for row in after_rows:
        master_id = row.get("master_id", "").strip()
        if master_id not in TARGET_IDS:
            continue

        row["application_url"] = SUPPRESSION_VALUE

        if master_id == SAMRIDH_ID:
            row["application_status"] = "APPLICATION_STATUS_REQUIRES_VERIFICATION"
        else:
            row["application_status"] = "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED"

        row["official_page_url"] = EXPECTED_OFFICIAL_PAGES[master_id]

    changed_non_target_rows = [
        index
        for index, (before, after) in enumerate(zip(before_rows, after_rows))
        if before != after and before.get("master_id", "").strip() not in TARGET_IDS
    ]
    if changed_non_target_rows:
        raise RuntimeError(
            f"Unexpected non-target row changes: {changed_non_target_rows[:10]}"
        )

    try:
        write_csv(ACTIVE, fields, after_rows)
        write_csv(PREVIEW_COPY, fields, after_rows)

        bundle, populations, records_by_id, main_ids = load_dashboard_records()

        checks: list[dict[str, object]] = []

        def add(name: str, passed: bool, details: str) -> None:
            checks.append(
                {"name": name, "passed": bool(passed), "details": details}
            )

        _, reloaded_rows = read_csv(ACTIVE)
        reloaded_by_id = {
            row.get("master_id", "").strip(): row
            for row in reloaded_rows
            if row.get("master_id", "").strip()
        }

        add(
            "active_row_count_139",
            len(reloaded_rows) == 139,
            f"actual={len(reloaded_rows)}",
        )
        add(
            "master_ids_unique",
            len(reloaded_by_id) == len(reloaded_rows),
            f"unique={len(reloaded_by_id)} rows={len(reloaded_rows)}",
        )
        add(
            "target_plan_values_suppress_db_fallback",
            all(
                reloaded_by_id[target_id].get("application_url")
                == SUPPRESSION_VALUE
                for target_id in TARGET_IDS
            ),
            "Both catalogue rows must contain the explicit non-URL suppression value.",
        )
        add(
            "dashboard_application_urls_blank",
            all(
                target_id in records_by_id
                and not getattr(records_by_id[target_id], "application_url", "")
                for target_id in TARGET_IDS
            ),
            "The dashboard loader must expose a blank application_url for both schemes.",
        )
        add(
            "invalid_logo_url_absent_from_loaded_records",
            all(
                INVALID_URL.casefold()
                not in getattr(records_by_id[target_id], "application_url", "").casefold()
                for target_id in TARGET_IDS
            ),
            "The MSH logo-application URL must not be exposed.",
        )
        add(
            "official_pages_preserved",
            all(
                target_id in records_by_id
                and getattr(records_by_id[target_id], "official_page_url", "")
                == EXPECTED_OFFICIAL_PAGES[target_id]
                for target_id in TARGET_IDS
            ),
            "Both records must retain their official scheme-information pages.",
        )
        add(
            "both_meity_records_main_visible",
            TARGET_IDS <= main_ids,
            f"visible={sorted(TARGET_IDS & main_ids)}",
        )
        add(
            "dashboard_visible_count_53",
            len(main_ids) == 53,
            f"actual={len(main_ids)}",
        )
        add(
            "non_target_rows_preserved",
            not changed_non_target_rows,
            f"changed_non_target_rows={len(changed_non_target_rows)}",
        )

        failed = [check for check in checks if not check["passed"]]
        status = "PASS" if not failed else "FAIL"

        from agents.publication_agent import content_hash

        release_catalogue = release_dir / "catalogue.csv"
        shutil.copy2(ACTIVE, release_catalogue)

        canonical_hash = content_hash(ACTIVE.read_bytes())
        published_at = datetime.now(timezone.utc).isoformat()

        new_manifest = deepcopy(before_manifest)
        new_manifest.update(
            {
                "run_id": run_id,
                "published_at": published_at,
                "catalogue_path": str(ACTIVE),
                "versioned_catalogue_path": str(release_catalogue),
                "row_count": 139,
                "catalogue_sha256": canonical_hash,
                "validation": {
                    "passed": status == "PASS",
                    "checks": {
                        check["name"]: check["passed"]
                        for check in checks
                    },
                    "errors": [
                        f"{check['name']}: {check['details']}"
                        for check in failed
                    ],
                },
                "summary": {
                    "service_version": VERSION,
                    "run_id": run_id,
                    "input_rows": 139,
                    "mapped_rows": 139,
                    "dashboard_visible_records": len(main_ids),
                    "meity_invalid_application_links_suppressed": 2,
                    "active_catalogue": str(ACTIVE),
                    "dry_run": False,
                },
            }
        )

        if status != "PASS":
            raise RuntimeError(
                "Hotfix validation failed: "
                + "; ".join(
                    f"{item['name']}={item['details']}" for item in failed
                )
            )

        write_json(CURRENT_MANIFEST, new_manifest)
        write_json(release_dir / "manifest.json", new_manifest)

        validation = {
            "version": VERSION,
            "phase": PHASE,
            "validation_status": status,
            "run_id": run_id,
            "counts": {
                "active_catalogue_rows": len(reloaded_rows),
                "dashboard_loaded_records": len(bundle.records),
                "dashboard_visible_records": len(main_ids),
                "target_records": 2,
            },
            "target_records": [
                {
                    "master_id": target_id,
                    "scheme_name": getattr(records_by_id[target_id], "scheme_name", ""),
                    "official_page_url": getattr(
                        records_by_id[target_id], "official_page_url", ""
                    ),
                    "application_url_exposed_to_dashboard": getattr(
                        records_by_id[target_id], "application_url", ""
                    ),
                    "application_status": getattr(
                        records_by_id[target_id], "application_status", ""
                    ),
                }
                for target_id in sorted(TARGET_IDS)
            ],
            "checks": checks,
            "failed_checks": [],
            "publication_performed": True,
            "database_modified": False,
            "dashboard_code_modified": False,
        }
        write_json(VALIDATION_PATH, validation)

        summary = {
            "version": VERSION,
            "phase": PHASE,
            "publication_status": "PASS",
            "run_id": run_id,
            "problem": (
                "Legacy database application_url values pointed SAMRIDH and "
                "TIDE 2.0 to the unrelated MeitY Startup Hub logo-application page."
            ),
            "resolution": (
                "The governed catalogue now explicitly suppresses application_url "
                "fallback for both schemes. Their official scheme-information pages "
                "remain available, but no Apply Now link is exposed."
            ),
            "active_catalogue_rows": 139,
            "dashboard_visible_records": 53,
            "rollback_catalogue": str(active_backup),
            "rollback_manifest": str(manifest_backup),
            "release_catalogue": str(release_catalogue),
        }
        write_json(SUMMARY_PATH, summary)

        audit = {
            "version": VERSION,
            "phase": PHASE,
            "run_id": run_id,
            "published_at": published_at,
            "before": {
                "active_catalogue_raw_sha256": before_active_raw_sha,
                "current_manifest_raw_sha256": before_manifest_raw_sha,
                "active_catalogue_rows": len(before_rows),
            },
            "after": {
                "active_catalogue_raw_sha256": raw_sha256(ACTIVE),
                "current_manifest_raw_sha256": raw_sha256(CURRENT_MANIFEST),
                "active_catalogue_rows": 139,
                "dashboard_visible_records": 53,
                "canonical_catalogue_hash": canonical_hash,
            },
            "backups": {
                "catalogue": str(active_backup),
                "manifest": str(manifest_backup),
            },
            "release": {
                "directory": str(release_dir),
                "catalogue": str(release_catalogue),
            },
            "database_modified": False,
            "dashboard_code_modified": False,
            "rollback_available": True,
        }
        write_json(AUDIT_PATH, audit)

        print()
        print("SSIP MeitY v3.4.2.0.3 application-link hotfix")
        print("---------------------------------------------------")
        print("Publication status:         PASS")
        print("Active catalogue rows:      139")
        print("Dashboard visible:          53")
        print("SAMRIDH application URL:    suppressed")
        print("TIDE 2.0 application URL:   suppressed")
        print("Invalid logo URL exposed:   No")
        print("Database modified:          No")
        print("Dashboard code modified:    No")
        print()
        print("New release:")
        print(release_dir)
        print()
        print("Validation:")
        print(VALIDATION_PATH)
        print()
        print("Rollback backup:")
        print(backup_dir)

        return 0

    except Exception:
        shutil.copy2(active_backup, ACTIVE)
        shutil.copy2(manifest_backup, CURRENT_MANIFEST)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"HOTFIX ERROR: {exc}", file=sys.stderr)
        raise
