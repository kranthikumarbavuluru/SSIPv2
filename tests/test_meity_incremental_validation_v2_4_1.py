from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ssip_agents.validator.meity_incremental_validation_v2_4 import (
    DECISION_ADMIN_REVIEW,
    DECISION_APPROVED,
    DECISION_MORE_EVIDENCE,
    MeityIncrementalValidationV24,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_meity_record(
    index: int,
    name: str,
    *,
    eligibility: bool = True,
    benefits: bool = True,
    application: bool = True,
    active_call: bool = False,
) -> dict[str, Any]:
    url = f"https://msh.meity.gov.in/schemes/test-{index}"
    return {
        "master_id": f"meity-{index}",
        "scheme_name": name,
        "short_name": name,
        "source": "MeitY Startup Hub",
        "ministry": "Ministry of Electronics and Information Technology",
        "department": "Ministry of Electronics and Information Technology",
        "implementing_agency": "MeitY Startup Hub",
        "scheme_type": ["Grant"],
        "target_beneficiaries": ["Startups"],
        "startup_stage": ["Prototype"],
        "sector": ["Digital Technology"],
        "geographic_scope": "National (India)",
        "states_or_uts": [],
        "objectives": ["Support technology startups and innovators."],
        "eligibility": ["DPIIT-recognised startups may apply."] if eligibility else [],
        "benefits": ["Selected startups receive structured support."] if benefits else [],
        "funding_amount": {
            "minimum": None,
            "maximum": 2_000_000,
            "currency": "INR",
            "funding_types": ["Grant"],
            "amount_mentions": [{"amount": 2_000_000, "currency": "INR"}],
        },
        "application_process": ["Apply through the official portal."] if application else [],
        "selection_process": [],
        "required_documents": [],
        "application_url": f"https://msh.meity.gov.in/apply/test-{index}" if application else None,
        "official_page_url": url,
        "guideline_urls": [],
        "opening_date": None,
        "closing_date": "2026-12-31" if active_call else None,
        "scheme_status": "OPEN_FOR_APPLICATIONS"
        if active_call
        else "SCHEME_INFORMATION_AVAILABLE_STATUS_UNVERIFIED",
        "contact_details": [],
        "source_evidence": [
            {
                "url": url,
                "title": name,
                "content_kind": "html",
                "source_hash": f"source-hash-{index}",
                "fetched_at": "2026-07-09T00:00:00+00:00",
                "rendered_with_browser": True,
                "text_length": 1200,
            }
        ],
        "field_evidence": {},
        "quality_flags": [
            flag
            for flag, missing in (
                ("ELIGIBILITY_NOT_FOUND", not eligibility),
                ("BENEFITS_NOT_FOUND", not benefits),
                ("APPLICATION_PROCESS_NOT_FOUND", not application),
                ("REQUIRED_DOCUMENTS_NOT_FOUND", True),
            )
            if missing
        ],
        "extraction_confidence": 1.0 if eligibility and benefits and application else 0.75,
        "master_readiness": "READY_FOR_EXTRACTION",
        "master_current_status": "ACTIVE_CALL_OPEN"
        if active_call
        else "SCHEME_INFORMATION_AVAILABLE",
        "extracted_at": "2026-07-09T00:00:00+00:00",
        "extractor_version": "2.3.0",
        "incremental_metadata": {
            "hotfix_version": "2.3.0",
            "action": "EXTRACTED_NEW",
            "source_fingerprint": f"fingerprint-{index}",
            "checked_at": "2026-07-09T00:00:00+00:00",
        },
    }


def make_existing_non_meity(index: int, decision: str) -> dict[str, Any]:
    return {
        "master_id": f"existing-{index}",
        "scheme_name": f"Existing Scheme {index}",
        "source": "DST" if index % 2 else "BIRAC",
        "official_page_url": f"https://example.gov.in/scheme-{index}",
        "source_evidence": [
            {
                "url": f"https://example.gov.in/scheme-{index}",
                "source_hash": f"existing-hash-{index}",
            }
        ],
        "validation_decision": decision,
        "decision": decision,
        "validation_score": 0.9,
        "validator_version": "1.0.0",
        "sentinel": f"PRESERVE-{index}",
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ssip_meity_validation_v2_4_1_") as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        output_dir = root / "preview"
        second_output_dir = root / "second"

        meity_records = [
            make_meity_record(1, "SAMRIDH"),
            make_meity_record(2, "TIDE 2.0", active_call=True),
            make_meity_record(3, "SASACT", benefits=False),
            make_meity_record(4, "GENESIS", eligibility=False),
            make_meity_record(5, "SITAA Challenge One", eligibility=False, benefits=False),
            make_meity_record(6, "SITAA Challenge Two", application=False, active_call=True),
        ]

        # Ten existing non-MeitY validation decisions, split like the v1 pipeline.
        existing_approved = [
            make_existing_non_meity(index, DECISION_APPROVED) for index in range(1, 5)
        ]
        existing_review = [
            make_existing_non_meity(index, DECISION_ADMIN_REVIEW) for index in range(5, 11)
        ]

        extracted_path = data_dir / "extracted_scheme_records_v1.json"
        write_json(extracted_path, meity_records)
        # Mirror the production v1 layout: unified file contains all ten,
        # review queue contains six, and no separate approved file exists.
        unified_existing = []
        for record in existing_approved:
            stripped = dict(record)
            stripped.pop("validation_decision", None)
            stripped.pop("decision", None)
            unified_existing.append(stripped)
        unified_existing.extend(existing_review)
        write_json(data_dir / "validated_scheme_records_v1.json", unified_existing)
        write_json(data_dir / "admin_review_queue_v1.json", existing_review)
        write_json(data_dir / "rejected_scheme_records_v1.json", [])
        write_json(data_dir / "validation_audit_v1.json", [{"sentinel": "OLD_AUDIT"}])

        agent = MeityIncrementalValidationV24(
            project_root=root,
            as_of_date=date(2026, 7, 9),
        )

        # Real MeitY pages may contain deadlines from older cohorts. Such a date
        # must not close an evergreen scheme, while a discovery/extraction conflict
        # on an active call must be surfaced for review rather than called historical.
        stale_scheme = make_meity_record(90, "Evergreen Scheme")
        stale_scheme["closing_date"] = "2024-12-31"
        stale_scheme["scheme_status"] = "CLOSED_OR_DEADLINE_PASSED"
        status, reasons = agent._programme_status(stale_scheme)
        assert status == "SCHEME_INFORMATION_AVAILABLE"
        assert "HISTORICAL_DATE_MENTION_ON_SCHEME_PAGE" in reasons

        conflicting_call = make_meity_record(91, "Active Call Conflict", active_call=True)
        conflicting_call["closing_date"] = "2024-12-31"
        status, reasons = agent._programme_status(conflicting_call)
        assert status == "CALL_STATUS_CONFLICT_REQUIRES_REVIEW"
        assert "CALL_STATUS_CONFLICT_REQUIRES_REVIEW" in reasons
        result = agent.run(
            extracted_records_path=extracted_path,
            output_dir=output_dir,
            publish_canonical=False,
        )

        assert result.summary["hotfix_version"] == "2.4.1"
        assert result.summary["input_extracted_record_count"] == 6
        assert result.summary["meity_extracted_record_count"] == 6
        assert result.summary["existing_validation_record_count"] == 10
        assert result.summary["existing_non_meity_validation_count"] == 10
        assert result.summary["existing_meity_validation_count"] == 0
        assert result.summary["processed_meity_validation_count"] == 6
        assert result.summary["output_validation_record_count"] == 16
        assert result.summary["output_meity_validation_count"] == 6
        assert result.summary["non_meity_validation_records_preserved"] == 10
        assert result.summary["failure_count"] == 0
        assert result.summary["actions"] == {"VALIDATED_NEW": 6}
        assert result.summary["decisions"] == {
            DECISION_APPROVED: 2,
            DECISION_ADMIN_REVIEW: 2,
            DECISION_MORE_EVIDENCE: 2,
        }
        assert result.summary["approved_for_database_count"] == 2
        assert result.summary["admin_review_queue_count"] == 4
        assert result.summary["rejected_count"] == 0
        assert result.summary["meity_approved_for_database_count"] == 2
        assert result.summary["meity_admin_review_queue_count"] == 4
        assert result.summary["meity_rejected_count"] == 0
        assert result.summary["merged_approved_for_database_count"] == 6
        assert result.summary["merged_admin_review_queue_count"] == 10
        # Programme pages remain scheme information even if stale cohort dates appear.
        scheme_record = next(item for item in result.meity_records if item["scheme_name"] == "SAMRIDH")
        assert scheme_record["programme_status"] == "SCHEME_INFORMATION_AVAILABLE"

        for index in range(1, 11):
            preserved = next(
                record for record in result.records if record.get("master_id") == f"existing-{index}"
            )
            assert preserved["sentinel"] == f"PRESERVE-{index}"

        expected_files = (
            "validated_scheme_records_v2_4.json",
            "approved_for_database_v2_4.json",
            "admin_review_queue_v2_4.json",
            "rejected_scheme_records_v2_4.json",
            "meity_incremental_validation_audit_v2_4.json",
            "meity_incremental_validation_failures_v2_4.json",
            "meity_incremental_validation_summary_v2_4.json",
        )
        for filename in expected_files:
            assert (output_dir / filename).exists(), filename

        incremental_approved = json.loads(
            (output_dir / "approved_for_database_v2_4.json").read_text(encoding="utf-8")
        )
        incremental_review = json.loads(
            (output_dir / "admin_review_queue_v2_4.json").read_text(encoding="utf-8")
        )
        assert len(incremental_approved) == 2
        assert len(incremental_review) == 4
        assert all(item.get("source") == "MeitY Startup Hub" for item in incremental_approved)
        assert all(item.get("source") == "MeitY Startup Hub" for item in incremental_review)

        # The second run against the v2.4 unified output must reuse all six MeitY decisions.
        second_result = agent.run(
            extracted_records_path=extracted_path,
            existing_validations_path=output_dir / "validated_scheme_records_v2_4.json",
            output_dir=second_output_dir,
            publish_canonical=False,
        )
        assert second_result.summary["actions"] == {"REUSED_UNCHANGED": 6}
        assert second_result.summary["actionable_meity_validation_count"] == 0
        assert second_result.summary["unchanged_meity_loader_suppressed_count"] == 6
        assert second_result.summary["approved_for_database_count"] == 0
        assert second_result.summary["admin_review_queue_count"] == 0
        assert second_result.summary["output_validation_record_count"] == 16
        assert second_result.summary["non_meity_validation_records_preserved"] == 10
        assert second_result.summary["failure_count"] == 0

        # Production publishing must preserve legacy category files, merge the unified
        # validation history, append audit, and create backups only for published files.
        published = agent.run(
            extracted_records_path=extracted_path,
            output_dir=data_dir,
            publish_canonical=True,
        )
        assert published.summary["canonical_published"] is True
        canonical_validated = json.loads(
            (data_dir / "validated_scheme_records_v1.json").read_text(encoding="utf-8")
        )
        canonical_review = json.loads(
            (data_dir / "admin_review_queue_v1.json").read_text(encoding="utf-8")
        )
        canonical_audit = json.loads(
            (data_dir / "validation_audit_v1.json").read_text(encoding="utf-8")
        )
        assert len(canonical_validated) == 16
        assert len(canonical_review) == 6
        assert len(canonical_audit) == 7
        assert published.summary["legacy_category_files_published"] is False
        assert not (data_dir / "approved_for_database_v1.pre_v2_4_backup.json").exists()
        assert not (data_dir / "admin_review_queue_v1.pre_v2_4_backup.json").exists()
        assert (data_dir / "validation_audit_v1.pre_v2_4_backup.json").exists()

        print(json.dumps(result.summary, indent=2))
        print("MeitY Incremental Validation v2.4.1 hotfix self-test passed.")


if __name__ == "__main__":
    main()
