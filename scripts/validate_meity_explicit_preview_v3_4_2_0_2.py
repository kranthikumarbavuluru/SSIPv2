from __future__ import annotations

import csv
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ACTIVE = (
    ROOT
    / "data"
    / "catalogue_preview"
    / "v3_3_2"
    / "catalogue_preview_v3_3_2.csv"
)

SOURCE_CANDIDATE = (
    ROOT
    / "data"
    / "departments"
    / "meity"
    / "v3_4_2_0_2"
    / "catalogue_candidate_v3_4_2_0_2.csv"
)

PREVIEW_DIR = (
    ROOT
    / "data"
    / "catalogue_preview"
    / "v3_4_2_0_2"
)

PREVIEW_CANDIDATE = (
    PREVIEW_DIR
    / "catalogue_preview_v3_4_2_0_2.csv"
)

VALIDATION = (
    ROOT
    / "data"
    / "departments"
    / "meity"
    / "v3_4_2_0_2"
    / "meity_explicit_preview_validation_v3_4_2_0_2.json"
)

EXPECTED_IDS = {
    "147173e17ea741687247",
    "6af79cf6c8a213dddce8",
}


def read_csv(path: Path):
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        return (
            list(reader.fieldnames or []),
            list(reader),
        )


def write_json(path: Path, value):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    if not ACTIVE.exists():
        raise RuntimeError(
            f"Active catalogue missing: {ACTIVE}"
        )

    if not SOURCE_CANDIDATE.exists():
        raise RuntimeError(
            "Generated candidate missing: "
            f"{SOURCE_CANDIDATE}"
        )

    PREVIEW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        SOURCE_CANDIDATE,
        PREVIEW_CANDIDATE,
    )

    active_fields, active_rows = read_csv(
        ACTIVE
    )

    candidate_fields, candidate_rows = read_csv(
        PREVIEW_CANDIDATE
    )

    existing_rows_unchanged = (
        len(candidate_rows) >= len(active_rows)
        and candidate_rows[: len(active_rows)]
        == active_rows
    )

    candidate_ids = [
        row.get("master_id", "")
        for row in candidate_rows
    ]

    raw_meity_rows = [
        row
        for row in candidate_rows
        if row.get("master_id") in EXPECTED_IDS
    ]

    from ssip_dashboard.catalogue import (
        load_catalogue,
    )
    from ssip_dashboard.catalogue_populations import (
        split_catalogue_populations,
    )
    from ssip_dashboard.config import (
        DashboardConfig,
    )

    base_config = DashboardConfig.from_env(
        ROOT
    )

    active_config = replace(
        base_config,
        normalization_path=ACTIVE.resolve(),
        preview_path_configured=False,
    )

    candidate_config = replace(
        base_config,
        normalization_path=(
            PREVIEW_CANDIDATE.resolve()
        ),
        preview_path_configured=True,
    )

    active_bundle = load_catalogue(
        active_config
    )

    candidate_bundle = load_catalogue(
        candidate_config
    )

    active_populations = (
        split_catalogue_populations(
            active_bundle.records
        )
    )

    candidate_populations = (
        split_catalogue_populations(
            candidate_bundle.records
        )
    )

    active_main_ids = {
        record.master_id
        for record in (
            active_populations.main_scheme_records
        )
        if record.master_id
    }

    candidate_loaded_ids = {
        record.master_id
        for record in candidate_bundle.records
        if record.master_id
    }

    candidate_main_ids = {
        record.master_id
        for record in (
            candidate_populations.main_scheme_records
        )
        if record.master_id
    }

    new_main_ids = (
        candidate_main_ids
        - active_main_ids
    )

    checks = [
        {
            "name": "active_raw_rows_137",
            "passed": len(active_rows) == 137,
            "details": f"actual={len(active_rows)}",
        },
        {
            "name": "candidate_raw_rows_139",
            "passed": len(candidate_rows) == 139,
            "details": f"actual={len(candidate_rows)}",
        },
        {
            "name": "column_order_preserved",
            "passed": active_fields == candidate_fields,
            "details": (
                f"active={len(active_fields)} "
                f"candidate={len(candidate_fields)}"
            ),
        },
        {
            "name": "existing_137_rows_unchanged",
            "passed": existing_rows_unchanged,
            "details": (
                "The original active rows must remain "
                "identical and in the same order."
            ),
        },
        {
            "name": "candidate_master_ids_unique",
            "passed": (
                len(candidate_ids)
                == len(set(candidate_ids))
            ),
            "details": (
                f"rows={len(candidate_ids)} "
                f"unique={len(set(candidate_ids))}"
            ),
        },
        {
            "name": "exactly_two_meity_raw_rows",
            "passed": (
                {
                    row.get("master_id")
                    for row in raw_meity_rows
                }
                == EXPECTED_IDS
            ),
            "details": (
                f"raw_ids={sorted(row.get('master_id') for row in raw_meity_rows)}"
            ),
        },
        {
            "name": "active_dashboard_visible_51",
            "passed": (
                len(active_main_ids) == 51
            ),
            "details": (
                f"actual={len(active_main_ids)}"
            ),
        },
        {
            "name": "candidate_dashboard_visible_53",
            "passed": (
                len(candidate_main_ids) == 53
            ),
            "details": (
                f"actual={len(candidate_main_ids)}"
            ),
        },
        {
            "name": "both_meity_records_loaded",
            "passed": (
                EXPECTED_IDS
                <= candidate_loaded_ids
            ),
            "details": (
                "loaded_ids="
                f"{sorted(EXPECTED_IDS & candidate_loaded_ids)}"
            ),
        },
        {
            "name": "both_meity_records_main_visible",
            "passed": (
                EXPECTED_IDS
                <= candidate_main_ids
            ),
            "details": (
                "visible_ids="
                f"{sorted(EXPECTED_IDS & candidate_main_ids)}"
            ),
        },
        {
            "name": "only_meity_added_to_main_population",
            "passed": (
                new_main_ids == EXPECTED_IDS
            ),
            "details": (
                f"new_main_ids={sorted(new_main_ids)}"
            ),
        },
        {
            "name": "no_open_application_claim",
            "passed": all(
                not row.get(
                    "application_url",
                    "",
                ).strip()
                and not row.get(
                    "application_status",
                    "",
                ).upper().startswith("OPEN")
                for row in raw_meity_rows
            ),
            "details": (
                "application_url must remain blank "
                "and no OPEN status may be asserted."
            ),
        },
    ]

    failed = [
        check
        for check in checks
        if not check["passed"]
    ]

    status = (
        "PASS"
        if not failed
        else "FAIL"
    )

    report = {
        "version": "3.4.2.0.2",
        "phase": (
            "MeitY explicit-preview candidate "
            "validation"
        ),
        "validation_status": status,
        "active_catalogue": str(ACTIVE),
        "candidate_catalogue": str(
            PREVIEW_CANDIDATE
        ),
        "counts": {
            "active_raw_rows": len(
                active_rows
            ),
            "candidate_raw_rows": len(
                candidate_rows
            ),
            "active_loaded_records": len(
                active_bundle.records
            ),
            "candidate_loaded_records": len(
                candidate_bundle.records
            ),
            "active_main_schemes": len(
                active_main_ids
            ),
            "candidate_main_schemes": len(
                candidate_main_ids
            ),
        },
        "meity_loaded_ids": sorted(
            EXPECTED_IDS
            & candidate_loaded_ids
        ),
        "meity_main_visible_ids": sorted(
            EXPECTED_IDS
            & candidate_main_ids
        ),
        "checks": checks,
        "failed_checks": [
            check["name"]
            for check in failed
        ],
        "publication_performed": False,
        "database_modified": False,
        "dashboard_modified": False,
    }

    write_json(
        VALIDATION,
        report,
    )

    print()
    print(
        "SSIP MeitY v3.4.2.0.2 "
        "explicit-preview validation"
    )
    print(
        "---------------------------------------------"
    )
    print(
        f"Validation status:       {status}"
    )
    print(
        f"Active raw rows:         {len(active_rows)}"
    )
    print(
        f"Candidate raw rows:      {len(candidate_rows)}"
    )
    print(
        "Active loaded records:  "
        f"{len(active_bundle.records)}"
    )
    print(
        "Candidate loaded records:"
        f" {len(candidate_bundle.records)}"
    )
    print(
        "Visible before:          "
        f"{len(active_main_ids)}"
    )
    print(
        "Visible after candidate: "
        f"{len(candidate_main_ids)}"
    )
    print(
        "MeitY loaded:            "
        f"{len(EXPECTED_IDS & candidate_loaded_ids)} of 2"
    )
    print(
        "MeitY main-visible:      "
        f"{len(EXPECTED_IDS & candidate_main_ids)} of 2"
    )
    print(
        "Publication performed:   No"
    )
    print()
    print("Explicit-preview candidate:")
    print(PREVIEW_CANDIDATE)
    print()
    print("Validation report:")
    print(VALIDATION)

    if failed:
        print()
        print("Failed checks:")

        for check in failed:
            print(
                f"- {check['name']}: "
                f"{check['details']}"
            )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
