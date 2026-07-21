from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

VERSION = "3.4.3.7"
PHASE = "MeitY Admin Verification Gate"
UPSTREAM_VERSION = "3.4.3.4"
SASACT_ID = "194b7ba77d6b53f30b91"
GENESIS_ID = "94f8ab0a070a6ff15fce"
TARGET_IDS = {SASACT_ID, GENESIS_ID}
TARGET_NAMES = {SASACT_ID: "SASACT", GENESIS_ID: "GENESIS"}
ALLOWED_DECISIONS = {"", "APPROVE", "RETURN_FOR_CORRECTION", "REJECT", "DEFER"}
REASON_REQUIRED = {"RETURN_FOR_CORRECTION", "REJECT", "DEFER"}
APPLICATION_SENTINELS = {
    "",
    "NO_CURRENT_APPLICATION_ROUTE",
    "NO_CURRENT_APPLICATION_ROUTE_CONFIRMED",
    "NOT_AVAILABLE",
    "N/A",
    "NONE",
}

QUEUE_FIELDS = [
    "review_id",
    "master_id",
    "canonical_name",
    "display_name",
    "source",
    "ministry",
    "department",
    "entity_type",
    "permanent_scheme_or_call",
    "parent_master_id",
    "parent_canonical_name",
    "candidate_change_type",
    "active_record_present",
    "candidate_record_present",
    "official_source_url",
    "canonical_scheme_url",
    "application_url",
    "guidelines_url",
    "page_role",
    "programme_status",
    "application_status",
    "opening_date",
    "deadline",
    "objective_summary",
    "eligibility_summary",
    "benefit_summary",
    "startup_relevance",
    "identity_confidence",
    "evidence_confidence",
    "evidence_completeness",
    "duplicate_check_status",
    "call_identity_check_status",
    "blocking_flags",
    "review_recommendation",
    "admin_decision",
    "admin_reason",
    "admin_name",
    "reviewed_at",
    "evidence_hash",
    "candidate_row_hash",
]


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Inputs:
    project_root: Path
    upstream_manifest: Path
    upstream_summary: Path
    upstream_validation: Path
    candidate_rows_file: Path | None
    active_catalogue: Path
    candidate_catalogue: Path
    source_generated_at: str


@dataclass
class GateResult:
    status: str
    summary: dict[str, Any]
    exit_code: int


def norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def upper(value: Any) -> str:
    return norm(value).upper()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def safe_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def resolve_project_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise GateError(f"Path escapes project root: {value}") from exc
    return resolved


def resolve_recorded_project_path(root: Path, value: str | Path) -> Path:
    """Remap absolute paths recorded on another SSIP checkout into this checkout."""
    text = str(value).replace("\\", "/")
    candidate = Path(value)
    recorded_absolute = candidate.is_absolute() or bool(re.match(r"^[A-Za-z]:/", text)) or text.startswith("//")
    if not recorded_absolute:
        return resolve_project_path(root, candidate)

    lowered = text.casefold()
    for anchor in ("data/", "apps/", "database/", "publication/", "scripts/", "tests/"):
        index = lowered.find(anchor)
        if index >= 0:
            remapped = (root / Path(text[index:])).resolve()
            try:
                remapped.relative_to(root.resolve())
            except ValueError:
                continue
            return remapped
    return resolve_project_path(root, candidate)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{key: value or "" for key, value in row.items()} for row in reader]
    return fields, rows


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(tmp, path)


def first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = norm(row.get(key))
        if value:
            return value
    return ""


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def find_exactly_one(root: Path, pattern: str) -> Path:
    matches = sorted(path for path in root.rglob(pattern) if path.is_file())
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches) or "none"
        raise GateError(f"Expected exactly one {pattern}; found {len(matches)}: {rendered}")
    return matches[0]


