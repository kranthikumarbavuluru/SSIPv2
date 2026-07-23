from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "3.4.3.8.0.1"
SOURCE_VERSION = "3.4.3.8.0"

PERMANENT_TYPES = {
    "PERMANENT_SCHEME",
    "PERMANENT_PROGRAMME",
    "ACCELERATOR_PROGRAMME",
    "GRANT_PROGRAMME",
    "INCUBATION_PROGRAMME",
    "ECOSYSTEM_PROGRAMME",
    "IMPLEMENTATION_PROGRAMME",
}
CALL_TYPES = {
    "APPLICATION_CALL",
    "CHALLENGE_CALL",
    "GRAND_CHALLENGE",
    "HACKATHON",
    "ACCELERATOR_COHORT",
    "EOI",
    "RFP",
    "IMPLEMENTATION_PARTNER_CALL",
}
HISTORICAL_TYPES = {
    "RESULT_ANNOUNCEMENT",
    "EXTENSION_NOTICE",
    "CORRIGENDUM",
    "WINNER_NOTICE",
    "SELECTED_COHORT",
}
ERROR_DISPOSITION = "EXCLUDED_ERROR_OR_NAVIGATION"
DOCUMENT_DISPOSITION = "SUPPORTING_DOCUMENT"
PROGRAMME_DISPOSITION = "PURIFIED_PROGRAMME_FAMILY"
CALL_DISPOSITION = "PURIFIED_CALL_OR_CHALLENGE"
HISTORICAL_DISPOSITION = "PURIFIED_HISTORICAL_EVENT"
REVIEW_DISPOSITION = "IDENTITY_OR_ROLE_REVIEW"


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split()).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def parse_bool(value: Any) -> bool:
    return clean(value).casefold() in {"1", "true", "yes", "y"}


def normalize_text(value: str) -> str:
    decoded = urllib.parse.unquote(clean(value))
    return clean(re.sub(r"[^a-z0-9]+", " ", decoded.casefold()))


def meaningful_tokens(value: str) -> list[str]:
    stop = {
        "the", "and", "for", "of", "to", "in", "on", "with",
        "meity", "startup", "hub", "scheme", "programme", "program",
        "call", "application", "official", "government", "india",
        "pdf", "view", "page",
    }
    return [
        token
        for token in normalize_text(value).split()
        if len(token) > 1 and token not in stop
    ]


def is_pdf_like(row: dict[str, str]) -> bool:
    values = " ".join(
        clean(row.get(key))
        for key in (
            "canonical_name",
            "official_page_url",
            "evidence_excerpt",
        )
    ).casefold()
    return (
        ".pdf" in urllib.parse.unquote(values)
        or clean(row.get("official_page_url")).casefold().endswith(".pdf")
    )


def raw_filename_title(title: str) -> bool:
    value = urllib.parse.unquote(clean(title))
    lowered = value.casefold()
    if lowered.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
        return True
    return bool(
        re.search(
            r"(?i)(?:%20|_|-).*\.(?:pdf|docx?|xlsx?)$",
            clean(title),
        )
    )


def evidence_blob(
    row: dict[str, str],
    evidence: dict[str, str] | None,
) -> str:
    parts = [
        row.get("canonical_name", ""),
        row.get("entity_reason", ""),
        row.get("evidence_excerpt", ""),
        row.get("status_evidence", ""),
        row.get("official_page_url", ""),
        row.get("quality_flags", ""),
    ]
    if evidence:
        parts.extend(
            [
                evidence.get("title", ""),
                evidence.get("text", ""),
                evidence.get("url", ""),
                evidence.get("final_url", ""),
                evidence.get("quality_flags", ""),
                evidence.get("error", ""),
                evidence.get("source_kind", ""),
            ]
        )
    return clean(" ".join(parts))


def has_marker(blob: str, markers: Iterable[str]) -> bool:
    lowered = blob.casefold()
    return any(clean(marker).casefold() in lowered for marker in markers)


