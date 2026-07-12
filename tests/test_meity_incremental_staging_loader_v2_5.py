from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.loader.meity_incremental_staging_loader_v2_5 import (
    AUDIT_TABLE,
    DECISION_ADMIN_REVIEW,
    DECISION_APPROVED,
    DECISION_MORE_EVIDENCE,
    MeityIncrementalStagingLoaderV25,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_record(index: int, decision: str = DECISION_ADMIN_REVIEW) -> dict[str, Any]:
    names = [
        "SAMRIDH",
        "TIDE 2.0",
        "SASACT",
        "GENESIS",
        "SITAA - Contactless Fingerprint Authentication",
        "SITAA - Presentation Attack Detection",
    ]
    return {
        "master_id": f"meity-{index}",
        "scheme_name": names[index - 1],
        "short_name": names[index - 1].split(" - ")[0],
        "source": "MeitY Startup Hub",
        "ministry": "Ministry of Electronics and Information Technology",
        "department": "MeitY Startup Hub",
        "implementing_agency": "MeitY Startup Hub",
        "official_page_url": f"https://msh.meity.gov.in/schemes/test-{index}",
        "application_url": None,
        "scheme_status": "SCHEME_INFORMATION_AVAILABLE_STATUS_UNVERIFIED",
        "geographic_scope": "National (India)",
        "funding_amount": {"minimum": None, "maximum": None, "currency": "INR"},
        "eligibility": ["Eligible technology startups may apply."] if index < 5 else [],
        "benefits": ["Programme support is available."] if index < 3 else [],
        "required_documents": [],
        "quality_flags": ["REQUIRED_DOCUMENTS_NOT_FOUND"],
        "validation_decision": decision,
        "decision": decision,
        "validation_score": 0.855,
        "programme_status": (
            "CALL_STATUS_CONFLICT_REQUIRES_REVIEW" if index in {5, 6}
            else "SCHEME_INFORMATION_AVAILABLE"
        ),
        "validation_reasons": (
            ["CALL_STATUS_CONFLICT_REQUIRES_REVIEW"] if index in {5, 6} else []
        ),
        "validation_checks": {"scheme_name_present": True},
        "validator_version": "2.4.1",
        "validated_at": "2026-07-09T05:15:17+00:00",
        "validation_metadata": {
            "hotfix_version": "2.4.1",
            "run_id": "validation-run",
            "checked_at": "2026-07-09T05:15:17+00:00",
            "extraction_fingerprint": f"extract-{index}",
        },
    }


def create_production_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE scheme_staging (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                short_name TEXT,
                source TEXT,
                ministry TEXT,
                department TEXT,
                implementing_agency TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                scheme_status TEXT,
                geographic_scope TEXT,
                official_page_url TEXT,
                application_url TEXT,
                opening_date TEXT,
                closing_date TEXT,
                validation_score REAL,
                validation_decision TEXT NOT NULL,
                publication_status TEXT NOT NULL DEFAULT 'STAGED',
                funding_minimum INTEGER,
                funding_maximum INTEGER,
                currency TEXT,
                beneficiary_support_minimum INTEGER,
                beneficiary_support_maximum INTEGER,
                intermediary_support_maximum INTEGER,
                scheme_corpus INTEGER,
                record_hash TEXT NOT NULL,
                raw_record_json TEXT NOT NULL,
                first_loaded_at TEXT NOT NULL,
                last_loaded_at TEXT NOT NULL,
                last_import_run_id TEXT
            );

            CREATE TABLE admin_review_queue (
                master_id TEXT PRIMARY KEY,
                scheme_name TEXT NOT NULL,
                source TEXT,
                record_kind TEXT,
                programme_status TEXT,
                application_status TEXT,
                official_page_url TEXT,
                application_url TEXT,
                decision TEXT NOT NULL,
                validation_score REAL,
                review_status TEXT NOT NULL DEFAULT 'PENDING',
                priority TEXT NOT NULL,
                decision_reasons_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                critical_flags_json TEXT NOT NULL,
                recommended_actions_json TEXT NOT NULL,
                validated_record_json TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                first_queued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_import_run_id TEXT
            );

            CREATE TABLE admin_review_actions (
                action_id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        for index in range(1, 5):
            connection.execute(
                """
                INSERT INTO scheme_staging
                (master_id, scheme_name, source, validation_decision,
                 record_hash, raw_record_json, first_loaded_at, last_loaded_at)
                VALUES (?, ?, 'DST', 'APPROVED_FOR_DATABASE', ?, ?, ?, ?)
                """,
                (
                    f"existing-stage-{index}", f"Existing Stage {index}",
                    f"stage-hash-{index}", json.dumps({"sentinel": index}),
                    "2026-07-08T00:00:00+00:00", "2026-07-08T00:00:00+00:00",
                ),
            )
        for index in range(1, 7):
            connection.execute(
                """
                INSERT INTO admin_review_queue
                (master_id, scheme_name, source, decision, validation_score,
                 review_status, priority, decision_reasons_json, warnings_json,
                 critical_flags_json, recommended_actions_json,
                 validated_record_json, record_hash, first_queued_at, updated_at)
                VALUES (?, ?, 'BIRAC', 'NEEDS_ADMIN_REVIEW', 0.8,
                        'APPROVED', 'NORMAL', '[]', '[]', '[]', '[]', ?, ?, ?, ?)
                """,
                (
                    f"existing-review-{index}", f"Existing Review {index}",
                    json.dumps({"sentinel": index}), f"review-hash-{index}",
                    "2026-07-08T00:00:00+00:00", "2026-07-08T12:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO admin_review_actions (master_id, action, actor, created_at) VALUES (?, 'APPROVED', 'admin', ?)",
                (f"existing-review-{index}", "2026-07-08T12:00:00+00:00"),
            )
        connection.commit()
    finally:
        connection.close()


def scalar(path: Path, sql: str, params: tuple[Any, ...] = ()) -> Any:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, params).fetchone()[0]
    finally:
        connection.close()


def row(path: Path, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        result = connection.execute(sql, params).fetchone()
        assert result is not None
        return dict(result)
    finally:
        connection.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ssip_meity_staging_v2_5_1_") as temp_dir:
        root = Path(temp_dir)
        data = root / "data"
        preview = root / "preview"
        database = root / "database" / "ssip_staging_v1.db"
        create_production_schema(database)

        records = [make_record(i, DECISION_MORE_EVIDENCE if i == 6 else DECISION_ADMIN_REVIEW) for i in range(1, 7)]
        write_json(data / "approved_for_database_v2_4.json", [])
        write_json(data / "admin_review_queue_v2_4.json", records)
        write_json(data / "rejected_scheme_records_v2_4.json", [])

        loader = MeityIncrementalStagingLoaderV25(project_root=root, database_path=database)
        dry = loader.run(output_dir=preview, dry_run=True)
        assert dry.summary["hotfix_version"] == "2.5.1"
        assert dry.summary["failure_count"] == 0
        assert dry.summary["actions"] == {"INSERTED_NEW": 6}
        assert dry.summary["database_committed"] is False
        assert scalar(database, "SELECT COUNT(*) FROM admin_review_queue") == 6

        first = loader.run(dry_run=False)
        assert first.summary["failure_count"] == 0
        assert first.summary["actions"] == {"INSERTED_NEW": 6}
        assert scalar(database, "SELECT COUNT(*) FROM admin_review_queue") == 12
        assert scalar(database, "SELECT COUNT(*) FROM scheme_staging") == 4
        assert scalar(database, "SELECT COUNT(*) FROM admin_review_actions") == 6
        assert scalar(database, f"SELECT COUNT(*) FROM {AUDIT_TABLE}") == 6

        inserted = row(database, "SELECT * FROM admin_review_queue WHERE master_id='meity-5'")
        assert inserted["review_status"] == "PENDING"
        assert inserted["decision"] == DECISION_ADMIN_REVIEW
        assert json.loads(inserted["decision_reasons_json"]) == ["CALL_STATUS_CONFLICT_REQUIRES_REVIEW"]
        assert json.loads(inserted["warnings_json"]) == ["REQUIRED_DOCUMENTS_NOT_FOUND"]
        assert json.loads(inserted["critical_flags_json"]) == []
        assert len(json.loads(inserted["recommended_actions_json"])) == 2
        assert json.loads(inserted["validated_record_json"])["scheme_name"].startswith("SITAA")
        assert len(inserted["record_hash"]) == 64
        assert inserted["first_queued_at"]
        assert inserted["last_import_run_id"]

        second = loader.run(dry_run=False)
        assert second.summary["actions"] == {"REUSED_UNCHANGED": 6}
        assert scalar(database, "SELECT COUNT(*) FROM admin_review_queue") == 12

        before = row(database, "SELECT * FROM admin_review_queue WHERE master_id='meity-1'")
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE admin_review_queue SET review_status='APPROVED' WHERE master_id='meity-1'"
            )
            connection.commit()
        finally:
            connection.close()

        records[0]["decision"] = DECISION_MORE_EVIDENCE
        records[0]["validation_decision"] = DECISION_MORE_EVIDENCE
        records[0]["validation_score"] = 0.700
        records[0]["validation_reasons"] = ["ELIGIBILITY_NOT_FOUND"]
        write_json(data / "admin_review_queue_v2_4.json", records)

        third = loader.run(dry_run=False)
        assert third.summary["updated_preserving_final_workflow_count"] == 1
        assert third.summary["reused_unchanged_count"] == 5
        after = row(database, "SELECT * FROM admin_review_queue WHERE master_id='meity-1'")
        assert after["review_status"] == "APPROVED"
        assert after["decision"] == DECISION_MORE_EVIDENCE
        assert after["validation_score"] == 0.7
        assert after["first_queued_at"] == before["first_queued_at"]
        assert json.loads(after["decision_reasons_json"]) == ["ELIGIBILITY_NOT_FOUND"]
        assert scalar(database, "SELECT COUNT(*) FROM admin_review_actions") == 6

        # Exact production staging schema must also accept an approved record.
        approved = make_record(1, DECISION_APPROVED)
        approved["master_id"] = "meity-approved-test"
        approved["scheme_name"] = "MeitY Approved Test"
        write_json(data / "approved_for_database_v2_4.json", [approved])
        write_json(data / "admin_review_queue_v2_4.json", [])
        fourth = loader.run(dry_run=False)
        assert fourth.summary["failure_count"] == 0
        staged = row(database, "SELECT * FROM scheme_staging WHERE master_id='meity-approved-test'")
        assert staged["validation_decision"] == DECISION_APPROVED
        assert len(staged["record_hash"]) == 64
        assert json.loads(staged["raw_record_json"])["scheme_name"] == "MeitY Approved Test"
        assert staged["first_loaded_at"] and staged["last_loaded_at"]

        print(json.dumps(first.summary, indent=2))
        print("MeitY Incremental Staging Loader v2.5.1 hotfix self-test passed.")


if __name__ == "__main__":
    main()