def manifest_outputs(root: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for item in manifest.get("outputs", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = resolve_project_path(root, item["path"])
        outputs[path.name] = path
        expected_hash = norm(item.get("sha256"))
        if expected_hash and path.exists() and sha256_file(path) != expected_hash:
            raise GateError(f"Upstream manifest hash mismatch: {path}")
    return outputs


def discover_inputs(root: Path) -> Inputs:
    base = root / "data" / "departments" / "meity"
    manifest_path = find_exactly_one(base, "meity_release_readiness_manifest_v3_4_3_4.json")
    manifest = read_json(manifest_path)
    if norm(manifest.get("version")) != UPSTREAM_VERSION:
        raise GateError("Unexpected upstream manifest version.")
    if upper(manifest.get("release_readiness_status")) != "PASS":
        raise GateError("v3.4.3.4 release-readiness status is not PASS.")

    outputs = manifest_outputs(root, manifest)
    summary_path = outputs.get("meity_release_readiness_summary_v3_4_3_4.json")
    validation_path = outputs.get("meity_dashboard_preview_validation_v3_4_3_4.json")
    candidate_rows_file = outputs.get("meity_publication_candidate_rows_v3_4_3_4.csv")

    if summary_path is None:
        summary_path = manifest_path.parent / "meity_release_readiness_summary_v3_4_3_4.json"
    if validation_path is None:
        validation_path = manifest_path.parent / "meity_dashboard_preview_validation_v3_4_3_4.json"
    if not summary_path.exists() or not validation_path.exists():
        raise GateError("Required v3.4.3.4 summary or validation file is missing.")

    summary = read_json(summary_path)
    validation = read_json(validation_path)
    if upper(summary.get("release_readiness_status")) != "PASS":
        raise GateError("v3.4.3.4 summary is not PASS.")
    if upper(validation.get("validation_status")) != "PASS":
        raise GateError("v3.4.3.4 validation is not PASS.")

    active_value = summary.get("active_catalogue")
    candidate_value = summary.get("candidate_catalogue")
    if not active_value or not candidate_value:
        raise GateError("Upstream summary does not identify active and candidate catalogues.")

    active = resolve_recorded_project_path(root, active_value)
    candidate = resolve_recorded_project_path(root, candidate_value)
    if not active.exists() or not candidate.exists():
        raise GateError("Active or candidate catalogue is missing.")

    return Inputs(
        project_root=root,
        upstream_manifest=manifest_path,
        upstream_summary=summary_path,
        upstream_validation=validation_path,
        candidate_rows_file=candidate_rows_file if candidate_rows_file and candidate_rows_file.exists() else None,
        active_catalogue=active,
        candidate_catalogue=candidate,
        source_generated_at=norm(manifest.get("generated_at")) or norm(summary.get("generated_at")),
    )


def index_by_master_id(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for position, row in enumerate(rows, start=2):
        master_id = first(row, "master_id")
        if not master_id:
            raise GateError(f"{label} contains a blank master_id at CSV row {position}.")
        if master_id in index:
            raise GateError(f"{label} contains duplicate master_id {master_id}.")
        index[master_id] = row
    return index


def material_delta(
    active_rows: list[dict[str, str]], candidate_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[str]]:
    active = index_by_master_id(active_rows, "active catalogue")
    candidate = index_by_master_id(candidate_rows, "candidate catalogue")
    removed = sorted(set(active) - set(candidate))
    if removed:
        raise GateError(f"Candidate removes active master IDs: {removed}")

    modified = [master_id for master_id in active if active[master_id] != candidate[master_id]]
    added = [candidate[master_id] for master_id in candidate if master_id not in active]
    return added, modified


def candidate_row_hash(row: dict[str, str]) -> str:
    return canonical_json_hash({key: row.get(key, "") for key in sorted(row)})


def identity_name(row: dict[str, str]) -> str:
    return first(row, "canonical_name", "scheme_name", "display_name", "title", "candidate_name")


def is_meity(row: dict[str, str]) -> bool:
    combined = " ".join(
        first(row, key)
        for key in ("source", "agency", "source_name", "ministry", "department", "implementing_agency")
    ).casefold()
    return "meity" in combined or "electronics and information technology" in combined


def infer_entity_type(row: dict[str, str]) -> str:
    return first(row, "record_kind", "record_type", "master_type", "scheme_type", "entity_type") or "SCHEME"


def call_like(row: dict[str, str]) -> bool:
    text = " ".join(
        first(row, key)
        for key in (
            "record_kind",
            "record_type",
            "entity_type",
            "call_type",
            "page_role",
            "title",
            "scheme_name",
            "canonical_name",
        )
    ).upper()
    return any(token in text for token in ("CALL", "CHALLENGE", "COHORT", "APPLICATION WINDOW", "ROUND"))


def queue_row(row: dict[str, str]) -> dict[str, str]:
    master_id = first(row, "master_id")
    name = identity_name(row)
    row_hash = candidate_row_hash(row)
    entity = infer_entity_type(row)
    permanent_or_call = "CALL" if call_like(row) else "PERMANENT_SCHEME"
    duplicate_status = "PASS" if master_id in TARGET_IDS else "FAIL"
    call_identity_status = "PASS" if permanent_or_call == "PERMANENT_SCHEME" else "FAIL"
    blocking: list[str] = []
    if not is_meity(row):
        blocking.append("SOURCE_NOT_MEITY")
    if master_id not in TARGET_IDS:
        blocking.append("UNEXPECTED_MASTER_ID")
    if permanent_or_call != "PERMANENT_SCHEME":
        blocking.append("CALL_MUST_NOT_REPLACE_PERMANENT_SCHEME")
    if not name:
        blocking.append("CANONICAL_NAME_MISSING")

    evidence = {
        "master_id": master_id,
        "canonical_name": name,
        "source": first(row, "source", "agency", "source_name"),
        "official_url": first(
            row,
            "official_page_url",
            "core_scheme_url",
            "best_available_url",
            "final_url",
            "scheme_url",
            "source_url",
        ),
        "programme_status": first(row, "programme_status", "scheme_status", "current_status"),
        "application_status": first(row, "application_status"),
        "objective": first(row, "objective", "description", "summary"),
        "eligibility": first(row, "eligibility", "eligible_applicants"),
        "benefit": first(row, "benefits", "funding", "funding_amount", "funding_support"),
        "candidate_row_hash": row_hash,
    }
    evidence_hash = canonical_json_hash(evidence)
    review_id = f"MEITY-{master_id}-{row_hash[:12]}"

    return {
        "review_id": review_id,
        "master_id": master_id,
        "canonical_name": name,
        "display_name": first(row, "display_name", "scheme_name", "canonical_name", "title"),
        "source": first(row, "source", "agency", "source_name"),
        "ministry": first(row, "ministry"),
        "department": first(row, "department"),
        "entity_type": entity,
        "permanent_scheme_or_call": permanent_or_call,
        "parent_master_id": first(row, "parent_master_id"),
        "parent_canonical_name": first(row, "parent_canonical_name", "parent_scheme_name", "parent_programme"),
        "candidate_change_type": "ADD",
        "active_record_present": "false",
        "candidate_record_present": "true",
        "official_source_url": evidence["official_url"],
        "canonical_scheme_url": evidence["official_url"],
        "application_url": first(row, "application_url"),
        "guidelines_url": first(row, "guidelines_url", "manual_url"),
        "page_role": first(row, "page_role"),
        "programme_status": evidence["programme_status"],
        "application_status": evidence["application_status"],
        "opening_date": first(row, "opening_date", "open_date"),
        "deadline": first(row, "deadline", "closing_date", "close_date", "application_deadline"),
        "objective_summary": evidence["objective"],
        "eligibility_summary": evidence["eligibility"],
        "benefit_summary": evidence["benefit"],
        "startup_relevance": first(row, "startup_relevance", "startup_relevance_status"),
        "identity_confidence": first(row, "identity_confidence", "confidence", "confidence_after_validation"),
        "evidence_confidence": first(row, "evidence_confidence", "confidence", "confidence_after_validation"),
        "evidence_completeness": first(row, "evidence_completeness", "evidence_completeness_score"),
        "duplicate_check_status": duplicate_status,
        "call_identity_check_status": call_identity_status,
        "blocking_flags": "|".join(blocking),
        "review_recommendation": "APPROVE" if not blocking else "RETURN_FOR_CORRECTION",
        "admin_decision": "",
        "admin_reason": "",
        "admin_name": "",
        "reviewed_at": "",
        "evidence_hash": evidence_hash,
        "candidate_row_hash": row_hash,
    }


def validate_expected_delta(rows: list[dict[str, str]], modified_ids: list[str]) -> list[dict[str, str]]:
    if modified_ids:
        raise GateError(f"Existing active rows changed materially: {modified_ids}")
    if len(rows) != 2:
        raise GateError(f"Expected exactly two material additions; found {len(rows)}.")
    ids = {first(row, "master_id") for row in rows}
    if ids != TARGET_IDS:
        raise GateError(f"Expected SASACT and GENESIS IDs; found {sorted(ids)}")
    for row in rows:
        if not is_meity(row):
            raise GateError(f"Unexpected non-MeitY material addition: {first(row, 'master_id')}")
        if call_like(row):
            raise GateError("A call/challenge is being represented as a permanent scheme addition.")
    return sorted((queue_row(row) for row in rows), key=lambda item: item["master_id"])


def application_button_count(queue: list[dict[str, str]]) -> int:
    count = 0
    for row in queue:
        url = upper(row.get("application_url"))
        if url not in APPLICATION_SENTINELS and re.match(r"^HTTPS?://", url):
            count += 1
    return count


def parse_date(value: str) -> date | None:
    text = norm(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def iter_structured_files(root: Path, excluded: Path) -> Iterable[Path]:
    meity_root = root / "data" / "departments" / "meity"
    if not meity_root.exists():
        return []
    files: list[Path] = []
    for path in meity_root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".csv", ".json"}:
            continue
        try:
            path.resolve().relative_to(excluded.resolve())
            continue
        except ValueError:
            pass
        files.append(path)
    return sorted(files)


def calls_coverage(root: Path, output_dir: Path) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    today = date.today()

    def inspect_row(path: Path, row: dict[str, Any], locator: str) -> None:
        if not call_like({key: norm(value) for key, value in row.items()}):
            return
        title = first(row, "call_title", "title", "canonical_name", "scheme_name", "candidate_name")
        status = upper(first(row, "call_status", "application_status", "programme_status", "current_status"))
        deadline = first(row, "deadline", "closing_date", "close_date", "application_deadline")
        application_url = first(row, "application_url", "apply_url", "application_link")
        parent = first(row, "parent_master_id", "parent_scheme_id", "scheme_master_id")
        deadline_date = parse_date(deadline)
        item = {
            "path": safe_relative(path, root),
            "locator": locator,
            "title": title,
            "status": status,
            "deadline": deadline,
            "application_url": application_url,
            "parent_master_id": parent,
            "verified_current": False,
        }
        is_open = status in {"OPEN", "OPEN_FOR_APPLICATIONS", "APPLICATIONS_OPEN"}
        valid_url = bool(re.match(r"^https?://", application_url, flags=re.I))
        current_deadline = deadline_date is not None and deadline_date >= today
        item["verified_current"] = bool(is_open and valid_url and current_deadline and parent)
        evidence.append(item)
        if item["verified_current"]:
            verified.append(item)

    for path in iter_structured_files(root, output_dir):
        try:
            if path.suffix.casefold() == ".csv":
                _, rows = read_csv(path)
                for index, row in enumerate(rows, start=2):
                    inspect_row(path, row, f"csv_row:{index}")
            else:
                payload = read_json(path)
                stack: list[tuple[str, Any]] = [("$", payload)]
                while stack:
                    locator, value = stack.pop()
                    if isinstance(value, dict):
                        inspect_row(path, value, locator)
                        for key, child in value.items():
                            stack.append((f"{locator}.{key}", child))
                    elif isinstance(value, list):
                        for index, child in enumerate(value):
                            stack.append((f"{locator}[{index}]", child))
        except (OSError, ValueError, csv.Error, json.JSONDecodeError):
            continue

    evidence = evidence[:250]
    return {
        "version": VERSION,
        "phase": "MeitY calls coverage gap declaration",
        "coverage_status": "COMPLETE" if verified else "INCOMPLETE",
        "verified_current_call_count": len(verified),
        "verified_current_calls": verified,
        "call_or_challenge_evidence_count": len(evidence),
        "call_or_challenge_evidence": evidence,
        "required_follow_up": (
            "Run MeitY Calls, Challenges and Application Windows Recovery; verify parent identity, "
            "opening date, deadline and application route before any OPEN status or Apply button."
        ),
        "network_requests_performed": False,
    }


def protected_files(inputs: Inputs, output_dir: Path) -> list[Path]:
    root = inputs.project_root
    protected: set[Path] = {
        inputs.active_catalogue,
        inputs.candidate_catalogue,
        inputs.upstream_manifest,
        inputs.upstream_summary,
        inputs.upstream_validation,
    }
    if inputs.candidate_rows_file:
        protected.add(inputs.candidate_rows_file)
    for path in (
        root / "data" / "publication" / "current_manifest.json",
        root / "apps" / "public_dashboard_app_v2_9.py",
    ):
        if path.exists():
            protected.add(path)
    for directory in (root / "publication" / "current", root / "database"):
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file():
                    protected.add(path)
    return sorted(path for path in protected if path.exists() and output_dir not in path.parents)


def hash_inventory(paths: Iterable[Path], root: Path) -> dict[str, str]:
    return {safe_relative(path, root): sha256_file(path) for path in paths}


def validate_baseline(inputs: Inputs) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    active_fields, active_rows = read_csv(inputs.active_catalogue)
    candidate_fields, candidate_rows = read_csv(inputs.candidate_catalogue)
    if active_fields != candidate_fields:
        raise GateError("Active and candidate catalogue columns differ.")
    if len(active_rows) != 139:
        raise GateError(f"Expected 139 active raw rows; found {len(active_rows)}.")
    if len(candidate_rows) != 141:
        raise GateError(f"Expected 141 candidate raw rows; found {len(candidate_rows)}.")

    validation = read_json(inputs.upstream_validation)
    counts = validation.get("counts", {})
    if int(counts.get("active_main_visible", -1)) != 53:
        raise GateError("Expected 53 active dashboard schemes in upstream validation.")
    if int(counts.get("candidate_main_visible", -1)) != 55:
        raise GateError("Expected 55 candidate dashboard schemes in upstream validation.")

    added, modified = material_delta(active_rows, candidate_rows)
    queue = validate_expected_delta(added, modified)
    if application_button_count(queue) != 0:
        raise GateError("MeitY candidate unexpectedly exposes a public application URL.")
    return active_fields, active_rows, candidate_rows, {"queue": queue, "validation": validation}


def evidence_bundle(inputs: Inputs, queue: list[dict[str, str]], candidate_rows: list[dict[str, str]]) -> dict[str, Any]:
    by_id = index_by_master_id(candidate_rows, "candidate catalogue")
    entries: list[dict[str, Any]] = []
    for review in queue:
        row = by_id[review["master_id"]]
        entries.append(
            {
                "review_id": review["review_id"],
                "stable_identity": {
                    "master_id": review["master_id"],
                    "canonical_name": review["canonical_name"],
                    "entity_type": review["entity_type"],
                    "permanent_scheme_or_call": review["permanent_scheme_or_call"],
                },
                "official_ownership": {
                    "source": review["source"],
                    "ministry": review["ministry"],
                    "department": review["department"],
                },
                "source_urls": {
                    "official_source_url": review["official_source_url"] or None,
                    "canonical_scheme_url": review["canonical_scheme_url"] or None,
                    "application_url": review["application_url"] or None,
                    "guidelines_url": review["guidelines_url"] or None,
                },
                "classification": {
                    "page_role": review["page_role"] or None,
                    "programme_status": review["programme_status"] or None,
                    "application_status": review["application_status"] or None,
                },
                "extracted_evidence": {
                    "objective": review["objective_summary"] or None,
                    "eligibility": review["eligibility_summary"] or None,
                    "benefits": review["benefit_summary"] or None,
                    "opening_date": review["opening_date"] or None,
                    "deadline": review["deadline"] or None,
                },
                "relationship_evidence": {
                    "parent_master_id": review["parent_master_id"] or None,
                    "parent_canonical_name": review["parent_canonical_name"] or None,
                    "call_identity_check_status": review["call_identity_check_status"],
                },
                "duplicate_evidence": {
                    "duplicate_check_status": review["duplicate_check_status"],
                },
                "confidence": {
                    "identity": review["identity_confidence"] or None,
                    "evidence": review["evidence_confidence"] or None,
                    "completeness": review["evidence_completeness"] or None,
                },
                "unresolved_warnings": [flag for flag in review["blocking_flags"].split("|") if flag],
                "hashes": {
                    "evidence_hash": review["evidence_hash"],
                    "candidate_row_hash": review["candidate_row_hash"],
                },
                "proposed_publication_fields": row,
            }
        )
    return {
        "version": VERSION,
        "phase": PHASE,
        "source_version": UPSTREAM_VERSION,
        "source_generated_at": inputs.source_generated_at or None,
        "entries": entries,
        "fabricated_evidence": False,
    }


def merge_or_create_decision_template(path: Path, queue: list[dict[str, str]]) -> None:
    if not path.exists():
        write_csv(path, QUEUE_FIELDS, queue)
        return

    fields, existing = read_csv(path)
    if fields != QUEUE_FIELDS:
        raise GateError("Existing decision template schema does not match v3.4.3.7.")
    by_id = {row["review_id"]: row for row in existing}
    if len(by_id) != len(existing):
        raise GateError("Existing decision template contains duplicate review IDs.")
    expected = {row["review_id"]: row for row in queue}
    if set(by_id) != set(expected):
        raise GateError("Existing decision template identities differ from the current queue.")
    for review_id, row in by_id.items():
        if row.get("candidate_row_hash") != expected[review_id]["candidate_row_hash"]:
            raise GateError("Existing decision template candidate hash is stale.")
        if row.get("evidence_hash") != expected[review_id]["evidence_hash"]:
            raise GateError("Existing decision template evidence hash is stale.")
    # Preserve the file byte-for-byte when it is valid, including administrator input.


def validate_decisions(path: Path, queue: list[dict[str, str]]) -> list[dict[str, str]]:
    fields, decisions = read_csv(path)
    if not set(QUEUE_FIELDS).issubset(fields):
        raise GateError("Decision file is missing required columns.")
    if len(decisions) != len(queue):
        raise GateError("Decision file row count differs from the review queue.")

    expected = {row["review_id"]: row for row in queue}
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for row in decisions:
        review_id = norm(row.get("review_id"))
        if review_id in seen:
            raise GateError(f"Duplicate review decision: {review_id}")
        seen.add(review_id)
        if review_id not in expected:
            raise GateError(f"Unknown review ID: {review_id}")
        base = expected[review_id]
        if norm(row.get("candidate_row_hash")) != base["candidate_row_hash"]:
            raise GateError(f"Candidate hash mismatch for {review_id}")
        if norm(row.get("evidence_hash")) != base["evidence_hash"]:
            raise GateError(f"Evidence hash mismatch for {review_id}")
        decision = upper(row.get("admin_decision"))
        if decision not in ALLOWED_DECISIONS:
            raise GateError(f"Unknown admin decision {decision!r} for {review_id}")
        reason = norm(row.get("admin_reason"))
        if decision in REASON_REQUIRED and not reason:
            raise GateError(f"{decision} requires admin_reason for {review_id}")
        merged = dict(base)
        for key in ("admin_decision", "admin_reason", "admin_name", "reviewed_at"):
            merged[key] = norm(row.get(key))
        merged["admin_decision"] = decision
        normalized.append(merged)
    return sorted(normalized, key=lambda row: row["master_id"])


def classify_decisions(decisions: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    buckets = {
        "APPROVE": [],
        "RETURN_FOR_CORRECTION": [],
        "REJECT": [],
        "DEFER": [],
        "PENDING": [],
    }
    for row in decisions:
        decision = row["admin_decision"] or "PENDING"
        if decision == "APPROVE" and row["blocking_flags"]:
            raise GateError(f"Approved candidate has blocking flags: {row['review_id']}")
        buckets[decision].append(row)
    return buckets


def output_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "queue": output_dir / "meity_admin_review_queue_v3_4_3_7.csv",
        "decisions": output_dir / "meity_admin_decision_template_v3_4_3_7.csv",
        "evidence": output_dir / "meity_admin_evidence_bundle_v3_4_3_7.json",
        "calls": output_dir / "meity_calls_coverage_gap_v3_4_3_7.json",
        "approved": output_dir / "meity_admin_approved_delta_v3_4_3_7.csv",
        "returned": output_dir / "meity_admin_returned_delta_v3_4_3_7.csv",
        "rejected": output_dir / "meity_admin_rejected_delta_v3_4_3_7.csv",
        "deferred": output_dir / "meity_admin_deferred_delta_v3_4_3_7.csv",
        "summary": output_dir / "meity_admin_verification_summary_v3_4_3_7.json",
        "gate": output_dir / "meity_admin_verification_gate_v3_4_3_7.json",
        "manifest": output_dir / "meity_admin_verification_manifest_v3_4_3_7.json",
        "protected": output_dir / "meity_admin_protected_file_hashes_v3_4_3_7.json",
    }


def public_delta_rows(rows: list[dict[str, str]], publication_eligible: bool) -> tuple[list[str], list[dict[str, str]]]:
    fields = QUEUE_FIELDS + ["publication_eligible", "published"]
    rendered: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["publication_eligible"] = bool_text(publication_eligible)
        item["published"] = "false"
        rendered.append(item)
    return fields, rendered


def write_manifest(path: Path, root: Path, status: str, generated: Iterable[Path], source_generated_at: str) -> None:
    files = []
    for output in sorted(set(generated)):
        if not output.exists() or output == path:
            continue
        files.append(
            {
                "path": safe_relative(output, root),
                "sha256": sha256_file(output),
                "size_bytes": output.stat().st_size,
            }
        )
    payload = {
        "version": VERSION,
        "phase": PHASE,
        "generated_at": source_generated_at or None,
        "gate_status": status,
        "outputs": files,
        "publication_status": "NOT_PUBLISHED",
    }
    write_json(path, payload)


def prepare(root: Path, output_dir: Path) -> GateResult:
    inputs = discover_inputs(root)
    output_dir = output_dir.resolve()
    paths = output_paths(output_dir)
    protected = protected_files(inputs, output_dir)
    before = hash_inventory(protected, root)

    _, active_rows, candidate_rows, baseline = validate_baseline(inputs)
    queue = baseline["queue"]
    calls = calls_coverage(root, output_dir)
    bundle = evidence_bundle(inputs, queue, candidate_rows)

    write_csv(paths["queue"], QUEUE_FIELDS, queue)
    merge_or_create_decision_template(paths["decisions"], queue)
    write_json(paths["evidence"], bundle)
    write_json(paths["calls"], calls)

    decision_rows = validate_decisions(paths["decisions"], queue)
    buckets = classify_decisions(decision_rows)
    status = "WAITING_FOR_ADMIN" if buckets["PENDING"] else "PASS"

    fields, approved = public_delta_rows(buckets["APPROVE"], True)
    write_csv(paths["approved"], fields, approved)
    for key, decision in (
        ("returned", "RETURN_FOR_CORRECTION"),
        ("rejected", "REJECT"),
        ("deferred", "DEFER"),
    ):
        _, rendered = public_delta_rows(buckets[decision], False)
        write_csv(paths[key], fields, rendered)

    after = hash_inventory(protected, root)
    unchanged = before == after
    if not unchanged:
        raise GateError("A protected file changed during admin-gate preparation.")

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "gate_status": status,
        "generated_at": inputs.source_generated_at or None,
        "inputs": {
            "active_catalogue": safe_relative(inputs.active_catalogue, root),
            "candidate_catalogue": safe_relative(inputs.candidate_catalogue, root),
            "upstream_manifest": safe_relative(inputs.upstream_manifest, root),
        },
        "counts": {
            "active_raw_rows": len(active_rows),
            "candidate_raw_rows": len(candidate_rows),
            "active_dashboard_schemes": 53,
            "candidate_dashboard_schemes": 55,
            "material_delta": len(queue),
            "review_queue": len(queue),
            "approved": len(buckets["APPROVE"]),
            "returned": len(buckets["RETURN_FOR_CORRECTION"]),
            "rejected": len(buckets["REJECT"]),
            "deferred": len(buckets["DEFER"]),
            "pending": len(buckets["PENDING"]),
            "verified_meity_current_calls": calls["verified_current_call_count"],
            "public_application_buttons": application_button_count(queue),
        },
        "targets": {
            "sasact_queued": any(row["master_id"] == SASACT_ID for row in queue),
            "genesis_queued": any(row["master_id"] == GENESIS_ID for row in queue),
        },
        "integrity": {
            "active_catalogue_unchanged": unchanged,
            "publication_current_unchanged": unchanged,
            "database_unchanged": unchanged,
            "dashboard_unchanged": unchanged,
            "publication_performed": False,
            "database_writes_performed": False,
            "network_requests_performed": False,
        },
        "calls_coverage_status": calls["coverage_status"],
    }
    write_json(paths["summary"], summary)
    write_json(paths["gate"], summary)
    write_json(
        paths["protected"],
        {
            "version": VERSION,
            "before": before,
            "after": after,
            "all_unchanged": unchanged,
        },
    )
    generated = [path for name, path in paths.items() if name != "manifest"]
    write_manifest(paths["manifest"], root, status, generated, inputs.source_generated_at)

    print_summary(summary, inputs, paths)
    return GateResult(status=status, summary=summary, exit_code=0)


def evaluate(root: Path, output_dir: Path, decisions_path: Path | None) -> GateResult:
    inputs = discover_inputs(root)
    paths = output_paths(output_dir.resolve())
    protected = protected_files(inputs, output_dir)
    before = hash_inventory(protected, root)

    _, active_rows, candidate_rows, baseline = validate_baseline(inputs)
    queue = baseline["queue"]
    decision_file = decisions_path.resolve() if decisions_path else paths["decisions"]
    if not decision_file.exists():
        raise GateError(f"Decision file not found: {decision_file}")
    decisions = validate_decisions(decision_file, queue)
    buckets = classify_decisions(decisions)
    status = "WAITING_FOR_ADMIN" if buckets["PENDING"] else "PASS"

    write_csv(paths["queue"], QUEUE_FIELDS, queue)
    write_json(paths["evidence"], evidence_bundle(inputs, queue, candidate_rows))
    calls = calls_coverage(root, output_dir)
    write_json(paths["calls"], calls)

    fields, approved = public_delta_rows(buckets["APPROVE"], True)
    write_csv(paths["approved"], fields, approved)
    for key, decision in (
        ("returned", "RETURN_FOR_CORRECTION"),
        ("rejected", "REJECT"),
        ("deferred", "DEFER"),
    ):
        _, rendered = public_delta_rows(buckets[decision], False)
        write_csv(paths[key], fields, rendered)

    after = hash_inventory(protected, root)
    unchanged = before == after
    if not unchanged:
        raise GateError("A protected file changed during admin-gate evaluation.")

    summary = {
        "version": VERSION,
        "phase": PHASE,
        "gate_status": status,
        "generated_at": inputs.source_generated_at or None,
        "inputs": {
            "active_catalogue": safe_relative(inputs.active_catalogue, root),
            "candidate_catalogue": safe_relative(inputs.candidate_catalogue, root),
            "upstream_manifest": safe_relative(inputs.upstream_manifest, root),
            "decisions": safe_relative(decision_file, root) if root.resolve() in decision_file.parents else str(decision_file),
        },
        "counts": {
            "active_raw_rows": len(active_rows),
            "candidate_raw_rows": len(candidate_rows),
            "active_dashboard_schemes": 53,
            "candidate_dashboard_schemes": 55,
            "material_delta": len(queue),
            "review_queue": len(queue),
            "approved": len(buckets["APPROVE"]),
            "returned": len(buckets["RETURN_FOR_CORRECTION"]),
            "rejected": len(buckets["REJECT"]),
            "deferred": len(buckets["DEFER"]),
            "pending": len(buckets["PENDING"]),
            "verified_meity_current_calls": calls["verified_current_call_count"],
            "public_application_buttons": application_button_count(queue),
        },
        "targets": {
            "sasact_queued": any(row["master_id"] == SASACT_ID for row in queue),
            "genesis_queued": any(row["master_id"] == GENESIS_ID for row in queue),
        },
        "integrity": {
            "active_catalogue_unchanged": unchanged,
            "publication_current_unchanged": unchanged,
            "database_unchanged": unchanged,
            "dashboard_unchanged": unchanged,
            "publication_performed": False,
            "database_writes_performed": False,
            "network_requests_performed": False,
        },
        "calls_coverage_status": calls["coverage_status"],
    }
    write_json(paths["summary"], summary)
    write_json(paths["gate"], summary)
    write_json(paths["protected"], {"version": VERSION, "before": before, "after": after, "all_unchanged": unchanged})
    generated = [path for name, path in paths.items() if name != "manifest"]
    write_manifest(paths["manifest"], root, status, generated, inputs.source_generated_at)

    print_summary(summary, inputs, paths)
    return GateResult(status=status, summary=summary, exit_code=0)


def print_summary(summary: dict[str, Any], inputs: Inputs, paths: dict[str, Path]) -> None:
    counts = summary["counts"]
    targets = summary["targets"]
    integrity = summary["integrity"]
    print()
    print("SSIP v3.4.3.7 — MeitY Admin Verification Gate")
    print("----------------------------------------------------")
    print(f"Gate status:                     {summary['gate_status']}")
    print(f"Active source file:              {inputs.active_catalogue}")
    print(f"Candidate source file:           {inputs.candidate_catalogue}")
    print(f"Active raw rows:                 {counts['active_raw_rows']}")
    print(f"Candidate raw rows:              {counts['candidate_raw_rows']}")
    print(f"Active dashboard schemes:        {counts['active_dashboard_schemes']}")
    print(f"Candidate dashboard schemes:     {counts['candidate_dashboard_schemes']}")
    print(f"Material delta count:            {counts['material_delta']}")
    print(f"MeitY review queue count:        {counts['review_queue']}")
    print(f"SASACT queued:                   {targets['sasact_queued']}")
    print(f"GENESIS queued:                  {targets['genesis_queued']}")
    print(f"Approved count:                  {counts['approved']}")
    print(f"Returned count:                  {counts['returned']}")
    print(f"Rejected count:                  {counts['rejected']}")
    print(f"Deferred count:                  {counts['deferred']}")
    print(f"Pending count:                   {counts['pending']}")
    print(f"Verified MeitY current calls:    {counts['verified_meity_current_calls']}")
    print(f"Public application buttons:      {counts['public_application_buttons']}")
    print(f"Active catalogue unchanged:      {integrity['active_catalogue_unchanged']}")
    print(f"Publication current unchanged:   {integrity['publication_current_unchanged']}")
    print(f"Database unchanged:              {integrity['database_unchanged']}")
    print(f"Final gate status:               {summary['gate_status']}")
    print()
    print(f"Decision template: {paths['decisions']}")
    print(f"Summary:           {paths['summary']}")


def fixture_row(master_id: str, name: str, source: str = "MeitY Startup Hub") -> dict[str, str]:
    return {
        "master_id": master_id,
        "canonical_name": name,
        "source": source,
        "ministry": "Ministry of Electronics and Information Technology (MeitY)",
        "record_kind": "SCHEME",
        "official_page_url": f"https://msh.meity.gov.in/schemes/{name.casefold()}",
        "programme_status": "SCHEME_INFORMATION_AVAILABLE",
        "application_status": "APPLICATION_STATUS_REQUIRES_VERIFICATION",
        "application_url": "NO_CURRENT_APPLICATION_ROUTE",
        "objective": f"Objective for {name}",
        "eligibility": "Eligible startups",
        "benefits": "Support",
        "confidence": "0.98",
    }


def build_self_test_fixture(root: Path) -> None:
    active_path = root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
    candidate_path = root / "data/catalogue_preview/v3_4_3_4/catalogue_preview_v3_4_3_4.csv"
    output = root / "data/departments/meity/v3_4_3_4"
    output.mkdir(parents=True, exist_ok=True)
    fields = list(fixture_row("x", "x"))
    active = [fixture_row(f"active-{index:03d}", f"Active {index}", source="DST") for index in range(139)]
    candidate = active + [fixture_row(SASACT_ID, "SASACT"), fixture_row(GENESIS_ID, "GENESIS")]
    write_csv(active_path, fields, active)
    write_csv(candidate_path, fields, candidate)

    summary = {
        "version": UPSTREAM_VERSION,
        "release_readiness_status": "PASS",
        "generated_at": "2026-07-13T00:00:00+00:00",
        "active_catalogue": safe_relative(active_path, root),
        "candidate_catalogue": safe_relative(candidate_path, root),
    }
    validation = {
        "version": UPSTREAM_VERSION,
        "validation_status": "PASS",
        "counts": {"active_main_visible": 53, "candidate_main_visible": 55},
    }
    summary_path = output / "meity_release_readiness_summary_v3_4_3_4.json"
    validation_path = output / "meity_dashboard_preview_validation_v3_4_3_4.json"
    rows_path = output / "meity_publication_candidate_rows_v3_4_3_4.csv"
    write_json(summary_path, summary)
    write_json(validation_path, validation)
    write_csv(rows_path, fields, candidate[-2:])
    generated = [candidate_path, rows_path, validation_path, summary_path]
    manifest_path = output / "meity_release_readiness_manifest_v3_4_3_4.json"
    write_json(
        manifest_path,
        {
            "version": UPSTREAM_VERSION,
            "release_readiness_status": "PASS",
            "generated_at": "2026-07-13T00:00:00+00:00",
            "outputs": [
                {
                    "path": safe_relative(path, root),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in generated
            ],
        },
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="ssip-meity-gate-") as temp:
        root = Path(temp)
        (root / "scripts").mkdir(parents=True)
        build_self_test_fixture(root)
        output = root / "data/departments/meity/v3_4_3_7"
        initial = prepare(root, output)
        assert initial.status == "WAITING_FOR_ADMIN"
        decision_path = output_paths(output)["decisions"]
        fields, rows = read_csv(decision_path)
        for row in rows:
            row["admin_decision"] = "APPROVE"
            row["admin_name"] = "Self Test Admin"
            row["reviewed_at"] = "2026-07-13T00:00:00+00:00"
        write_csv(decision_path, fields, rows)
        evaluated = evaluate(root, output, decision_path)
        assert evaluated.status == "PASS"
        approved_fields, approved_rows = read_csv(output_paths(output)["approved"])
        assert "publication_eligible" in approved_fields
        assert len(approved_rows) == 2
        assert all(row["publication_eligible"] == "true" for row in approved_rows)
        assert all(row["published"] == "false" for row in approved_rows)
    print("MeitY v3.4.3.7 admin-gate self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=PHASE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--evaluate", action="store_true")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = project_root()
    output_dir = args.output_dir or (root / "data" / "departments" / "meity" / "v3_4_3_7")
    result = evaluate(root, output_dir, args.decisions) if args.evaluate else prepare(root, output_dir)
    if result.status == "FAIL":
        return 2
    if result.status == "WAITING_FOR_ADMIN" and args.strict:
        return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"ADMIN-GATE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"ADMIN-GATE UNEXPECTED ERROR: {exc}", file=sys.stderr)
        raise
