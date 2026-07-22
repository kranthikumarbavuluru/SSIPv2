from __future__ import annotations

"""Evidence-linked entity and department intelligence for media candidates."""

from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .intake_v3_4_7_0 import MediaIntakePaths, parse_ingest_date


MEDIA_ENTITY_SCHEMA_VERSION = "3.4.7.2"


@dataclass(frozen=True, slots=True)
class DepartmentRule:
    department: str
    ministry: str
    aliases: tuple[str, ...]
    agency: str = ""


DEPARTMENT_RULES: tuple[DepartmentRule, ...] = (
    DepartmentRule(
        "Department of Science and Technology (DST)",
        "Ministry of Science and Technology",
        ("department of science and technology", "dst", "nidhi", "anrfs"),
    ),
    DepartmentRule(
        "Ministry of Electronics and Information Technology (MeitY)",
        "Ministry of Electronics and Information Technology",
        ("meity", "meit y", "electronics and information technology"),
    ),
    DepartmentRule(
        "Department for Promotion of Industry and Internal Trade (DPIIT)",
        "Ministry of Commerce and Industry",
        ("dpiit", "promotion of industry and internal trade", "startup india"),
    ),
    DepartmentRule(
        "Department of Biotechnology (DBT)",
        "Ministry of Science and Technology",
        ("department of biotechnology", "dbt", "birac"),
        agency="Biotechnology Industry Research Assistance Council (BIRAC)",
    ),
    DepartmentRule(
        "Ministry of Micro, Small and Medium Enterprises (MSME)",
        "Ministry of Micro, Small and Medium Enterprises",
        ("ministry of micro", "msme", "mymsme", "small and medium enterprises"),
    ),
    DepartmentRule(
        "Information Technology Electronics & Communication (ITE&C) Department Government of Andhra Pradesh",
        "Government of Andhra Pradesh",
        ("ite&c", "itec", "information technology electronics", "ratan tata innovation hub", "rtih", "andhra pradesh"),
    ),
)


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
    output: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                output.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return output


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _joined_text(extraction: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            extraction.get("raw_text", ""),
            " ".join(extraction.get("links", [])),
            " ".join(extraction.get("qr_values", [])),
            " ".join(str(item.get("value", "")) for item in extraction.get("barcodes", []) if isinstance(item, dict)),
            extraction.get("relative_path", ""),
        )
        if value
    ).casefold()


def classify_record_kind(text: str) -> tuple[str, float, str]:
    normalized = _normalise(text)
    if any(token in normalized for token in ("challenge", "competition", "hackathon", "grand challenge")):
        return "CHALLENGE", 0.9, "challenge terminology"
    if any(token in normalized for token in ("call for", "application call", "applications", "applications open", "apply now", "last date", "deadline", "grant call")):
        return "APPLICATION_CALL", 0.88, "application-window terminology"
    if any(token in normalized for token in ("scheme", "programme", "program", "mission", "initiative")):
        return "SCHEME", 0.76, "programme identity terminology"
    return "OTHER", 0.35, "no decisive record-kind terminology"


def map_department(text: str) -> tuple[DepartmentRule, float, str] | None:
    normalized = _normalise(text)
    best: tuple[DepartmentRule, float, str] | None = None
    for rule in DEPARTMENT_RULES:
        matches = [alias for alias in rule.aliases if _normalise(alias) in normalized]
        if not matches:
            continue
        confidence = min(0.98, 0.58 + 0.11 * len(matches))
        candidate = (rule, confidence, ", ".join(matches))
        if best is None or candidate[1] > best[1]:
            best = candidate
    return best


def _candidate_id(asset_id: str, canonical_name: str, department: str) -> str:
    seed = f"{asset_id}:{_normalise(canonical_name)}:{_normalise(department)}".encode("utf-8")
    return f"media-candidate-{hashlib.sha256(seed).hexdigest()[:20]}"


def _canonical_name(extraction: dict[str, Any]) -> str:
    text = " ".join(str(extraction.get("raw_text", "")).split())
    if text:
        return text[:140]
    filename = Path(str(extraction.get("relative_path", "media"))).stem
    return filename.replace("_", " ").replace("-", " ").strip().title()


