from __future__ import annotations

from datetime import date, timedelta
from typing import Any


OPEN_STATUSES = {"OPEN", "OPEN_FOR_APPLICATIONS", "ACTIVE_APPLICATION_WINDOW"}
UPCOMING_STATUSES = {"UPCOMING", "COMING_SOON", "ANNOUNCED"}
VERIFICATION_MARKERS = {
    "DEADLINE_UNVERIFIED",
    "STATUS_UNVERIFIED",
    "CALL_STATUS_CONFLICT_REQUIRES_REVIEW",
}


def clean_token(value: Any) -> str:
    return str(value or "").strip().upper()


def is_closed_record(record: Any) -> bool:
    status = clean_token(getattr(record, "application_status", ""))
    section = clean_token(getattr(record, "catalogue_section", ""))
    return "CLOSED" in status or "CLOSED" in section


def is_historical_record(record: Any) -> bool:
    section = clean_token(getattr(record, "catalogue_section", ""))
    return "HISTORICAL" in section


def requires_verification(record: Any) -> bool:
    status = clean_token(getattr(record, "application_status", ""))
    inclusion = clean_token(getattr(record, "catalogue_inclusion", ""))
    section = clean_token(getattr(record, "catalogue_section", ""))
    if inclusion == "PENDING_REVALIDATION" or "VERIFICATION" in section:
        return True
    return any(marker in status for marker in VERIFICATION_MARKERS)


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def status_bucket(
    record: Any,
    *,
    today: date | None = None,
    closing_soon_days: int = 30,
) -> str:
    status = clean_token(getattr(record, "application_status", ""))
    today = today or date.today()
    opening = parse_date(getattr(record, "opening_date", None))
    closing = parse_date(getattr(record, "closing_date", None))

    if is_historical_record(record):
        return "HISTORICAL"
    if is_closed_record(record):
        return "CLOSED"
    if requires_verification(record):
        return "VERIFICATION_REQUIRED"
    if closing is not None and closing < today:
        return "CLOSED"
    if status in OPEN_STATUSES:
        if closing is not None and closing <= today + timedelta(days=closing_soon_days):
            return "CLOSING_SOON"
        return "OPEN"
    if status in UPCOMING_STATUSES or (opening is not None and opening > today):
        return "UPCOMING"
    return "REFERENCE"


def status_label(record: Any) -> str:
    labels = {
        "OPEN": "Open Now",
        "CLOSING_SOON": "Closing Soon",
        "UPCOMING": "Upcoming",
        "VERIFICATION_REQUIRED": "Verification Required",
        "CLOSED": "Closed",
        "HISTORICAL": "Historical",
        "REFERENCE": "Reference",
    }
    return labels.get(status_bucket(record), "Reference")


def status_css_class(record: Any) -> str:
    return {
        "OPEN": "status-open",
        "CLOSING_SOON": "status-upcoming",
        "UPCOMING": "status-upcoming",
        "VERIFICATION_REQUIRED": "status-warning",
        "CLOSED": "status-closed",
        "HISTORICAL": "status-history",
        "REFERENCE": "status-reference",
    }.get(status_bucket(record), "status-reference")
