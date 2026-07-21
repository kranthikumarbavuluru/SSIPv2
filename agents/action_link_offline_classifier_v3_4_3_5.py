from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from agents.action_link_agent_v3_4_3_5 import (
    EXPECTED_SOURCE_SHA256,
    load_json,
    sha256_file,
    snapshot_hashes,
)


VERSION = "3.4.3.5"

CLASSIFICATION_COLUMNS = [
    "classification_id",
    "inventory_id",
    "source_row_number",
    "master_id",
    "canonical_name",
    "record_type",
    "source_name",
    "department",
    "ministry",
    "source_field_names",
    "source_strength",
    "original_url",
    "normalized_url",
    "url_domain",
    "url_path",
    "file_extension",
    "proposed_action_type",
    "link_role",
    "verification_status",
    "confidence",
    "official_domain_policy_result",
    "entity_url_match",
    "classification_evidence",
    "manual_review_required",
    "manual_review_reason",
    "eligible_for_public_button",
    "network_status",
    "classified_at_utc",
]

REVIEW_COLUMNS = [
    "queue_id",
    "queue_type",
    "priority",
    "inventory_id",
    "master_id",
    "canonical_name",
    "normalized_url",
    "proposed_action_type",
    "link_role",
    "current_status",
    "reason",
    "source_field_names",
    "confidence",
    "eligible_for_public_button",
    "created_at_utc",
]

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
}

