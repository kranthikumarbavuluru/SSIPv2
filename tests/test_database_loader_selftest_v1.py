from __future__ import annotations

import json
import tempfile
from pathlib import Path

from database.staging_loader_v1 import LoaderPaths, load_to_staging


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "data").mkdir()
        (root / "database").mkdir()

        source_schema = Path(__file__).resolve().parents[1] / "database" / "schema_staging_v1.sql"
        schema_path = root / "database" / "schema_staging_v1.sql"
        schema_path.write_text(source_schema.read_text(encoding="utf-8"), encoding="utf-8")

        approved = [
            {
                "master_id": "selftest-1",
                "scheme_name": "Self-Test Scheme",
                "short_name": "STS",
                "source": "Test Authority",
                "ministry": "Test Ministry",
                "department": "Test Department",
                "implementing_agency": "Test Agency",
                "scheme_type": ["Grant"],
                "target_beneficiaries": ["Startups"],
                "startup_stage": ["Prototype"],
                "sector": ["Technology"],
                "geographic_scope": "National (India)",
                "states_or_uts": [],
                "objectives": ["Support validated innovations."],
                "eligibility": ["DPIIT-recognised startup."],
                "benefits": ["Grant support."],
                "funding_amount": {
                    "minimum": None,
                    "maximum": 2000000,
                    "currency": "INR",
                    "beneficiary_support": {"minimum": None, "maximum": 2000000},
                    "intermediary_support_maximum": None,
                    "scheme_corpus": None,
                },
                "application_process": ["Apply online."],
                "selection_process": [],
                "required_documents": ["Registration certificate"],
                "application_url": "https://example.gov.in/apply",
                "official_page_url": "https://example.gov.in/scheme",
                "guideline_urls": [],
                "opening_date": "2026-07-01",
                "closing_date": "2026-07-31",
                "scheme_status": "OPEN_FOR_APPLICATIONS",
                "contact_details": [{"type": "email", "value": "help@example.gov.in"}],
                "source_evidence": [
                    {
                        "url": "https://example.gov.in/scheme",
                        "title": "Self-Test Scheme",
                        "content_kind": "html",
                        "source_hash": "abc",
                        "fetched_at": "2026-07-08T00:00:00+00:00",
                        "rendered_with_browser": False,
                        "text_length": 500,
                    }
                ],
                "quality_flags": [],
                "record_kind": "APPLICATION_CALL",
                "programme_status": "CALL_INFORMATION_CURRENT",
                "application_status": "OPEN",
                "validation": {
                    "decision": "APPROVED_FOR_DATABASE",
                    "validation_score": 0.95,
                    "warnings": [],
                    "critical_flags": [],
                    "corrections": [],
                    "record_hash": "selftest-hash",
                },
            }
        ]
        review = [
            {
                "master_id": "selftest-review-1",
                "scheme_name": "Review Scheme",
                "source": "Test Authority",
                "record_kind": "APPLICATION_CALL",
                "programme_status": "CALL_INFORMATION_CURRENT",
                "application_status": "OPEN",
                "official_page_url": "https://example.gov.in/review",
                "application_url": None,
                "decision": "NEEDS_MORE_EVIDENCE",
                "validation_score": 0.55,
                "decision_reasons": ["Missing eligibility."],
                "warnings": ["ELIGIBILITY_REQUIRES_EVIDENCE"],
                "critical_flags": [],
                "recommended_admin_actions": ["Verify eligibility."],
                "validated_record": {
                    "master_id": "selftest-review-1",
                    "scheme_name": "Review Scheme",
                    "validation": {"record_hash": "review-hash"},
                },
            }
        ]
        rejected = []
        audit = approved + [review[0]["validated_record"] | {
            "validation": {
                "decision": "NEEDS_MORE_EVIDENCE",
                "validation_score": 0.55,
                "warnings": ["ELIGIBILITY_REQUIRES_EVIDENCE"],
                "critical_flags": [],
                "corrections": [],
                "record_hash": "review-hash",
            },
            "source": "Test Authority",
        }]

        files = {
            "approved": root / "data" / "validated_scheme_records_v1.json",
            "review": root / "data" / "admin_review_queue_v1.json",
            "rejected": root / "data" / "rejected_scheme_records_v1.json",
            "audit": root / "data" / "validation_audit_v1.json",
        }
        for key, payload in {
            "approved": approved,
            "review": review,
            "rejected": rejected,
            "audit": audit,
        }.items():
            files[key].write_text(json.dumps(payload), encoding="utf-8")

        paths = LoaderPaths(
            approved_path=files["approved"],
            review_path=files["review"],
            rejected_path=files["rejected"],
            audit_path=files["audit"],
            database_path=root / "database" / "selftest.db",
            schema_path=schema_path,
            summary_path=root / "data" / "database_load_summary_v1.json",
        )
        summary = load_to_staging(paths)

        assert summary["staged_scheme_count"] == 1
        assert summary["pending_review_count"] == 1
        assert summary["rejected_table_count"] == 0
        assert summary["validation_audit_count"] == 2
        assert paths.database_path.exists()
        assert paths.summary_path.exists()

        print("Database loader self-test passed.")
        print(f"Staged schemes: {summary['staged_scheme_count']}")
        print(f"Pending review: {summary['pending_review_count']}")
        print(f"Database: {paths.database_path}")


if __name__ == "__main__":
    main()
