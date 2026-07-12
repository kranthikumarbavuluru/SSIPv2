from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

HOTFIX_VERSION = "2.2.0"
SOURCE_NAME = "MeitY Startup Hub"


class HotfixError(RuntimeError):
    """Raised when the MeitY classification outputs are not safe to patch."""


@dataclass(frozen=True)
class HotfixPaths:
    project_root: Path
    classified_path: Path
    masters_path: Path
    summary_path: Path
    config_path: Path
    output_summary_path: Path
    backup_dir: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise HotfixError(f"Required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HotfixError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def default_paths(project_root: Path | None = None) -> HotfixPaths:
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    return HotfixPaths(
        project_root=root,
        classified_path=root / "data" / "classified_candidates_v1.json",
        masters_path=root / "data" / "scheme_master_candidates_v1.json",
        summary_path=root / "data" / "classification_summary_v1.json",
        config_path=root / "config" / "meity_classification_hotfix_v2_2.json",
        output_summary_path=root / "data" / "meity_classification_hotfix_summary_v2_2.json",
        backup_dir=root / "data" / "backups",
    )


def normalized_url_path(url: str) -> str:
    path = urlsplit(url or "").path.rstrip("/")
    return path or "/"


def stable_master_id(url: str) -> str:
    payload = f"{SOURCE_NAME}|{url}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def append_unique(values: Any, item: str) -> list[str]:
    result = list(values) if isinstance(values, list) else []
    if item not in result:
        result.append(item)
    return result


def load_mapping(config_path: Path) -> dict[str, dict[str, str]]:
    config = load_json(config_path)
    if config.get("hotfix_version") != HOTFIX_VERSION:
        raise HotfixError(
            f"Unexpected hotfix config version: {config.get('hotfix_version')!r}"
        )
    records = config.get("records")
    if not isinstance(records, dict) or not records:
        raise HotfixError("MeitY hotfix configuration contains no URL mappings.")
    return {str(path).rstrip("/"): dict(value) for path, value in records.items()}


def patch_classified_record(
    original: dict[str, Any], mapping: dict[str, str], generated_at: str
) -> dict[str, Any]:
    record = copy.deepcopy(original)
    canonical_name = mapping["canonical_name"]
    classification = mapping["classification"]

    record["title"] = canonical_name
    record["anchor_text"] = canonical_name
    record["classification"] = classification
    record["classification_confidence"] = 1.0
    record["classification_reasons"] = append_unique(
        record.get("classification_reasons"), "MeitY official URL mapping"
    )
    record["programme_family"] = canonical_name
    record["programme_family_confidence"] = 1.0
    record["programme_family_method"] = "meity-url-map-v2.2"
    record["call_sequence"] = None
    record["lifecycle_status"] = "CURRENT_UNVERIFIED"
    record["lifecycle_confidence"] = max(
        float(record.get("lifecycle_confidence") or 0.0), 0.75
    )
    record["review_decision"] = "PRIORITY_REVIEW"
    record["dashboard_relevance"] = "HIGH"
    record["dashboard_relevance_score"] = max(
        int(record.get("dashboard_relevance_score") or 0), 8
    )
    record["classified_at"] = generated_at
    record["classifier_version"] = "1.0.0+meity-hotfix-2.2"
    record["classification_hotfix_version"] = HOTFIX_VERSION
    record["title_resolution_method"] = "official-url-and-bootstrap-metadata"
    record["title_resolution_confidence"] = 1.0
    return record


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": record.get("canonical_url") or record.get("url"),
        "title": record.get("title"),
        "anchor_text": record.get("anchor_text"),
        "classification": record.get("classification"),
        "lifecycle_status": record.get("lifecycle_status"),
        "deadline": record.get("deadline"),
        "relevance_score": record.get("relevance_score"),
        "dashboard_relevance": record.get("dashboard_relevance"),
    }


