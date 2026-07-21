from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agents.action_link_agent_v3_4_3_5 import (
    EXPECTED_SOURCE_SHA256,
    load_json,
    sha256_file,
    snapshot_hashes,
)


VERSION = "3.4.3.5"
EXPECTED_ACTION_COUNT = 4
EXPECTED_SCHEMES = {"GENESIS", "SAMRIDH", "SASACT", "TIDE 2.0"}

ACTION_COLUMNS = [
    "action_id",
    "master_id",
    "canonical_name",
    "action_type",
    "link_role",
    "public_button_label",
    "button_order",
    "original_url",
    "resolved_url",
    "official_domain",
    "source_authority",
    "verification_status",
    "http_status",
    "is_active",
    "is_time_bound",
    "deadline",
    "deadline_status",
    "parent_master_id",
    "call_instance_id",
    "confidence",
    "evidence",
    "rejection_reason",
    "last_verified_at",
    "eligible_for_public_button",
    "verification_source",
    "schema_version",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(*parts: str) -> str:
    material = "|".join([VERSION, "public-action", *parts])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def read_csv(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(50_000_000)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key): (value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_actions(
    rendered_rows: list[dict[str, str]],
    classification_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    classification_by_id = {
        row.get("classification_id", ""): row
        for row in classification_rows
    }

    actions: list[dict[str, Any]] = []
    for rendered in rendered_rows:
        if rendered.get("verification_status") != "VERIFIED_INFORMATION_PAGE":
            continue
        if rendered.get("eligible_for_public_button") != "True":
            continue

        classification_id = rendered.get("classification_id", "")
        classified = classification_by_id.get(classification_id)
        if not classified:
            raise RuntimeError(
                f"Missing offline classification for {classification_id}"
            )

        if classified.get("proposed_action_type") != "SCHEME_DETAILS":
            raise RuntimeError(
                "Only SCHEME_DETAILS records are allowed in this checkpoint."
            )
        if classified.get("link_role") != "SCHEME_MASTER":
            raise RuntimeError(
                "Only SCHEME_MASTER records are allowed in this checkpoint."
            )

        resolved_url = rendered.get("final_url", "").strip()
        original_url = rendered.get("requested_url", "").strip()
        domain = (urlsplit(resolved_url).hostname or "").casefold()
        confidence = float(rendered.get("confidence", "0") or 0)

        evidence_parts = [
            f"browser_engine={rendered.get('browser_engine', '')}",
            f"http_status={rendered.get('http_status', '')}",
            f"page_title={rendered.get('page_title', '')}",
            f"strong_marker_evidence={rendered.get('strong_marker_evidence', '')}",
            f"heading_marker_evidence={rendered.get('heading_marker_evidence', '')}",
            f"visible_text_length={rendered.get('visible_text_length', '')}",
            "verification_policy=VISIBLE_RENDERED_DOM",
        ]

        actions.append(
            {
                "action_id": stable_id(
                    rendered.get("master_id", ""),
                    "SCHEME_DETAILS",
                    resolved_url,
                ),
                "master_id": rendered.get("master_id", ""),
                "canonical_name": rendered.get("canonical_name", ""),
                "action_type": "SCHEME_DETAILS",
                "link_role": "SCHEME_MASTER",
                "public_button_label": "Scheme Details",
                "button_order": 3,
                "original_url": original_url,
                "resolved_url": resolved_url,
                "official_domain": domain,
                "source_authority": (
                    classified.get("source_name", "").strip()
                    or "MeitY Startup Hub"
                ),
                "verification_status": "VERIFIED_INFORMATION_PAGE",
                "http_status": rendered.get("http_status", ""),
                "is_active": "True",
                "is_time_bound": "False",
                "deadline": "",
                "deadline_status": "NOT_APPLICABLE",
                "parent_master_id": "",
                "call_instance_id": "",
                "confidence": f"{confidence:.2f}",
                "evidence": " | ".join(evidence_parts),
                "rejection_reason": "",
                "last_verified_at": rendered.get("verified_at_utc", ""),
                "eligible_for_public_button": "True",
                "verification_source": (
                    "meity_scheme_page_browser_verification_v3_4_3_5.csv"
                ),
                "schema_version": VERSION,
            }
        )

    actions.sort(key=lambda row: row["canonical_name"])
    return actions


def validate_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    names = {str(row["canonical_name"]) for row in actions}
    resolved_urls = [str(row["resolved_url"]) for row in actions]

    checks = {
        "exactly_four_actions": len(actions) == EXPECTED_ACTION_COUNT,
        "expected_schemes_only": names == EXPECTED_SCHEMES,
        "all_scheme_details": all(
            row["action_type"] == "SCHEME_DETAILS"
            for row in actions
        ),
        "all_scheme_master_roles": all(
            row["link_role"] == "SCHEME_MASTER"
            for row in actions
        ),
        "all_verified_information_pages": all(
            row["verification_status"] == "VERIFIED_INFORMATION_PAGE"
            for row in actions
        ),
        "all_public_button_eligible": all(
            row["eligible_for_public_button"] == "True"
            for row in actions
        ),
        "all_active_non_time_bound": all(
            row["is_active"] == "True"
            and row["is_time_bound"] == "False"
            and row["deadline_status"] == "NOT_APPLICABLE"
            for row in actions
        ),
        "all_https": all(
            url.casefold().startswith("https://")
            for url in resolved_urls
        ),
        "all_official_meity_domains": all(
            (urlsplit(url).hostname or "").casefold()
            == "msh.meity.gov.in"
            for url in resolved_urls
        ),
        "unique_resolved_urls": (
            len(set(resolved_urls)) == len(resolved_urls)
        ),
        "no_apply_now_actions": all(
            row["action_type"] != "APPLY_NOW"
            for row in actions
        ),
        "no_open_call_actions": all(
            row["action_type"] != "VIEW_OPEN_CALL"
            for row in actions
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
    }


def load_inputs(
    project_root: Path,
) -> tuple[
    dict[str, Any],
    Path,
    Path,
    Path,
    list[dict[str, str]],
    list[dict[str, str]],
]:
    config_path = project_root / "config/action_link_rules_v3_4_3_5.json"
    config = load_json(config_path)

    if config.get("schema_version") != VERSION:
        raise RuntimeError("Configuration version mismatch.")
    if config.get("execution_mode") != "PREVIEW_ONLY":
        raise RuntimeError("Configuration is not PREVIEW_ONLY.")
    if config.get("output", {}).get("publication_allowed") is not False:
        raise RuntimeError("Publication must remain disabled.")
    if config.get("output", {}).get("database_writes_allowed") is not False:
        raise RuntimeError("Database writes must remain disabled.")
    if config.get("output", {}).get(
        "dashboard_code_changes_allowed"
    ) is not False:
        raise RuntimeError("Dashboard code changes must remain disabled.")

    source_path = project_root / Path(config["source"]["catalogue_path"])
    if sha256_file(source_path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Frozen v3.4.3.4 source candidate hash mismatch.")

    output_dir = project_root / Path(config["output"]["directory"])
    classification_path = (
        output_dir / "meity_action_link_offline_classification_v3_4_3_5.csv"
    )
    rendered_path = (
        output_dir / "meity_scheme_page_browser_verification_v3_4_3_5.csv"
    )
    rendered_summary_path = (
        output_dir
        / "meity_scheme_page_browser_verification_summary_v3_4_3_5.json"
    )

    if not classification_path.exists():
        raise FileNotFoundError(
            f"Missing offline classification: {classification_path}"
        )
    if not rendered_path.exists():
        raise FileNotFoundError(
            f"Missing browser verification: {rendered_path}"
        )
    if not rendered_summary_path.exists():
        raise FileNotFoundError(
            f"Missing browser verification summary: {rendered_summary_path}"
        )

    rendered_summary = load_json(rendered_summary_path)
    if rendered_summary.get("stage") != (
        "BROWSER_RENDERED_SCHEME_PAGE_VERIFICATION"
    ):
        raise RuntimeError("Browser verification stage is not current.")
    if rendered_summary.get("release_readiness_status") != "PASS":
        raise RuntimeError(
            "Browser verification must be PASS before actions are generated."
        )
    if rendered_summary.get("verified_information_page_count") != 4:
        raise RuntimeError(
            "Exactly four information pages must be verified."
        )
    if rendered_summary.get("scheme_details_button_candidate_count") != 4:
        raise RuntimeError(
            "Exactly four Scheme Details candidates are required."
        )
    if rendered_summary.get("apply_now_button_count") != 0:
        raise RuntimeError("Unexpected Apply Now buttons found.")
    if rendered_summary.get("open_call_button_count") != 0:
        raise RuntimeError("Unexpected open-call buttons found.")
    if not all(rendered_summary.get("safety", {}).values()):
        raise RuntimeError(
            "Browser verification safety checks did not all pass."
        )

    return (
        config,
        source_path,
        classification_path,
        rendered_path,
        read_csv(classification_path),
        read_csv(rendered_path),
    )


def run_public_action_builder(project_root: Path) -> dict[str, Any]:
    (
        config,
        source_path,
        classification_path,
        rendered_path,
        classification_rows,
        rendered_rows,
    ) = load_inputs(project_root)

    output_dir = project_root / Path(config["output"]["directory"])
    actions_path = (
        output_dir / "meity_verified_public_actions_v3_4_3_5.csv"
    )
    summary_path = (
        output_dir / "meity_verified_public_actions_summary_v3_4_3_5.json"
    )

    source_hash_before = sha256_file(source_path)
    classification_hash_before = sha256_file(classification_path)
    rendered_hash_before = sha256_file(rendered_path)

    inventory_path = (
        output_dir / "meity_action_link_inventory_v3_4_3_5.csv"
    )
    quarantine_path = (
        output_dir / "meity_action_link_inventory_quarantine_v3_4_3_5.csv"
    )
    inventory_hash_before = sha256_file(inventory_path)
    quarantine_hash_before = sha256_file(quarantine_path)

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

    actions = build_actions(rendered_rows, classification_rows)
    validation = validate_actions(actions)
    if not validation["passed"]:
        raise RuntimeError(
            f"Public action validation failed: {validation}"
        )

    write_csv(actions_path, actions, ACTION_COLUMNS)

    summary: dict[str, Any] = {
        "version": VERSION,
        "stage": "VERIFIED_PUBLIC_ACTIONS_PREVIEW",
        "execution_mode": "PREVIEW_ONLY",
        "release_readiness_status": "PASS",
        "verified_public_action_count": len(actions),
        "action_type_counts": {"SCHEME_DETAILS": len(actions)},
        "verified_scheme_names": [
            row["canonical_name"] for row in actions
        ],
        "apply_now_button_count": 0,
        "open_call_button_count": 0,
        "scheme_details_button_count": len(actions),
        "guidelines_button_count": 0,
        "manual_button_count": 0,
        "notification_button_count": 0,
        "review_required_count": 0,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "validation": validation,
        "actions_path": actions_path.relative_to(project_root).as_posix(),
        "source_sha256": source_hash_before,
        "classification_sha256": classification_hash_before,
        "browser_verification_sha256": rendered_hash_before,
        "inventory_sha256": inventory_hash_before,
        "quarantine_sha256": quarantine_hash_before,
        "actions_sha256": sha256_file(actions_path),
        "generated_at_utc": utc_now_iso(),
    }
    write_json(summary_path, summary)

    source_hash_after = sha256_file(source_path)
    classification_hash_after = sha256_file(classification_path)
    rendered_hash_after = sha256_file(rendered_path)
    inventory_hash_after = sha256_file(inventory_path)
    quarantine_hash_after = sha256_file(quarantine_path)

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
        "source_candidate_unchanged": source_hash_before == source_hash_after,
        "offline_classification_unchanged": (
            classification_hash_before == classification_hash_after
        ),
        "browser_verification_unchanged": (
            rendered_hash_before == rendered_hash_after
        ),
        "clean_inventory_unchanged": (
            inventory_hash_before == inventory_hash_after
        ),
        "quarantine_inventory_unchanged": (
            quarantine_hash_before == quarantine_hash_after
        ),
        "database_files_unchanged": database_before == database_after,
        "dashboard_python_files_unchanged": dashboard_before == dashboard_after,
        "publication_current_unchanged": (
            publication_existed_before == publication_exists_after
        ),
    }
    summary["safety"] = safety
    write_json(summary_path, summary)

    if not all(safety.values()):
        raise RuntimeError(f"Safety validation failed: {safety}")

    return summary
