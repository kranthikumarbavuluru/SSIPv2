from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.action_link_agent_v3_4_3_5 import snapshot_hashes


VERSION = "3.4.3.5"
EXPECTED_SOURCE_SHA256 = (
    "ef43bd7e27df2ead5fe88ab8bf2751a80eac6c4e13e8894173a6625b57650a8c"
)
EXPECTED_ACTIONS_SHA256 = (
    "28f6174ebf4313394f205682dc1735451f14f060f346264c84d857d6cee0836e"
)
EXPECTED_SOURCE_ROWS = 141
EXPECTED_ACTIONS = 4
EXPECTED_SCHEMES = {"GENESIS", "SAMRIDH", "SASACT", "TIDE 2.0"}

MASTER_ID_ALIASES = (
    "master_id",
    "scheme_id",
    "programme_id",
    "program_id",
    "record_id",
    "id",
)

CANONICAL_NAME_ALIASES = (
    "canonical_name",
    "scheme_name",
    "programme_name",
    "program_name",
    "title",
    "name",
)

APPENDED_COLUMNS = [
    "verified_public_action_count",
    "verified_public_action_ids",
    "verified_public_action_types",
    "verified_public_action_labels",
    "verified_public_action_urls",
    "verified_public_action_status",
    "verified_public_action_source",
    "verified_public_action_last_verified_at",
    "verified_public_actions_json",
    "verified_public_action_schema_version",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(50_000_000)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"No CSV header found in {path}")
        rows = [
            {str(key): (value or "") for key, value in row.items()}
            for row in reader
        ]
    return list(reader.fieldnames), rows


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def find_column(
    fieldnames: list[str],
    aliases: tuple[str, ...],
) -> str:
    by_casefold = {name.casefold(): name for name in fieldnames}
    for alias in aliases:
        actual = by_casefold.get(alias.casefold())
        if actual:
            return actual
    return ""


def validate_action_rows(actions: list[dict[str, str]]) -> dict[str, Any]:
    action_ids = [row.get("action_id", "").strip() for row in actions]
    master_ids = [row.get("master_id", "").strip() for row in actions]
    names = {row.get("canonical_name", "").strip() for row in actions}
    resolved_urls = [row.get("resolved_url", "").strip() for row in actions]

    checks = {
        "exactly_four_actions": len(actions) == EXPECTED_ACTIONS,
        "expected_schemes_only": names == EXPECTED_SCHEMES,
        "all_action_ids_present": all(action_ids),
        "unique_action_ids": len(set(action_ids)) == len(action_ids),
        "all_master_ids_present": all(master_ids),
        "unique_master_ids": len(set(master_ids)) == len(master_ids),
        "all_scheme_details": all(
            row.get("action_type") == "SCHEME_DETAILS"
            for row in actions
        ),
        "all_scheme_master_roles": all(
            row.get("link_role") == "SCHEME_MASTER"
            for row in actions
        ),
        "all_verified_information_pages": all(
            row.get("verification_status") == "VERIFIED_INFORMATION_PAGE"
            for row in actions
        ),
        "all_public_button_eligible": all(
            row.get("eligible_for_public_button") == "True"
            for row in actions
        ),
        "all_active": all(
            row.get("is_active") == "True"
            for row in actions
        ),
        "all_non_time_bound": all(
            row.get("is_time_bound") == "False"
            and row.get("deadline_status") == "NOT_APPLICABLE"
            for row in actions
        ),
        "all_urls_present": all(resolved_urls),
        "unique_urls": len(set(resolved_urls)) == len(resolved_urls),
        "no_apply_now": all(
            row.get("action_type") != "APPLY_NOW"
            for row in actions
        ),
        "no_open_call": all(
            row.get("action_type") != "VIEW_OPEN_CALL"
            for row in actions
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}


def action_reference_payload(action: dict[str, str]) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        "action_type": action["action_type"],
        "link_role": action["link_role"],
        "label": action["public_button_label"],
        "resolved_url": action["resolved_url"],
        "verification_status": action["verification_status"],
        "confidence": float(action["confidence"]),
        "is_active": action["is_active"] == "True",
        "is_time_bound": action["is_time_bound"] == "True",
        "deadline_status": action["deadline_status"],
        "last_verified_at": action["last_verified_at"],
        "verification_source": action["verification_source"],
    }


