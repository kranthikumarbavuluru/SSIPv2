from __future__ import annotations

import json
from contextlib import closing
import shutil
import sqlite3
import tempfile
from pathlib import Path

from database.staging_loader_v1 import open_database, stable_json, upsert_review_item
from services.admin_review_service_v1 import AdminReviewService


def sample_review(master_id: str, name: str) -> dict:
    record = {
        "master_id": master_id,
        "scheme_name": name,
        "short_name": "",
        "source": "DST",
        "ministry": "Ministry of Science and Technology",
        "department": "Department of Science and Technology (DST)",
        "implementing_agency": "Department of Science and Technology (DST)",
        "scheme_type": ["Challenge / Call"],
        "target_beneficiaries": ["Startups"],
        "startup_stage": ["Early Stage"],
        "sector": ["Technology"],
        "geographic_scope": "National (India)",
        "states_or_uts": [],
        "objectives": ["Support innovation."],
        "eligibility": ["DPIIT-recognised startups."],
        "benefits": ["Grant support."],
        "funding_amount": {
            "minimum": None,
            "maximum": 2000000,
            "currency": "INR",
            "funding_types": ["Grant / Scholarship"],
            "amount_mentions": [],
            "beneficiary_support": {"minimum": None, "maximum": 2000000},
            "intermediary_support_maximum": None,
            "scheme_corpus": None,
        },
        "application_process": ["Apply online."],
        "selection_process": [],
        "required_documents": [],
        "application_url": f"https://example.gov.in/apply/{master_id}",
        "official_page_url": f"https://example.gov.in/scheme/{master_id}",
        "guideline_urls": [],
        "opening_date": None,
        "closing_date": "2026-07-31",
        "scheme_status": "OPEN_FOR_APPLICATIONS",
        "contact_details": [],
        "source_evidence": [
            {
                "url": f"https://example.gov.in/scheme/{master_id}",
                "title": "Official Scheme",
                "content_kind": "html",
            }
        ],
        "field_evidence": {},
        "quality_flags": [],
        "record_kind": "APPLICATION_CALL",
        "programme_status": "CALL_INFORMATION_CURRENT",
        "application_status": "OPEN",
        "applicant_layer": "DIRECT_BENEFICIARY",
        "parent_resolution": "STANDALONE_OFFICIAL_CALL",
        "status_evidence": "Official call page and closing date verified.",
        "last_verified_at": "2026-07-11",
        "validation": {
            "decision": "NEEDS_ADMIN_REVIEW",
            "validation_score": 0.75,
            "warnings": [],
            "critical_flags": [],
            "corrections": [],
        },
    }
    return {
        "master_id": master_id,
        "scheme_name": name,
        "source": "DST",
        "record_kind": "APPLICATION_CALL",
        "programme_status": "CALL_INFORMATION_CURRENT",
        "application_status": "OPEN",
        "official_page_url": record["official_page_url"],
        "application_url": record["application_url"],
        "decision": "NEEDS_ADMIN_REVIEW",
        "validation_score": 0.75,
        "decision_reasons": ["Manual verification required."],
        "warnings": [],
        "critical_flags": [],
        "recommended_admin_actions": ["Verify and decide."],
        "validated_record": record,
    }


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    schema_path = project_root / "database" / "schema_staging_v1.sql"

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "admin_review_selftest.db"
        connection = open_database(db_path, schema_path)
        try:
            run_id = "selftest_import"
            now = "2026-07-08T00:00:00+00:00"
            connection.execute(
                """
                INSERT INTO import_runs(run_id, started_at, completed_at, status, summary_json)
                VALUES (?, ?, ?, 'COMPLETED', ?)
                """,
                (run_id, now, now, stable_json({"selftest": True})),
            )
            upsert_review_item(connection, sample_review("review-approve", "Approve Me"), run_id, now)
            upsert_review_item(connection, sample_review("review-reject", "Reject Me"), run_id, now)
            connection.commit()
        finally:
            connection.close()

        service = AdminReviewService(db_path)
        assert service.dashboard_counts()["pending_reviews"] == 2

        approve_item = service.get_review("review-approve")
        edited = approve_item["validated_record"]
        edited["benefits"] = ["Verified grant support up to INR 20 lakh."]
        service.save_draft(
            "review-approve", edited, reviewer="Self Test", notes="Corrected benefit text."
        )
        service.approve(
            "review-approve", edited, reviewer="Self Test", notes="Official source verified."
        )

        reject_item = service.get_review("review-reject")
        service.reject(
            "review-reject",
            reject_item["validated_record"],
            reviewer="Self Test",
            notes="Record is outside dashboard scope.",
        )

        with closing(sqlite3.connect(db_path)) as connection:
            staged = connection.execute(
                "SELECT COUNT(*) FROM scheme_staging WHERE master_id='review-approve'"
            ).fetchone()[0]
            rejected = connection.execute(
                "SELECT COUNT(*) FROM rejected_scheme_records WHERE master_id='review-reject'"
            ).fetchone()[0]
            actions = connection.execute(
                "SELECT COUNT(*) FROM admin_review_actions"
            ).fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM admin_review_queue WHERE review_status='PENDING'"
            ).fetchone()[0]

        assert staged == 1
        assert rejected == 1
        assert actions == 3
        assert pending == 0
        print("Admin review service self-test passed.")
        print(f"Staged after approval: {staged}")
        print(f"Rejected after decision: {rejected}")
        print(f"Audit actions: {actions}")


if __name__ == "__main__":
    main()
