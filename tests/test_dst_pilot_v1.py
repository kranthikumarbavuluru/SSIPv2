from __future__ import annotations

import csv
import gzip
import shutil
import sqlite3
import uuid
from datetime import date
from pathlib import Path

from ssip_agents.dst_pilot.call_extractor import SnapshotCallExtractor, calculate_status
from ssip_agents.dst_pilot.profile import DepartmentProfile
from ssip_agents.dst_pilot.repository import EvidenceRepository
from ssip_agents.dst_pilot.live_refresh import OfficialLiveCallRefresher
import requests


ROOT = Path(__file__).resolve().parents[1]
PROFILE = DepartmentProfile.load(ROOT / "config/dst_department_agent_v1.json")


def _test_dir() -> Path:
    path = ROOT / "data/test_runs" / f"dst_pilot_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _fixture_crawl(tmp_path: Path) -> tuple[Path, Path]:
    crawl_root = tmp_path / "crawl"
    snapshots = crawl_root / "snapshots/html"
    snapshots.mkdir(parents=True)
    index_html = """
    <html><body><table><tr><th>Title</th><th>Attachment</th><th>Start Date</th><th>End Date</th></tr>
    <tr><td><a href='/callforproposals/nidhi-prayas-startups'>NIDHI PRAYAS Call for Startups 2026</a></td><td><a href='/files/prayas.pdf'>Download</a></td><td>01/07/2026</td><td>31/07/2026</td></tr>
    <tr><td><a href='/callforproposals/research'>Research proposals in basic science</a></td><td></td><td>01/01/2020</td><td>31/01/2020</td></tr>
    </table></body></html>
    """
    detail_html = "<html><main>Innovators and startups may apply under NIDHI PRAYAS for agriculture technology prototypes.</main></html>"
    for name, content in (("index.html.gz", index_html), ("detail.html.gz", detail_html)):
        with gzip.open(snapshots / name, "wt", encoding="utf-8") as handle:
            handle.write(content)
    csv_path = crawl_root / "pages.csv"
    fields = ["final_url", "snapshot_path", "fetched_at"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            {"final_url": "https://dst.gov.in/archive-call-for-proposals", "snapshot_path": "snapshots/html/index.html.gz", "fetched_at": "2026-07-11T00:00:00+00:00"},
            {"final_url": "https://dst.gov.in/callforproposals/nidhi-prayas-startups", "snapshot_path": "snapshots/html/detail.html.gz", "fetched_at": "2026-07-11T00:00:00+00:00"},
        ])
    return csv_path, crawl_root


def _fixture_monitored_application_page(tmp_path: Path) -> tuple[Path, Path]:
    crawl_root = tmp_path / "crawl"
    snapshots = crawl_root / "snapshots/html"
    snapshots.mkdir(parents=True)
    page_html = """
    <html><body><main>
      <h1>RDIF - TDB as Second Level Fund Manager (SLFM)</h1>
      <p>Indian legal entities including DPIIT startups at TRL 4 and above may apply
      for loan, equity or hybrid support across sunrise and strategic sectors.</p>
      <a href="https://www.e-techcom.tdb.gov.in/rdif-registration.php">Apply Now</a>
    </main></body></html>
    """
    with gzip.open(snapshots / "rdif.html.gz", "wt", encoding="utf-8") as handle:
        handle.write(page_html)
    csv_path = crawl_root / "pages.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["final_url", "snapshot_path", "fetched_at"])
        writer.writeheader()
        writer.writerow({
            "final_url": "https://tdb.gov.in/rdi_slfm",
            "snapshot_path": "snapshots/html/rdif.html.gz",
            "fetched_at": "2026-07-11T00:00:00+00:00",
        })
    return csv_path, crawl_root


def test_archive_container_expands_to_individual_calls() -> None:
    path = _test_dir()
    try:
        csv_path, crawl_root = _fixture_crawl(path)
        calls = SnapshotCallExtractor(PROFILE, date(2026, 7, 11)).extract(csv_path, crawl_root)
        assert len(calls) == 2
        assert all("Archive Call for Proposals" not in item.values["call_title"] for item in calls)
    finally:
        shutil.rmtree(path)


