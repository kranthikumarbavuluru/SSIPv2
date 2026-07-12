from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import PUBLIC_RELEVANCE_CLASSES, canonical_key, first, read_csv


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    checks: dict[str, bool]
    details: dict[str, Any]


class PublicationGuardAgent:
    BLOCKED_ROLES = {
        "NAVIGATION_OR_UTILITY", "CATEGORY_OR_INDEX_PAGE", "REPORT_OR_PUBLICATION",
        "SUPPORTING_DOCUMENT", "GUIDELINE_OR_NOTIFICATION", "CALL_INSTANCE",
    }

    @staticmethod
    def approved_deletions(path: Path | None) -> set[str]:
        if not path or not path.exists():
            return set()
        rows, _ = read_csv(path)
        return {
            first(row, "master_id") for row in rows
            if first(row, "proposed_action") == "APPROVE_REMOVAL"
            and first(row, "approved_by") and first(row, "approval_date")
        }

    def validate(
        self,
        public_rows: list[dict[str, str]],
        call_rows: list[dict[str, str]],
        active_public_ids: set[str],
        input_snapshot_exists: bool,
        active_unchanged: bool,
        taxonomy: set[str],
        deletion_approval_path: Path | None = None,
    ) -> GuardResult:
        ids = [first(row, "scheme_master_id", "master_id") for row in public_rows]
        identities = [canonical_key(first(row, "canonical_name", "scheme_name")) for row in public_rows]
        candidate_ids = {item for item in ids if item}
        missing_active = active_public_ids - candidate_ids
        approved = self.approved_deletions(deletion_approval_path)
        checks = {
            "input_snapshot_exists": input_snapshot_exists,
            "active_catalogue_unchanged_during_run": active_unchanged,
            "all_public_records_have_master_id": all(ids),
            "all_public_records_have_canonical_name": all(first(row, "canonical_name", "scheme_name") for row in public_rows),
            "all_public_records_have_official_source": all(first(row, "official_master_url", "official_page_url", "source_url") for row in public_rows),
            "all_public_records_have_startup_relevance_evidence": all(first(row, "startup_beneficiary_evidence") and first(row, "startup_access_evidence") for row in public_rows),
            "all_public_records_have_primary_sector": all(first(row, "primary_sector", "sector") for row in public_rows),
            "no_navigation_records_in_public": all(first(row, "record_role") != "NAVIGATION_OR_UTILITY" for row in public_rows),
            "no_reports_in_public": all(first(row, "record_role") != "REPORT_OR_PUBLICATION" for row in public_rows),
            "no_supporting_documents_in_public": all(first(row, "record_role") not in {"SUPPORTING_DOCUMENT", "GUIDELINE_OR_NOTIFICATION"} for row in public_rows),
            "no_calls_counted_as_schemes": all(first(row, "record_role") != "CALL_INSTANCE" for row in public_rows),
            "no_duplicate_master_ids": len(ids) == len(set(ids)),
            "no_duplicate_canonical_identities": len(identities) == len(set(identities)),
            "all_calls_have_parent_or_manual_review": all(first(row, "parent_scheme_id") or first(row, "manual_review_required").lower() == "true" for row in call_rows),
            "all_sector_values_in_taxonomy": all(first(row, "primary_sector", "sector") in taxonomy for row in public_rows),
            "all_deletions_require_manual_approval": missing_active.issubset(approved),
            "no_review_required_records_in_public": all(first(row, "manual_review_required").lower() != "true" and first(row, "sector_review_required").lower() != "true" for row in public_rows),
            "only_allowed_relevance_classes_public": all(first(row, "startup_relevance_classification") in PUBLIC_RELEVANCE_CLASSES for row in public_rows),
            "sector_and_primary_sector_match": all(first(row, "sector") == first(row, "primary_sector") for row in public_rows),
        }
        checks["validation_passed"] = all(checks.values())
        return GuardResult(
            checks["validation_passed"],
            checks,
            {
                "active_public_count": len(active_public_ids),
                "candidate_public_count": len(public_rows),
                "proposed_deletion_count": len(missing_active),
                "approved_deletion_count": len(missing_active & approved),
                "unapproved_deletion_ids": sorted(missing_active - approved),
            },
        )
