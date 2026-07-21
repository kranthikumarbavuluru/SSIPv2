from __future__ import annotations

from typing import Any

from services.admin_review_service_v1 import (
    AdminReviewService as BaseAdminReviewService,
)


class AdminReviewService(BaseAdminReviewService):
    """Admin service aware of explicit audited legacy identity mappings."""

    def reconciled_aliases(
        self,
        canonical_master_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            exists = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type='table'
                  AND name='identity_reconciliations'
                """
            ).fetchone()
            if not exists:
                return []

            rows = connection.execute(
                """
                SELECT legacy_master_id,canonical_master_id,
                       canonical_name,legacy_table,legacy_status,
                       official_page_url,reconciliation_reason,
                       mapping_version,created_at,import_run_id
                FROM identity_reconciliations
                WHERE canonical_master_id=?
                ORDER BY reconciliation_id
                """,
                (canonical_master_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def duplicate_candidates(
        self,
        master_id: str,
        record: dict[str, Any],
    ) -> list[dict[str, str]]:
        matches = super().duplicate_candidates(master_id, record)
        reconciled_legacy_ids = {
            row["legacy_master_id"]
            for row in self.reconciled_aliases(master_id)
        }
        return [
            match
            for match in matches
            if not (
                match.get("table") == "admin_review_queue"
                and str(match.get("status") or "").upper()
                == "REJECTED"
                and match.get("master_id")
                in reconciled_legacy_ids
            )
        ]