def test_startup_call_has_parent_dates_and_specific_call_sector() -> None:
    path = _test_dir()
    try:
        csv_path, crawl_root = _fixture_crawl(path)
        rows = [item.values for item in SnapshotCallExtractor(PROFILE, date(2026, 7, 11)).extract(csv_path, crawl_root)]
        call = next(row for row in rows if "PRAYAS" in row["call_title"])
        assert call["parent_master_id"] == "dst_programme_nidhi_prayas"
        assert call["startup_relevance"] == "STARTUP_RELEVANT"
        assert call["applicant_layer"] == "DIRECT_BENEFICIARY"
        assert call["application_status"] == "OPEN"
        assert call["sector_scope"] == "SPECIFIC"
        assert call["primary_sector"] == "Agriculture & AgriTech"
    finally:
        shutil.rmtree(path)


def test_unrelated_research_call_is_not_startup_relevant() -> None:
    path = _test_dir()
    try:
        csv_path, crawl_root = _fixture_crawl(path)
        rows = [item.values for item in SnapshotCallExtractor(PROFILE, date(2026, 7, 11)).extract(csv_path, crawl_root)]
        call = next(row for row in rows if row["call_title"].startswith("Research"))
        assert call["startup_relevance"] == "NOT_STARTUP_RELEVANT"
        assert call["application_status"] == "CLOSED"
    finally:
        shutil.rmtree(path)


def test_status_requires_official_date_window() -> None:
    assert calculate_status("01/07/2026", "31/07/2026", date(2026, 7, 11))[0] == "OPEN"
    assert calculate_status("", "", date(2026, 7, 11))[0] == "STATUS_UNVERIFIED"


def test_monitored_official_apply_route_creates_open_rdif_call() -> None:
    path = _test_dir()
    try:
        csv_path, crawl_root = _fixture_monitored_application_page(path)
        rows = [item.values for item in SnapshotCallExtractor(PROFILE, date(2026, 7, 11)).extract(csv_path, crawl_root)]
        assert len(rows) == 1
        call = rows[0]
        assert call["parent_master_id"] == "dst_programme_rdif"
        assert call["implementing_entity"] == "Technology Development Board"
        assert call["application_status"] == "OPEN"
        assert call["status_basis"] == "EXPLICIT_OFFICIAL_APPLY_ROUTE"
        assert call["application_url"] == "https://www.e-techcom.tdb.gov.in/rdif-registration.php"
        assert call["last_verified_at"] == "2026-07-11T00:00:00+00:00"
    finally:
        shutil.rmtree(path)


def test_profile_keeps_unknown_sectors_blank() -> None:
    for entity in PROFILE.entities:
        if entity["sector_scope"] == "UNKNOWN":
            assert entity["primary_sector"] == ""


def test_evidence_repository_has_first_class_call_and_evidence_tables() -> None:
    directory = _test_dir()
    path = directory / "pilot.db"
    try:
        repository = EvidenceRepository(path)
        repository.close()
        connection = sqlite3.connect(path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        assert {"programme_master", "call_instance", "field_evidence", "curation_queue", "pilot_run"}.issubset(tables)
    finally:
        shutil.rmtree(directory)


def test_live_refresh_records_page_failures_without_losing_successful_pages() -> None:
    directory = _test_dir()
    try:
        refresher = OfficialLiveCallRefresher(PROFILE, directory)

        def fake_fetch(url: str) -> tuple[str, str]:
            if "dst.gov.in/call-for-proposals" in url:
                raise requests.ConnectionError("fixture index failure")
            return url, "<html><body><main><h1>RDIF monitored page</h1></main></body></html>"

        refresher._fetch = fake_fetch  # type: ignore[method-assign]
        inventory = refresher.run()
        with inventory.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert {row["fetch_status"] for row in rows} == {"ERROR", "OK"}
        assert any(row["error"].startswith("ConnectionError:") for row in rows)
    finally:
        shutil.rmtree(directory)
