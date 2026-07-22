from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Iterable
from urllib.parse import urlsplit

from .catalogue import CatalogueRecord


MSME_OFFICIAL_HOSTS = {
    "apmsmeone.ap.gov.in",
    "champions.gov.in",
    "dcmsme.gov.in",
    "msme.gov.in",
    "nsic.co.in",
}
CALL_KINDS = {"APPLICATION_CALL", "CHALLENGE"}
CURRENT_STATUSES = {"OPEN", "UPCOMING"}
HISTORICAL_STATUSES = {"CLOSED", "CLOSED_OR_HISTORICAL", "ARCHIVED", "HISTORICAL"}
DIRECTORY_TITLES = {
    "existing schemes.aspx",
    "new schemes.aspx",
    "register challenge.aspx",
    "schemes",
    "schemes for starters.aspx",
    "schemes.aspx",
    "view challenge.aspx",
}


@dataclass(frozen=True)
class MSMEPublicBundle:
    permanent_records: tuple[CatalogueRecord, ...]
    current_calls: tuple[CatalogueRecord, ...]
    historical_records: tuple[CatalogueRecord, ...]
    documents: tuple[CatalogueRecord, ...]
    excluded_count: int
    latest_verification_date: str

    @property
    def public_records(self) -> tuple[CatalogueRecord, ...]:
        return (
            *self.permanent_records,
            *self.current_calls,
            *self.historical_records,
        )


def _text(record: CatalogueRecord) -> str:
    return " ".join(
        (
            record.ministry,
            record.department,
            record.implementing_agency,
            record.source,
        )
    ).casefold()


def is_msme_owned(record: CatalogueRecord) -> bool:
    ownership = _text(record)
    return is_official_msme_url(record.official_page_url) and any(
        marker in ownership
        for marker in (
            "ap msme one",
            "andhra pradesh",
            "micro, small and medium enterprises",
            "national small industries corporation",
            "msme champions",
            "dc msme",
        )
    )


def is_official_msme_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().strip(".")
    return parsed.scheme in {"http", "https"} and any(
        host == allowed or host.endswith("." + allowed)
        for allowed in MSME_OFFICIAL_HOSTS
    )


def is_supporting_document(record: CatalogueRecord) -> bool:
    title = record.scheme_name.casefold().strip()
    path = urlsplit(record.official_page_url).path.casefold()
    return title.endswith((".pdf", ".xml")) or path.endswith((".pdf", ".xml"))


def is_directory_or_index(record: CatalogueRecord) -> bool:
    return record.scheme_name.casefold().strip() in DIRECTORY_TITLES


def _verified_date(value: str) -> str:
    candidate = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return ""


def _safe_public_record(record: CatalogueRecord, *, keep_application: bool = False) -> CatalogueRecord:
    application_url = record.application_url if (
        keep_application and is_official_msme_url(record.application_url)
    ) else ""
    return replace(record, application_url=application_url)


def _is_verified_current_call(record: CatalogueRecord) -> bool:
    closing_date = _verified_date(record.closing_date)
    return (
        record.record_kind.upper() in CALL_KINDS
        and record.application_status.upper() in CURRENT_STATUSES
        and bool(record.status_evidence.strip())
        and (not closing_date or closing_date >= date.today().isoformat())
    )


def build_msme_public_bundle(records: Iterable[CatalogueRecord]) -> MSMEPublicBundle:
    owned = [
        record
        for record in records
        if is_msme_owned(record) and is_official_msme_url(record.official_page_url)
    ]
    permanent: list[CatalogueRecord] = []
    current: list[CatalogueRecord] = []
    historical: list[CatalogueRecord] = []
    documents: list[CatalogueRecord] = []
    excluded = 0

    for record in owned:
        status = record.application_status.upper()
        kind = record.record_kind.upper()
        if is_supporting_document(record):
            documents.append(_safe_public_record(record))
        elif is_directory_or_index(record):
            excluded += 1
        elif status in HISTORICAL_STATUSES:
            historical.append(_safe_public_record(record))
        elif _is_verified_current_call(record):
            current.append(_safe_public_record(record, keep_application=True))
        elif kind in CALL_KINDS:
            excluded += 1
        else:
            permanent.append(_safe_public_record(record))

    sort_key = lambda item: item.scheme_name.casefold()
    permanent.sort(key=sort_key)
    current.sort(key=sort_key)
    historical.sort(key=sort_key)
    documents.sort(key=sort_key)

    verification_dates = [
        parsed
        for record in (*permanent, *current, *historical)
        if (parsed := _verified_date(record.last_verified_at or record.last_updated))
    ]
    return MSMEPublicBundle(
        permanent_records=tuple(permanent),
        current_calls=tuple(current),
        historical_records=tuple(historical),
        documents=tuple(documents),
        excluded_count=excluded,
        latest_verification_date=max(verification_dates) if verification_dates else "Not recorded",
    )


def filter_msme_records(
    records: Iterable[CatalogueRecord],
    *,
    keyword: str = "",
    agency: str = "All",
    support_type: str = "All",
) -> list[CatalogueRecord]:
    needle = keyword.strip().casefold()
    visible: list[CatalogueRecord] = []
    for record in records:
        record_agency = record.implementing_agency or record.department or record.source
        haystack = " ".join(
            (
                record.scheme_name,
                record_agency,
                record.record_kind,
                record.search_blob,
                *record.sectors,
                *record.scheme_types,
            )
        ).casefold()
        if needle and needle not in haystack:
            continue
        if agency != "All" and record_agency != agency:
            continue
        if support_type != "All" and record.record_kind != support_type:
            continue
        visible.append(record)
    return visible
