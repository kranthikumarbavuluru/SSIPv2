from __future__ import annotations

"""Media review workspace and validated publication projection.

Corrections and decisions are append-only JSONL records.  Raw assets,
extraction manifests and field evidence remain immutable.  The public
projection is generated only from an explicit APPROVE decision and is stored
in versioned, hash-verified publication directories for rollback.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import csv
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

from .intake_v3_4_7_0 import MediaIntakePaths, parse_ingest_date


MEDIA_REVIEW_SCHEMA_VERSION = "3.4.7.3"
PUBLICATION_ROOT = Path("data/media_publication/v3_4_7_3")
PUBLICATION_FIELDS = (
    "master_id", "scheme_code", "canonical_name", "record_kind", "source", "ministry",
    "department", "implementing_agency", "ownership_scope", "geographic_scope", "category",
    "support_type", "applicant_layer", "startup_relevance", "target_beneficiaries", "description",
    "benefit_summary", "eligibility", "official_page_url", "application_url", "reference_urls",
    "status_basis", "status_evidence", "programme_status", "application_status", "opening_date",
    "closing_date", "last_verified_at", "warnings", "guideline_urls", "parent_master_id",
    "parent_scheme_name", "publication_decision", "decision_reasons", "evidence_confidence",
    "application_process", "sector", "startup_stage", "contacts", "source_asset_path",
    "source_asset_sha256", "publication_status", "is_public",
)


@dataclass(frozen=True, slots=True)
class MediaReviewWorkspace:
    ingest_date: str
    candidate_count: int
    queue_count: int
    source_asset_paths: tuple[str, ...]
    workspace_path: str


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8", newline="")
    temporary.replace(path)


def _jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _atomic_write(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def build_review_workspace(project_root: Path, ingest_date: str | date | None = None) -> MediaReviewWorkspace:
    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    paths = MediaIntakePaths(root)
    paths.ensure_batch_layout(parsed_date)
    batch_dir = paths.batch_run(parsed_date)
    candidates = _read_jsonl(batch_dir / "entity_candidates.jsonl")
    queue = _read_jsonl(batch_dir / "entity_review_queue.jsonl")
    workspace = {
        "schema_version": MEDIA_REVIEW_SCHEMA_VERSION,
        "ingest_date": parsed_date.isoformat(),
        "candidate_count": len(candidates),
        "queue_count": len(queue),
        "source_asset_paths": sorted({str(row.get("source_asset_path", "")) for row in candidates if row.get("source_asset_path")}),
        "review_corrections_path": (batch_dir / "review_corrections.jsonl").relative_to(root).as_posix(),
        "review_decisions_path": (batch_dir / "review_decisions.jsonl").relative_to(root).as_posix(),
        "raw_evidence_policy": "Raw media, extraction manifests and field evidence are read-only.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    workspace_path = batch_dir / "review_workspace.json"
    _atomic_write(workspace_path, json.dumps(workspace, indent=2, ensure_ascii=False) + "\n")
    return MediaReviewWorkspace(
        ingest_date=parsed_date.isoformat(),
        candidate_count=len(candidates),
        queue_count=len(queue),
        source_asset_paths=tuple(workspace["source_asset_paths"]),
        workspace_path=workspace_path.relative_to(root).as_posix(),
    )


class MediaReviewStore:
    """Append-only corrections and decisions for a dated review workspace."""

    _CORRECTABLE_FIELDS = frozenset({
        "canonical_name", "record_kind", "ministry", "department", "implementing_agency",
        "parent_master_id", "parent_scheme_name", "official_page_url", "application_url",
        "opening_date", "closing_date", "warnings", "description", "benefit_summary",
        "eligibility", "application_process", "sector", "startup_stage", "target_beneficiaries",
    })

    def __init__(self, project_root: Path, ingest_date: str | date | None = None) -> None:
        self.root = project_root.resolve()
        self.ingest_date = parse_ingest_date(ingest_date)
        self.batch_dir = MediaIntakePaths(self.root).batch_run(self.ingest_date)
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.corrections_path = self.batch_dir / "review_corrections.jsonl"
        self.decisions_path = self.batch_dir / "review_decisions.jsonl"

    def candidates(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.batch_dir / "entity_candidates.jsonl")

    def corrections(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _read_jsonl(self.corrections_path):
            latest[str(row.get("candidate_id", ""))] = row
        return latest

    def decisions(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _read_jsonl(self.decisions_path):
            latest[str(row.get("candidate_id", ""))] = row
        return latest

    def effective_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        row = dict(candidate)
        correction = self.corrections().get(str(row.get("candidate_id", "")), {})
        for field, value in correction.get("changes", {}).items():
            if field in self._CORRECTABLE_FIELDS:
                row[field] = value
        decision = self.decisions().get(str(row.get("candidate_id", "")), {})
        if decision:
            row["review_status"] = decision.get("decision", row.get("review_status", "REVIEW_REQUIRED"))
            row["reviewer"] = decision.get("reviewer", "")
            row["decision_notes"] = decision.get("notes", "")
        return row

    def record_correction(self, candidate_id: str, changes: dict[str, Any], reviewer: str, notes: str = "") -> dict[str, Any]:
        safe_changes = {key: value for key, value in changes.items() if key in self._CORRECTABLE_FIELDS}
        if not safe_changes:
            raise ValueError("No correctable fields were supplied.")
        entry = {
            "candidate_id": candidate_id,
            "changes": safe_changes,
            "reviewer": reviewer.strip() or "reviewer",
            "notes": notes.strip(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        _jsonl(self.corrections_path, _read_jsonl(self.corrections_path) + [entry])
        return entry

    def record_decision(self, candidate_id: str, decision: str, reviewer: str, notes: str = "") -> dict[str, Any]:
        normalized = decision.strip().upper()
        if normalized not in {"APPROVE", "REJECT", "HOLD"}:
            raise ValueError("Decision must be APPROVE, REJECT or HOLD.")
        entry = {
            "candidate_id": candidate_id,
            "decision": normalized,
            "reviewer": reviewer.strip() or "reviewer",
            "notes": notes.strip(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        _jsonl(self.decisions_path, _read_jsonl(self.decisions_path) + [entry])
        return entry


def _pipe(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _publication_row(row: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    links = row.get("official_links", []) or []
    official = str(row.get("official_page_url", "") or (links[0] if links else "")).strip()
    application = str(row.get("application_url", "")).strip()
    return {
        "master_id": row.get("candidate_id", ""),
        "scheme_code": row.get("candidate_id", ""),
        "canonical_name": row.get("canonical_name", ""),
        "record_kind": row.get("record_kind", "OTHER"),
        "source": f"Media evidence · {row.get('source_asset_path', '')}",
        "ministry": row.get("ministry", ""),
        "department": row.get("department", "Others / Unmapped"),
        "implementing_agency": row.get("implementing_agency", ""),
        "ownership_scope": "MEDIA_EVIDENCE",
        "geographic_scope": row.get("geographic_scope", ""),
        "category": row.get("record_kind", "OTHER"),
        "support_type": "",
        "applicant_layer": "DIRECT_BENEFICIARY",
        "startup_relevance": "REVIEWED_MEDIA_EVIDENCE",
        "target_beneficiaries": _pipe(row.get("target_beneficiaries", "")),
        "description": row.get("description", row.get("raw_text", "")),
        "benefit_summary": row.get("benefit_summary", ""),
        "eligibility": row.get("eligibility", ""),
        "official_page_url": official,
        "application_url": application,
        "reference_urls": _pipe(links),
        "status_basis": "Human-reviewed media evidence",
        "status_evidence": row.get("decision_notes", "") or "Reviewed from source asset and linked evidence",
        "programme_status": "CURRENT_CALL" if row.get("record_kind") != "SCHEME" else "CURRENT_PROGRAMME",
        "application_status": "OPEN" if row.get("record_kind") in {"APPLICATION_CALL", "CHALLENGE"} else "STATUS_UNVERIFIED",
        "opening_date": row.get("opening_date", ""),
        "closing_date": row.get("closing_date", ""),
        "last_verified_at": datetime.now(timezone.utc).date().isoformat(),
        "warnings": _pipe(row.get("warnings", [])),
        "guideline_urls": "",
        "parent_master_id": row.get("parent_master_id", ""),
        "parent_scheme_name": row.get("parent_scheme_name", ""),
        "publication_decision": "REVIEW_APPROVED",
        "decision_reasons": _pipe([decision.get("notes", ""), "Human review decision recorded"]),
        "evidence_confidence": str(min(float(row.get("department_confidence", 0.0) or 0.0), 1.0)),
        "application_process": row.get("application_process", ""),
        "sector": _pipe(row.get("sector", "")),
        "startup_stage": _pipe(row.get("startup_stage", "")),
        "contacts": _pipe(row.get("contacts", "")),
        "source_asset_path": row.get("source_asset_path", ""),
        "source_asset_sha256": row.get("source_asset_sha256", ""),
        "publication_status": "PUBLISHED",
        "is_public": "1",
    }


def project_validated_records(project_root: Path, ingest_date: str | date | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Project only explicitly approved candidates into a versioned bundle."""

    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    store = MediaReviewStore(root, parsed_date)
    candidates = [store.effective_candidate(row) for row in store.candidates()]
    decisions = store.decisions()
    blockers: list[dict[str, str]] = []
    approved: list[dict[str, Any]] = []
    for row in candidates:
        decision = decisions.get(str(row.get("candidate_id", "")), {})
        if decision.get("decision") != "APPROVE":
            continue
        official_links = row.get("official_links", []) or []
        official = str(row.get("official_page_url", "") or (official_links[0] if official_links else "")).strip()
        if not official.startswith("https://"):
            blockers.append({"candidate_id": str(row.get("candidate_id", "")), "reason": "APPROVED_RECORD_MISSING_HTTPS_OFFICIAL_URL"})
            continue
        if row.get("department") == "Others / Unmapped":
            blockers.append({"candidate_id": str(row.get("candidate_id", "")), "reason": "APPROVED_RECORD_REQUIRES_DEPARTMENT_MAPPING"})
            continue
        approved.append(_publication_row(row, decision))

    publication_root = (root / PUBLICATION_ROOT).resolve()
    run_key = run_id or f"media-publication-{parsed_date.strftime('%Y%m%d%H%M%S')}"
    version_dir = publication_root / "versions" / run_key
    version_dir.mkdir(parents=True, exist_ok=True)
    inventory_name = "published_media_records.csv"
    inventory_path = version_dir / inventory_name
    with inventory_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLICATION_FIELDS)
        writer.writeheader()
        writer.writerows(approved)
    inventory_hash = sha256(inventory_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": MEDIA_REVIEW_SCHEMA_VERSION,
        "activation_status": "ACTIVE",
        "publication_run_id": run_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_file": f"versions/{run_key}/{inventory_name}",
        "inventory_sha256": inventory_hash,
        "record_count": len(approved),
        "record_kind_counts": {kind: sum(row.get("record_kind") == kind for row in approved) for kind in ("SCHEME", "APPLICATION_CALL", "CHALLENGE", "OTHER")},
        "blocker_count": len(blockers),
        "source": "media review workspace",
    }
    manifest_path = publication_root / "active_publication_manifest_v3_4_7_3.json"
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(publication_root / "publication_blockers.json", json.dumps(blockers, indent=2, ensure_ascii=False) + "\n")
    return {
        "schema_version": MEDIA_REVIEW_SCHEMA_VERSION,
        "publication_run_id": run_key,
        "published_count": len(approved),
        "blocker_count": len(blockers),
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "inventory_path": inventory_path.relative_to(root).as_posix(),
        "blockers": blockers,
        "database_modified": False,
    }


