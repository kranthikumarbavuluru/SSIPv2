from __future__ import annotations

import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from database.staging_loader_v1 import open_database, upsert_review_item
from services.admin_review_service_v1 import AdminReviewService
from ssip_agents.dst_pilot.admin_bridge import (
    ACTION_INSERT,
    ACTION_SKIP_SEMANTIC,
    BridgePaths,
    DSTAdminBridge,
    plan_signature,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data/departments/dst/pilot_v1"


def _test_directory() -> Path:
    path = ROOT / "data/test_runs" / f"dst_admin_bridge_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def bridge_for(database_path: Path, report_dir: Path) -> DSTAdminBridge:
    return DSTAdminBridge(BridgePaths(ROOT, PILOT, database_path, report_dir))


def test_bridge_builds_all_curated_programmes_and_calls() -> None:
    bridge = bridge_for(ROOT / "database/ssip_staging_v1.db", PILOT / "admin_bridge")
    items = bridge.build_items()
    assert len(items) == 37
    assert sum(item["record_kind"] == "APPLICATION_CALL" for item in items) == 27
    rdif = next(item for item in items if item["master_id"] == "dst_programme_rdif")
    assert rdif["record_kind"] == "FUND"
    call = next(item for item in items if item["master_id"].startswith("dst_call_") and "RDI Fund" in item["scheme_name"])
    record = call["validated_record"]
    assert record["parent_master_id"] == "dst_programme_rdif"
    assert record["implementing_entity"] == "Technology Development Board"
    assert record["applicant_layer"] == "DIRECT_BENEFICIARY"
    assert record["status_basis"] == "EXPLICIT_OFFICIAL_APPLY_ROUTE"
    assert record["application_url"] == "https://www.e-techcom.tdb.gov.in/rdif-registration.php"


def test_dry_run_is_read_only_and_skips_decided_semantic_duplicate() -> None:
    directory = _test_directory()
    database_path = directory / "bridge.db"
    try:
        connection = open_database(database_path, ROOT / "database/schema_staging_v1.sql")
        bridge = bridge_for(database_path, directory / "reports")
        duplicate = next(item for item in bridge.build_items() if "U.S.-India Partnerships" in item["scheme_name"])
        duplicate = {**duplicate, "master_id": "existing-us-india", "validated_record": {**duplicate["validated_record"], "master_id": "existing-us-india"}}
        connection.execute(
            "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('fixture','2026-07-11','COMPLETED',1)"
        )
        upsert_review_item(connection, duplicate, "fixture", "2026-07-11T00:00:00+00:00")
        connection.execute("UPDATE admin_review_queue SET review_status='APPROVED' WHERE master_id='existing-us-india'")
        connection.commit()
        before = connection.execute("SELECT COUNT(*) FROM admin_review_queue").fetchone()[0]
        connection.close()

        report = bridge.run(apply=False)
        assert report["database_modified"] is False
        target = next(action for action in report["actions"] if "U.S.-India Partnerships" in action["scheme_name"])
        assert target["action"] == ACTION_SKIP_SEMANTIC
        assert report["proposed_insert_count"] == sum(action["action"] == ACTION_INSERT for action in report["actions"])
        with closing(sqlite3.connect(database_path)) as check:
            assert check.execute("SELECT COUNT(*) FROM admin_review_queue").fetchone()[0] == before
    finally:
        shutil.rmtree(directory)


def test_admin_service_filters_dst_record_type_and_applicant_layer() -> None:
    directory = _test_directory()
    database_path = directory / "filters.db"
    try:
        connection = open_database(database_path, ROOT / "database/schema_staging_v1.sql")
        bridge = bridge_for(database_path, directory / "reports")
        rdif_call = next(item for item in bridge.build_items() if "RDI Fund" in item["scheme_name"])
        connection.execute(
            "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('fixture','2026-07-11','COMPLETED',1)"
        )
        upsert_review_item(connection, rdif_call, "fixture", "2026-07-11T00:00:00+00:00")
        connection.commit()
        connection.close()

        service = AdminReviewService(database_path)
        options = service.filter_options()
        assert "APPLICATION_CALL" in options["record_kinds"]
        assert "DIRECT_BENEFICIARY" in options["applicant_layers"]
        rows = service.list_reviews(
            source="DST", record_kind="APPLICATION_CALL", applicant_layer="DIRECT_BENEFICIARY"
        )
        assert [row["master_id"] for row in rows] == [rdif_call["master_id"]]
        assert rows[0]["priority"] == "HIGH"
    finally:
        shutil.rmtree(directory)


def test_apply_rejects_a_plan_that_changed_after_dry_run() -> None:
    directory = _test_directory()
    database_path = directory / "stale.db"
    try:
        connection = open_database(database_path, ROOT / "database/schema_staging_v1.sql")
        connection.close()
        bridge = bridge_for(database_path, directory / "reports")
        dry_run = bridge.run(apply=False)
        target = next(item for item in bridge.build_items() if "RDI Fund" in item["scheme_name"])
        duplicate = {
            **target,
            "master_id": "new-semantic-conflict",
            "validated_record": {**target["validated_record"], "master_id": "new-semantic-conflict"},
        }
        connection = open_database(database_path, ROOT / "database/schema_staging_v1.sql")
        connection.execute(
            "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('changed','2026-07-11','COMPLETED',1)"
        )
        upsert_review_item(connection, duplicate, "changed", "2026-07-11T00:00:00+00:00")
        connection.commit()
        connection.close()

        with pytest.raises(RuntimeError, match="plan changed"):
            bridge.run(apply=True, expected_signature=dry_run["plan_signature"])
        assert plan_signature(bridge.plan()) != dry_run["plan_signature"]
    finally:
        shutil.rmtree(directory)
