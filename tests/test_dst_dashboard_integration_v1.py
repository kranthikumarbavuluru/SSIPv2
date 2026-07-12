from __future__ import annotations

from pathlib import Path

from ssip_dashboard.dst_pilot import (
    default_dst_pilot_path,
    filter_dst_calls,
    filter_dst_programmes,
    load_dst_pilot,
)


ROOT = Path(__file__).resolve().parents[1]


def _bundle():
    return load_dst_pilot(default_dst_pilot_path(ROOT))


def test_programmes_and_calls_are_separate_populations() -> None:
    bundle = _bundle()
    assert len(bundle.programmes) == 10
    assert len(bundle.calls) == 352
    assert len(bundle.direct_calls) == 23
    assert len(bundle.ecosystem_calls) == 4
    assert all(not item.is_ecosystem for item in bundle.direct_calls)
    assert all(item.is_ecosystem for item in bundle.ecosystem_calls)


def test_direct_calls_have_open_and_closed_filters() -> None:
    calls = _bundle().direct_calls
    assert len(filter_dst_calls(calls, status="OPEN")) == 3
    assert len(filter_dst_calls(calls, status="CLOSED")) == 20
    assert not filter_dst_calls(calls, status="UPCOMING")


def test_intermediary_calls_never_appear_as_direct_opportunities() -> None:
    bundle = _bundle()
    direct_ids = {item.call_id for item in bundle.direct_calls}
    ecosystem_ids = {item.call_id for item in bundle.ecosystem_calls}
    assert direct_ids.isdisjoint(ecosystem_ids)
    assert all(item.applicant_layer == "INTERMEDIARY_IMPLEMENTER" for item in bundle.ecosystem_calls)


def test_sector_keyword_and_parent_filters() -> None:
    bundle = _bundle()
    quantum = filter_dst_calls(bundle.direct_calls, sector="Quantum Technology")
    assert any(item.application_status == "OPEN" for item in quantum)
    prayas = next(item for item in bundle.programmes if item.code == "NIDHI-PRAYAS")
    assert filter_dst_programmes(bundle.programmes, keyword="NIDHI-PRAYAS") == [prayas]
    related = filter_dst_calls(bundle.calls, parent_id=prayas.master_id)
    assert related
    assert all(item.parent_master_id == prayas.master_id for item in related)


def test_rdif_call_is_separate_from_tdb_core_funding() -> None:
    bundle = _bundle()
    rdif = next(item for item in bundle.programmes if item.code == "RDIF")
    tdb_core = next(item for item in bundle.programmes if item.code == "TDB-CORE-FUNDING")
    related = filter_dst_calls(bundle.calls, parent_id=rdif.master_id)
    assert len(related) == 1
    call = related[0]
    assert call.application_status == "OPEN"
    assert call.status_basis == "EXPLICIT_OFFICIAL_APPLY_ROUTE"
    assert call.implementing_entity == "Technology Development Board"
    assert call.application_url == "https://www.e-techcom.tdb.gov.in/rdif-registration.php"
    assert not filter_dst_calls(bundle.calls, parent_id=tdb_core.master_id)


def test_archive_containers_and_unsafe_links_are_not_exposed() -> None:
    bundle = _bundle()
    assert all(not item.call_title.startswith("Archive Call for Proposals | Page") for item in bundle.calls)
    assert all(not item.detail_url or item.detail_url.startswith(("http://", "https://")) for item in bundle.calls)


def test_streamlit_navigation_exposes_three_dst_views() -> None:
    app = (ROOT / "apps/public_dashboard_app_v2_9.py").read_text(encoding="utf-8")
    assert '"DST Schemes"' in app
    assert '"Calls & Opportunities"' in app
    assert '"Incubators & Ecosystem"' in app
    assert "render_dst_schemes()" in app