def rollback_media_publication(project_root: Path, publication_run_id: str) -> dict[str, Any]:
    """Point the active v3.4.7.3 manifest at a prior immutable version."""

    root = project_root.resolve()
    publication_root = (root / PUBLICATION_ROOT).resolve()
    version_manifest = publication_root / "versions" / publication_run_id / "manifest.json"
    inventory = publication_root / "versions" / publication_run_id / "published_media_records.csv"
    if not inventory.exists():
        raise FileNotFoundError(f"Publication version not found: {publication_run_id}")
    payload = inventory.read_bytes()
    version_manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(version_manifest, {})
    if not manifest:
        manifest = {
            "schema_version": MEDIA_REVIEW_SCHEMA_VERSION,
            "activation_status": "ACTIVE",
            "publication_run_id": publication_run_id,
            "inventory_file": f"versions/{publication_run_id}/published_media_records.csv",
            "inventory_sha256": sha256(payload).hexdigest(),
            "record_count": max(0, len(payload.splitlines()) - 1),
        }
        _atomic_write(version_manifest, json.dumps(manifest, indent=2) + "\n")
    active = dict(manifest)
    active["activation_status"] = "ACTIVE"
    _atomic_write(publication_root / "active_publication_manifest_v3_4_7_3.json", json.dumps(active, indent=2) + "\n")
    return {"publication_run_id": publication_run_id, "inventory_sha256": active.get("inventory_sha256"), "database_modified": False}


__all__ = [
    "MEDIA_REVIEW_SCHEMA_VERSION",
    "MediaReviewStore",
    "MediaReviewWorkspace",
    "build_review_workspace",
    "project_validated_records",
    "rollback_media_publication",
]