ENTITY_HINTS = {
    "samridh": ("samridh",),
    "tide 2.0": ("tide", "tide 2.0", "tide%202.0", "tide_2.0"),
    "sasact": ("sasact",),
    "genesis": ("genesis",),
    "sitaa": ("sitaa",),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def stable_id(prefix: str, *parts: str) -> str:
    material = "|".join([VERSION, prefix, *parts])
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


def domain_is_official(domain: str, policy: dict[str, Any]) -> bool:
    host = normalize_text(domain).strip(".")
    if not host:
        return False

    exact = {
        normalize_text(item).strip(".")
        for item in policy.get("trusted_exact_domains", [])
    }
    if host in exact:
        return True

    for suffix in policy.get("permitted_domain_suffixes", []):
        clean_suffix = normalize_text(suffix).strip(".")
        if host == clean_suffix or host.endswith("." + clean_suffix):
            return True
    return False


def canonical_entity_key(canonical_name: str) -> str:
    name = normalize_text(canonical_name)
    for entity_key in ENTITY_HINTS:
        if entity_key in name:
            return entity_key
    return ""


def entity_matches_url(canonical_name: str, normalized_url: str) -> bool:
    entity_key = canonical_entity_key(canonical_name)
    if not entity_key:
        return False
    haystack = unquote(normalized_url).casefold()
    return any(hint in haystack for hint in ENTITY_HINTS[entity_key])


def infer_offline_role(row: dict[str, str]) -> dict[str, Any]:
    path = unquote(row.get("url_path", "")).casefold()
    url = unquote(row.get("normalized_url", "")).casefold()
    fields = normalize_text(row.get("source_field_names", ""))
    extension = normalize_text(row.get("file_extension", ""))
    evidence: list[str] = []

    if extension in DOCUMENT_EXTENSIONS:
        evidence.append(f"document_extension={extension}")

        if any(token in path for token in ("user manual", "user-manual", "manual", "handbook")):
            return {
                "proposed_action_type": "USER_MANUAL",
                "link_role": "USER_MANUAL_DOCUMENT",
                "confidence": 0.82,
                "priority": "MEDIUM",
                "manual_review_reason": "DOCUMENT_PURPOSE_AND_AUTHORITY_REQUIRE_VERIFICATION",
                "evidence": evidence + ["filename_indicates_user_manual"],
            }

        if any(
            token in path
            for token in (
                "administrative approval",
                "administrative%20approval",
                "notification",
                "circular",
                "sanction",
                "office order",
                "office-order",
                "approval",
            )
        ):
            return {
                "proposed_action_type": "OFFICIAL_NOTIFICATION",
                "link_role": "OFFICIAL_NOTIFICATION",
                "confidence": 0.80,
                "priority": "MEDIUM",
                "manual_review_reason": "DOCUMENT_PURPOSE_AND_CURRENT_RELEVANCE_REQUIRE_VERIFICATION",
                "evidence": evidence + ["filename_indicates_official_approval_or_notification"],
            }

        if any(
            token in path
            for token in (
                "guideline",
                "guidelines",
                "scheme report",
                "scheme-report",
                "framework",
            )
        ) or "guideline" in fields:
            return {
                "proposed_action_type": "GUIDELINES",
                "link_role": "GUIDELINES_DOCUMENT",
                "confidence": 0.78,
                "priority": "MEDIUM",
                "manual_review_reason": "DOCUMENT_PURPOSE_AND_SCHEME_ASSOCIATION_REQUIRE_VERIFICATION",
                "evidence": evidence + ["field_or_filename_indicates_guidelines"],
            }

        return {
            "proposed_action_type": "OFFICIAL_NOTIFICATION",
            "link_role": "OFFICIAL_NOTIFICATION",
            "confidence": 0.60,
            "priority": "MEDIUM",
            "manual_review_reason": "GENERIC_DOCUMENT_ROLE_REQUIRES_MANUAL_REVIEW",
            "evidence": evidence + ["generic_official_document_candidate"],
        }

    if any(
        token in url
        for token in (
            "/apply",
            "/application",
            "/applications",
            "/register",
            "/registration",
            "/portal",
        )
    ) or any(token in fields for token in ("application_url", "apply_url", "portal_url")):
        return {
            "proposed_action_type": "APPLICATION_PORTAL",
            "link_role": "APPLICATION_PORTAL",
            "confidence": 0.72,
            "priority": "HIGH",
            "manual_review_reason": "APPLICATION_DESTINATION_AND_OPEN_STATUS_NOT_VERIFIED",
            "evidence": ["url_or_field_indicates_application_destination"],
        }

    if any(
        token in url
        for token in (
            "/call",
            "/calls",
            "/challenge",
            "/cohort",
            "/announcement",
            "/cfp",
            "/round",
        )
    ):
        return {
            "proposed_action_type": "VIEW_OPEN_CALL",
            "link_role": "OPEN_CALL_PAGE",
            "confidence": 0.72,
            "priority": "HIGH",
            "manual_review_reason": "CALL_IDENTITY_DEADLINE_AND_OPEN_STATUS_NOT_VERIFIED",
            "evidence": ["url_path_indicates_call_or_application_window"],
        }

    if "/contact" in url or "contact_url" in fields:
        return {
            "proposed_action_type": "CONTACT_DETAILS",
            "link_role": "CONTACT_PAGE",
            "confidence": 0.72,
            "priority": "LOW",
            "manual_review_reason": "CONTACT_PAGE_PURPOSE_REQUIRES_VERIFICATION",
            "evidence": ["url_or_field_indicates_contact_page"],
        }

    if "/schemes/" in url or any(
        token in fields
        for token in ("official_page_url", "scheme_url", "programme_url", "program_url")
    ):
        return {
            "proposed_action_type": "SCHEME_DETAILS",
            "link_role": "SCHEME_MASTER",
            "confidence": 0.90,
            "priority": "LOW",
            "manual_review_reason": "OFFICIAL_PAGE_CONTENT_AND_CANONICAL_IDENTITY_REQUIRE_NETWORK_VERIFICATION",
            "evidence": ["official_scheme_page_pattern"],
        }

    return {
        "proposed_action_type": "SCHEME_DETAILS",
        "link_role": "INFORMATION_PAGE",
        "confidence": 0.58,
        "priority": "MEDIUM",
        "manual_review_reason": "GENERIC_INFORMATION_PAGE_ROLE_REQUIRES_MANUAL_REVIEW",
        "evidence": ["fallback_information_page_candidate"],
    }


def classify_inventory(
    inventory_rows: list[dict[str, str]],
    quarantine_rows: list[dict[str, str]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    classified_at = utc_now_iso()
    domain_policy = config["official_domain_policy"]

    classifications: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []

    for row in inventory_rows:
        role = infer_offline_role(row)
        official = domain_is_official(row.get("url_domain", ""), domain_policy)
        entity_match = entity_matches_url(
            row.get("canonical_name", ""),
            row.get("normalized_url", ""),
        )

        evidence = list(role["evidence"])
        evidence.append(f"official_domain_policy={'PASS' if official else 'FAIL'}")
        evidence.append(f"entity_url_match={entity_match}")
        evidence.append(f"source_strength={row.get('source_strength', '')}")

        review_reason = role["manual_review_reason"]
        if not official:
            review_reason = "NON_OFFICIAL_DOMAIN_REQUIRES_REJECTION_OR_EVIDENCE"
        elif not entity_match:
            review_reason = "ENTITY_URL_ASSOCIATION_REQUIRES_MANUAL_VERIFICATION"

        confidence = float(role["confidence"])
        if not official:
            confidence = min(confidence, 0.35)
        if not entity_match:
            confidence = min(confidence, 0.65)

        classification_id = stable_id(
            "classification",
            row.get("inventory_id", ""),
            role["proposed_action_type"],
            role["link_role"],
        )

        record = {
            "classification_id": classification_id,
            "inventory_id": row.get("inventory_id", ""),
            "source_row_number": row.get("source_row_number", ""),
            "master_id": row.get("master_id", ""),
            "canonical_name": row.get("canonical_name", ""),
            "record_type": row.get("record_type", ""),
            "source_name": row.get("source_name", ""),
            "department": row.get("department", ""),
            "ministry": row.get("ministry", ""),
            "source_field_names": row.get("source_field_names", ""),
            "source_strength": row.get("source_strength", ""),
            "original_url": row.get("original_url", ""),
            "normalized_url": row.get("normalized_url", ""),
            "url_domain": row.get("url_domain", ""),
            "url_path": row.get("url_path", ""),
            "file_extension": row.get("file_extension", ""),
            "proposed_action_type": role["proposed_action_type"],
            "link_role": role["link_role"],
            "verification_status": "UNVERIFIED",
            "confidence": f"{confidence:.2f}",
            "official_domain_policy_result": "PASS" if official else "FAIL",
            "entity_url_match": str(entity_match),
            "classification_evidence": " | ".join(evidence),
            "manual_review_required": "True",
            "manual_review_reason": review_reason,
            "eligible_for_public_button": "False",
            "network_status": "NOT_REQUESTED",
            "classified_at_utc": classified_at,
        }
        classifications.append(record)

        review_queue.append(
            {
                "queue_id": stable_id(
                    "review",
                    row.get("inventory_id", ""),
                    role["proposed_action_type"],
                ),
                "queue_type": "OFFLINE_VERIFICATION",
                "priority": role["priority"],
                "inventory_id": row.get("inventory_id", ""),
                "master_id": row.get("master_id", ""),
                "canonical_name": row.get("canonical_name", ""),
                "normalized_url": row.get("normalized_url", ""),
                "proposed_action_type": role["proposed_action_type"],
                "link_role": role["link_role"],
                "current_status": "UNVERIFIED",
                "reason": review_reason,
                "source_field_names": row.get("source_field_names", ""),
                "confidence": f"{confidence:.2f}",
                "eligible_for_public_button": "False",
                "created_at_utc": classified_at,
            }
        )

    quarantine_priority = {
        "CROSS_ENTITY_EVIDENCE": "HIGH",
        "SHARED_AMBIGUOUS_DOCUMENT": "HIGH",
        "LOCAL_OR_PRIVATE_ENDPOINT": "HIGH",
        "MODEL_API_ENDPOINT": "HIGH",
        "NON_PUBLIC_TECHNICAL_FIELD": "MEDIUM",
    }

    for row in quarantine_rows:
        reason = row.get("quarantine_reason", "HYGIENE_QUARANTINE")
        review_queue.append(
            {
                "queue_id": stable_id(
                    "quarantine-review",
                    row.get("inventory_id", ""),
                    reason,
                ),
                "queue_type": "HYGIENE_QUARANTINE",
                "priority": quarantine_priority.get(reason, "MEDIUM"),
                "inventory_id": row.get("inventory_id", ""),
                "master_id": row.get("master_id", ""),
                "canonical_name": row.get("canonical_name", ""),
                "normalized_url": row.get("normalized_url", ""),
                "proposed_action_type": "",
                "link_role": "",
                "current_status": "QUARANTINED",
                "reason": reason,
                "source_field_names": row.get("source_field_names", ""),
                "confidence": "0.00",
                "eligible_for_public_button": "False",
                "created_at_utc": classified_at,
            }
        )

    action_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for item in classifications:
        action = str(item["proposed_action_type"])
        role = str(item["link_role"])
        action_counts[action] = action_counts.get(action, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1

    summary = {
        "version": VERSION,
        "stage": "OFFLINE_CLASSIFICATION_ONLY",
        "execution_mode": "PREVIEW_ONLY",
        "input_inventory_row_count": len(inventory_rows),
        "input_quarantine_row_count": len(quarantine_rows),
        "classified_row_count": len(classifications),
        "review_queue_row_count": len(review_queue),
        "action_counts": action_counts,
        "link_role_counts": role_counts,
        "verification_status_counts": {"UNVERIFIED": len(classifications)},
        "public_button_eligible_count": 0,
        "apply_now_button_count": 0,
        "network_requests": 0,
        "database_writes": 0,
        "dashboard_code_changes": 0,
        "publication_performed": False,
        "classified_at_utc": classified_at,
    }
    return classifications, review_queue, summary


def run_offline_classification(project_root: Path) -> dict[str, Any]:
    config_path = project_root / "config" / "action_link_rules_v3_4_3_5.json"
    config = load_json(config_path)
    if config.get("schema_version") != VERSION:
        raise RuntimeError("Configuration version mismatch.")
    if config.get("execution_mode") != "PREVIEW_ONLY":
        raise RuntimeError("Configuration is not PREVIEW_ONLY.")
    if config.get("output", {}).get("publication_allowed") is not False:
        raise RuntimeError("Publication must remain disabled.")
    if config.get("output", {}).get("database_writes_allowed") is not False:
        raise RuntimeError("Database writes must remain disabled.")

    source_path = project_root / Path(config["source"]["catalogue_path"])
    if sha256_file(source_path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Frozen v3.4.3.4 source candidate hash mismatch.")

    output_dir = project_root / Path(config["output"]["directory"])
    inventory_path = output_dir / "meity_action_link_inventory_v3_4_3_5.csv"
    quarantine_path = output_dir / "meity_action_link_inventory_quarantine_v3_4_3_5.csv"
    inventory_summary_path = (
        output_dir / "meity_action_link_inventory_summary_v3_4_3_5.json"
    )

    if not inventory_path.exists():
        raise FileNotFoundError(f"Clean inventory not found: {inventory_path}")
    if not quarantine_path.exists():
        raise FileNotFoundError(f"Quarantine inventory not found: {quarantine_path}")
    if not inventory_summary_path.exists():
        raise FileNotFoundError(f"Inventory summary not found: {inventory_summary_path}")

    inventory_summary = load_json(inventory_summary_path)
    if inventory_summary.get("stage") != "HYGIENE_INVENTORY_ONLY":
        raise RuntimeError("Run the hygienic inventory stage before offline classification.")
    if inventory_summary.get("network_requests") != 0:
        raise RuntimeError("Inventory summary reports unexpected network requests.")
    if not all(inventory_summary.get("safety", {}).values()):
        raise RuntimeError("Inventory safety checks were not all successful.")

    classification_path = (
        output_dir / "meity_action_link_offline_classification_v3_4_3_5.csv"
    )
    review_queue_path = (
        output_dir / "meity_action_link_review_queue_v3_4_3_5.csv"
    )
    summary_path = (
        output_dir / "meity_action_link_offline_classification_summary_v3_4_3_5.json"
    )

    source_hash_before = sha256_file(source_path)
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
    publication_current = project_root / "publication" / "current"
    publication_existed_before = publication_current.exists()

    inventory_rows = read_csv(inventory_path)
    quarantine_rows = read_csv(quarantine_path)
    classifications, review_queue, summary = classify_inventory(
        inventory_rows,
        quarantine_rows,
        config,
    )

    write_csv(classification_path, classifications, CLASSIFICATION_COLUMNS)
    write_csv(review_queue_path, review_queue, REVIEW_COLUMNS)

    summary["source_sha256"] = source_hash_before
    summary["inventory_sha256"] = inventory_hash_before
    summary["quarantine_sha256"] = quarantine_hash_before
    summary["classification_path"] = classification_path.relative_to(
        project_root
    ).as_posix()
    summary["review_queue_path"] = review_queue_path.relative_to(
        project_root
    ).as_posix()
    summary["classification_sha256"] = sha256_file(classification_path)
    summary["review_queue_sha256"] = sha256_file(review_queue_path)
    write_json(summary_path, summary)

    source_hash_after = sha256_file(source_path)
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
        "clean_inventory_unchanged": inventory_hash_before == inventory_hash_after,
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
