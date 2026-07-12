from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from services.dst_historical_archive_approval_v1 import DSTHistoricalArchiveApprovalService


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/migrations/20260712_dst_historical_archive_v1.sql"


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "archive.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    return path


def test_sample_review_and_publication_are_separate_atomic_actions(tmp_path: Path) -> None:
    database = _database(tmp_path)
    service = DSTHistoricalArchiveApprovalService(database, ROOT)
    assert service.schema_ready()
    assert service.status()["approval_status"] == "PREVIEW"

    reviewed = service.review_sample(
        reviewer="Archive Reviewer",
        notes="Reviewed every record in the deterministic sample.",
        expected_signature=service.manifest["signature"],
        reviewed_sample_ids=service.manifest["sample_ids"],
    )
    assert reviewed["status"] == "SAMPLE_REVIEWED"
    assert reviewed["record_count"] == 348
    state = service.status()
    assert state["approval_status"] == "SAMPLE_REVIEWED"
    assert state["archive_records"] == 348
    assert state["public_records"] == 0

    published = service.publish(
        publisher="Archive Publisher",
        notes="Approved as official historical reference evidence.",
        expected_signature=service.manifest["signature"],
    )
    assert published["status"] == "APPROVED"
    assert published["public_count"] == 348
    assert service.status()["public_records"] == 348

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM public_historical_calls").fetchone()[0] == 348
        assert connection.execute("SELECT COUNT(*) FROM historical_archive_actions").fetchone()[0] == 2
    finally:
        connection.close()


def test_sample_review_rejects_partial_or_changed_sample(tmp_path: Path) -> None:
    service = DSTHistoricalArchiveApprovalService(_database(tmp_path), ROOT)
    with pytest.raises(ValueError, match="complete signed stratified sample"):
        service.review_sample(
            reviewer="Archive Reviewer",
            notes="Partial review",
            expected_signature=service.manifest["signature"],
            reviewed_sample_ids=service.manifest["sample_ids"][:-1],
        )
    with pytest.raises(ValueError, match="manifest changed"):
        service.review_sample(
            reviewer="Archive Reviewer",
            notes="Changed manifest",
            expected_signature="wrong",
            reviewed_sample_ids=service.manifest["sample_ids"],
        )

