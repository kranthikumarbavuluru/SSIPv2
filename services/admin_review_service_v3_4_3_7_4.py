from __future__ import annotations

from typing import Any

from services.admin_review_service_v3_4_3_7_2 import (
    AdminReviewService as BaseAdminReviewService,
)
from services.organization_canonicalization_v3_4_3_7_4 import (
    MINISTRY_LEVEL_LABEL,
)


class AdminReviewService(BaseAdminReviewService):
    """Admin review service with ministry-level department filtering."""

    def list_reviews(
        self,
        *,
        review_status: str = "PENDING",
        priority: str | None = None,
        decision: str | None = None,
        source: str | None = None,
        record_kind: str | None = None,
        applicant_layer: str | None = None,
        department: str | None = None,
        ministry: str | None = None,
        import_run: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if review_status and review_status != "ALL":
            clauses.append("review_status = ?")
            params.append(review_status)
        if priority and priority != "ALL":
            clauses.append("priority = ?")
            params.append(priority)
        if decision and decision != "ALL":
            clauses.append("decision = ?")
            params.append(decision)
        if source and source != "ALL":
            clauses.append("source = ?")
            params.append(source)
        if record_kind and record_kind != "ALL":
            clauses.append("record_kind = ?")
            params.append(record_kind)
        if applicant_layer and applicant_layer != "ALL":
            clauses.append(
                "json_extract(validated_record_json, '$.applicant_layer') = ?"
            )
            params.append(applicant_layer)
        if department and department != "ALL":
            if department == MINISTRY_LEVEL_LABEL:
                clauses.append(
                    "COALESCE(TRIM(json_extract(validated_record_json, '$.department')), '') = '' "
                    "AND COALESCE(TRIM(json_extract(validated_record_json, '$.ministry')), '') <> ''"
                )
            else:
                clauses.append(
                    "json_extract(validated_record_json, '$.department') = ?"
                )
                params.append(department)
        if ministry and ministry != "ALL":
            clauses.append(
                "json_extract(validated_record_json, '$.ministry') = ?"
            )
            params.append(ministry)
        if import_run and import_run != "ALL":
            clauses.append("last_import_run_id = ?")
            params.append(import_run)
        if search:
            clauses.append("(scheme_name LIKE ? OR master_id LIKE ? OR source LIKE ?)")
            term = f"%{search.strip()}%"
            params.extend([term, term, term])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT master_id, scheme_name, source, record_kind, programme_status,
                   application_status, official_page_url, application_url, decision,
                   validation_score, review_status, priority, warnings_json,
                   recommended_actions_json, updated_at, last_import_run_id,
                   json_extract(validated_record_json, '$.department') AS department,
                   json_extract(validated_record_json, '$.ministry') AS ministry,
                   json_extract(validated_record_json, '$.applicant_layer') AS applicant_layer,
                   json_extract(validated_record_json, '$.parent_scheme_name') AS parent_scheme_name
            FROM admin_review_queue
            {where}
            ORDER BY
                CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                CASE review_status WHEN 'PENDING' THEN 1 WHEN 'APPROVED' THEN 2 ELSE 3 END,
                validation_score DESC,
                scheme_name
        """
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()

        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["warnings"] = self._decode_json(item.pop("warnings_json", None), [])
            item["recommended_actions"] = self._decode_json(
                item.pop("recommended_actions_json", None), []
            )
            if (
                not str(item.get("department") or "").strip()
                and str(item.get("ministry") or "").strip()
            ):
                item["department"] = MINISTRY_LEVEL_LABEL
            output.append(item)
        return output

    @staticmethod
    def _decode_json(value: Any, default: Any) -> Any:
        import copy
        import json

        if value in (None, ""):
            return copy.deepcopy(default)
        if isinstance(value, (dict, list)):
            return copy.deepcopy(value)
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return copy.deepcopy(default)

    def filter_options(self) -> dict[str, list[str]]:
        options = super().filter_options()
        with self._connect() as connection:
            ministry_level_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM admin_review_queue
                WHERE COALESCE(
                    TRIM(json_extract(validated_record_json, '$.department')),
                    ''
                ) = ''
                  AND COALESCE(
                    TRIM(json_extract(validated_record_json, '$.ministry')),
                    ''
                ) <> ''
                """
            ).fetchone()[0]
        departments = [
            value
            for value in options.get("departments", [])
            if str(value or "").strip()
        ]
        if ministry_level_count:
            departments.append(MINISTRY_LEVEL_LABEL)
        options["departments"] = sorted(set(departments))
        return options
