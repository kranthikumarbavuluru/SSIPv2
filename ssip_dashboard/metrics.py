from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .funding import funding_summary, has_structured_funding
from .status import status_bucket
from .catalogue_populations import (
    primary_sector,
    primary_sector_counts,
    primary_support_type,
    primary_support_type_counts,
    split_catalogue_populations,
)


GOVERNMENT_LEVELS = ("Central Government", "State Government", "Unspecified")
MAIN_SCHEME_RECORD_KINDS = {
    "SCHEME",
    "PROGRAMME",
    "SCHEME_OR_PROGRAMME",
    "GRANT",
    "FUND",
    "CREDIT_SUPPORT",
    "CREDIT_GUARANTEE",
    "SUBSIDY",
    "INCENTIVE",
    "FELLOWSHIP",
    "INCUBATION_SUPPORT",
    "ACCELERATOR_SUPPORT",
    "INFRASTRUCTURE_SUPPORT",
    "RESEARCH_SUPPORT",
    "PROCUREMENT_SUPPORT",
    "GOVERNMENT_SERVICE",
    "ECOSYSTEM_OPPORTUNITY",
}


def record_kind(record: Any) -> str:
    return str(getattr(record, "record_kind", "") or "SCHEME_OR_PROGRAMME").strip().upper()


def explicit_count(records: list[Any], field_name: str) -> int:
    values = {
        str(getattr(record, field_name, "") or "").strip()
        for record in records
        if str(getattr(record, field_name, "") or "").strip()
    }
    return len(values)


