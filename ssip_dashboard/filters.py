from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .funding import structured_funding_values
from .status import parse_date, status_bucket


@dataclass
class FilterState:
    keyword: str = ""
    ministries: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    agencies: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    applicant_types: list[str] = field(default_factory=list)
    startup_stages: list[str] = field(default_factory=list)
    scheme_types: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    min_funding: int | None = None
    max_funding: int | None = None
    opening_from: date | None = None
    closing_to: date | None = None
    include_archived: bool = True
    include_verification_required: bool = True


def unique_options(records: list[Any], field_name: str) -> list[str]:
    options: set[str] = set()
    for record in records:
        value = getattr(record, field_name, "")
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text:
                options.add(text)
    return sorted(options, key=str.casefold)


def intersects(record_values: list[str], selected: list[str]) -> bool:
    if not selected:
        return True
    selected_keys = {item.casefold() for item in selected}
    return any(str(value).casefold() in selected_keys for value in record_values)


def record_matches_funding(record: Any, minimum: int | None, maximum: int | None) -> bool:
    if minimum is None and maximum is None:
        return True
    values = structured_funding_values(record)
    if not values:
        return False
    if minimum is not None and max(values) < minimum:
        return False
    if maximum is not None and min(values) > maximum:
        return False
    return True


def apply_filters(records: list[Any], state: FilterState) -> list[Any]:
    keyword = state.keyword.strip().casefold()
    output: list[Any] = []

    for record in records:
        bucket = status_bucket(record)
        if keyword and keyword not in getattr(record, "search_blob", ""):
            continue
        if state.ministries and getattr(record, "ministry", "") not in state.ministries:
            continue
        if state.departments and getattr(record, "department", "") not in state.departments:
            continue
        if state.agencies and getattr(record, "implementing_agency", "") not in state.agencies:
            continue
        if not intersects(getattr(record, "sectors", []) or [], state.sectors):
            continue
        if not intersects(getattr(record, "target_beneficiaries", []) or [], state.applicant_types):
            continue
        if not intersects(getattr(record, "startup_stage", []) or [], state.startup_stages):
            continue
        if not intersects(getattr(record, "scheme_types", []) or [], state.scheme_types):
            continue
        if state.statuses and bucket not in state.statuses:
            continue
        if not state.include_archived and bucket in {"CLOSED", "HISTORICAL"}:
            continue
        if not state.include_verification_required and bucket == "VERIFICATION_REQUIRED":
            continue
        if not record_matches_funding(record, state.min_funding, state.max_funding):
            continue

        opening = parse_date(getattr(record, "opening_date", None))
        closing = parse_date(getattr(record, "closing_date", None))
        if state.opening_from and opening and opening < state.opening_from:
            continue
        if state.closing_to and closing and closing > state.closing_to:
            continue
        output.append(record)

    return output
