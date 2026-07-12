from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .catalogue_populations import (
    primary_sector,
    primary_support_type,
    split_catalogue_populations,
)
from .funding import has_structured_funding
from .metrics import government_level
from .status import status_bucket


MISSING_SECTOR = "Sector Not Specified"
MISSING_SUPPORT = "SUPPORT_TYPE_NOT_SPECIFIED"


@dataclass(frozen=True)
class ReadinessMeasure:
    label: str
    complete: int
    total: int

    @property
    def percentage(self) -> int:
        return 0 if self.total <= 0 else round((self.complete / self.total) * 100)


@dataclass(frozen=True)
class PublicAnalyticsSnapshot:
    scheme_count: int
    call_count: int
    open_call_windows: int
    closing_soon_calls: int
    verification_required_calls: int
    scheme_statuses: Counter[str]
    call_statuses: Counter[str]
    government_levels: Counter[str]
    departments: Counter[str]
    structured_sectors: Counter[str]
    structured_support_types: Counter[str]
    readiness: tuple[ReadinessMeasure, ...]
    latest_verification_signal: str


def _text(record: Any, field: str) -> str:
    if isinstance(record, dict):
        return str(record.get(field, "") or "").strip()
    return str(getattr(record, field, "") or "").strip()


def _department_label(record: Any) -> str:
    return (
        _text(record, "department")
        or _text(record, "implementing_agency")
        or _text(record, "source")
        or "Unspecified"
    )


def _latest_signal(records: list[Any]) -> str:
    values = [
        _text(record, "last_verified_at") or _text(record, "last_updated")
        for record in records
    ]
    values = [value for value in values if value]
    return max(values)[:10] if values else "Not available"


def build_public_analytics(
    records: list[Any],
    *,
    government_lookup: dict[str, str] | None = None,
) -> PublicAnalyticsSnapshot:
    populations = split_catalogue_populations(records)
    schemes = populations.main_scheme_records
    calls = populations.application_call_records
    scheme_statuses = Counter(status_bucket(record) for record in schemes)
    call_statuses = Counter(status_bucket(record) for record in calls)

    departments = Counter(_department_label(record) for record in schemes)
    sectors = Counter(primary_sector(record) for record in schemes)
    sectors.pop(MISSING_SECTOR, None)
    support_types = Counter(primary_support_type(record) for record in schemes)
    support_types.pop(MISSING_SUPPORT, None)

    total = len(schemes)
    readiness = (
        ReadinessMeasure("Ministry mapped", sum(bool(_text(record, "ministry")) for record in schemes), total),
        ReadinessMeasure("Department mapped", sum(bool(_text(record, "department")) for record in schemes), total),
        ReadinessMeasure("Sector evidenced", sum(primary_sector(record) != MISSING_SECTOR for record in schemes), total),
        ReadinessMeasure("Funding structured", sum(has_structured_funding(record) for record in schemes), total),
        ReadinessMeasure("Official page linked", sum(bool(_text(record, "official_page_url")) for record in schemes), total),
    )

    government_levels = Counter(
        government_level(record, government_lookup or {}) for record in schemes
    )
    for label in ("Central Government", "State Government", "Unspecified"):
        government_levels.setdefault(label, 0)

    return PublicAnalyticsSnapshot(
        scheme_count=total,
        call_count=len(calls),
        open_call_windows=call_statuses["OPEN"] + call_statuses["CLOSING_SOON"],
        closing_soon_calls=call_statuses["CLOSING_SOON"],
        verification_required_calls=call_statuses["VERIFICATION_REQUIRED"],
        scheme_statuses=scheme_statuses,
        call_statuses=call_statuses,
        government_levels=government_levels,
        departments=departments,
        structured_sectors=sectors,
        structured_support_types=support_types,
        readiness=readiness,
        latest_verification_signal=_latest_signal([*schemes, *calls]),
    )
