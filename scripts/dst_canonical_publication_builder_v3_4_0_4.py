#!/usr/bin/env python3
"""
SSIP v3.4.0.4 — DST Canonical Identity Lock and Public Dashboard Adapter

Consumes the corrected permanent DST inventories produced by v3.4.0.3.3.1,
locks stable permanent identities, preserves unresolved/manual targets outside
the public catalogue, and creates dashboard-ready CSV and SQLite outputs.

Safety rules
------------
* Calls, deadlines, cohorts, rounds, results and other time-bound pages cannot
  become canonical permanent identities.
* Generic navigation, category, archive, policy and supporting pages cannot be
  locked or published.
* Canonical IDs are stable and derived from the upstream provisional identity
  (falling back to official URL/name only when required).
* Manual entity-review rows are carried forward but never published.
* Upstream files are read-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

VERSION = "3.4.0.4"
DEPARTMENT_CODE = "DST"
DEPARTMENT_NAME = "Department of Science and Technology"
MINISTRY_NAME = "Ministry of Science and Technology"

UPSTREAM_DIR = Path("data/departments/dst/v3_4_0_3_3_1")
INVENTORY_DIR = Path("data/departments/dst/v3_4_0_3")
OUTPUT_DIR = Path("data/departments/dst/v3_4_0_4")

SCHEMES_INPUT = "dst_final_corrected_schemes_v3_4_0_3_3_1.csv"
PROGRAMMES_INPUT = "dst_final_corrected_programmes_v3_4_0_3_3_1.csv"
MANUAL_REVIEW_INPUT = "dst_manual_entity_review_candidates_v3_4_0_3_3_1.csv"
FINAL_REVIEW_INPUT = "dst_final_unresolved_review_queue_v3_4_0_3_3_1.csv"
UPSTREAM_VALIDATION_INPUT = "dst_calibration_validation_v3_4_0_3_3_1.json"
UPSTREAM_SUMMARY_INPUT = "dst_calibration_summary_v3_4_0_3_3_1.json"

ALIASES_INPUT = "dst_scheme_alias_candidates_v3_4_0_3.csv"
HIERARCHY_INPUT = "dst_programme_hierarchy_candidates_v3_4_0_3.csv"
EVIDENCE_INPUT = "dst_master_source_evidence_v3_4_0_3.csv"

OVERRIDES_INPUT = "dst_identity_curation_overrides_v3_4_0_4.csv"

ENTITY_OUTPUT = "dst_canonical_entity_registry_v3_4_0_4.csv"
SCHEME_OUTPUT = "dst_canonical_scheme_registry_v3_4_0_4.csv"
PROGRAMME_OUTPUT = "dst_canonical_programme_registry_v3_4_0_4.csv"
ALIAS_OUTPUT = "dst_canonical_alias_registry_v3_4_0_4.csv"
RELATIONSHIP_REVIEW_OUTPUT = "dst_relationship_review_queue_v3_4_0_4.csv"
MANUAL_REVIEW_OUTPUT = "dst_manual_entity_review_queue_v3_4_0_4.csv"
REJECTED_OUTPUT = "dst_identity_lock_rejections_v3_4_0_4.csv"
PUBLICATION_OUTPUT = "dst_publication_catalogue_v3_4_0_4.csv"
PUBLICATION_JSON_OUTPUT = "dst_publication_catalogue_v3_4_0_4.json"
DATABASE_OUTPUT = "ssip_public_preview_v3_4_0_4.db"
AUDIT_OUTPUT = "dst_identity_lock_audit_v3_4_0_4.csv"
VALIDATION_OUTPUT = "dst_canonical_validation_v3_4_0_4.json"
SUMMARY_OUTPUT = "dst_canonical_summary_v3_4_0_4.json"

ENTITY_FIELDS = [
    "master_id", "department_code", "ministry", "department", "entity_type",
    "canonical_name", "official_abbreviation", "canonical_name_normalized",
    "official_source_url", "source_page_id", "source_page_role",
    "upstream_provisional_entity_id", "upstream_identity_confidence",
    "upstream_quality_confidence", "canonical_identity_status",
    "identity_locked", "identity_lock_version", "identity_locked_at",
    "publication_decision", "public_status", "review_flags", "source_version",
]

PUBLICATION_FIELDS = [
    "master_id", "scheme_name", "entity_type", "record_kind", "source",
    "ministry", "department", "programme_status", "application_status",
    "public_status", "official_page_url", "application_url", "guideline_url",
    "objective", "eligibility", "benefits", "funding_summary",
    "application_process", "required_documents", "contact_information",
    "official_abbreviation", "information_completeness", "verification_status",
    "last_verified_date", "identity_lock_version",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "expected_scheme_count": 3,
    "expected_programme_count": 20,
    "require_upstream_ready": True,
    "allowed_domains": ["dst.gov.in", "www.dst.gov.in"],
    "minimum_identity_confidence": 0.45,
    "maximum_canonical_name_length": 220,
    "generic_names": [
        "home", "archive", "about dst", "about us", "introduction", "mandate",
        "vision mission", "schemes", "scheme", "programmes", "programme",
        "schemes programmes", "schemes and programmes", "programmes and initiatives",
        "funding mechanism", "about the schemes", "guidelines", "contact",
        "screen reader access", "accessibility", "site map", "sitemap",
        "national missions", "whats new", "what's new",
    ],
    "blocked_name_terms": [
        "call for proposal", "call for proposals", "applications invited",
        "application invited", "inviting applications", "expression of interest",
        "deadline extension", "last date extended", "corrigendum", "addendum",
        "result of", "selected proposals", "shortlisted", "apply now",
        "submission deadline", "closing date", "open call", "special call",
        "joint call", "request for proposal", "recruitment", "vacancy", "tender",
        "press release", "annual report", "budget", "policy 2013",
    ],
    "blocked_url_terms": [
        "/call-for-proposals", "/callforproposals", "/announcement/applications",
        "/corrigendum", "/results", "/recruitment", "/vacancies", "/tenders",
        "/screen-reader-access", "/sitemap", "/archive", "/press-release",
    ],
    "temporary_year_pattern": r"\b(?:19|20)\d{2}\b",
    "publication_status": "SCHEME_INFORMATION_AVAILABLE",
    "application_status": "NO_CURRENT_APPLICATION_WINDOW_VERIFIED",
    "public_status": "Scheme information available",
}


@dataclass
class BuildResult:
    entities: list[dict[str, Any]]
    aliases: list[dict[str, Any]]
    relationship_review: list[dict[str, Any]]
    manual_review: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    publication: list[dict[str, Any]]
    audit: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collapse_ws(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def lower(value: Any) -> str:
    return collapse_ws(value).casefold()


def upper(value: Any) -> str:
    return collapse_ws(value).upper()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(collapse_ws(value))
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    return lower(value) in {"1", "true", "yes", "y", "locked", "approved"}


def first_value(row: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = collapse_ws(row.get(name))
        if value:
            return value
    return ""


def stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(collapse_ws(part) for part in parts if collapse_ws(part))
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def normalize_name(value: str) -> str:
    text = html.unescape(collapse_ws(value)).casefold().replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_url(value: str) -> str:
    value = collapse_ws(value)
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    scheme = (parts.scheme or "https").casefold()
    netloc = parts.netloc.casefold()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def read_csv(path: Path, required: bool = True) -> list[dict[str, str]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return []
    if path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required input not found: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    materialized = [dict(row) for row in rows]
    if fields is None:
        fields_list: list[str] = []
        seen: set[str] = set()
        for row in materialized:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields_list.append(key)
        fields = fields_list
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not fields:
        tmp.write_text("", encoding="utf-8")
    else:
        with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(materialized)
    os.replace(tmp, path)


def load_config(path: Path | None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path and path.exists():
        supplied = read_json(path)
        config.update(supplied)
    return config


def load_overrides(path: Path | None) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    by_id: dict[str, dict[str, str]] = {}
    by_url: dict[str, dict[str, str]] = {}
    if not path or not path.exists() or path.stat().st_size == 0:
        return by_id, by_url
    for row in read_csv(path, required=False):
        provisional_id = first_value(row, "provisional_entity_id", "upstream_provisional_entity_id")
        source_url = normalize_url(first_value(row, "official_source_url", "source_url"))
        if provisional_id:
            by_id[provisional_id] = row
        if source_url:
            by_url[source_url] = row
    return by_id, by_url


def is_allowed_domain(url: str, config: Mapping[str, Any]) -> bool:
    try:
        host = urlsplit(url).netloc.casefold()
    except ValueError:
        return False
    return host in {lower(x) for x in config.get("allowed_domains", [])}


def safety_reasons(name: str, url: str, config: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    normalized = normalize_name(name)
    if not name:
        reasons.append("MISSING_CANONICAL_NAME")
    if len(name) > int(config.get("maximum_canonical_name_length", 220)):
        reasons.append("CANONICAL_NAME_TOO_LONG")
    generic = {normalize_name(x) for x in config.get("generic_names", [])}
    if normalized in generic:
        reasons.append("GENERIC_OR_NAVIGATION_NAME")
    name_l = f" {lower(name)} "
    for term in config.get("blocked_name_terms", []):
        if f" {lower(term)} " in name_l or lower(term) in lower(name):
            reasons.append(f"BLOCKED_NAME_TERM:{term}")
            break
    for term in config.get("blocked_url_terms", []):
        if lower(term) in lower(url):
            reasons.append(f"BLOCKED_URL_TERM:{term}")
            break
    year_pattern = str(config.get("temporary_year_pattern") or "")
    if year_pattern and re.search(year_pattern, name):
        transient_context = any(token in lower(name) for token in ["call", "round", "cohort", "application", "deadline", "result"])
        if transient_context:
            reasons.append("TIME_BOUND_IDENTITY_TITLE")
    if not url:
        reasons.append("MISSING_OFFICIAL_SOURCE_URL")
    elif not is_allowed_domain(url, config):
        reasons.append("NON_DST_OFFICIAL_DOMAIN")
    return sorted(set(reasons))


def prepare_entity(
    row: Mapping[str, Any],
    entity_type: str,
    config: Mapping[str, Any],
    override: Mapping[str, Any] | None,
    locked_at: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    provisional_id = first_value(row, "provisional_entity_id", "entity_id", "candidate_id")
    source_url = normalize_url(first_value(row, "official_source_url", "source_url", "final_url", "canonical_url"))
    original_name = first_value(row, "proposed_canonical_name", "proposed_name", "canonical_name_candidate", "source_page_title", "page_title", "title")
    abbreviation = first_value(row, "official_abbreviation_candidate", "official_abbreviation", "abbreviation")
    action = upper(first_value(override or {}, "action", "decision")) or "LOCK"
    canonical_name = first_value(override or {}, "canonical_name", "locked_name") or original_name
    override_type = upper(first_value(override or {}, "entity_type"))
    if override_type in {"SCHEME", "PROGRAMME"}:
        entity_type = override_type
    abbreviation = first_value(override or {}, "official_abbreviation") or abbreviation
    public_status = first_value(override or {}, "public_status") or str(config.get("public_status"))

    audit = {
        "audit_id": stable_id("dst_lock_audit", provisional_id or source_url or original_name, entity_type),
        "upstream_provisional_entity_id": provisional_id,
        "original_name": original_name,
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "official_source_url": source_url,
        "override_action": action,
        "override_applied": bool(override),
        "audit_at": locked_at,
    }

    if action in {"EXCLUDE", "REJECT"}:
        rejection = {
            **audit,
            "rejection_reason": "CURATION_OVERRIDE_EXCLUDED",
            "details": first_value(override or {}, "notes", "reason"),
        }
        audit["outcome"] = "REJECTED"
        return None, rejection, audit
    if action in {"REVIEW", "HOLD"}:
        rejection = {
            **audit,
            "rejection_reason": "CURATION_OVERRIDE_REQUIRES_REVIEW",
            "details": first_value(override or {}, "notes", "reason"),
        }
        audit["outcome"] = "HELD_FOR_REVIEW"
        return None, rejection, audit

    reasons = safety_reasons(canonical_name, source_url, config)
    confidence = max(
        safe_float(first_value(row, "quality_confidence")),
        safe_float(first_value(row, "identity_confidence")),
        safe_float(first_value(row, "confidence")),
    )
    if confidence < safe_float(config.get("minimum_identity_confidence"), 0.45):
        reasons.append("IDENTITY_CONFIDENCE_BELOW_LOCK_THRESHOLD")
    if reasons:
        rejection = {
            **audit,
            "rejection_reason": " | ".join(sorted(set(reasons))),
            "details": first_value(row, "quality_review_flags", "review_flags", "identity_evidence"),
        }
        audit["outcome"] = "REJECTED_BY_SAFETY_GATE"
        return None, rejection, audit

    seed = provisional_id or source_url or canonical_name
    prefix = "dst_scheme" if entity_type == "SCHEME" else "dst_programme"
    master_id = stable_id(prefix, seed)
    entity = {
        "master_id": master_id,
        "department_code": DEPARTMENT_CODE,
        "ministry": MINISTRY_NAME,
        "department": DEPARTMENT_NAME,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "official_abbreviation": abbreviation,
        "canonical_name_normalized": normalize_name(canonical_name),
        "official_source_url": source_url,
        "source_page_id": first_value(row, "source_page_id", "page_id"),
        "source_page_role": first_value(row, "source_page_role", "page_role", "target_page_role"),
        "upstream_provisional_entity_id": provisional_id,
        "upstream_identity_confidence": first_value(row, "identity_confidence", "confidence"),
        "upstream_quality_confidence": first_value(row, "quality_confidence"),
        "canonical_identity_status": "LOCKED_VERIFIED_PERMANENT_IDENTITY",
        "identity_locked": "true",
        "identity_lock_version": VERSION,
        "identity_locked_at": locked_at,
        "publication_decision": "PUBLISH_LIMITED_INFORMATION",
        "public_status": public_status,
        "review_flags": first_value(row, "quality_review_flags", "review_flags"),
        "source_version": "3.4.0.3.3.1",
    }
    audit["outcome"] = "IDENTITY_LOCKED"
    audit["master_id"] = master_id
    return entity, None, audit


def make_publication_row(entity: Mapping[str, Any], source_row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    detailed_fields = {
        "objective": first_value(source_row, "objective", "scheme_objective", "description", "main_text_excerpt"),
        "eligibility": first_value(source_row, "eligibility", "eligibility_criteria"),
        "benefits": first_value(source_row, "benefits", "benefit", "support_provided"),
        "funding_summary": first_value(source_row, "funding_summary", "funding", "financial_assistance"),
        "application_process": first_value(source_row, "application_process", "how_to_apply"),
        "required_documents": first_value(source_row, "required_documents", "documents_required"),
        "contact_information": first_value(source_row, "contact_information", "contact", "contact_details"),
    }
    populated = sum(bool(collapse_ws(v)) for v in detailed_fields.values())
    completeness = round(populated / len(detailed_fields), 2)
    return {
        "master_id": entity["master_id"],
        "scheme_name": entity["canonical_name"],
        "entity_type": entity["entity_type"],
        "record_kind": "SCHEME_OR_PROGRAMME",
        "source": DEPARTMENT_CODE,
        "ministry": MINISTRY_NAME,
        "department": DEPARTMENT_NAME,
        "programme_status": str(config.get("publication_status")),
        "application_status": str(config.get("application_status")),
        "public_status": entity["public_status"],
        "official_page_url": entity["official_source_url"],
        "application_url": first_value(source_row, "application_url", "apply_url"),
        "guideline_url": first_value(source_row, "guideline_url", "guidelines_url"),
        **detailed_fields,
        "official_abbreviation": entity["official_abbreviation"],
        "information_completeness": f"{completeness:.2f}",
        "verification_status": "IDENTITY_VERIFIED_ATTRIBUTES_PENDING" if completeness < 0.70 else "VERIFIED_INFORMATION_AVAILABLE",
        "last_verified_date": date.today().isoformat(),
        "identity_lock_version": VERSION,
    }


def build(
    schemes: list[dict[str, str]],
    programmes: list[dict[str, str]],
    manual_rows: list[dict[str, str]],
    aliases: list[dict[str, str]],
    hierarchy: list[dict[str, str]],
    evidence: list[dict[str, str]],
    config: Mapping[str, Any],
    overrides_by_id: Mapping[str, Mapping[str, Any]],
    overrides_by_url: Mapping[str, Mapping[str, Any]],
) -> BuildResult:
    locked_at = utc_now()
    entities: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    publication: list[dict[str, Any]] = []
    source_by_provisional: dict[str, dict[str, str]] = {}

    for entity_type, rows in (("SCHEME", schemes), ("PROGRAMME", programmes)):
        for row in rows:
            if upper(first_value(row, "record_status")) == "NO_RECORDS":
                continue
            provisional_id = first_value(row, "provisional_entity_id", "entity_id", "candidate_id")
            url = normalize_url(first_value(row, "official_source_url", "source_url", "final_url"))
            override = overrides_by_id.get(provisional_id) or overrides_by_url.get(url)
            entity, rejection, audit_row = prepare_entity(row, entity_type, config, override, locked_at)
            audit.append(audit_row)
            if rejection:
                rejected.append(rejection)
                continue
            assert entity is not None
            entities.append(entity)
            source_by_provisional[provisional_id] = row
            publication.append(make_publication_row(entity, row, config))

    # Exact duplicate protections.
    seen_names: dict[tuple[str, str], str] = {}
    seen_urls: dict[str, str] = {}
    duplicate_ids: set[str] = set()
    for entity in entities:
        key = (entity["entity_type"], entity["canonical_name_normalized"])
        if key in seen_names:
            duplicate_ids.add(entity["master_id"])
            duplicate_ids.add(seen_names[key])
        else:
            seen_names[key] = entity["master_id"]
        url = normalize_url(entity["official_source_url"])
        if url in seen_urls:
            duplicate_ids.add(entity["master_id"])
            duplicate_ids.add(seen_urls[url])
        else:
            seen_urls[url] = entity["master_id"]

    if duplicate_ids:
        kept_entities: list[dict[str, Any]] = []
        kept_publication: list[dict[str, Any]] = []
        for entity in entities:
            if entity["master_id"] in duplicate_ids:
                rejected.append({
                    "master_id": entity["master_id"],
                    "original_name": entity["canonical_name"],
                    "entity_type": entity["entity_type"],
                    "official_source_url": entity["official_source_url"],
                    "rejection_reason": "DUPLICATE_CANONICAL_NAME_OR_URL",
                    "details": "Resolve by curation override before identity lock.",
                })
            else:
                kept_entities.append(entity)
        for row in publication:
            if row["master_id"] not in duplicate_ids:
                kept_publication.append(row)
        entities, publication = kept_entities, kept_publication

    id_map = {
        first_value(entity, "upstream_provisional_entity_id"): entity["master_id"]
        for entity in entities if first_value(entity, "upstream_provisional_entity_id")
    }
    canonical_aliases: list[dict[str, Any]] = []
    alias_seen: set[tuple[str, str]] = set()
    for row in aliases:
        provisional_id = first_value(row, "provisional_entity_id")
        master_id = id_map.get(provisional_id)
        if not master_id:
            continue
        alias_text = first_value(row, "alias_text", "alias", "alternative_name")
        if not alias_text:
            continue
        key = (master_id, normalize_name(alias_text))
        if key in alias_seen:
            continue
        alias_seen.add(key)
        canonical_aliases.append({
            "alias_id": stable_id("dst_alias", master_id, alias_text),
            "master_id": master_id,
            "alias_text": alias_text,
            "alias_type": first_value(row, "alias_type") or "OFFICIAL_VARIANT",
            "alias_confidence": first_value(row, "alias_confidence") or "0.75",
            "source_url": first_value(row, "source_url"),
            "status": "LOCKED_ALIAS",
            "identity_lock_version": VERSION,
        })

    relationship_review: list[dict[str, Any]] = []
    for row in hierarchy:
        child_id = id_map.get(first_value(row, "child_provisional_entity_id", "provisional_entity_id"))
        if not child_id:
            continue
        relationship_review.append({
            "relationship_review_id": stable_id("dst_relationship_review", child_id, first_value(row, "parent_name_text")),
            "child_master_id": child_id,
            "child_name": first_value(row, "child_name"),
            "parent_name_text": first_value(row, "parent_name_text"),
            "relationship_type": first_value(row, "relationship_type") or "POSSIBLE_COMPONENT_OF",
            "relationship_confidence": first_value(row, "relationship_confidence"),
            "source_url": first_value(row, "source_url"),
            "review_status": "REQUIRES_CURATED_PARENT_RESOLUTION",
        })

    evidence_counts = Counter(
        first_value(row, "provisional_entity_id") for row in evidence if first_value(row, "provisional_entity_id")
    )
    for entity in entities:
        entity["identity_evidence_count"] = evidence_counts.get(entity["upstream_provisional_entity_id"], 0)

    carried_manual: list[dict[str, Any]] = []
    seen_manual: set[str] = set()
    for row in manual_rows:
        if upper(first_value(row, "record_status")) == "NO_RECORDS":
            continue
        review_id = first_value(row, "review_id") or stable_id(
            "dst_manual_review", first_value(row, "proposed_name", "proposed_canonical_name"), first_value(row, "source_url")
        )
        if review_id in seen_manual:
            continue
        seen_manual.add(review_id)
        carried_manual.append({
            "review_id": review_id,
            "review_type": first_value(row, "review_type") or "MANUAL_ENTITY_REVIEW",
            "proposed_name": first_value(row, "proposed_name", "proposed_canonical_name"),
            "proposed_entity_type": first_value(row, "proposed_entity_type") or "UNRESOLVED",
            "confidence": first_value(row, "confidence", "identity_confidence"),
            "review_flags": first_value(row, "review_flags"),
            "evidence": first_value(row, "evidence"),
            "source_url": first_value(row, "source_url", "target_url"),
            "recommended_action": first_value(row, "recommended_action") or "MANUAL_REVIEW_BEFORE_ANY_FUTURE_IDENTITY_LOCK",
            "publication_status": "NOT_PUBLISHED",
            "carried_forward_version": VERSION,
        })

    return BuildResult(
        entities=entities,
        aliases=canonical_aliases,
        relationship_review=relationship_review,
        manual_review=carried_manual,
        rejected=rejected,
        publication=publication,
        audit=audit,
    )


def validate(
    result: BuildResult,
    config: Mapping[str, Any],
    upstream_validation: Mapping[str, Any],
    partial_run: bool = False,
) -> dict[str, Any]:
    scheme_count = sum(row["entity_type"] == "SCHEME" for row in result.entities)
    programme_count = sum(row["entity_type"] == "PROGRAMME" for row in result.entities)
    ids = [row["master_id"] for row in result.entities]
    names = [(row["entity_type"], row["canonical_name_normalized"]) for row in result.entities]
    urls = [normalize_url(row["official_source_url"]) for row in result.entities]

    publication_ids = {row["master_id"] for row in result.publication}
    entity_ids = set(ids)
    publication_call_contamination = [
        row for row in result.publication
        if safety_reasons(row["scheme_name"], row["official_page_url"], config)
    ]
    manual_published = [row for row in result.manual_review if row.get("review_id") in publication_ids]
    upstream_ready = bool(upstream_validation.get("ready_for_v3_4_0_4"))
    require_upstream = bool(config.get("require_upstream_ready", True))

    checks = {
        "upstream_ready_for_v3_4_0_4": upstream_ready or not require_upstream,
        "all_entities_identity_locked": all(truthy(row.get("identity_locked")) for row in result.entities),
        "canonical_ids_unique": len(ids) == len(set(ids)),
        "canonical_names_unique_within_type": len(names) == len(set(names)),
        "official_urls_unique": len(urls) == len(set(urls)),
        "publication_matches_locked_entities": publication_ids == entity_ids,
        "no_call_or_generic_contamination": not publication_call_contamination,
        "manual_review_not_published": not manual_published,
        "no_rejected_entities_published": not ({row.get("master_id") for row in result.rejected} & publication_ids),
        "scheme_count_matches_expected": partial_run or scheme_count == int(config.get("expected_scheme_count", scheme_count)),
        "programme_count_matches_expected": partial_run or programme_count == int(config.get("expected_programme_count", programme_count)),
        "public_catalogue_non_empty": bool(result.publication),
    }
    passed = all(checks.values())
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "validated_at": utc_now(),
        "partial_run": partial_run,
        "counts": {
            "canonical_entities": len(result.entities),
            "canonical_schemes": scheme_count,
            "canonical_programmes": programme_count,
            "canonical_aliases": len(result.aliases),
            "relationship_reviews": len(result.relationship_review),
            "manual_entity_reviews": len(result.manual_review),
            "identity_lock_rejections": len(result.rejected),
            "publication_records": len(result.publication),
        },
        "checks": checks,
        "quality": {
            "publication_call_or_generic_contamination": publication_call_contamination,
            "manual_rows_published": manual_published,
            "rejected_master_ids": [row.get("master_id", "") for row in result.rejected],
        },
        "canonical_validation_passed": passed,
        "ready_for_dashboard_preview": passed,
        "ready_for_v3_4_0_5": passed,
    }


def write_database(path: Path, result: BuildResult, validation: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        con = sqlite3.connect(temp_path)
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript(
            """
            CREATE TABLE departments (
                department_code TEXT PRIMARY KEY,
                ministry TEXT NOT NULL,
                department_name TEXT NOT NULL,
                total_entities INTEGER NOT NULL,
                total_schemes INTEGER NOT NULL,
                total_programmes INTEGER NOT NULL,
                last_verified_date TEXT NOT NULL,
                source_version TEXT NOT NULL
            );
            CREATE TABLE canonical_entities (
                master_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_name TEXT NOT NULL,
                official_abbreviation TEXT,
                official_source_url TEXT NOT NULL,
                canonical_identity_status TEXT NOT NULL,
                identity_locked INTEGER NOT NULL,
                identity_lock_version TEXT NOT NULL,
                identity_locked_at TEXT NOT NULL,
                public_status TEXT NOT NULL
            );
            CREATE TABLE publication_catalogue (
                master_id TEXT PRIMARY KEY REFERENCES canonical_entities(master_id),
                scheme_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                ministry TEXT NOT NULL,
                department TEXT NOT NULL,
                programme_status TEXT NOT NULL,
                application_status TEXT NOT NULL,
                public_status TEXT NOT NULL,
                official_page_url TEXT NOT NULL,
                application_url TEXT,
                guideline_url TEXT,
                objective TEXT,
                eligibility TEXT,
                benefits TEXT,
                funding_summary TEXT,
                application_process TEXT,
                required_documents TEXT,
                contact_information TEXT,
                official_abbreviation TEXT,
                information_completeness REAL NOT NULL,
                verification_status TEXT NOT NULL,
                last_verified_date TEXT NOT NULL,
                identity_lock_version TEXT NOT NULL
            );
            CREATE TABLE aliases (
                alias_id TEXT PRIMARY KEY,
                master_id TEXT NOT NULL REFERENCES canonical_entities(master_id),
                alias_text TEXT NOT NULL,
                alias_type TEXT,
                alias_confidence REAL,
                source_url TEXT,
                status TEXT NOT NULL
            );
            CREATE TABLE manual_review_queue (
                review_id TEXT PRIMARY KEY,
                review_type TEXT,
                proposed_name TEXT,
                proposed_entity_type TEXT,
                confidence REAL,
                review_flags TEXT,
                evidence TEXT,
                source_url TEXT,
                recommended_action TEXT,
                publication_status TEXT NOT NULL
            );
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        scheme_count = validation["counts"]["canonical_schemes"]
        programme_count = validation["counts"]["canonical_programmes"]
        con.execute(
            "INSERT INTO departments VALUES (?,?,?,?,?,?,?,?)",
            (DEPARTMENT_CODE, MINISTRY_NAME, DEPARTMENT_NAME, len(result.entities), scheme_count, programme_count, date.today().isoformat(), VERSION),
        )
        for row in result.entities:
            con.execute(
                "INSERT INTO canonical_entities VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    row["master_id"], row["entity_type"], row["canonical_name"], row["official_abbreviation"],
                    row["official_source_url"], row["canonical_identity_status"], 1, row["identity_lock_version"],
                    row["identity_locked_at"], row["public_status"],
                ),
            )
        for row in result.publication:
            con.execute(
                "INSERT INTO publication_catalogue VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["master_id"], row["scheme_name"], row["entity_type"], row["ministry"], row["department"],
                    row["programme_status"], row["application_status"], row["public_status"], row["official_page_url"],
                    row["application_url"], row["guideline_url"], row["objective"], row["eligibility"], row["benefits"],
                    row["funding_summary"], row["application_process"], row["required_documents"], row["contact_information"],
                    row["official_abbreviation"], safe_float(row["information_completeness"]), row["verification_status"],
                    row["last_verified_date"], row["identity_lock_version"],
                ),
            )
        for row in result.aliases:
            con.execute(
                "INSERT INTO aliases VALUES (?,?,?,?,?,?,?)",
                (
                    row["alias_id"], row["master_id"], row["alias_text"], row["alias_type"],
                    safe_float(row["alias_confidence"]), row["source_url"], row["status"],
                ),
            )
        for row in result.manual_review:
            con.execute(
                "INSERT INTO manual_review_queue VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    row["review_id"], row["review_type"], row["proposed_name"], row["proposed_entity_type"],
                    safe_float(row["confidence"]), row["review_flags"], row["evidence"], row["source_url"],
                    row["recommended_action"], row["publication_status"],
                ),
            )
        con.execute("INSERT INTO metadata VALUES (?,?)", ("validation", json.dumps(validation, ensure_ascii=False)))
        con.commit()
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        con.close()
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def build_summary(result: BuildResult, validation: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "department_name": DEPARTMENT_NAME,
        "completed_at": utc_now(),
        "identity_policy": {
            "permanent_identity_locked": True,
            "temporary_calls_can_rename_scheme": False,
            "manual_review_rows_published": False,
            "description": "Only corrected permanent DST scheme/programme identities are locked. Calls remain separate future instances.",
        },
        "counts": validation["counts"],
        "canonical_validation_passed": validation["canonical_validation_passed"],
        "ready_for_dashboard_preview": validation["ready_for_dashboard_preview"],
        "ready_for_v3_4_0_5": validation["ready_for_v3_4_0_5"],
        "dashboard": {
            "application": "apps/ssip_public_dashboard_v3_4_0_4.py",
            "database": str(output_dir / DATABASE_OUTPUT),
            "default_port": 8502,
            "public_preview_records": len(result.publication),
        },
        "outputs": {
            "canonical_entities": ENTITY_OUTPUT,
            "canonical_schemes": SCHEME_OUTPUT,
            "canonical_programmes": PROGRAMME_OUTPUT,
            "canonical_aliases": ALIAS_OUTPUT,
            "relationship_review": RELATIONSHIP_REVIEW_OUTPUT,
            "manual_review": MANUAL_REVIEW_OUTPUT,
            "rejections": REJECTED_OUTPUT,
            "publication_catalogue": PUBLICATION_OUTPUT,
            "publication_json": PUBLICATION_JSON_OUTPUT,
            "database": DATABASE_OUTPUT,
            "audit": AUDIT_OUTPUT,
            "validation": VALIDATION_OUTPUT,
            "summary": SUMMARY_OUTPUT,
        },
        "output_directory": str(output_dir),
    }


