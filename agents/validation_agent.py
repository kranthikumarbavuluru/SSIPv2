from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class ValidationResult:
    passed: bool
    checks: dict[str, bool]
    errors: list[str]

class PublicationValidationAgent:
    def validate(
        self,
        original_rows: list[dict[str, Any]],
        updated_rows: list[dict[str, Any]],
        taxonomy_names: set[str],
        id_column: str,
        sector_column: str,
        allow_review_rows: bool,
    ) -> ValidationResult:
        original_ids = [str(r.get(id_column, "")) for r in original_rows]
        updated_ids = [str(r.get(id_column, "")) for r in updated_rows]
        invalid = [
            r for r in updated_rows
            if str(r.get(sector_column, "")).strip() not in taxonomy_names
        ]
        review_rows = [
            r for r in updated_rows
            if str(r.get("sector_review_required", "")).casefold() in {"true", "1", "yes"}
        ]
        checks = {
            "row_count_preserved": len(original_rows) == len(updated_rows),
            "identity_order_preserved": original_ids == updated_ids,
            "zero_blank_sector": all(str(r.get(sector_column, "")).strip() for r in updated_rows),
            "all_sectors_in_taxonomy": len(invalid) == 0,
            "review_policy_satisfied": allow_review_rows or len(review_rows) == 0,
            "one_output_per_input": len(updated_rows) == len(original_rows),
        }
        errors = [name for name, passed in checks.items() if not passed]
        return ValidationResult(all(checks.values()), checks, errors)