def _load_publication_seeds(project_root: Path) -> dict[str, dict[str, str]]:
    """Use already-governed media rows as traceable seeds for reruns.

    This keeps a daily rerun useful when optional OCR/QR engines are absent:
    known source assets retain their reviewed mapping, while new assets still
    require extraction and review.
    """

    output: dict[str, dict[str, str]] = {}
    for inventory in (
        project_root / "data/media_publication/v3_4_7_0/published_media_records_v3_4_7_0.csv",
        project_root / "data/media_publication/v3_4_7_3/published_media_records.csv",
    ):
        if not inventory.exists():
            continue
        try:
            with inventory.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    path = str(row.get("source_asset_path", "")).strip()
                    if path:
                        output[path] = row
        except OSError:
            continue
    return output


def _parent_hint(extraction: dict[str, Any], text: str) -> tuple[str, str, str]:
    normalized = _normalise(text)
    if "nidhi" in normalized or "ignition grant" in normalized:
        return "dst_programme_nidhi_itbi", "NIDHI Inclusive Technology Business Incubator", "NIDHI terminology in media evidence"
    if "ratan tata innovation hub" in normalized or "rtih" in normalized:
        return "", "", "RTIH is an implementing ecosystem; no parent programme asserted"
    return "", "", "No parent identity asserted by extracted evidence"