def hard_error_reason(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> str:
    title_key = normalize_text(row.get("canonical_name", ""))
    generic = {
        normalize_text(value)
        for value in config["generic_titles"]
    }
    blob = evidence_blob(row, evidence)

    if title_key in generic:
        return "GENERIC_OR_PORTAL_TITLE"
    if has_marker(blob, config["error_markers"]):
        return "ERROR_OR_NOT_FOUND_PAGE"
    if clean(row.get("canonical_name")).casefold() in {
        "meitystartuphub",
        "meity startup hub",
    }:
        return "PORTAL_NAME_NOT_ENTITY"
    evidence_status = clean((evidence or {}).get("status_code"))
    if evidence_status and evidence_status not in {"200", "201"}:
        return "NON_SUCCESS_HTTP_STATUS"
    url_path = urllib.parse.urlsplit(
        clean(row.get("official_page_url"))
    ).path.casefold().rstrip("/")
    if url_path in {
        "",
        "/",
        "/schemes",
        "/challenges",
        "/whatsnew",
        "/successtoryview",
        "/press-release-all",
    }:
        return "DIRECTORY_OR_UNPARAMETERISED_ROUTE"
    return ""


def document_role(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> str:
    blob = evidence_blob(row, evidence)
    for role, markers in config["document_roles"].items():
        if has_marker(blob, markers):
            return role
    return "SUPPORTING_EVIDENCE"


def explicit_deadline_context(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> bool:
    blob = evidence_blob(row, evidence)
    return has_marker(blob, config["deadline_markers"])


def explicit_opening_context(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> bool:
    blob = evidence_blob(row, evidence)
    return has_marker(blob, config["opening_markers"])


def footer_date_present(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> bool:
    return has_marker(
        evidence_blob(row, evidence),
        config["footer_date_markers"],
    )


def date_role_repair(
    row: dict[str, str],
    evidence: dict[str, str] | None,
    config: dict[str, Any],
) -> tuple[str, str, list[str]]:
    opening = clean(row.get("opening_date"))
    closing = clean(row.get("closing_date"))
    flags: list[str] = []

    if opening and not explicit_opening_context(row, evidence, config):
        opening = ""
        flags.append("OPENING_DATE_CONTEXT_NOT_PROVEN")

    if closing and not explicit_deadline_context(row, evidence, config):
        closing = ""
        flags.append("CLOSING_DATE_CONTEXT_NOT_PROVEN")

    if footer_date_present(row, evidence, config):
        if clean(row.get("closing_date")) and not closing:
            flags.append("FOOTER_DATE_REMOVED")
        if clean(row.get("opening_date")) and not opening:
            flags.append("FOOTER_OR_PAGE_DATE_REMOVED")

    return opening, closing, flags


def best_alias_match(
    title: str,
    blob: str,
    definitions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    title_key = normalize_text(title)
    blob_key = normalize_text(blob)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    title_tokens = set(meaningful_tokens(title))

    for definition in definitions:
        for alias in [
            definition["canonical_name"],
            *definition.get("aliases", []),
        ]:
            alias_key = normalize_text(alias)
            alias_tokens = set(meaningful_tokens(alias))
            score = 0.0
            if title_key == alias_key:
                score = 1.0
            elif alias_key and alias_key in title_key:
                score = 0.94
            elif alias_key and alias_key in blob_key:
                score = 0.84
            elif title_tokens and alias_tokens:
                score = len(title_tokens & alias_tokens) / len(
                    title_tokens | alias_tokens
                )
            if score > best[0]:
                best = (score, definition)

    return best[1] if best[0] >= 0.58 else None


def candidate_quality(
    row: dict[str, str],
    evidence: dict[str, str] | None,
) -> int:
    score = 0
    title = clean(row.get("canonical_name"))
    if parse_bool(row.get("existing_public_record")):
        score += 12
    if clean(row.get("existing_master_id")):
        score += 5
    if not raw_filename_title(title):
        score += 4
    if len(meaningful_tokens(title)) >= 2:
        score += 3
    if clean(row.get("official_page_url")):
        score += 2
    if (evidence or {}).get("source_kind") in {
        "HTML_STATIC",
        "HTML_BROWSER_RENDERED",
        "JSON_RECORD",
        "PDF_DOCUMENT",
    }:
        score += 2
    if clean(row.get("startup_relevance")) != "RELEVANCE_REVIEW":
        score += 1
    return score


def merge_flags(*values: Any) -> str:
    flags: list[str] = []
    for value in values:
        if isinstance(value, list):
            pieces = value
        else:
            pieces = clean(value).split(";")
        for piece in pieces:
            piece = clean(piece)
            if piece and piece not in flags:
                flags.append(piece)
    return ";".join(flags)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


@dataclass(frozen=True)
class PurificationPaths:
    project_root: Path
    source_dir: Path
    output_dir: Path
    database_path: Path
    config_path: Path

    @classmethod
    def defaults(cls, project_root: Path) -> "PurificationPaths":
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_dir=root / "data/departments/meity/v3_4_3_8_0",
            output_dir=root / "data/departments/meity/v3_4_3_8_0_1",
            database_path=root / "database/ssip_staging_v1.db",
            config_path=(
                root
                / "config/meity_candidate_purification_v3_4_3_8_0_1.json"
            ),
        )


class CandidatePurifier:
    def __init__(
        self,
        paths: PurificationPaths,
        config: dict[str, Any],
    ) -> None:
        self.paths = paths
        self.config = config

    def load_source_candidates(self) -> list[dict[str, str]]:
        files = [
            "meity_programme_inventory_v3_4_3_8_0.csv",
            "meity_current_calls_challenges_v3_4_3_8_0.csv",
            "meity_historical_calls_results_v3_4_3_8_0.csv",
            "meity_exclusions_v3_4_3_8_0.csv",
        ]
        by_id: dict[str, dict[str, str]] = {}
        for name in files:
            for row in read_csv(self.paths.source_dir / name):
                candidate_id = clean(row.get("candidate_id"))
                if candidate_id:
                    by_id[candidate_id] = row
        return list(by_id.values())

    def load_evidence(self) -> dict[str, dict[str, str]]:
        rows = read_csv(
            self.paths.source_dir
            / "meity_document_and_page_evidence_v3_4_3_8_0.csv"
        )
        return {
            clean(row.get("evidence_id")): row
            for row in rows
            if clean(row.get("evidence_id"))
        }

    def database_hash(self) -> str:
        if not self.paths.database_path.exists():
            return ""
        return hashlib.sha256(
            self.paths.database_path.read_bytes()
        ).hexdigest()

    def purify(self) -> dict[str, Any]:
        candidates = self.load_source_candidates()
        evidence_map = self.load_evidence()
        source_manifest_path = (
            self.paths.source_dir
            / "meity_complete_intelligence_manifest_v3_4_3_8_0.json"
        )
        source_manifest = json.loads(
            source_manifest_path.read_text(encoding="utf-8-sig")
        )

        source_count = len(candidates)
        dispositions: list[dict[str, Any]] = []
        programme_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        call_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        historical_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        documents: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        review: list[dict[str, Any]] = []

        for row in candidates:
            evidence = evidence_map.get(clean(row.get("evidence_id")))
            repaired = dict(row)
            original_title = clean(row.get("canonical_name"))
            blob = evidence_blob(row, evidence)
            opening, closing, date_flags = date_role_repair(
                row,
                evidence,
                self.config,
            )
            repaired["opening_date"] = opening
            repaired["closing_date"] = closing
            repaired["quality_flags"] = merge_flags(
                row.get("quality_flags"),
                date_flags,
            )
            repaired["original_canonical_name"] = original_title
            repaired["source_entity_type"] = clean(row.get("entity_type"))
            repaired["source_admin_queue"] = clean(row.get("admin_queue"))
            repaired["source_candidate_id"] = clean(row.get("candidate_id"))
            repaired["source_evidence_id"] = clean(row.get("evidence_id"))

            error_reason = hard_error_reason(
                row,
                evidence,
                self.config,
            )
            if error_reason:
                repaired.update(
                    {
                        "disposition": ERROR_DISPOSITION,
                        "decision_reason": error_reason,
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                excluded.append(repaired)
                dispositions.append(repaired)
                continue

            if is_pdf_like(row) or raw_filename_title(original_title):
                role = document_role(row, evidence, self.config)
                repaired.update(
                    {
                        "disposition": DOCUMENT_DISPOSITION,
                        "document_role": role,
                        "canonical_name": "",
                        "decision_reason": (
                            "Document retained as supporting evidence; "
                            "filename is not a canonical entity identity."
                        ),
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                documents.append(repaired)
                dispositions.append(repaired)
                continue

            call_definition = best_alias_match(
                original_title,
                blob,
                self.config["call_families"],
            )
            programme_definition = best_alias_match(
                original_title,
                blob,
                self.config["programme_families"],
            )
            source_type = clean(row.get("entity_type"))

            if call_definition and (
                source_type in CALL_TYPES
                or source_type in PERMANENT_TYPES
                or call_definition["canonical_name"].casefold()
                in blob.casefold()
            ):
                canonical = call_definition["canonical_name"]
                repaired.update(
                    {
                        "canonical_name": canonical,
                        "entity_type": call_definition["entity_type"],
                        "record_kind": "APPLICATION_CALL",
                        "disposition": CALL_DISPOSITION,
                        "identity_family": canonical,
                        "decision_reason": (
                            "Known challenge/hackathon family; "
                            "not a permanent scheme."
                        ),
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                key = normalize_text(canonical)
                call_groups[key].append(repaired)
                dispositions.append(repaired)
                continue

            if programme_definition and source_type in PERMANENT_TYPES:
                canonical = programme_definition["canonical_name"]
                repaired.update(
                    {
                        "canonical_name": canonical,
                        "entity_type": programme_definition["family_kind"],
                        "record_kind": "SCHEME_PROGRAMME",
                        "disposition": PROGRAMME_DISPOSITION,
                        "identity_family": canonical,
                        "decision_reason": (
                            "Evidence consolidated into a known "
                            "permanent programme family."
                        ),
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                key = normalize_text(canonical)
                programme_groups[key].append(repaired)
                dispositions.append(repaired)
                continue

            if source_type in HISTORICAL_TYPES or clean(
                row.get("application_status")
            ) in {"HISTORICAL_CLOSED", "CLOSED"}:
                repaired.update(
                    {
                        "disposition": HISTORICAL_DISPOSITION,
                        "identity_family": normalize_text(original_title),
                        "decision_reason": "Historical or result evidence retained.",
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                key = (
                    normalize_text(clean(row.get("official_page_url")))
                    or normalize_text(original_title)
                )
                historical_groups[key].append(repaired)
                dispositions.append(repaired)
                continue

            if source_type in CALL_TYPES:
                repaired.update(
                    {
                        "disposition": CALL_DISPOSITION,
                        "identity_family": normalize_text(original_title),
                        "decision_reason": "Call/challenge identity retained for review.",
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                key = (
                    normalize_text(clean(row.get("official_page_url")))
                    or normalize_text(original_title)
                )
                call_groups[key].append(repaired)
                dispositions.append(repaired)
                continue

            if source_type in PERMANENT_TYPES:
                if len(meaningful_tokens(original_title)) < 2:
                    repaired.update(
                        {
                            "disposition": REVIEW_DISPOSITION,
                            "decision_reason": (
                                "Permanent-programme evidence is insufficient "
                                "for a canonical identity."
                            ),
                            "publication_eligible": False,
                            "apply_action_allowed": False,
                        }
                    )
                    review.append(repaired)
                    dispositions.append(repaired)
                    continue

                repaired.update(
                    {
                        "disposition": PROGRAMME_DISPOSITION,
                        "identity_family": normalize_text(original_title),
                        "decision_reason": (
                            "Unmapped permanent-programme candidate retained "
                            "as a unique evidence-based family."
                        ),
                        "publication_eligible": False,
                        "apply_action_allowed": False,
                    }
                )
                key = (
                    normalize_text(clean(row.get("official_page_url")))
                    or normalize_text(original_title)
                )
                programme_groups[key].append(repaired)
                dispositions.append(repaired)
                continue

            repaired.update(
                {
                    "disposition": REVIEW_DISPOSITION,
                    "decision_reason": "Entity role requires Admin evidence review.",
                    "publication_eligible": False,
                    "apply_action_allowed": False,
                }
            )
            review.append(repaired)
            dispositions.append(repaired)

        def consolidate(
            groups: dict[str, list[dict[str, Any]]],
            default_disposition: str,
        ) -> list[dict[str, Any]]:
            output: list[dict[str, Any]] = []
            for key, members in sorted(groups.items()):
                selected = max(
                    members,
                    key=lambda item: candidate_quality(
                        item,
                        evidence_map.get(clean(item.get("source_evidence_id"))),
                    ),
                )
                merged = dict(selected)
                merged["disposition"] = default_disposition
                merged["source_candidate_count"] = len(members)
                merged["source_candidate_ids"] = ";".join(
                    sorted(
                        {
                            clean(item.get("source_candidate_id"))
                            for item in members
                            if clean(item.get("source_candidate_id"))
                        }
                    )
                )
                merged["evidence_ids"] = ";".join(
                    sorted(
                        {
                            clean(item.get("source_evidence_id"))
                            for item in members
                            if clean(item.get("source_evidence_id"))
                        }
                    )
                )
                merged["source_titles"] = ";".join(
                    sorted(
                        {
                            clean(item.get("original_canonical_name"))
                            for item in members
                            if clean(item.get("original_canonical_name"))
                        }
                    )
                )
                merged["source_urls"] = ";".join(
                    sorted(
                        {
                            clean(item.get("official_page_url"))
                            for item in members
                            if clean(item.get("official_page_url"))
                        }
                    )
                )
                merged["quality_flags"] = merge_flags(
                    *[item.get("quality_flags") for item in members],
                    "ALIASES_AND_EVIDENCE_CONSOLIDATED"
                    if len(members) > 1
                    else "",
                )
                merged["publication_eligible"] = False
                merged["apply_action_allowed"] = False
                output.append(merged)
            return output

        programmes = consolidate(
            programme_groups,
            PROGRAMME_DISPOSITION,
        )
        calls = consolidate(
            call_groups,
            CALL_DISPOSITION,
        )
        historical = consolidate(
            historical_groups,
            HISTORICAL_DISPOSITION,
        )

        disposition_counts = Counter(
            item["disposition"]
            for item in dispositions
        )
        partition_total = sum(disposition_counts.values())
        if partition_total != source_count:
            raise RuntimeError(
                "Source candidate partition mismatch: "
                f"{partition_total} != {source_count}"
            )

        unsafe_programmes = [
            row
            for row in programmes
            if (
                normalize_text(row.get("canonical_name", ""))
                in {
                    normalize_text(value)
                    for value in self.config["generic_titles"]
                }
                or raw_filename_title(clean(row.get("canonical_name")))
                or has_marker(
                    evidence_blob(
                        row,
                        evidence_map.get(clean(row.get("source_evidence_id"))),
                    ),
                    self.config["error_markers"],
                )
            )
        ]
        if unsafe_programmes:
            raise RuntimeError(
                "Unsafe programme identities survived purification: "
                + ", ".join(
                    clean(row.get("canonical_name"))
                    for row in unsafe_programmes[:10]
                )
            )

        output_dir = self.paths.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        common_fields = [
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "record_kind",
            "application_status",
            "programme_status",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "source",
            "ministry",
            "implementing_agency",
            "startup_relevance",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "existing_master_id",
            "existing_public_record",
            "identity_family",
            "disposition",
            "decision_reason",
            "document_role",
            "source_candidate_id",
            "source_candidate_ids",
            "source_candidate_count",
            "source_evidence_id",
            "evidence_ids",
            "source_titles",
            "source_urls",
            "evidence_excerpt",
            "status_evidence",
            "quality_flags",
            "publication_eligible",
            "apply_action_allowed",
        ]

        write_csv(
            output_dir / "meity_purified_programme_families_v3_4_3_8_0_1.csv",
            programmes,
            common_fields,
        )
        write_csv(
            output_dir / "meity_purified_calls_challenges_v3_4_3_8_0_1.csv",
            calls,
            common_fields,
        )
        write_csv(
            output_dir / "meity_purified_historical_events_v3_4_3_8_0_1.csv",
            historical,
            common_fields,
        )
        write_csv(
            output_dir / "meity_supporting_documents_v3_4_3_8_0_1.csv",
            documents,
            common_fields,
        )
        write_csv(
            output_dir / "meity_excluded_error_pages_v3_4_3_8_0_1.csv",
            excluded,
            common_fields,
        )
        write_csv(
            output_dir / "meity_identity_role_review_v3_4_3_8_0_1.csv",
            review,
            common_fields,
        )
        write_csv(
            output_dir / "meity_source_candidate_dispositions_v3_4_3_8_0_1.csv",
            dispositions,
            common_fields,
        )

        review_rows = [
            *programmes,
            *calls,
            *historical,
            *review,
        ]
        write_csv(
            output_dir / "meity_purified_admin_review_v3_4_3_8_0_1.csv",
            review_rows,
            common_fields,
        )
        (
            output_dir / "meity_purified_admin_review_v3_4_3_8_0_1.json"
        ).write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "generated_at": utc_now(),
                    "database_write_performed": False,
                    "publication_performed": False,
                    "records": review_rows,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        signature_payload = {
            "version": VERSION,
            "source_signature": source_manifest["signature"],
            "programme_families": programmes,
            "calls": calls,
            "historical": historical,
            "documents": documents,
            "excluded": excluded,
            "review": review,
            "disposition_counts": dict(sorted(disposition_counts.items())),
        }
        signature = hashlib.sha256(
            stable_json(signature_payload).encode("utf-8")
        ).hexdigest()

        manifest = {
            "version": VERSION,
            "source_version": SOURCE_VERSION,
            "generated_at": utc_now(),
            "signature": signature,
            "source_manifest_signature": source_manifest["signature"],
            "source_candidate_count": source_count,
            "source_evidence_count": source_manifest.get("evidence_count", 0),
            "partition_total": partition_total,
            "partition_complete": partition_total == source_count,
            "disposition_counts": dict(sorted(disposition_counts.items())),
            "purified_programme_family_count": len(programmes),
            "purified_call_challenge_count": len(calls),
            "purified_historical_event_count": len(historical),
            "supporting_document_count": len(documents),
            "excluded_error_page_count": len(excluded),
            "identity_role_review_count": len(review),
            "admin_review_count": len(review_rows),
            "verified_open_count": 0,
            "apply_action_allowed_count": 0,
            "unsafe_programme_identity_count": len(unsafe_programmes),
            "database_write_performed": False,
            "publication_performed": False,
        }
        (
            output_dir / "meity_candidate_purification_manifest_v3_4_3_8_0_1.json"
        ).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return manifest


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_purification(project_root: Path) -> dict[str, Any]:
    paths = PurificationPaths.defaults(project_root)
    config = load_config(paths.config_path)
    return CandidatePurifier(paths, config).purify()