def self_test() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    schemes = [{
        "provisional_entity_id": "p1", "proposed_canonical_name": "Innovation Fellowship Scheme",
        "official_source_url": "https://dst.gov.in/innovation-fellowship", "identity_confidence": "0.92",
    }]
    programmes = [{
        "provisional_entity_id": "p2", "proposed_canonical_name": "Technology Development Programme",
        "official_source_url": "https://dst.gov.in/technology-development", "quality_confidence": "0.81",
    }]
    manual = [{
        "review_id": "r1", "proposed_name": "International Cooperation & Mega Science",
        "source_url": "https://dst.gov.in/international-cooperation-mega-science",
    }]
    aliases = [{"provisional_entity_id": "p1", "alias_text": "IFS"}]
    hierarchy = [{"child_provisional_entity_id": "p2", "parent_name_text": "Innovation Division"}]
    result = build(schemes, programmes, manual, aliases, hierarchy, [], config, {}, {})
    partial_validation = validate(result, {**config, "require_upstream_ready": False}, {}, partial_run=True)
    blocked_result = build(
        [{"provisional_entity_id": "bad", "proposed_canonical_name": "Call for Proposals 2026", "official_source_url": "https://dst.gov.in/call-for-proposals/2026", "identity_confidence": "0.9"}],
        [], [], [], [], [], config, {}, {},
    )
    tests = {
        "scheme_locked": len(result.entities) == 2 and result.entities[0]["identity_locked"] == "true",
        "stable_ids_created": all(row["master_id"].startswith("dst_") for row in result.entities),
        "manual_review_not_published": len(result.manual_review) == 1 and len(result.publication) == 2,
        "alias_linked": len(result.aliases) == 1 and result.aliases[0]["master_id"] in {x["master_id"] for x in result.entities},
        "relationship_kept_for_review": len(result.relationship_review) == 1,
        "call_identity_blocked": len(blocked_result.entities) == 0 and len(blocked_result.rejected) == 1,
        "publication_adapter_created": all(field in result.publication[0] for field in PUBLICATION_FIELDS),
        "partial_validation_passed": partial_validation["canonical_validation_passed"],
    }
    return {
        "service_version": VERSION,
        "department_code": DEPARTMENT_CODE,
        "tests": tests,
        "self_test_passed": all(tests.values()),
        "preview_counts": {
            "entities": len(result.entities), "publication": len(result.publication),
            "manual_review": len(result.manual_review), "blocked": len(blocked_result.rejected),
        },
    }


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    root = Path(args.project_root).resolve()
    upstream_dir = root / (Path(args.upstream_dir) if args.upstream_dir else UPSTREAM_DIR)
    inventory_dir = root / (Path(args.inventory_dir) if args.inventory_dir else INVENTORY_DIR)
    output_dir = root / (Path(args.output_dir) if args.output_dir else OUTPUT_DIR)
    override_path = root / (Path(args.overrides) if args.overrides else Path("config") / OVERRIDES_INPUT)
    return {
        "root": root, "upstream": upstream_dir, "inventory": inventory_dir,
        "output": output_dir, "overrides": override_path,
    }