def build_master(
    record: dict[str, Any], mapping: dict[str, str], generated_at: str
) -> dict[str, Any]:
    url = str(record.get("canonical_url") or record.get("url") or "")
    if not url:
        raise HotfixError("A mapped MeitY record has no URL.")

    canonical_name = mapping["canonical_name"]
    master_type = mapping["master_type"]
    is_call = master_type == "ACTIVE_CALL_FAMILY"
    compact = compact_record(record)

    return {
        "master_id": stable_master_id(url),
        "canonical_name": canonical_name,
        "source": SOURCE_NAME,
        "master_type": master_type,
        "current_status": (
            "ACTIVE_CALL_OPEN" if is_call else "SCHEME_INFORMATION_AVAILABLE"
        ),
        "readiness": (
            "NEEDS_CONTENT_EXTRACTION_AND_REVIEW"
            if is_call
            else "READY_FOR_EXTRACTION"
        ),
        "official_page_url": None if is_call else url,
        "official_page_title": None if is_call else canonical_name,
        "best_available_url": url,
        "best_available_title": canonical_name,
        "best_relevance_score": record.get("relevance_score"),
        "programme_family_confidence": 1.0,
        "source_records_count": 1,
        "core_page_count": 0 if is_call else 1,
        "active_call_count": 1 if is_call else 0,
        "closed_call_count": 0,
        "supporting_document_count": 0,
        "active_calls": [compact] if is_call else [],
        "supporting_documents": [],
        "core_pages": [] if is_call else [compact],
        "all_member_urls": [url],
        "generated_at": generated_at,
        "classifier_version": "1.0.0+meity-hotfix-2.2",
        "classification_hotfix_version": HOTFIX_VERSION,
        "status_note": (
            "Challenge application status and deadline require official-source verification."
            if is_call
            else None
        ),
    }


