from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from ssip_agents.extractor.utils import (
    atomic_write_json,
    load_json,
    normalize_space,
    utc_now_iso,
)


logger = logging.getLogger(__name__)

HOTFIX_VERSION = "2.4.1"
MEITY_SOURCE_NAME = "MeitY Startup Hub"
MEITY_HOSTS = {
    "msh.meity.gov.in",
    "meitystartuphub.in",
    "www.meitystartuphub.in",
}

DECISION_APPROVED = "APPROVED_FOR_DATABASE"
DECISION_ADMIN_REVIEW = "NEEDS_ADMIN_REVIEW"
DECISION_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
DECISION_REJECTED = "REJECTED"
VALID_DECISIONS = {
    DECISION_APPROVED,
    DECISION_ADMIN_REVIEW,
    DECISION_MORE_EVIDENCE,
    DECISION_REJECTED,
}
REVIEW_DECISIONS = {DECISION_ADMIN_REVIEW, DECISION_MORE_EVIDENCE}

DEFAULT_CONFIG: dict[str, Any] = {
    "minimum_approval_score": 0.78,
    "minimum_approval_extraction_confidence": 0.75,
    "minimum_reviewable_extraction_confidence": 0.45,
    "publish_canonical": True,
    "publish_legacy_category_files": False,
    "canonical_validated_filename": "validated_scheme_records_v1.json",
    "canonical_approved_filename": "approved_for_database_v1.json",
    "canonical_review_filename": "admin_review_queue_v1.json",
    "canonical_rejected_filename": "rejected_scheme_records_v1.json",
    "canonical_audit_filename": "validation_audit_v1.json",
    "versioned_validated_filename": "validated_scheme_records_v2_4.json",
    "versioned_approved_filename": "approved_for_database_v2_4.json",
    "versioned_review_filename": "admin_review_queue_v2_4.json",
    "versioned_rejected_filename": "rejected_scheme_records_v2_4.json",
    "versioned_audit_filename": "meity_incremental_validation_audit_v2_4.json",
    "versioned_failures_filename": "meity_incremental_validation_failures_v2_4.json",
    "versioned_summary_filename": "meity_incremental_validation_summary_v2_4.json",
}

PREFERRED_VALIDATION_FILES = (
    "validated_scheme_records_v1.json",
    "validation_records_v1.json",
    "scheme_validation_results_v1.json",
    "validated_records_v1.json",
)
PREFERRED_APPROVED_FILES = (
    "approved_for_database_v1.json",
    "approved_scheme_records_v1.json",
    "validation_approved_v1.json",
)
PREFERRED_REVIEW_FILES = (
    "admin_review_queue_v1.json",
    "validation_review_queue_v1.json",
    "review_queue_v1.json",
)
PREFERRED_REJECTED_FILES = (
    "rejected_scheme_records_v1.json",
    "validation_rejected_v1.json",
    "rejected_records_v1.json",
)
PREFERRED_AUDIT_FILES = (
    "validation_audit_v1.json",
    "validation_audit_log_v1.json",
)

VOLATILE_EXTRACTION_KEYS = {
    "extracted_at",
    "validated_at",
    "validation_metadata",
    "validation_decision",
    "decision",
    "validation_status",
    "validation_score",
    "validation_reasons",
    "validation_checks",
    "programme_status",
    "validator_version",
}


@dataclass(slots=True)
class MeityValidationRunResult:
    records: list[dict[str, Any]]
    meity_records: list[dict[str, Any]]
    approved_records: list[dict[str, Any]]
    review_records: list[dict[str, Any]]
    rejected_records: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    audit: list[dict[str, Any]]
    summary: dict[str, Any]


