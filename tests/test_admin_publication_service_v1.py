from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest

from database.staging_loader_v1 import open_database, upsert_review_item
from services.admin_publication_service_v1 import AdminPublicationService
from services.admin_review_service_v1 import AdminReviewService
from scripts.migrate_publication_control_v2_7_3 import run_migration


ROOT = Path(__file__).resolve().parents[1]


def _directory() -> Path:
    path = ROOT / "data/test_runs" / f"admin_publication_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def review_item(master_id: str, name: str) -> dict:
    url = f"https://example.gov.in/schemes/{master_id}"
    record = {
        "master_id": master_id,
        "scheme_name": name,
        "short_name": "",
        "source": "Test Department",
        "ministry": "Test Ministry",
        "department": "Test Department",
        "implementing_agency": "Test Agency",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "programme_status": "SCHEME_INFORMATION_AVAILABLE",
        "application_status": "NOT_APPLICABLE",
        "scheme_status": "REFERENCE_PROGRAMME",
        "geographic_scope": "National (India)",
        "official_page_url": url,
        "application_url": None,
        "opening_date": None,
        "closing_date": None,
        "scheme_type": ["Scheme"],
        "target_beneficiaries": ["Startups"],
        "startup_stage": [],
        "sector": ["Deep Technology"],
        "source_evidence": [{"url": url, "title": "Official page", "content_kind": "html"}],
        "field_evidence": {"identity": "Official scheme page"},
        "last_verified_at": "2026-07-11",
        "funding_amount": {
            "minimum": None, "maximum": None, "currency": "INR",
            "beneficiary_support": {"minimum": None, "maximum": None},
        },
        "validation": {"decision": "NEEDS_ADMIN_REVIEW", "validation_score": None},
    }
    return {
        "master_id": master_id, "scheme_name": name, "source": "Test Department",
        "record_kind": "SCHEME_OR_PROGRAMME", "programme_status": record["programme_status"],
        "application_status": "NOT_APPLICABLE", "official_page_url": url,
        "application_url": None, "decision": "NEEDS_ADMIN_REVIEW", "validation_score": None,
        "priority": "NORMAL", "decision_reasons": ["Curator verification required"],
        "warnings": [], "critical_flags": [], "recommended_admin_actions": [],
        "validated_record": record,
    }


def approved_database(path: Path, count: int = 2) -> list[str]:
    connection = open_database(path, ROOT / "database/schema_staging_v1.sql")
    connection.execute(
        "INSERT INTO import_runs(run_id,started_at,status,review_input_count) VALUES ('fixture','2026-07-11','COMPLETED',?)",
        (count,),
    )
    ids = [f"publication-{index}" for index in range(count)]
    for index, master_id in enumerate(ids):
        upsert_review_item(connection, review_item(master_id, f"Publication Scheme {index}"), "fixture", "2026-07-11")
    connection.commit()
    connection.close()
    review = AdminReviewService(path)
    for master_id in ids:
        record = review.get_review(master_id)["validated_record"]
        review.approve(master_id, record, reviewer="Curator", notes="Official evidence verified")
    run_migration(
        database_path=path,
        apply_changes=True,
        backup_dir=path.parent / "backups",
        applied_by="Publication Test",
    )
    return ids


def test_bulk_ready_and_publish_are_atomic_and_audited() -> None:
    directory = _directory()
    path = directory / "publication.db"
    try:
        ids = approved_database(path)
        service = AdminPublicationService(path)
        ready_plan = service.plan("mark-ready", ids)
        assert ready_plan["eligible_ids"] == sorted(ids)
        ready = service.bulk_action(
            action="mark-ready", master_ids=ids, actor="Publisher", reason="Curator-approved batch",
            expected_signature=ready_plan["signature"],
        )
        assert ready["record_count"] == 2
        assert ready["public_count_after"] == 0

        publish_plan = service.plan("publish", ids)
        assert publish_plan["eligible_ids"] == sorted(ids)
        published = service.bulk_action(
            action="publish", master_ids=ids, actor="Publisher", reason="Public release approved",
            expected_signature=publish_plan["signature"],
        )
        assert published["public_count_before"] == 0
        assert published["public_count_after"] == 2
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM public_schemes").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM publication_audit_log").fetchone()[0] == 4
    finally:
        shutil.rmtree(directory)


def test_publication_plan_excludes_record_missing_stored_evidence() -> None:
    directory = _directory()
    path = directory / "excluded.db"
    try:
        ids = approved_database(path, count=1)
        with closing(sqlite3.connect(path)) as connection:
            raw = json.loads(connection.execute(
                "SELECT raw_record_json FROM scheme_staging WHERE master_id=?", (ids[0],)
            ).fetchone()[0])
            raw["source_evidence"] = []
            connection.execute(
                "UPDATE scheme_staging SET raw_record_json=? WHERE master_id=?",
                (json.dumps(raw), ids[0]),
            )
            connection.commit()
        plan = AdminPublicationService(path).plan("mark-ready", ids)
        assert plan["eligible_ids"] == []
        assert "At least one official evidence URL must be stored." in plan["records"][0]["blockers"]
    finally:
        shutil.rmtree(directory)


def test_stale_bulk_plan_cannot_publish_partial_batch() -> None:
    directory = _directory()
    path = directory / "stale.db"
    try:
        ids = approved_database(path)
        service = AdminPublicationService(path)
        ready_plan = service.plan("mark-ready", ids)
        service.bulk_action(
            action="mark-ready", master_ids=ids, actor="Publisher", reason="Prepare",
            expected_signature=ready_plan["signature"],
        )
        stale = service.plan("publish", ids)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE scheme_staging SET record_version=record_version+1 WHERE master_id=?", (ids[0],)
            )
            connection.commit()
        with pytest.raises(Exception, match="plan changed"):
            service.bulk_action(
                action="publish", master_ids=ids, actor="Publisher", reason="Release",
                expected_signature=stale["signature"],
            )
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM public_schemes").fetchone()[0] == 0
    finally:
        shutil.rmtree(directory)


def test_admin_ui_exposes_guarded_bulk_publication_controls() -> None:
    source = (ROOT / "ui/admin_review_app_v1.py").read_text(encoding="utf-8-sig")
    assert '"Publication Queue"' in source
    assert "Run bulk publication preflight" in source
    assert "Select all" in source
    assert "Publisher identity *" in source
    assert "Type {phrase} to confirm *" in source
    assert "publication.bulk_action(" in source