def count_field(records: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        value = record.get(field)
        if value is not None and str(value):
            counter[str(value)] += 1
    return dict(counter)


def update_summary(
    existing_summary: dict[str, Any] | None,
    classified: list[dict[str, Any]],
    masters: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    summary = copy.deepcopy(existing_summary) if existing_summary else {}
    summary["deduplicated_record_count"] = len(classified)
    summary["master_candidate_count"] = len(masters)
    summary["records_by_source"] = count_field(classified, "source")
    summary["records_by_classification"] = count_field(classified, "classification")
    summary["records_by_lifecycle"] = count_field(classified, "lifecycle_status")
    summary["records_by_review_decision"] = count_field(
        classified, "review_decision"
    )
    summary["records_by_dashboard_relevance"] = count_field(
        classified, "dashboard_relevance"
    )
    summary["masters_by_source"] = count_field(masters, "source")
    summary["masters_by_status"] = count_field(masters, "current_status")
    summary["generated_at"] = generated_at
    summary["classifier_version"] = "1.0.0+meity-hotfix-2.2"
    summary["meity_classification_hotfix"] = {
        "version": HOTFIX_VERSION,
        "resolved_record_count": 6,
        "separate_master_count": 6,
    }
    return summary


def validate_inputs(
    classified: Any,
    masters: Any,
    mapping_by_path: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(classified, list) or not all(
        isinstance(item, dict) for item in classified
    ):
        raise HotfixError("classified_candidates_v1.json must contain a JSON array.")
    if not isinstance(masters, list) or not all(isinstance(item, dict) for item in masters):
        raise HotfixError("scheme_master_candidates_v1.json must contain a JSON array.")

    meity_records = [r for r in classified if r.get("source") == SOURCE_NAME]
    paths = {
        normalized_url_path(str(r.get("canonical_url") or r.get("url") or ""))
        for r in meity_records
    }
    expected_paths = set(mapping_by_path)
    missing = sorted(expected_paths - paths)
    unexpected = sorted(paths - expected_paths)
    if missing or unexpected:
        raise HotfixError(
            "MeitY URL set does not match the v2.2 mapping. "
            f"Missing={missing}; Unexpected={unexpected}"
        )
    if len(meity_records) != len(expected_paths):
        raise HotfixError(
            f"Expected {len(expected_paths)} MeitY classified records; "
            f"found {len(meity_records)}."
        )
    return classified, masters


def apply_hotfix_payloads(
    classified: list[dict[str, Any]],
    masters: list[dict[str, Any]],
    mapping_by_path: dict[str, dict[str, str]],
    existing_summary: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    generated_at = generated_at or utc_now()
    validate_inputs(classified, masters, mapping_by_path)

    patched_classified: list[dict[str, Any]] = []
    meity_record_by_path: dict[str, dict[str, Any]] = {}

    for original in classified:
        if original.get("source") != SOURCE_NAME:
            patched_classified.append(copy.deepcopy(original))
            continue
        path = normalized_url_path(
            str(original.get("canonical_url") or original.get("url") or "")
        )
        patched = patch_classified_record(
            original, mapping_by_path[path], generated_at
        )
        patched_classified.append(patched)
        meity_record_by_path[path] = patched

    non_meity_masters = [
        copy.deepcopy(master) for master in masters if master.get("source") != SOURCE_NAME
    ]
    meity_masters = [
        build_master(meity_record_by_path[path], mapping_by_path[path], generated_at)
        for path in mapping_by_path
    ]

    # Insert the six resolved records where the previous generic MeitY master appeared.
    first_meity_index = next(
        (index for index, master in enumerate(masters) if master.get("source") == SOURCE_NAME),
        len(non_meity_masters),
    )
    before = [
        copy.deepcopy(master)
        for master in masters[:first_meity_index]
        if master.get("source") != SOURCE_NAME
    ]
    after = [
        copy.deepcopy(master)
        for master in masters[first_meity_index:]
        if master.get("source") != SOURCE_NAME
    ]
    patched_masters = before + meity_masters + after

    updated_summary = update_summary(
        existing_summary, patched_classified, patched_masters, generated_at
    )

    hotfix_summary = {
        "hotfix_version": HOTFIX_VERSION,
        "source": SOURCE_NAME,
        "classified_record_count_before": len(classified),
        "classified_record_count_after": len(patched_classified),
        "meity_classified_record_count": len(meity_record_by_path),
        "master_candidate_count_before": len(masters),
        "master_candidate_count_after": len(patched_masters),
        "meity_master_count_before": sum(
            1 for master in masters if master.get("source") == SOURCE_NAME
        ),
        "meity_master_count_after": len(meity_masters),
        "non_meity_classified_records_preserved": sum(
            1 for record in classified if record.get("source") != SOURCE_NAME
        ),
        "non_meity_masters_preserved": len(non_meity_masters),
        "meity_candidates": [
            {
                "master_id": master["master_id"],
                "canonical_name": master["canonical_name"],
                "master_type": master["master_type"],
                "current_status": master["current_status"],
                "best_available_url": master["best_available_url"],
            }
            for master in meity_masters
        ],
        "generated_at": generated_at,
    }
    return patched_classified, patched_masters, updated_summary, hotfix_summary


def backup_files(paths: HotfixPaths, token: str) -> dict[str, str]:
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    backups: dict[str, str] = {}
    for label, source in (
        ("classified", paths.classified_path),
        ("masters", paths.masters_path),
        ("summary", paths.summary_path),
    ):
        if not source.exists():
            continue
        destination = paths.backup_dir / f"{source.stem}_before_meity_classification_hotfix_{token}{source.suffix}"
        shutil.copy2(source, destination)
        backups[label] = str(destination)
    return backups


def run_hotfix(
    project_root: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    paths = default_paths(project_root)
    mapping_by_path = load_mapping(paths.config_path)
    classified = load_json(paths.classified_path)
    masters = load_json(paths.masters_path)
    existing_summary = load_json(paths.summary_path) if paths.summary_path.exists() else None

    patched_classified, patched_masters, updated_summary, hotfix_summary = (
        apply_hotfix_payloads(
            classified,
            masters,
            mapping_by_path,
            existing_summary=existing_summary,
        )
    )

    backups: dict[str, str] = {}
    if not dry_run:
        backups = backup_files(paths, timestamp_token())
        write_json(paths.classified_path, patched_classified)
        write_json(paths.masters_path, patched_masters)
        write_json(paths.summary_path, updated_summary)
        write_json(paths.output_summary_path, hotfix_summary)

    result = {
        **hotfix_summary,
        "dry_run": dry_run,
        "classified_output_path": str(paths.classified_path),
        "masters_output_path": str(paths.masters_path),
        "classification_summary_output_path": str(paths.summary_path),
        "hotfix_summary_output_path": str(paths.output_summary_path),
        "backup_paths": backups,
    }
    return result


def print_result(result: dict[str, Any]) -> None:
    print("\n" + "=" * 92)
    print("MEITY CLASSIFICATION HOTFIX V2.2 COMPLETED")
    print("=" * 92)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n" + "=" * 92)
    print("MEITY MASTER CANDIDATES")
    print("=" * 92)
    for candidate in result["meity_candidates"]:
        print(f"{candidate['canonical_name']} | {candidate['master_type']}")
        print(f"  {candidate['best_available_url']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply MeitY Classification Hotfix v2.2")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="SSIP project root. Defaults to the root inferred from this file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and calculate outputs without writing files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_hotfix(args.project_root, dry_run=args.dry_run)
    print_result(result)


if __name__ == "__main__":
    main()
