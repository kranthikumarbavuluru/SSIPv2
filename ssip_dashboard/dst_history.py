from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from .dst_pilot import DSTCall, DSTPilotBundle, default_dst_pilot_path, load_dst_pilot


ARCHIVE_SERVICE_VERSION = "1.0.0"
RELEVANCE_ORDER = (
    "STARTUP_RELEVANT",
    "STARTUP_ECOSYSTEM_CALL",
    "REVIEW_REQUIRED",
    "GENERAL_DST",
)


@dataclass(frozen=True)
class HistoricalCallAssessment:
    call: DSTCall
    closing_date: date | None
    closing_year: int | None
    archive_state: str
    blocking_gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    relevance_group: str

    @property
    def qualified(self) -> bool:
        return self.archive_state in {"AUTO_QUALIFIED", "QUALIFIED_WITH_WARNINGS"}


@dataclass(frozen=True)
class DSTHistoricalArchive:
    assessments: tuple[HistoricalCallAssessment, ...]
    manifest: dict
    source_path: Path

    @property
    def historical_records(self) -> list[HistoricalCallAssessment]:
        return [item for item in self.assessments if item.qualified]

    @property
    def exceptions(self) -> list[HistoricalCallAssessment]:
        return [item for item in self.assessments if item.archive_state == "EXCEPTION_REVIEW"]

    @property
    def current_calls(self) -> list[HistoricalCallAssessment]:
        return [item for item in self.assessments if item.archive_state == "CURRENT_EXCLUDED"]


def parse_call_date(value: str) -> date | None:
    text = str(value or "").strip()
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def relevance_group(call: DSTCall) -> str:
    value = call.startup_relevance.upper()
    if value in {"STARTUP_RELEVANT", "STARTUP_ECOSYSTEM_CALL", "REVIEW_REQUIRED"}:
        return value
    return "GENERAL_DST"


def _official_historical_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    return parsed.scheme in {"http", "https"} and (
        host == "dst.gov.in" or host.endswith(".dst.gov.in") or host == "tdb.gov.in" or host.endswith(".tdb.gov.in")
    )


def _identity_key(call: DSTCall) -> str:
    url = call.detail_url.casefold().rstrip("/")
    if url:
        return f"url:{url}"
    title = " ".join(call.call_title.casefold().split())
    return f"title-date:{title}|{call.closing_date}"


def assess_historical_calls(
    calls: Iterable[DSTCall],
    *,
    today: date | None = None,
) -> tuple[HistoricalCallAssessment, ...]:
    now = today or date.today()
    calls_list = list(calls)
    identity_counts = Counter(_identity_key(call) for call in calls_list)
    output: list[HistoricalCallAssessment] = []
    for call in calls_list:
        closing = parse_call_date(call.closing_date)
        blockers: list[str] = []
        warnings: list[str] = []
        status = call.application_status.upper()

        if status in {"OPEN", "UPCOMING"}:
            state = "CURRENT_EXCLUDED"
        else:
            if status != "CLOSED":
                blockers.append("Application status is not confirmed CLOSED.")
            if not call.call_title.strip():
                blockers.append("Call title is missing.")
            if call.call_title.casefold().startswith("archive call for proposals | page"):
                blockers.append("Archive index container cannot be treated as an individual call.")
            if not _official_historical_url(call.detail_url):
                blockers.append("A supported official DST/TDB detail URL is missing.")
            if closing is None:
                blockers.append("A parseable historical closing date is missing.")
            elif closing >= now:
                blockers.append("Closing date is not in the past.")
            if identity_counts[_identity_key(call)] > 1:
                blockers.append("Canonical call identity is duplicated.")

            if not call.parent_master_id:
                warnings.append("Parent programme is unresolved.")
            if not call.primary_sector:
                warnings.append("Sector classification is not recorded.")
            if relevance_group(call) == "GENERAL_DST":
                warnings.append("Call is not classified as a startup opportunity.")
            if not call.last_verified_at:
                warnings.append("Last verification date is not recorded.")

            state = "EXCEPTION_REVIEW" if blockers else (
                "QUALIFIED_WITH_WARNINGS" if warnings else "AUTO_QUALIFIED"
            )

        output.append(HistoricalCallAssessment(
            call=call,
            closing_date=closing,
            closing_year=closing.year if closing else None,
            archive_state=state,
            blocking_gaps=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            relevance_group=relevance_group(call),
        ))
    return tuple(output)


def _sample_ids(qualified: list[HistoricalCallAssessment], *, per_year: int = 3) -> list[str]:
    by_year: dict[int | None, list[HistoricalCallAssessment]] = defaultdict(list)
    for item in qualified:
        by_year[item.closing_year].append(item)
    selected: set[str] = set()
    for year in sorted(by_year, key=lambda value: (value is None, value or 0)):
        ranked = sorted(
            by_year[year],
            key=lambda item: hashlib.sha256(item.call.call_id.encode("utf-8")).hexdigest(),
        )
        selected.update(item.call.call_id for item in ranked[:per_year])
    # Guarantee representation for every relevance class in the human sample.
    for group in RELEVANCE_ORDER:
        ranked = sorted(
            (item for item in qualified if item.relevance_group == group),
            key=lambda item: hashlib.sha256(item.call.call_id.encode("utf-8")).hexdigest(),
        )
        selected.update(item.call.call_id for item in ranked[:3])
    return sorted(selected)


def build_archive_manifest(assessments: tuple[HistoricalCallAssessment, ...]) -> dict:
    qualified = [item for item in assessments if item.qualified]
    exceptions = [item for item in assessments if item.archive_state == "EXCEPTION_REVIEW"]
    current = [item for item in assessments if item.archive_state == "CURRENT_EXCLUDED"]
    years = Counter(str(item.closing_year or "UNKNOWN") for item in qualified)
    relevance = Counter(item.relevance_group for item in qualified)
    states = Counter(item.archive_state for item in assessments)
    manifest = {
        "service_version": ARCHIVE_SERVICE_VERSION,
        "total_normalized_calls": len(assessments),
        "qualified_historical_calls": len(qualified),
        "current_calls_excluded": len(current),
        "exception_count": len(exceptions),
        "state_counts": dict(sorted(states.items())),
        "year_counts": dict(sorted(years.items())),
        "relevance_counts": {key: relevance.get(key, 0) for key in RELEVANCE_ORDER},
        "sample_ids": _sample_ids(qualified),
        "exception_ids": sorted(item.call.call_id for item in exceptions),
        "current_call_ids": sorted(item.call.call_id for item in current),
    }
    signature_payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["signature"] = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()
    return manifest


def load_dst_historical_archive(project_root: Path) -> DSTHistoricalArchive:
    source_path = default_dst_pilot_path(project_root)
    pilot: DSTPilotBundle = load_dst_pilot(source_path)
    assessments = assess_historical_calls(pilot.calls)
    return DSTHistoricalArchive(
        assessments=assessments,
        manifest=build_archive_manifest(assessments),
        source_path=source_path,
    )


def year_relevance_counts(records: Iterable[HistoricalCallAssessment]) -> dict[int, dict[str, int]]:
    output: dict[int, Counter[str]] = defaultdict(Counter)
    for item in records:
        if item.closing_year is not None:
            output[item.closing_year][item.relevance_group] += 1
    return {
        year: {group: counts.get(group, 0) for group in RELEVANCE_ORDER}
        for year, counts in sorted(output.items())
    }