def flattened_counter(records: list[Any], field_name: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        values = getattr(record, field_name, []) or []
        if isinstance(values, str):
            values = [values]
        for value in values:
            text = str(value or "").strip()
            if text:
                counter[text] += 1
    return counter


def scalar_counter(records: list[Any], field_name: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        value = str(getattr(record, field_name, "") or "").strip()
        if value:
            counter[value] += 1
    return counter


def is_rejected_record(record: Any) -> bool:
    return str(getattr(record, "current_decision", "") or "").strip().upper() == "REJECTED"


def visible_records(records: list[Any]) -> list[Any]:
    return [record for record in records if not is_rejected_record(record)]


@dataclass(frozen=True)
class DashboardMetrics:
    total_catalogue_records: int
    application_call_records: int
    evidence_or_directory_records: int
    total_explicit_ministries: int
    total_explicit_departments: int
    total_implementing_agencies: int
    total_source_organisations: int
    total_sectors: int
    total_grant_support_types: int
    open_records: int
    closing_soon_records: int
    upcoming_records: int
    verification_required_records: int
    closed_records: int
    historical_records: int
    records_with_funding_information: int
    records_missing_funding_information: int
    records_with_application_portals: int
    records_with_manuals_guidelines: int
    minimum_recorded_funding: int | None
    maximum_recorded_funding: int | None
    records_missing_ministry: int
    records_missing_department: int
    records_missing_sector: int


def compute_metrics(records: list[Any]) -> DashboardMetrics:
    populations = split_catalogue_populations(visible_records(records))
    scheme_records = populations.main_scheme_records
    application_call_records = populations.application_call_records

    bucket_counts = Counter(status_bucket(record) for record in scheme_records)
    funding = funding_summary(scheme_records)

    sector_values = {
        primary_sector(record)
        for record in scheme_records
        if primary_sector(record) != "Sector Not Specified"
    }
    support_values = {
        primary_support_type(record)
        for record in scheme_records
        if primary_support_type(record) != "SUPPORT_TYPE_NOT_SPECIFIED"
    }

    return DashboardMetrics(
        total_catalogue_records=len(scheme_records),
        application_call_records=len(application_call_records),
        evidence_or_directory_records=(
            len(populations.evidence_only_records)
            + len(populations.excluded_records)
        ),
        total_explicit_ministries=explicit_count(scheme_records, "ministry"),
        total_explicit_departments=explicit_count(scheme_records, "department"),
        total_implementing_agencies=explicit_count(
            scheme_records, "implementing_agency"
        ),
        total_source_organisations=explicit_count(scheme_records, "source"),
        total_sectors=len(sector_values),
        total_grant_support_types=len(support_values),
        open_records=bucket_counts["OPEN"],
        closing_soon_records=bucket_counts["CLOSING_SOON"],
        upcoming_records=bucket_counts["UPCOMING"],
        verification_required_records=bucket_counts["VERIFICATION_REQUIRED"],
        closed_records=bucket_counts["CLOSED"],
        historical_records=bucket_counts["HISTORICAL"],
        records_with_funding_information=funding["records_with_funding"],
        records_missing_funding_information=funding["records_missing_funding"],
        records_with_application_portals=sum(
            1 for record in scheme_records
            if getattr(record, "application_url", "")
        ),
        records_with_manuals_guidelines=sum(
            1 for record in scheme_records
            if getattr(record, "guideline_urls", [])
        ),
        minimum_recorded_funding=funding["minimum_recorded_funding"],
        maximum_recorded_funding=funding["maximum_recorded_funding"],
        records_missing_ministry=sum(
            1 for record in scheme_records
            if not str(getattr(record, "ministry", "") or "").strip()
        ),
        records_missing_department=sum(
            1 for record in scheme_records
            if not str(getattr(record, "department", "") or "").strip()
        ),
        records_missing_sector=sum(
            1 for record in scheme_records
            if primary_sector(record) == "Sector Not Specified"
        ),
    )


def latest_records(records: list[Any], *, limit: int = 5) -> list[Any]:
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    return sorted(
        main_records,
        key=lambda record: str(getattr(record, "last_updated", "") or ""),
        reverse=True,
    )[:limit]


def open_records(records: list[Any], *, limit: int | None = None) -> list[Any]:
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    output = [
        record
        for record in main_records
        if status_bucket(record) in {"OPEN", "CLOSING_SOON"}
    ]
    return output if limit is None else output[:limit]


def latest_update_records(records: list[Any], *, limit: int = 5) -> list[Any]:
    return latest_records(records, limit=limit)


def normalize_government_level(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if not text:
        return "Unspecified"
    if text in {"central", "central government", "union government", "national government"}:
        return "Central Government"
    if text in {"state", "state/ut", "state government", "state governments", "ut", "union territory"}:
        return "State Government"
    return "Unspecified"


def source_scope_lookup(sources: list[Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    conflicts: set[str] = set()
    for source in sources:
        level = normalize_government_level(getattr(source, "scope", ""))
        if level == "Unspecified":
            continue
        for field in ("name", "agency", "department", "ministry"):
            value = str(getattr(source, field, "") or "").strip()
            if not value:
                continue
            key = value.casefold()
            if key in lookup and lookup[key] != level:
                conflicts.add(key)
                continue
            lookup[key] = level
    for key in conflicts:
        lookup.pop(key, None)
    return lookup


def government_level(record: Any, lookup: dict[str, str] | None = None) -> str:
    explicit = normalize_government_level(getattr(record, "government_level", ""))
    if explicit != "Unspecified":
        return explicit
    lookup = lookup or {}
    for field in ("source", "implementing_agency", "department", "ministry"):
        value = str(getattr(record, field, "") or "").strip().casefold()
        if value and value in lookup:
            return lookup[value]
    return "Unspecified"


def government_level_coverage(
    records: list[Any],
    lookup: dict[str, str] | None = None,
) -> Counter[str]:
    counter: Counter[str] = Counter(
        {level: 0 for level in GOVERNMENT_LEVELS}
    )
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    for record in main_records:
        counter[government_level(record, lookup)] += 1
    return counter


def status_coverage(records: list[Any]) -> Counter[str]:
    counter: Counter[str] = Counter()
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    for record in main_records:
        counter[status_bucket(record)] += 1
    return counter


def department_coverage(records: list[Any]) -> Counter[str]:
    counter: Counter[str] = Counter()
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    for record in main_records:
        label = (
            str(getattr(record, "department", "") or "").strip()
            or str(getattr(record, "implementing_agency", "") or "").strip()
            or str(getattr(record, "source", "") or "").strip()
            or "Unspecified"
        )
        counter[label] += 1
    return counter


def sector_coverage(records: list[Any]) -> Counter[str]:
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    return primary_sector_counts(main_records)


def grant_support_distribution(records: list[Any]) -> Counter[str]:
    main_records = split_catalogue_populations(
        visible_records(records)
    ).main_scheme_records
    return primary_support_type_counts(main_records)


def resource_counts(records: list[Any]) -> dict[str, int]:
    records = visible_records(records)
    return {
        "application_portals": sum(1 for record in records if getattr(record, "application_url", "")),
        "manuals_guidelines": sum(1 for record in records if getattr(record, "guideline_urls", [])),
        "official_pages": sum(1 for record in records if getattr(record, "official_page_url", "")),
    }
