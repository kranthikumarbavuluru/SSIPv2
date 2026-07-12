from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationAssessment:
    category: str
    ready_for_approval: bool
    checks: tuple[dict[str, Any], ...]
    blocking_gaps: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed_checks(self) -> int:
        return sum(bool(check["passed"]) for check in self.checks)


def text(record: dict[str, Any], field: str) -> str:
    return str(record.get(field) or "").strip()


def values(record: dict[str, Any], field: str) -> list[Any]:
    value = record.get(field) or []
    return value if isinstance(value, list) else [value]


def record_category(record: dict[str, Any]) -> str:
    kind = text(record, "record_kind").upper()
    layer = text(record, "applicant_layer").upper()
    if kind in {"APPLICATION_CALL", "CHALLENGE"}:
        return "ECOSYSTEM_CALL" if layer == "INTERMEDIARY_IMPLEMENTER" else "APPLICATION_CALL"
    if kind in {"UMBRELLA_PROGRAMME"}:
        return "UMBRELLA_PROGRAMME"
    return "SCHEME_OR_PROGRAMME"


def verification_assessment(record: dict[str, Any]) -> VerificationAssessment:
    category = record_category(record)
    is_call = category in {"APPLICATION_CALL", "ECOSYSTEM_CALL"}
    status = text(record, "application_status").upper()
    source_evidence = [item for item in values(record, "source_evidence") if isinstance(item, dict) and item.get("url")]
    sectors = [str(item).strip() for item in values(record, "sector") if str(item).strip()]

    checks: list[dict[str, Any]] = []

    def add(code: str, label: str, passed: bool, required: bool, reason: str) -> None:
        checks.append({"code": code, "label": label, "passed": passed, "required": required, "reason": reason})

    add("IDENTITY", "Stable identity and name", bool(text(record, "master_id") and text(record, "scheme_name")), True,
        "master_id and scheme_name are required.")
    add("AUTHORITY", "Government authority", bool(text(record, "department") or text(record, "implementing_agency") or text(record, "source")), True,
        "A department, implementing agency or authoritative source is required.")
    add("OFFICIAL_URL", "Official primary page", text(record, "official_page_url").startswith(("http://", "https://")), True,
        "Approval requires an official HTTP(S) page.")
    add("SOURCE_EVIDENCE", "Stored source evidence", bool(source_evidence), True,
        "At least one official evidence URL must be stored.")
    add("RECORD_KIND", "Scheme/call classification", bool(text(record, "record_kind")), True,
        "The record must be explicitly classified as a scheme, programme or call.")

    if is_call:
        status_supported = bool(status) and (
            status not in {"OPEN", "UPCOMING"}
            or bool(text(record, "status_evidence"))
            or bool(text(record, "closing_date"))
        )
        add("CALL_STATUS", "Application status evidence", status_supported, True,
            "Open/upcoming calls require a closing date or explicit official status evidence.")
        add("APPLICANT_LAYER", "Direct versus intermediary applicant", bool(text(record, "applicant_layer")), True,
            "The applicant layer must distinguish founder opportunities from ecosystem calls.")
        parent_resolved = bool(text(record, "parent_master_id")) or text(record, "parent_resolution").upper() in {
            "CURATED_OFFICIAL_RELATIONSHIP", "MONITORED_OFFICIAL_RELATIONSHIP", "STANDALONE_OFFICIAL_CALL"
        }
        add("PARENT_RELATIONSHIP", "Permanent parent or standalone basis", parent_resolved, True,
            "A call needs a verified permanent parent or an explicit standalone-call decision.")
        if status == "OPEN":
            add("APPLICATION_ROUTE", "Current application route", bool(text(record, "application_url")), True,
                "An open call requires a current official application URL.")

    add("SECTOR", "Sector evidence", bool(sectors) or text(record, "sector_scope").upper() == "AGNOSTIC", False,
        "Sector remains unknown; retain UNKNOWN rather than inferring agnostic.")
    add("VERIFIED_DATE", "Last verification date", bool(text(record, "last_verified_at")), False,
        "Store when official evidence was last checked.")

    blocking = tuple(check["reason"] for check in checks if check["required"] and not check["passed"])
    warnings = tuple(check["reason"] for check in checks if not check["required"] and not check["passed"])
    return VerificationAssessment(
        category=category,
        ready_for_approval=not blocking,
        checks=tuple(checks),
        blocking_gaps=blocking,
        warnings=warnings,
    )