def build_entity_candidate(extraction: dict[str, Any], seed: dict[str, str] | None = None) -> dict[str, Any]:
    seed = seed or {}
    text = " ".join(
        value
        for value in (
            _joined_text(extraction),
            seed.get("canonical_name", ""),
            seed.get("department", ""),
            seed.get("ministry", ""),
            seed.get("record_kind", ""),
            seed.get("parent_scheme_name", ""),
            seed.get("description", ""),
        )
        if value
    )
    name = str(seed.get("canonical_name", "")).strip() or _canonical_name(extraction)
    kind, kind_confidence, kind_basis = classify_record_kind(text)
    mapped = map_department(text)
    if mapped:
        rule, department_confidence, department_basis = mapped
        department = rule.department
        ministry = rule.ministry
        agency = rule.agency
        mapping_status = "MAPPED"
    else:
        department = str(seed.get("department", "")).strip() or "Others / Unmapped"
        ministry = str(seed.get("ministry", "")).strip() or "Others / Unmapped"
        agency = str(seed.get("implementing_agency", "")).strip()
        department_confidence = 0.0
        department_basis = "No configured department alias matched"
        mapping_status = "UNMAPPED"
    parent_id, parent_name, parent_basis = _parent_hint(extraction, text)
    parent_id = parent_id or str(seed.get("parent_master_id", "")).strip()
    parent_name = parent_name or str(seed.get("parent_scheme_name", "")).strip()
    if parent_name and not parent_id:
        parent_basis = "Parent identity carried from governed media publication seed"
    candidate_id = _candidate_id(str(extraction.get("asset_id", "")), name, department)
    evidence_ids = list(extraction.get("evidence_ids", []))
    evidence_ids.append(f"mapping:{candidate_id}:department")
    evidence_ids.append(f"mapping:{candidate_id}:record_kind")
    warnings = list(extraction.get("warnings", []))
    if mapping_status == "UNMAPPED":
        warnings.append("DEPARTMENT_UNMAPPED")
    if kind == "OTHER":
        warnings.append("RECORD_KIND_REVIEW_REQUIRED")
    seed_links = [seed.get("official_page_url", "")] + [item.strip() for item in seed.get("reference_urls", "").split("|") if item.strip()]
    return {
        "schema_version": MEDIA_ENTITY_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "asset_id": extraction.get("asset_id", ""),
        "source_asset_path": extraction.get("relative_path", ""),
        "source_asset_sha256": extraction.get("source_sha256", ""),
        "canonical_name": name,
        "record_kind": kind,
        "record_kind_confidence": kind_confidence,
        "record_kind_basis": kind_basis,
        "department": department,
        "ministry": ministry,
        "implementing_agency": agency,
        "department_confidence": department_confidence,
        "department_mapping_basis": department_basis,
        "department_mapping_status": mapping_status,
        "parent_master_id": parent_id,
        "parent_scheme_name": parent_name,
        "parent_relationship_basis": parent_basis,
        "official_links": list(dict.fromkeys(list(extraction.get("links", [])) + [value for value in seed_links if value])),
        "qr_values": extraction.get("qr_values", []),
        "barcodes": extraction.get("barcodes", []),
        "raw_text": extraction.get("raw_text", ""),
        "language": extraction.get("language", "und"),
        "evidence_ids": sorted(set(evidence_ids)),
        "warnings": sorted(set(warnings + [value for value in str(seed.get("warnings", "")).split("|") if value])),
        "review_status": "REVIEW_REQUIRED",
        "publication_decision": "HOLD",
        "publication_status": "UNPUBLISHED",
        "is_public": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _candidate_duplicate_key(row: dict[str, Any]) -> str:
    return "|".join((_normalise(str(row.get("canonical_name", ""))), _normalise(str(row.get("department", "")))))


def build_entity_candidates(project_root: Path, ingest_date: str | date | None = None) -> dict[str, Any]:
    """Build evidence-linked candidates and a duplicate-aware review queue."""

    root = project_root.resolve()
    parsed_date = parse_ingest_date(ingest_date)
    paths = MediaIntakePaths(root)
    paths.ensure_batch_layout(parsed_date)
    batch_dir = paths.batch_run(parsed_date)
    extractions = _read_jsonl(batch_dir / "extraction_manifest.jsonl")
    seeds = _load_publication_seeds(root)
    candidates = [
        build_entity_candidate(row, seeds.get(str(row.get("relative_path", "")).strip()))
        for row in extractions
    ]
    seen: dict[str, str] = {}
    duplicate_count = 0
    queue: list[dict[str, Any]] = []
    for row in candidates:
        key = _candidate_duplicate_key(row)
        prior = seen.get(key)
        if prior:
            row["duplicate_of"] = prior
            row["warnings"] = sorted(set(row.get("warnings", []) + ["POSSIBLE_DUPLICATE"]))
            duplicate_count += 1
        else:
            seen[key] = row["candidate_id"]
        if row.get("review_status") != "APPROVED" or row.get("department_mapping_status") == "UNMAPPED" or row.get("warnings"):
            queue.append(row)
    candidates.sort(key=lambda row: row.get("candidate_id", ""))
    queue.sort(key=lambda row: row.get("candidate_id", ""))
    candidate_path = batch_dir / "entity_candidates.jsonl"
    queue_path = batch_dir / "entity_review_queue.jsonl"
    _jsonl(candidate_path, candidates)
    _jsonl(queue_path, queue)
    report = {
        "schema_version": MEDIA_ENTITY_SCHEMA_VERSION,
        "run_id": f"media-entity-{parsed_date.strftime('%Y%m%d')}",
        "ingest_date": parsed_date.isoformat(),
        "candidate_count": len(candidates),
        "review_queue_count": len(queue),
        "mapped_count": sum(row.get("department_mapping_status") == "MAPPED" for row in candidates),
        "unmapped_count": sum(row.get("department_mapping_status") == "UNMAPPED" for row in candidates),
        "duplicate_count": duplicate_count,
        "record_kind_counts": {
            kind: sum(row.get("record_kind") == kind for row in candidates)
            for kind in ("SCHEME", "APPLICATION_CALL", "CHALLENGE", "OTHER")
        },
        "candidate_path": candidate_path.relative_to(root).as_posix(),
        "review_queue_path": queue_path.relative_to(root).as_posix(),
        "database_modified": False,
    }
    _atomic_write(batch_dir / "entity_report.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


__all__ = [
    "DEPARTMENT_RULES",
    "MEDIA_ENTITY_SCHEMA_VERSION",
    "build_entity_candidate",
    "build_entity_candidates",
    "classify_record_kind",
    "map_department",
]