class MeityIncrementalValidationV24:
    """Validate only MeitY extraction records while preserving prior decisions.

    The validator is intentionally standalone. It can consume a unified existing
    validation file or reconstruct the prior validation state from separate
    approved, review, and rejected JSON outputs.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        config_path: Path | None = None,
        as_of_date: date | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.as_of_date = as_of_date or date.today()

        self.config = dict(DEFAULT_CONFIG)
        if config_path is None:
            config_path = self.project_root / "config" / "meity_validation_v2_4.json"
        file_config = load_json(config_path, default={})
        if isinstance(file_config, dict):
            self.config.update(file_config)

    @staticmethod
    def _url_is_meity(url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").casefold()
        except ValueError:
            return False
        return host in MEITY_HOSTS or host.endswith(".msh.meity.gov.in")

    @classmethod
    def _record_urls(cls, record: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("official_page_url", "application_url"):
            value = normalize_space(record.get(key))
            if value:
                urls.append(value)
        for item in record.get("source_evidence") or []:
            if isinstance(item, dict):
                value = normalize_space(item.get("url"))
                if value:
                    urls.append(value)
        return urls

    @classmethod
    def _is_meity_record(cls, record: dict[str, Any]) -> bool:
        source = normalize_space(record.get("source")).casefold()
        if source == MEITY_SOURCE_NAME.casefold():
            return True
        return any(cls._url_is_meity(url) for url in cls._record_urls(record))

    @staticmethod
    def _record_key(record: dict[str, Any]) -> tuple[str, str, str]:
        master_id = normalize_space(record.get("master_id"))
        if master_id:
            return ("master_id", master_id, "")
        return (
            "fallback",
            normalize_space(record.get("source")).casefold(),
            normalize_space(record.get("scheme_name")).casefold(),
        )

    @staticmethod
    def _decision_of(record: dict[str, Any]) -> str:
        for key in ("validation_decision", "decision", "validation_status"):
            value = normalize_space(record.get(key)).upper()
            if value in VALID_DECISIONS:
                return value
        return ""

    @staticmethod
    def _normalise_json(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): MeityIncrementalValidationV24._normalise_json(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if key not in VOLATILE_EXTRACTION_KEYS
            }
        if isinstance(value, list):
            return [MeityIncrementalValidationV24._normalise_json(item) for item in value]
        return value

    @classmethod
    def _extraction_fingerprint(cls, record: dict[str, Any]) -> str:
        incremental = record.get("incremental_metadata")
        if isinstance(incremental, dict):
            source_fingerprint = normalize_space(incremental.get("source_fingerprint"))
            if source_fingerprint:
                stable = {
                    "master_id": normalize_space(record.get("master_id")),
                    "source_fingerprint": source_fingerprint,
                    "quality_flags": sorted(str(x) for x in (record.get("quality_flags") or [])),
                    "extraction_confidence": float(record.get("extraction_confidence") or 0),
                }
                payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(payload.encode("utf-8")).hexdigest()

        payload = json.dumps(
            cls._normalise_json(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_iso_date(value: Any) -> date | None:
        text = normalize_space(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None

    def _programme_status(self, record: dict[str, Any]) -> tuple[str, list[str]]:
        scheme_status = normalize_space(record.get("scheme_status")).upper()
        master_status = normalize_space(record.get("master_current_status")).upper()
        closing_date = self._parse_iso_date(record.get("closing_date"))
        reasons: list[str] = []

        active_signal = (
            master_status == "ACTIVE_CALL_OPEN"
            or scheme_status == "OPEN_FOR_APPLICATIONS"
            or scheme_status == "OPEN_STATUS_REQUIRES_DEADLINE_VERIFICATION"
        )

        # A scheme/programme landing page may contain dates from old cohorts or calls.
        # Preserve the discovery agent's programme-level classification instead of
        # treating every historical date mention as closure of the whole scheme.
        if master_status == "SCHEME_INFORMATION_AVAILABLE" or scheme_status.startswith(
            "SCHEME_INFORMATION_AVAILABLE"
        ):
            if scheme_status == "CLOSED_OR_DEADLINE_PASSED" or (
                closing_date is not None and closing_date < self.as_of_date
            ):
                reasons.append("HISTORICAL_DATE_MENTION_ON_SCHEME_PAGE")
            return "SCHEME_INFORMATION_AVAILABLE", reasons

        if active_signal and closing_date is not None:
            if closing_date >= self.as_of_date:
                return "CALL_INFORMATION_CURRENT", reasons
            if master_status == "ACTIVE_CALL_OPEN":
                reasons.extend(
                    [
                        "MASTER_ACTIVE_BUT_EXTRACTED_DEADLINE_PASSED",
                        "CALL_STATUS_CONFLICT_REQUIRES_REVIEW",
                    ]
                )
                return "CALL_STATUS_CONFLICT_REQUIRES_REVIEW", reasons
            reasons.append("DEADLINE_ALREADY_PASSED")
            return "CALL_INFORMATION_HISTORICAL", reasons

        if active_signal:
            reasons.append("ACTIVE_CALL_DEADLINE_NOT_VERIFIED")
            return "CALL_INFORMATION_REQUIRES_DEADLINE_VERIFICATION", reasons

        if scheme_status == "CLOSED_OR_DEADLINE_PASSED":
            return "CALL_INFORMATION_HISTORICAL", reasons

        if master_status == "HISTORICAL_EVIDENCE_ONLY":
            return "HISTORICAL_INFORMATION_AVAILABLE", reasons

        reasons.append("PROGRAMME_STATUS_REQUIRES_REVIEW")
        return "INFORMATION_REQUIRES_REVIEW", reasons

    @staticmethod
    def _has_source_evidence(record: dict[str, Any]) -> bool:
        return any(
            isinstance(item, dict)
            and normalize_space(item.get("url"))
            and normalize_space(item.get("source_hash"))
            for item in (record.get("source_evidence") or [])
        )

    @classmethod
    def _has_official_meity_evidence(cls, record: dict[str, Any]) -> bool:
        return any(
            isinstance(item, dict)
            and cls._url_is_meity(normalize_space(item.get("url")))
            for item in (record.get("source_evidence") or [])
        )

    def _validation_checks(self, record: dict[str, Any]) -> dict[str, bool]:
        funding = record.get("funding_amount")
        amount_mentions = funding.get("amount_mentions") if isinstance(funding, dict) else []
        return {
            "scheme_name_present": bool(normalize_space(record.get("scheme_name"))),
            "master_id_present": bool(normalize_space(record.get("master_id"))),
            "official_page_url_present": bool(normalize_space(record.get("official_page_url"))),
            "source_evidence_present": self._has_source_evidence(record),
            "official_meity_evidence_present": self._has_official_meity_evidence(record),
            "implementing_agency_present": bool(normalize_space(record.get("implementing_agency"))),
            "eligibility_present": bool(record.get("eligibility")),
            "benefits_present": bool(record.get("benefits")),
            "application_route_present": bool(
                normalize_space(record.get("application_url"))
                or record.get("application_process")
            ),
            "funding_or_scheme_type_present": bool(amount_mentions or record.get("scheme_type")),
            "source_is_meity": self._is_meity_record(record),
        }

    @staticmethod
    def _validation_score(record: dict[str, Any], checks: dict[str, bool]) -> float:
        weighted_checks = {
            "scheme_name_present": 0.10,
            "master_id_present": 0.05,
            "official_page_url_present": 0.10,
            "source_evidence_present": 0.15,
            "official_meity_evidence_present": 0.10,
            "implementing_agency_present": 0.08,
            "eligibility_present": 0.13,
            "benefits_present": 0.12,
            "application_route_present": 0.09,
            "funding_or_scheme_type_present": 0.03,
            "source_is_meity": 0.05,
        }
        evidence_score = sum(weight for key, weight in weighted_checks.items() if checks.get(key))
        confidence = max(0.0, min(1.0, float(record.get("extraction_confidence") or 0.0)))
        # Evidence dominates; extraction confidence contributes a modest adjustment.
        return round(min(1.0, evidence_score * 0.90 + confidence * 0.10), 3)

    def _decide(
        self,
        record: dict[str, Any],
    ) -> tuple[str, float, str, list[str], dict[str, bool]]:
        checks = self._validation_checks(record)
        score = self._validation_score(record, checks)
        programme_status, status_reasons = self._programme_status(record)
        confidence = float(record.get("extraction_confidence") or 0.0)
        quality_flags = {normalize_space(x) for x in (record.get("quality_flags") or [])}
        reasons: list[str] = list(status_reasons)

        if not checks["scheme_name_present"]:
            reasons.append("SCHEME_NAME_MISSING")
        if not checks["master_id_present"]:
            reasons.append("MASTER_ID_MISSING")
        if not checks["official_page_url_present"]:
            reasons.append("OFFICIAL_PAGE_URL_MISSING")
        if not checks["source_evidence_present"]:
            reasons.append("SOURCE_EVIDENCE_MISSING")
        if not checks["official_meity_evidence_present"]:
            reasons.append("OFFICIAL_MEITY_EVIDENCE_MISSING")
        if not checks["eligibility_present"]:
            reasons.append("ELIGIBILITY_NOT_FOUND")
        if not checks["benefits_present"]:
            reasons.append("BENEFITS_NOT_FOUND")
        if not checks["application_route_present"]:
            reasons.append("APPLICATION_ROUTE_NOT_FOUND")
        if "NO_SOURCE_DOCUMENTS_FETCHED" in quality_flags:
            reasons.append("NO_SOURCE_DOCUMENTS_FETCHED")

        fatal = (
            not checks["scheme_name_present"]
            or not checks["source_is_meity"]
            or (
                not checks["official_page_url_present"]
                and not checks["source_evidence_present"]
            )
            or confidence < 0.20
        )
        if fatal:
            return DECISION_REJECTED, score, programme_status, sorted(set(reasons)), checks

        major_evidence_gap = (
            not checks["source_evidence_present"]
            or (
                not checks["eligibility_present"]
                and not checks["benefits_present"]
            )
            or not checks["application_route_present"]
            or confidence < float(self.config["minimum_reviewable_extraction_confidence"])
        )
        if major_evidence_gap:
            return (
                DECISION_MORE_EVIDENCE,
                score,
                programme_status,
                sorted(set(reasons)),
                checks,
            )

        approval_blockers = (
            not checks["eligibility_present"]
            or not checks["benefits_present"]
            or not checks["official_meity_evidence_present"]
            or "ACTIVE_CALL_DEADLINE_NOT_VERIFIED" in reasons
            or "CALL_STATUS_CONFLICT_REQUIRES_REVIEW" in reasons
            or confidence < float(self.config["minimum_approval_extraction_confidence"])
            or score < float(self.config["minimum_approval_score"])
        )
        if approval_blockers:
            return (
                DECISION_ADMIN_REVIEW,
                score,
                programme_status,
                sorted(set(reasons)),
                checks,
            )

        return DECISION_APPROVED, score, programme_status, sorted(set(reasons)), checks

    def _validate_record(
        self,
        *,
        extraction_record: dict[str, Any],
        existing_validation: dict[str, Any] | None,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        now = utc_now_iso()
        fingerprint = self._extraction_fingerprint(extraction_record)
        previous_fingerprint = ""
        previous_version = ""
        previous_decision = ""

        if existing_validation:
            metadata = existing_validation.get("validation_metadata")
            if isinstance(metadata, dict):
                previous_fingerprint = normalize_space(metadata.get("extraction_fingerprint"))
            previous_version = normalize_space(existing_validation.get("validator_version"))
            previous_decision = self._decision_of(existing_validation)

        if (
            existing_validation
            and previous_fingerprint == fingerprint
            and previous_version == HOTFIX_VERSION
            and previous_decision in VALID_DECISIONS
        ):
            reused = copy.deepcopy(existing_validation)
            reused_metadata = dict(reused.get("validation_metadata") or {})
            reused_metadata.update(
                {
                    "hotfix_version": HOTFIX_VERSION,
                    "action": "REUSED_UNCHANGED",
                    "extraction_fingerprint": fingerprint,
                    "previous_extraction_fingerprint": previous_fingerprint,
                    "checked_at": now,
                    "run_id": run_id,
                }
            )
            reused["validation_metadata"] = reused_metadata
            audit = {
                "run_id": run_id,
                "master_id": extraction_record.get("master_id"),
                "scheme_name": extraction_record.get("scheme_name"),
                "source": extraction_record.get("source"),
                "action": "REUSED_UNCHANGED",
                "previous_decision": previous_decision,
                "current_decision": previous_decision,
                "previous_extraction_fingerprint": previous_fingerprint,
                "current_extraction_fingerprint": fingerprint,
                "validation_score": reused.get("validation_score"),
                "programme_status": reused.get("programme_status"),
                "checked_at": now,
                "validator_version": HOTFIX_VERSION,
            }
            return reused, audit

        if not existing_validation:
            action = "VALIDATED_NEW"
        elif not previous_fingerprint:
            action = "REVALIDATED_MISSING_FINGERPRINT"
        elif previous_version != HOTFIX_VERSION:
            action = "REVALIDATED_RULES_CHANGED"
        else:
            action = "REVALIDATED_EXTRACTION_CHANGED"

        decision, score, programme_status, reasons, checks = self._decide(extraction_record)
        validated = copy.deepcopy(extraction_record)
        validated.update(
            {
                "validation_decision": decision,
                "decision": decision,
                "validation_score": score,
                "validation_reasons": reasons,
                "validation_checks": checks,
                "programme_status": programme_status,
                "validated_at": now,
                "validator_version": HOTFIX_VERSION,
                "validation_metadata": {
                    "hotfix_version": HOTFIX_VERSION,
                    "action": action,
                    "extraction_fingerprint": fingerprint,
                    "previous_extraction_fingerprint": previous_fingerprint or None,
                    "previous_decision": previous_decision or None,
                    "checked_at": now,
                    "run_id": run_id,
                },
            }
        )
        audit = {
            "run_id": run_id,
            "master_id": extraction_record.get("master_id"),
            "scheme_name": extraction_record.get("scheme_name"),
            "source": extraction_record.get("source"),
            "action": action,
            "previous_decision": previous_decision or None,
            "current_decision": decision,
            "previous_extraction_fingerprint": previous_fingerprint or None,
            "current_extraction_fingerprint": fingerprint,
            "validation_score": score,
            "programme_status": programme_status,
            "validation_reasons": reasons,
            "checked_at": now,
            "validator_version": HOTFIX_VERSION,
        }
        return validated, audit

    @staticmethod
    def _with_inferred_decision(record: dict[str, Any], decision: str) -> dict[str, Any]:
        result = copy.deepcopy(record)
        if not MeityIncrementalValidationV24._decision_of(result):
            result["validation_decision"] = decision
            result["decision"] = decision
        return result

    @staticmethod
    def _load_list(path: Path) -> list[dict[str, Any]]:
        payload = load_json(path, default=[])
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _first_existing(data_dir: Path, names: Iterable[str]) -> Path | None:
        for name in names:
            path = data_dir / name
            if path.exists():
                return path
        return None

    def _generic_existing_file(
        self,
        *,
        include_any: tuple[str, ...],
        exclude_any: tuple[str, ...] = (),
    ) -> Path | None:
        candidates: list[Path] = []
        for path in self.data_dir.glob("*.json"):
            name = path.name.casefold()
            if "v2_4" in name or "v2.4" in name:
                continue
            if not any(token in name for token in include_any):
                continue
            if any(token in name for token in exclude_any):
                continue
            candidates.append(path)
        candidates.sort(key=lambda item: ("v1" not in item.name.casefold(), item.name.casefold()))
        return candidates[0] if candidates else None

    def _discover_existing_validation_paths(self) -> dict[str, Path | None]:
        unified = self._first_existing(self.data_dir, PREFERRED_VALIDATION_FILES)
        if unified is None:
            unified = self._generic_existing_file(
                include_any=("validated", "validation_record", "validation_result"),
                exclude_any=("summary", "audit", "failure", "approved", "review", "reject"),
            )

        approved = self._first_existing(self.data_dir, PREFERRED_APPROVED_FILES)
        if approved is None:
            approved = self._generic_existing_file(
                include_any=("approved",),
                exclude_any=("summary", "audit", "failure"),
            )

        review = self._first_existing(self.data_dir, PREFERRED_REVIEW_FILES)
        if review is None:
            review = self._generic_existing_file(
                include_any=("review_queue", "admin_review", "needs_review"),
                exclude_any=("summary", "audit", "failure"),
            )

        rejected = self._first_existing(self.data_dir, PREFERRED_REJECTED_FILES)
        if rejected is None:
            rejected = self._generic_existing_file(
                include_any=("rejected", "rejection"),
                exclude_any=("summary", "audit", "failure"),
            )

        audit = self._first_existing(self.data_dir, PREFERRED_AUDIT_FILES)
        if audit is None:
            audit = self._generic_existing_file(
                include_any=("validation_audit",),
                exclude_any=("summary", "failure"),
            )

        return {
            "unified": unified,
            "approved": approved,
            "review": review,
            "rejected": rejected,
            "audit": audit,
        }

    def _load_existing_validations(
        self,
        *,
        explicit_unified_path: Path | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Path | None], list[dict[str, Any]]]:
        discovered = self._discover_existing_validation_paths()
        if explicit_unified_path is not None:
            discovered["unified"] = explicit_unified_path

        records: list[dict[str, Any]] = []
        unified_records: list[dict[str, Any]] = []
        unified = discovered.get("unified")
        if unified and unified.exists():
            unified_records = self._load_list(unified)

        category_records: dict[str, list[dict[str, Any]]] = {
            "approved": [],
            "review": [],
            "rejected": [],
        }
        category_specs = (
            ("approved", DECISION_APPROVED),
            ("review", DECISION_ADMIN_REVIEW),
            ("rejected", DECISION_REJECTED),
        )
        category_keys: dict[str, set[tuple[str, str, str]]] = {
            "approved": set(),
            "review": set(),
            "rejected": set(),
        }
        for category, fallback_decision in category_specs:
            path = discovered.get(category)
            if not path or not path.exists():
                continue
            for record in self._load_list(path):
                decision = self._decision_of(record) or fallback_decision
                normalised = self._with_inferred_decision(record, decision)
                category_records[category].append(normalised)
                category_keys[category].add(self._record_key(normalised))

        # Some v1 deployments stored all validation records in the unified file,
        # wrote only the review/rejected category files, and omitted an approved
        # category file. In that layout, records in the unified file which are not
        # present in review/rejected are the approved set. Infer that decision so
        # prior approved records are not silently dropped from merged counts.
        has_partition_evidence = bool(
            (discovered.get("review") and discovered["review"].exists())
            or (discovered.get("rejected") and discovered["rejected"].exists())
            or (discovered.get("approved") and discovered["approved"].exists())
        )
        for record in unified_records:
            key = self._record_key(record)
            decision = self._decision_of(record)
            if not decision:
                if key in category_keys["approved"]:
                    decision = DECISION_APPROVED
                elif key in category_keys["review"]:
                    matching = next(
                        (item for item in category_records["review"] if self._record_key(item) == key),
                        None,
                    )
                    decision = self._decision_of(matching or {}) or DECISION_ADMIN_REVIEW
                elif key in category_keys["rejected"]:
                    decision = DECISION_REJECTED
                elif has_partition_evidence:
                    decision = DECISION_APPROVED
            records.append(self._with_inferred_decision(record, decision) if decision else copy.deepcopy(record))

        for category in ("approved", "review", "rejected"):
            records.extend(category_records[category])

        # Deduplicate records that may occur in both unified and split outputs.
        best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        order: list[tuple[str, str, str]] = []
        for record in records:
            key = self._record_key(record)
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = record
                order.append(key)
                continue
            # Prefer the richer record and one with an explicit recognised decision.
            existing_decision = self._decision_of(existing)
            current_decision = self._decision_of(record)
            existing_score = len(existing) + (20 if existing_decision else 0)
            current_score = len(record) + (20 if current_decision else 0)
            if current_score > existing_score or (
                current_decision and not existing_decision
            ):
                best_by_key[key] = record

        audit_path = discovered.get("audit")
        existing_audit = self._load_list(audit_path) if audit_path and audit_path.exists() else []
        return [best_by_key[key] for key in order], discovered, existing_audit

    def _merge_records(
        self,
        *,
        existing_records: list[dict[str, Any]],
        processed_by_key: dict[tuple[str, str, str], dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, int]:
        merged: list[dict[str, Any]] = []
        consumed: set[tuple[str, str, str]] = set()
        non_meity_preserved = 0
        orphaned_meity_preserved = 0

        for existing in existing_records:
            key = self._record_key(existing)
            replacement = processed_by_key.get(key)
            if replacement is not None:
                merged.append(replacement)
                consumed.add(key)
            else:
                merged.append(copy.deepcopy(existing))
                if self._is_meity_record(existing):
                    orphaned_meity_preserved += 1
                else:
                    non_meity_preserved += 1

        for key, record in processed_by_key.items():
            if key not in consumed:
                merged.append(record)

        # Final duplicate guard.
        deduplicated: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for record in merged:
            key = self._record_key(record)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(record)

        deduplicated.sort(
            key=lambda item: (
                normalize_space(item.get("source")),
                normalize_space(item.get("scheme_name")),
            )
        )
        return deduplicated, non_meity_preserved, orphaned_meity_preserved

    @staticmethod
    def _partition(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        approved: list[dict[str, Any]] = []
        review: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for record in records:
            decision = MeityIncrementalValidationV24._decision_of(record)
            if decision == DECISION_APPROVED:
                approved.append(record)
            elif decision in REVIEW_DECISIONS:
                review.append(record)
            elif decision == DECISION_REJECTED:
                rejected.append(record)
        return approved, review, rejected

    @staticmethod
    def _backup_and_write(path: Path, payload: Any) -> Path | None:
        backup_path: Path | None = None
        if path.exists():
            backup_path = path.with_name(f"{path.stem}.pre_v2_4_backup{path.suffix}")
            shutil.copy2(path, backup_path)
        atomic_write_json(path, payload)
        return backup_path

    def run(
        self,
        *,
        extracted_records_path: Path | None = None,
        existing_validations_path: Path | None = None,
        output_dir: Path | None = None,
        limit: int | None = None,
        publish_canonical: bool | None = None,
    ) -> MeityValidationRunResult:
        extracted_records_path = (
            extracted_records_path or self.data_dir / "extracted_scheme_records_v1.json"
        )
        output_dir = output_dir or self.data_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex

        extracted_records = load_json(extracted_records_path, default=None)
        if not isinstance(extracted_records, list):
            raise ValueError(
                f"Expected a JSON list in {extracted_records_path}, got "
                f"{type(extracted_records).__name__ if extracted_records is not None else 'missing file'}"
            )
        extracted_records = [item for item in extracted_records if isinstance(item, dict)]

        existing_records, discovered_paths, existing_audit = self._load_existing_validations(
            explicit_unified_path=existing_validations_path,
        )
        existing_by_key = {self._record_key(record): record for record in existing_records}

        meity_extracted = [record for record in extracted_records if self._is_meity_record(record)]
        meity_extracted.sort(
            key=lambda item: (
                0 if normalize_space(item.get("master_current_status")) == "ACTIVE_CALL_OPEN" else 1,
                normalize_space(item.get("scheme_name")),
            )
        )
        if limit is not None and limit >= 0:
            meity_extracted = meity_extracted[:limit]

        processed_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        audit: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for extraction_record in meity_extracted:
            key = self._record_key(extraction_record)
            try:
                validated, audit_item = self._validate_record(
                    extraction_record=extraction_record,
                    existing_validation=existing_by_key.get(key),
                    run_id=run_id,
                )
                processed_by_key[key] = validated
                audit.append(audit_item)
            except Exception as exc:
                logger.exception(
                    "MeitY validation failed for %s",
                    normalize_space(extraction_record.get("scheme_name")),
                )
                failure = {
                    "run_id": run_id,
                    "master_id": extraction_record.get("master_id"),
                    "scheme_name": extraction_record.get("scheme_name"),
                    "source": extraction_record.get("source"),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                    "failed_at": utc_now_iso(),
                    "validator_version": HOTFIX_VERSION,
                }
                failures.append(failure)
                previous = existing_by_key.get(key)
                if previous is not None:
                    processed_by_key[key] = copy.deepcopy(previous)
                    audit.append(
                        {
                            "run_id": run_id,
                            "master_id": extraction_record.get("master_id"),
                            "scheme_name": extraction_record.get("scheme_name"),
                            "source": extraction_record.get("source"),
                            "action": "RETAINED_AFTER_VALIDATION_FAILURE",
                            "previous_decision": self._decision_of(previous),
                            "current_decision": self._decision_of(previous),
                            "checked_at": utc_now_iso(),
                            "validator_version": HOTFIX_VERSION,
                        }
                    )

        merged, non_meity_preserved, orphaned_meity_preserved = self._merge_records(
            existing_records=existing_records,
            processed_by_key=processed_by_key,
        )
        approved, review, rejected = self._partition(merged)
        meity_records = [record for record in merged if self._is_meity_record(record)]

        action_by_key = {
            self._record_key(item): normalize_space(item.get("action")) for item in audit
        }
        loader_actions = {
            "VALIDATED_NEW",
            "REVALIDATED_MISSING_FINGERPRINT",
            "REVALIDATED_RULES_CHANGED",
            "REVALIDATED_EXTRACTION_CHANGED",
        }
        incremental_meity_records = [
            record
            for key, record in processed_by_key.items()
            if action_by_key.get(key) in loader_actions
        ]
        incremental_approved, incremental_review, incremental_rejected = self._partition(
            incremental_meity_records
        )

        versioned_paths = {
            "validated": output_dir / str(self.config["versioned_validated_filename"]),
            "approved": output_dir / str(self.config["versioned_approved_filename"]),
            "review": output_dir / str(self.config["versioned_review_filename"]),
            "rejected": output_dir / str(self.config["versioned_rejected_filename"]),
            "audit": output_dir / str(self.config["versioned_audit_filename"]),
            "failures": output_dir / str(self.config["versioned_failures_filename"]),
            "summary": output_dir / str(self.config["versioned_summary_filename"]),
        }

        publish = (
            bool(self.config.get("publish_canonical", True))
            if publish_canonical is None
            else publish_canonical
        )

        canonical_paths: dict[str, Path] = {
            "validated": discovered_paths.get("unified")
            or self.data_dir / str(self.config["canonical_validated_filename"]),
            "approved": discovered_paths.get("approved")
            or self.data_dir / str(self.config["canonical_approved_filename"]),
            "review": discovered_paths.get("review")
            or self.data_dir / str(self.config["canonical_review_filename"]),
            "rejected": discovered_paths.get("rejected")
            or self.data_dir / str(self.config["canonical_rejected_filename"]),
            "audit": discovered_paths.get("audit")
            or self.data_dir / str(self.config["canonical_audit_filename"]),
        }

        summary = {
            "hotfix_version": HOTFIX_VERSION,
            "run_id": run_id,
            "source": MEITY_SOURCE_NAME,
            "as_of_date": self.as_of_date.isoformat(),
            "input_extracted_record_count": len(extracted_records),
            "meity_extracted_record_count": len(meity_extracted),
            "existing_validation_record_count": len(existing_records),
            "existing_meity_validation_count": sum(
                1 for record in existing_records if self._is_meity_record(record)
            ),
            "existing_non_meity_validation_count": sum(
                1 for record in existing_records if not self._is_meity_record(record)
            ),
            "processed_meity_validation_count": len(processed_by_key),
            "actionable_meity_validation_count": len(incremental_meity_records),
            "unchanged_meity_loader_suppressed_count": len(processed_by_key)
            - len(incremental_meity_records),
            "output_validation_record_count": len(merged),
            "output_meity_validation_count": len(meity_records),
            "non_meity_validation_records_preserved": non_meity_preserved,
            "orphaned_meity_validation_records_preserved": orphaned_meity_preserved,
            "failure_count": len(failures),
            "actions": dict(Counter(item.get("action") for item in audit)),
            "decisions": dict(
                Counter(self._decision_of(record) or "DECISION_MISSING" for record in meity_records)
            ),
            "programme_status": dict(
                Counter(
                    normalize_space(record.get("programme_status")) or "STATUS_MISSING"
                    for record in meity_records
                )
            ),
            "quality_flags": dict(
                Counter(
                    flag
                    for record in meity_records
                    for flag in (record.get("quality_flags") or [])
                )
            ),
            "approved_for_database_count": len(incremental_approved),
            "admin_review_queue_count": len(incremental_review),
            "rejected_count": len(incremental_rejected),
            "meity_approved_for_database_count": len(incremental_approved),
            "meity_admin_review_queue_count": len(incremental_review),
            "meity_rejected_count": len(incremental_rejected),
            "merged_approved_for_database_count": len(approved),
            "merged_admin_review_queue_count": len(review),
            "merged_rejected_count": len(rejected),
            "incremental_loader_input_is_meity_only": True,
            "average_meity_validation_score": round(
                sum(float(record.get("validation_score") or 0.0) for record in meity_records)
                / len(meity_records),
                3,
            )
            if meity_records
            else 0.0,
            "input_path": str(extracted_records_path),
            "existing_validation_paths": {
                key: str(value) if value else None for key, value in discovered_paths.items()
            },
            "versioned_output_paths": {
                key: str(value) for key, value in versioned_paths.items()
            },
            "canonical_output_paths": {
                "validated": str(canonical_paths["validated"]),
                "audit": str(canonical_paths["audit"]),
            }
            if publish
            else {},
            "legacy_category_files_published": bool(
                publish and self.config.get("publish_legacy_category_files", False)
            ),
            "generated_at": utc_now_iso(),
            "canonical_published": publish,
        }

        atomic_write_json(versioned_paths["validated"], merged)
        # Versioned category files are intentionally MeitY-only. They are safe
        # inputs for an incremental staging loader and cannot restage old sources.
        atomic_write_json(versioned_paths["approved"], incremental_approved)
        atomic_write_json(versioned_paths["review"], incremental_review)
        atomic_write_json(versioned_paths["rejected"], incremental_rejected)
        atomic_write_json(versioned_paths["audit"], audit)
        atomic_write_json(versioned_paths["failures"], failures)
        atomic_write_json(versioned_paths["summary"], summary)

        if publish:
            self._backup_and_write(canonical_paths["validated"], merged)
            self._backup_and_write(canonical_paths["audit"], existing_audit + audit)

            # The legacy v1 category files may already have been consumed by the
            # staging loader and admin-review UI. Rewriting them could requeue or
            # restage old records, so it is opt-in only. Use the MeitY-only v2.4
            # category files for incremental loading.
            if bool(self.config.get("publish_legacy_category_files", False)):
                self._backup_and_write(canonical_paths["approved"], approved)
                self._backup_and_write(canonical_paths["review"], review)
                self._backup_and_write(canonical_paths["rejected"], rejected)

        return MeityValidationRunResult(
            records=merged,
            meity_records=meity_records,
            approved_records=approved,
            review_records=review,
            rejected_records=rejected,
            failures=failures,
            audit=audit,
            summary=summary,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SSIP MeitY Incremental Validation v2.4")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="SSIP project root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional extracted scheme records JSON. Defaults to data/extracted_scheme_records_v1.json.",
    )
    parser.add_argument(
        "--existing-validation",
        type=Path,
        default=None,
        help="Optional unified existing validation JSON. Split v1 outputs are auto-detected when omitted.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for v2.4 outputs. Defaults to the project data directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of MeitY extraction records to validate.",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Generate versioned preview outputs without replacing canonical v1 validation files.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    agent = MeityIncrementalValidationV24(project_root=args.project_root)
    result = agent.run(
        extracted_records_path=args.input,
        existing_validations_path=args.existing_validation,
        output_dir=args.output_dir,
        limit=args.limit,
        publish_canonical=not args.no_publish,
    )
    print(json.dumps(result.summary, indent=2))


if __name__ == "__main__":
    main()