def execute(args: argparse.Namespace) -> tuple[BuildResult, dict[str, Any], dict[str, Any]]:
    paths = resolve_paths(args)
    config_path = paths["root"] / args.config if args.config else None
    config = load_config(config_path)

    upstream_validation = read_json(paths["upstream"] / UPSTREAM_VALIDATION_INPUT)
    read_json(paths["upstream"] / UPSTREAM_SUMMARY_INPUT)
    schemes = read_csv(paths["upstream"] / SCHEMES_INPUT)
    programmes = read_csv(paths["upstream"] / PROGRAMMES_INPUT)
    manual = read_csv(paths["upstream"] / MANUAL_REVIEW_INPUT, required=False)
    final_review = read_csv(paths["upstream"] / FINAL_REVIEW_INPUT, required=False)
    # Merge only explicit manual entity rows; never carry NO_RECORDS placeholders.
    combined_manual = manual + [row for row in final_review if upper(first_value(row, "review_type")) == "MANUAL_ENTITY_REVIEW"]
    aliases = read_csv(paths["inventory"] / ALIASES_INPUT, required=False)
    hierarchy = read_csv(paths["inventory"] / HIERARCHY_INPUT, required=False)
    evidence = read_csv(paths["inventory"] / EVIDENCE_INPUT, required=False)
    overrides_by_id, overrides_by_url = load_overrides(paths["overrides"])

    result = build(
        schemes, programmes, combined_manual, aliases, hierarchy, evidence,
        config, overrides_by_id, overrides_by_url,
    )
    validation = validate(result, config, upstream_validation, partial_run=args.partial)
    summary = build_summary(result, validation, paths["output"])

    if not args.dry_run:
        paths["output"].mkdir(parents=True, exist_ok=True)
        write_csv(paths["output"] / ENTITY_OUTPUT, result.entities, ENTITY_FIELDS + ["identity_evidence_count"])
        write_csv(paths["output"] / SCHEME_OUTPUT, [x for x in result.entities if x["entity_type"] == "SCHEME"], ENTITY_FIELDS + ["identity_evidence_count"])
        write_csv(paths["output"] / PROGRAMME_OUTPUT, [x for x in result.entities if x["entity_type"] == "PROGRAMME"], ENTITY_FIELDS + ["identity_evidence_count"])
        write_csv(paths["output"] / ALIAS_OUTPUT, result.aliases)
        write_csv(paths["output"] / RELATIONSHIP_REVIEW_OUTPUT, result.relationship_review)
        write_csv(paths["output"] / MANUAL_REVIEW_OUTPUT, result.manual_review)
        write_csv(paths["output"] / REJECTED_OUTPUT, result.rejected)
        write_csv(paths["output"] / PUBLICATION_OUTPUT, result.publication, PUBLICATION_FIELDS)
        write_json(paths["output"] / PUBLICATION_JSON_OUTPUT, result.publication)
        write_csv(paths["output"] / AUDIT_OUTPUT, result.audit)
        write_json(paths["output"] / VALIDATION_OUTPUT, validation)
        write_json(paths["output"] / SUMMARY_OUTPUT, summary)
        write_database(paths["output"] / DATABASE_OUTPUT, result, validation)
    return result, validation, summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--upstream-dir")
    parser.add_argument("--inventory-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--config", default="config/dst_canonical_publication_rules_v3_4_0_4.json")
    parser.add_argument("--overrides", default=f"config/{OVERRIDES_INPUT}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--partial", action="store_true", help="Relax expected production counts for controlled tests.")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        payload = self_test()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload["self_test_passed"] else 2
    try:
        _, validation, summary = execute(args)
    except Exception as exc:  # pragma: no cover - CLI safety
        print(json.dumps({"service_version": VERSION, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.strict and not validation["canonical_validation_passed"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
