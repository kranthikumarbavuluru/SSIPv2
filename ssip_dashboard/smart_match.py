from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .funding import structured_funding_values
from .status import status_bucket


@dataclass
class MatchProfile:
    applicant_types: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    startup_stages: list[str] = field(default_factory=list)
    geographic_scope: str = ""
    funding_requirement: int | None = None
    include_closed: bool = False
    include_verification_required: bool = True


@dataclass
class MatchResult:
    record: Any
    score: int
    matched_fields: list[str]
    unmatched_requirements: list[str]
    reasons: list[str]
    missing_data_warnings: list[str]


def normalize_values(values: list[str]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def overlap_score(
    user_values: list[str],
    record_values: list[str],
    *,
    field_name: str,
    weight: int,
) -> tuple[int, str | None, str | None, str | None]:
    user = normalize_values(user_values)
    if not user:
        return 0, None, None, None
    record = normalize_values(record_values)
    if not record:
        return 0, None, field_name, f"{field_name} data is missing for this record."
    overlap = user & record
    if overlap:
        return weight, field_name, None, None
    return 0, None, field_name, None


def score_record(record: Any, profile: MatchProfile) -> MatchResult:
    bucket = status_bucket(record)
    matched: list[str] = []
    unmatched: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []
    score = 0

    if bucket in {"OPEN", "CLOSING_SOON"}:
        score += 15
        matched.append("application status")
        reasons.append("The opportunity is currently actionable in the catalogue status data.")
    elif bucket in {"CLOSED", "HISTORICAL"}:
        if not profile.include_closed:
            unmatched.append("application status")
            reasons.append("The record is closed or historical, so it is useful for reference rather than immediate application.")
        else:
            score += 3
            reasons.append("Closed and historical records are included by your preference.")
    elif bucket == "VERIFICATION_REQUIRED":
        if profile.include_verification_required:
            score += 5
            warnings.append("Application status requires verification before acting.")
        else:
            unmatched.append("application status")
    elif bucket == "UPCOMING":
        score += 10
        matched.append("application status")
        reasons.append("The record appears upcoming based on structured status/date data.")

    for points, match_field, missing_field, warning in [
        overlap_score(
            profile.applicant_types,
            getattr(record, "target_beneficiaries", []) + getattr(record, "eligibility", []),
            field_name="applicant type",
            weight=25,
        ),
        overlap_score(
            profile.sectors,
            getattr(record, "sectors", []),
            field_name="sector",
            weight=25,
        ),
        overlap_score(
            profile.startup_stages,
            getattr(record, "startup_stage", []),
            field_name="startup stage",
            weight=20,
        ),
    ]:
        score += points
        if match_field:
            matched.append(match_field)
            reasons.append(f"Matched {match_field} against structured catalogue fields.")
        if missing_field:
            unmatched.append(missing_field)
        if warning:
            warnings.append(warning)

    if profile.geographic_scope:
        record_scope = str(getattr(record, "geographic_scope", "") or "").casefold()
        desired_scope = profile.geographic_scope.casefold()
        if not record_scope:
            warnings.append("Geographic scope data is missing for this record.")
        elif desired_scope in record_scope or "national" in record_scope:
            score += 10
            matched.append("geographic scope")
            reasons.append("Geographic scope appears compatible.")
        else:
            unmatched.append("geographic scope")

    if profile.funding_requirement:
        values = structured_funding_values(record)
        if not values:
            warnings.append("Structured funding data is missing for this record.")
        elif max(values) >= profile.funding_requirement:
            score += 5
            matched.append("funding requirement")
            reasons.append("Recorded structured funding can meet or exceed the requested amount.")
        else:
            unmatched.append("funding requirement")

    if not reasons:
        reasons.append("No strong structured match was found; review the official source before acting.")

    return MatchResult(
        record=record,
        score=max(0, min(score, 100)),
        matched_fields=sorted(set(matched)),
        unmatched_requirements=sorted(set(unmatched)),
        reasons=reasons,
        missing_data_warnings=sorted(set(warnings)),
    )


def explainable_smart_match(
    records: list[Any],
    profile: MatchProfile,
    *,
    limit: int = 10,
) -> list[MatchResult]:
    candidates: list[MatchResult] = []
    for record in records:
        bucket = status_bucket(record)
        if bucket in {"CLOSED", "HISTORICAL"} and not profile.include_closed:
            continue
        if bucket == "VERIFICATION_REQUIRED" and not profile.include_verification_required:
            continue
        candidates.append(score_record(record, profile))
    return sorted(
        candidates,
        key=lambda result: (result.score, result.record.scheme_name.casefold()),
        reverse=True,
    )[:limit]