def merge_actions_into_catalogue(
    source_fieldnames: list[str],
    source_rows: list[dict[str, str]],
    actions: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    master_id_column = find_column(source_fieldnames, MASTER_ID_ALIASES)
    canonical_name_column = find_column(
        source_fieldnames,
        CANONICAL_NAME_ALIASES,
    )
    if not master_id_column:
        raise RuntimeError(
            "Catalogue master-id column could not be identified."
        )
    if not canonical_name_column:
        raise RuntimeError(
            "Catalogue canonical-name column could not be identified."
        )

    actions_by_master_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    for action in actions:
        actions_by_master_id[action["master_id"].strip()].append(action)

    source_indices_by_master_id: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(source_rows):
        master_id = row.get(master_id_column, "").strip()
        if master_id:
            source_indices_by_master_id[master_id].append(index)

    missing_master_ids = sorted(
        master_id
        for master_id in actions_by_master_id
        if master_id not in source_indices_by_master_id
    )
    multiply_matched_master_ids = {
        master_id: indices
        for master_id, indices in source_indices_by_master_id.items()
        if master_id in actions_by_master_id and len(indices) != 1
    }

    if missing_master_ids:
        raise RuntimeError(
            "Verified actions reference missing catalogue master IDs: "
            + ", ".join(missing_master_ids)
        )
    if multiply_matched_master_ids:
        raise RuntimeError(
            "Verified actions must match exactly one catalogue row each: "
            + json.dumps(multiply_matched_master_ids, sort_keys=True)
        )

    output_fieldnames = list(source_fieldnames)
    for column in APPENDED_COLUMNS:
        if column in output_fieldnames:
            raise RuntimeError(
                f"Source catalogue already contains reserved output column: {column}"
            )
        output_fieldnames.append(column)

    output_rows: list[dict[str, Any]] = []
    enriched_rows: list[dict[str, Any]] = []

    for row_index, source_row in enumerate(source_rows):
        output_row: dict[str, Any] = dict(source_row)
        master_id = source_row.get(master_id_column, "").strip()
        matched_actions = sorted(
            actions_by_master_id.get(master_id, []),
            key=lambda item: (
                int(item.get("button_order", "999") or 999),
                item.get("action_id", ""),
            ),
        )

        references = [
            action_reference_payload(action)
            for action in matched_actions
        ]

        output_row["verified_public_action_count"] = str(len(references))
        output_row["verified_public_action_ids"] = "|".join(
            item["action_id"] for item in references
        )
        output_row["verified_public_action_types"] = "|".join(
            item["action_type"] for item in references
        )
        output_row["verified_public_action_labels"] = "|".join(
            item["label"] for item in references
        )
        output_row["verified_public_action_urls"] = "|".join(
            item["resolved_url"] for item in references
        )
        output_row["verified_public_action_status"] = (
            "VERIFIED"
            if references
            else "NO_VERIFIED_PUBLIC_ACTION"
        )
        output_row["verified_public_action_source"] = (
            "data/departments/meity/v3_4_3_5/"
            "meity_verified_public_actions_v3_4_3_5.csv"
            if references
            else ""
        )
        output_row["verified_public_action_last_verified_at"] = "|".join(
            item["last_verified_at"] for item in references
        )
        output_row["verified_public_actions_json"] = json.dumps(
            references,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        output_row["verified_public_action_schema_version"] = VERSION

        if references:
            enriched_rows.append(
                {
                    "row_number": row_index + 1,
                    "master_id": master_id,
                    "canonical_name": source_row.get(
                        canonical_name_column,
                        "",
                    ),
                    "action_count": len(references),
                    "action_ids": [
                        item["action_id"] for item in references
                    ],
                }
            )

        output_rows.append(output_row)

    source_cell_preservation = all(
        all(
            output_rows[index].get(column, "")
            == source_rows[index].get(column, "")
            for column in source_fieldnames
        )
        for index in range(len(source_rows))
    )

    matched_names = {
        item["canonical_name"].strip()
        for item in enriched_rows
    }
    validation_checks = {
        "source_row_count_is_141": len(source_rows) == EXPECTED_SOURCE_ROWS,
        "output_row_count_equals_source": (
            len(output_rows) == len(source_rows)
        ),
        "source_columns_preserved_in_order": (
            output_fieldnames[: len(source_fieldnames)]
            == source_fieldnames
        ),
        "only_expected_columns_appended": (
            output_fieldnames[len(source_fieldnames):]
            == APPENDED_COLUMNS
        ),
        "original_cell_values_preserved": source_cell_preservation,
        "exactly_four_rows_enriched": len(enriched_rows) == EXPECTED_ACTIONS,
        "expected_schemes_enriched": matched_names == EXPECTED_SCHEMES,
        "one_action_per_enriched_row": all(
            item["action_count"] == 1 for item in enriched_rows
        ),
        "sasact_enriched": "SASACT" in matched_names,
        "genesis_enriched": "GENESIS" in matched_names,
        "non_action_rows_have_zero_count": sum(
            row["verified_public_action_count"] == "0"
            for row in output_rows
        ) == len(output_rows) - EXPECTED_ACTIONS,
        "no_apply_now_references": all(
            "APPLY_NOW"
            not in row["verified_public_action_types"]
            for row in output_rows
        ),
        "no_open_call_references": all(
            "VIEW_OPEN_CALL"
            not in row["verified_public_action_types"]
            for row in output_rows
        ),
    }

    return (
        output_fieldnames,
        output_rows,
        {
            "master_id_column": master_id_column,
            "canonical_name_column": canonical_name_column,
            "enriched_rows": enriched_rows,
            "checks": validation_checks,
            "passed": all(validation_checks.values()),
        },
    )


def backup_existing_outputs(
    project_root: Path,
    paths: list[Path],
) -> str:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return ""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = (
        project_root
        / "backups"
        / f"before_v3_4_3_5_catalogue_action_merge_{stamp}"
    )
    for path in existing:
        relative = path.relative_to(project_root)
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    return backup_root.relative_to(project_root).as_posix()


def run_catalogue_action_merge(project_root: Path) -> dict[str, Any]:
    source_path = (
        project_root
        / "data/catalogue_preview/v3_4_3_4/"
        "catalogue_preview_v3_4_3_4.csv"
    )
    actions_path = (
        project_root
        / "data/departments/meity/v3_4_3_5/"
        "meity_verified_public_actions_v3_4_3_5.csv"
    )
    output_path = (
        project_root
        / "data/catalogue_preview/v3_4_3_5/"
        "catalogue_preview_v3_4_3_5.csv"
    )
    summary_path = (
        project_root
        / "data/departments/meity/v3_4_3_5/"
        "meity_catalogue_action_merge_summary_v3_4_3_5.json"
    )
    validation_path = (
        project_root
        / "data/departments/meity/v3_4_3_5/"
        "meity_catalogue_action_merge_validation_v3_4_3_5.json"
    )

    if not source_path.exists():
        raise FileNotFoundError(f"Source catalogue not found: {source_path}")
    if not actions_path.exists():
        raise FileNotFoundError(f"Verified actions not found: {actions_path}")

    source_hash_before = sha256_file(source_path)
    actions_hash_before = sha256_file(actions_path)

    if source_hash_before != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "Frozen v3.4.3.4 source catalogue hash mismatch."
        )
    if actions_hash_before != EXPECTED_ACTIONS_SHA256:
        raise RuntimeError(
            "Verified public actions hash mismatch."
        )

    source_fieldnames, source_rows = read_csv(source_path)
    action_fieldnames, actions = read_csv(actions_path)

    required_action_columns = {
        "action_id",
        "master_id",
        "canonical_name",
        "action_type",
        "link_role",
        "public_button_label",
        "resolved_url",
        "verification_status",
        "confidence",
        "is_active",
        "is_time_bound",
        "deadline_status",
        "last_verified_at",
        "eligible_for_public_button",
        "verification_source",
    }
    missing_action_columns = sorted(
        required_action_columns - set(action_fieldnames)
    )
    if missing_action_columns:
        raise RuntimeError(
            "Verified actions file is missing required columns: "
            + ", ".join(missing_action_columns)
        )

    action_validation = validate_action_rows(actions)
    if not action_validation["passed"]:
        raise RuntimeError(
            f"Verified action validation failed: {action_validation}"
        )

    (
        output_fieldnames,
        output_rows,
        merge_validation,
    ) = merge_actions_into_catalogue(
        source_fieldnames,
        source_rows,
        actions,
    )
    if not merge_validation["passed"]:
        raise RuntimeError(
            f"Catalogue merge validation failed: {merge_validation}"
        )

    database_before = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_before = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_current = project_root / "publication/current"
    publication_existed_before = publication_current.exists()

    backup_location = backup_existing_outputs(
        project_root,
        [output_path, summary_path, validation_path],
    )

    write_csv(output_path, output_fieldnames, output_rows)

    source_hash_after = sha256_file(source_path)
    actions_hash_after = sha256_file(actions_path)
    output_hash = sha256_file(output_path)

    database_after = snapshot_hashes(
        project_root,
        ("database/**/*.db", "database/**/*.sqlite", "database/**/*.sqlite3"),
    )
    dashboard_after = snapshot_hashes(
        project_root,
        ("apps/**/*.py", "ssip_dashboard/**/*.py"),
    )
    publication_exists_after = publication_current.exists()

    safety = {
        "source_catalogue_unchanged": (
            source_hash_before == source_hash_after
        ),
        "verified_actions_unchanged": (
            actions_hash_before == actions_hash_after
        ),
        "database_files_unchanged": database_before == database_after,
        "dashboard_python_files_unchanged": dashboard_before == dashboard_after,
        "publication_current_unchanged": (
            publication_existed_before == publication_exists_after
        ),
    }

    validation_payload: dict[str, Any] = {
        "version": VERSION,
        "stage": "CATALOGUE_ACTION_REFERENCE_MERGE_VALIDATION",
        "execution_mode": "PREVIEW_ONLY",
        "release_readiness_status": "PASS",
        "action_validation": action_validation,
        "merge_validation": merge_validation,
        "safety": safety,
        "passed": (
            action_validation["passed"]
            and merge_validation["passed"]
            and all(safety.values())
        ),
        "validated_at_utc": utc_now_iso(),
    }
    write_json(validation_path, validation_payload)

    summary: dict[str, Any] = {
        "version": VERSION,
        "stage": "CATALOGUE_ACTION_REFERENCE_PREVIEW",
        "execution_mode": "PREVIEW_ONLY",
        "release_readiness_status": "PASS",
        "source_catalogue_rows": len(source_rows),
        "output_catalogue_rows": len(output_rows),
        "source_column_count": len(source_fieldnames),
        "output_column_count": len(output_fieldnames),
        "appended_column_count": len(APPENDED_COLUMNS),
        "verified_public_action_count": len(actions),
        "action_enriched_row_count": len(
            merge_validation["enriched_rows"]
        ),
        "scheme_details_reference_count": len(actions),
        "apply_now_reference_count": 0,
        "open_call_reference_count": 0,
        "sasact_action_reference_present": any(
            item["canonical_name"] == "SASACT"
            for item in merge_validation["enriched_rows"]
        ),
        "genesis_action_reference_present": any(
            item["canonical_name"] == "GENESIS"
            for item in merge_validation["enriched_rows"]
        ),
        "active_catalogue_modified": False,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "backup_location": backup_location,
        "source_path": source_path.relative_to(project_root).as_posix(),
        "actions_path": actions_path.relative_to(project_root).as_posix(),
        "output_path": output_path.relative_to(project_root).as_posix(),
        "validation_path": validation_path.relative_to(project_root).as_posix(),
        "source_sha256": source_hash_before,
        "actions_sha256": actions_hash_before,
        "output_sha256": output_hash,
        "safety": safety,
        "generated_at_utc": utc_now_iso(),
    }
    write_json(summary_path, summary)

    if not validation_payload["passed"]:
        raise RuntimeError(
            f"Final catalogue merge validation failed: {validation_payload}"
        )

    return summary
