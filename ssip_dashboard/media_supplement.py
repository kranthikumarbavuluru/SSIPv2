from __future__ import annotations

"""Governed publication bundle for media-derived scheme and call records.

The media agent writes an immutable, hash-verified inventory after visual and
source review.  The public dashboard reads only the active bundle; it never
publishes directly from an inbox image or from OCR output without a manifest.
"""

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PUBLICATION_DIR = Path("data/media_publication/v3_4_7_0")
MANIFEST_NAME = "active_publication_manifest_v3_4_7_0.json"
PUBLICATION_CANDIDATES = (
    (Path("data/media_publication/v3_4_7_3"), "active_publication_manifest_v3_4_7_3.json"),
    (PUBLICATION_DIR, MANIFEST_NAME),
)


class MediaPublicationError(RuntimeError):
    """Raised when the active media publication bundle fails a gate."""


@dataclass(frozen=True)
class MediaPublication:
    records: tuple[dict[str, Any], ...]
    manifest: dict[str, Any]


def _split(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def _https_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def _official_or_organizer_url(value: str) -> bool:
    return _https_url(value) and not str(value).casefold().endswith(".example.com")


def _record_from_row(row: dict[str, str]) -> dict[str, Any]:
    master_id = row.get("master_id", "").strip()
    source_url = row.get("official_page_url", "").strip()
    if not master_id:
        raise MediaPublicationError("Media publication row has a blank master_id.")
    if row.get("publication_decision", "").strip() != "AUTO_APPROVED":
        raise MediaPublicationError(f"Media record is not approved: {master_id}")
    if row.get("publication_status", "").strip().upper() != "PUBLISHED":
        raise MediaPublicationError(f"Media record is not published: {master_id}")
    if row.get("is_public", "").strip() != "1":
        raise MediaPublicationError(f"Media record is not public: {master_id}")
    if not _official_or_organizer_url(source_url):
        raise MediaPublicationError(f"Unsafe media source URL: {source_url}")

    application_url = row.get("application_url", "").strip()
    if application_url and not _official_or_organizer_url(application_url):
        raise MediaPublicationError(f"Unsafe media application URL: {application_url}")

    reference_urls = _split(row.get("reference_urls", ""))
    if not all(_official_or_organizer_url(url) for url in reference_urls):
        raise MediaPublicationError(f"Unsafe media reference URL: {master_id}")

    return {
        "master_id": master_id,
        "scheme_name": row.get("canonical_name", "").strip(),
        "source": row.get("source", "Media evidence").strip(),
        "ministry": row.get("ministry", "").strip(),
        "department": row.get("department", "").strip(),
        "implementing_agency": row.get("implementing_agency", "").strip(),
        "parent_master_id": row.get("parent_master_id", "").strip(),
        "parent_scheme_name": row.get("parent_scheme_name", "").strip(),
        "applicant_layer": row.get("applicant_layer", "DIRECT_BENEFICIARY").strip(),
        "implementation_role": row.get("ownership_scope", "").strip(),
        "status_basis": row.get("status_basis", "").strip(),
        "status_evidence": row.get("status_evidence", "").strip(),
        "last_verified_at": row.get("last_verified_at", "").strip(),
        "record_kind": row.get("record_kind", "APPLICATION_CALL").strip(),
        "programme_status": row.get("programme_status", "CURRENT_CALL").strip(),
        "application_status": row.get("application_status", "STATUS_UNVERIFIED").strip(),
        "geographic_scope": row.get("geographic_scope", "").strip(),
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "APPLICATION_CALLS",
        "publication_status": "PUBLISHED",
        "is_public": 1,
        "current_location": "MEDIA_ACTIVE_PUBLICATION",
        "current_review_status": "AUTOMATED_GATES_PASSED",
        "current_decision": "APPROVED_FOR_PUBLICATION",
        "official_page_url": source_url,
        "application_url": application_url,
        "opening_date": row.get("opening_date", "").strip(),
        "closing_date": row.get("closing_date", "").strip(),
        "currency": "INR",
        "funding_maximum": int(row["funding_maximum"]) if row.get("funding_maximum", "").strip() else None,
        "objectives": _split(row.get("description", "")),
        "eligibility": _split(row.get("eligibility", "")),
        "benefits": _split(row.get("benefit_summary", "")),
        "application_process": _split(row.get("application_process", "")),
        "sectors": _split(row.get("sector", "")),
        "scheme_types": _split("|".join(filter(None, (row.get("category", ""), row.get("support_type", ""))))),
        "target_beneficiaries": _split(row.get("target_beneficiaries", "")),
        "startup_stage": _split(row.get("startup_stage", "")),
        "guideline_urls": _split(row.get("guideline_urls", "")),
        "reference_urls": reference_urls,
        "contacts": _split(row.get("contacts", "")),
        "warnings": _split(row.get("warnings", "")),
        "recommended_actions": _split(row.get("recommended_actions", "")),
        "decision_reasons": _split(row.get("decision_reasons", "")),
        "last_updated": row.get("last_verified_at", "").strip(),
        "search_blob": " ".join(
            value.strip()
            for value in (
                row.get("scheme_code", ""),
                row.get("canonical_name", ""),
                row.get("description", ""),
                row.get("benefit_summary", ""),
                row.get("department", ""),
                row.get("implementing_agency", ""),
                row.get("sector", ""),
                row.get("target_beneficiaries", ""),
            )
            if value.strip()
        ).casefold(),
    }


def load_active_media_publication(project_root: Path) -> MediaPublication:
    directory: Path | None = None
    manifest_path: Path | None = None
    for candidate_dir, candidate_manifest in PUBLICATION_CANDIDATES:
        resolved_dir = (project_root / candidate_dir).resolve()
        resolved_manifest = resolved_dir / candidate_manifest
        if resolved_manifest.exists():
            if candidate_dir != PUBLICATION_DIR:
                try:
                    candidate_payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    candidate_payload = {}
                if int(candidate_payload.get("record_count", 0) or 0) == 0:
                    # An empty review projection must not blank a known-good
                    # fallback bundle before any records are approved.
                    continue
            directory = resolved_dir
            manifest_path = resolved_manifest
            break
    if directory is None or manifest_path is None:
        return MediaPublication(records=(), manifest={"status": "NOT_CONFIGURED"})

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaPublicationError(f"Cannot read media publication manifest: {manifest_path}") from exc
    if manifest.get("activation_status") != "ACTIVE":
        return MediaPublication(records=(), manifest=manifest)

    inventory_name = str(manifest.get("inventory_file", "")).strip()
    inventory_path = (directory / inventory_name).resolve()
    if directory not in inventory_path.parents:
        raise MediaPublicationError("Media inventory path escapes its governed directory.")
    try:
        payload = inventory_path.read_bytes()
    except OSError as exc:
        raise MediaPublicationError(f"Cannot read media inventory: {inventory_path}") from exc
    if sha256(payload).hexdigest() != manifest.get("inventory_sha256"):
        raise MediaPublicationError("Media inventory hash does not match its manifest.")

    rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
    records = tuple(_record_from_row(row) for row in rows)
    master_ids = [record["master_id"] for record in records]
    if not master_ids or len(master_ids) != len(set(master_ids)):
        raise MediaPublicationError("Duplicate or blank master IDs in media publication inventory.")
    if len(records) != int(manifest.get("record_count", -1)):
        raise MediaPublicationError("Media publication record count does not match its manifest.")
    return MediaPublication(records=records, manifest=manifest)
