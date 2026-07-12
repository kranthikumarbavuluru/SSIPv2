from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

from ssip_dashboard.dst_history import (
    RELEVANCE_ORDER,
    assess_historical_calls,
    load_dst_historical_archive,
    year_relevance_counts,
)
from ssip_dashboard.dst_pilot import default_dst_pilot_path, load_dst_pilot


ROOT = Path(__file__).resolve().parents[1]


def _archive():
    return load_dst_historical_archive(ROOT)


def test_archive_reconciles_normalized_closed_and_current_populations() -> None:
    archive = _archive()
    assert archive.manifest["total_normalized_calls"] == 352
    assert archive.manifest["qualified_historical_calls"] == 348
    assert archive.manifest["current_calls_excluded"] == 4
    assert archive.manifest["exception_count"] == 0
    assert len(archive.historical_records) == 348
    assert all(item.call.application_status == "CLOSED" for item in archive.historical_records)
    assert all(item.call.application_status == "OPEN" for item in archive.current_calls)


def test_historical_year_counts_are_complete_and_exact() -> None:
    archive = _archive()
    assert archive.manifest["year_counts"] == {
        "2017": 46,
        "2018": 59,
        "2019": 42,
        "2020": 38,
        "2021": 38,
        "2022": 27,
        "2023": 37,
        "2024": 27,
        "2025": 27,
        "2026": 7,
    }
    assert sum(archive.manifest["year_counts"].values()) == 348
    assert sum(sum(groups.values()) for groups in year_relevance_counts(archive.historical_records).values()) == 348


def test_relevance_segments_do_not_recast_general_dst_calls_as_startup_calls() -> None:
    archive = _archive()
    counts = archive.manifest["relevance_counts"]
    assert tuple(counts) == RELEVANCE_ORDER
    assert counts == {
        "STARTUP_RELEVANT": 12,
        "STARTUP_ECOSYSTEM_CALL": 4,
        "REVIEW_REQUIRED": 8,
        "GENERAL_DST": 324,
    }
    assert sum(counts.values()) == 348


def test_stratified_sample_covers_every_year_and_relevance_group() -> None:
    archive = _archive()
    sample_ids = set(archive.manifest["sample_ids"])
    sample = [item for item in archive.historical_records if item.call.call_id in sample_ids]
    assert len(sample) == 36
    assert all(value >= 3 for value in Counter(item.closing_year for item in sample).values())
    assert set(item.relevance_group for item in sample) == set(RELEVANCE_ORDER)


def test_archive_gate_rejects_index_containers_and_future_closed_dates() -> None:
    pilot = load_dst_pilot(default_dst_pilot_path(ROOT))
    baseline = next(item for item in pilot.calls if item.application_status == "CLOSED")
    index_call = replace(
        baseline,
        call_id="synthetic-index",
        call_title="Archive Call for Proposals | Page 1",
    )
    future_call = replace(
        baseline,
        call_id="synthetic-future",
        closing_date="31/12/2027",
    )
    assessments = assess_historical_calls(
        [index_call, future_call],
        today=date(2026, 7, 12),
    )
    assert all(item.archive_state == "EXCEPTION_REVIEW" for item in assessments)
    assert "Archive index container cannot be treated as an individual call." in assessments[0].blocking_gaps
    assert "Closing date is not in the past." in assessments[1].blocking_gaps


def test_public_and_admin_apps_expose_governed_archive_views() -> None:
    public_app = (ROOT / "apps/public_dashboard_app_v2_9.py").read_text(encoding="utf-8")
    admin_app = (ROOT / "ui/admin_review_app_v1.py").read_text(encoding="utf-8")
    assert '"HISTORICAL_ARCHIVE"' in public_app
    assert "DST Historical Calls by Closing Year" in public_app
    assert "page_size = 30" in public_app
    assert 'key="dst_history_page"' in public_app
    assert "visible[page_start:page_start + page_size]" in public_app
    assert "no active Apply action is displayed" in public_app
    assert '"Historical Archive"' in admin_app
    assert "Stratified sample" in admin_app
