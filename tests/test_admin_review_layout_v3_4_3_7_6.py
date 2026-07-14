from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = PROJECT_ROOT / "ui/admin_review_app_v1.py"
HELPER_NAME = "_render_three_column_review_workspace"


class AdminReviewThreeColumnLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = UI_PATH.read_text(encoding="utf-8-sig")
        cls.tree = ast.parse(cls.text)
        cls.helper = next(
            (
                node
                for node in cls.tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == HELPER_NAME
            ),
            None,
        )

    def test_ui_is_valid_python(self) -> None:
        self.assertIsNotNone(self.tree)
        self.assertIsNotNone(self.helper)

    def test_three_primary_reading_columns_exist(self) -> None:
        for marker in (
            "### 1. Identity & ownership",
            "### 2. Official evidence & status",
            "### 3. Readiness, conflicts & history",
        ):
            self.assertIn(marker, self.text)

    def test_all_editable_sections_are_visible_without_tabs(self) -> None:
        for marker in (
            "## All editable review fields",
            "### A. Identity, organization & relationship",
            "### B. Status, dates & official evidence",
            "### C. Funding & support",
            "### D. Structured content — one item per line",
        ):
            self.assertIn(marker, self.text)

    def test_all_existing_editable_fields_are_covered(self) -> None:
        expected = {
            "scheme_name",
            "short_name",
            "source",
            "ministry",
            "department",
            "implementing_agency",
            "record_kind",
            "programme_status",
            "application_status",
            "scheme_status",
            "geographic_scope",
            "official_page_url",
            "application_url",
            "opening_date",
            "closing_date",
            "parent_master_id",
            "parent_scheme_name",
            "parent_resolution",
            "applicant_layer",
            "startup_relevance",
            "implementation_role",
            "sector_scope",
            "status_basis",
            "status_evidence",
            "last_verified_at",
            "source_evidence_urls",
            "funding_minimum",
            "funding_maximum",
            "currency",
            "beneficiary_minimum",
            "beneficiary_maximum",
            "intermediary_support_maximum",
            "scheme_corpus",
            "scheme_type",
            "target_beneficiaries",
            "startup_stage",
            "sector",
            "states_or_uts",
            "objectives",
            "eligibility",
            "benefits",
            "application_process",
            "selection_process",
            "required_documents",
            "guideline_urls",
        }

        self.assertIsNotNone(self.helper)

        helper_string_constants = {
            node.value
            for node in ast.walk(self.helper)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        }

        literal_value_assignments: set[str] = set()
        dynamic_values_assignment_found = False

        for node in ast.walk(self.helper):
            if not isinstance(node, ast.Subscript):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id != "values":
                continue

            slice_node = node.slice
            if isinstance(slice_node, ast.Constant) and isinstance(
                slice_node.value,
                str,
            ):
                literal_value_assignments.add(slice_node.value)
            elif isinstance(slice_node, ast.Name) and slice_node.id == "field":
                dynamic_values_assignment_found = True

        covered = helper_string_constants | literal_value_assignments
        missing = sorted(expected - covered)

        self.assertTrue(
            dynamic_values_assignment_found,
            "Structured-list fields must be rendered through values[field].",
        )
        self.assertEqual(missing, [])

    def test_structured_fields_are_split_across_three_columns(self) -> None:
        expected_groups = (
            {
                "scheme_type",
                "target_beneficiaries",
                "objectives",
                "eligibility",
            },
            {
                "startup_stage",
                "sector",
                "benefits",
                "application_process",
            },
            {
                "states_or_uts",
                "selection_process",
                "required_documents",
                "guideline_urls",
            },
        )

        self.assertIsNotNone(self.helper)
        helper_constants = {
            node.value
            for node in ast.walk(self.helper)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        }

        for group in expected_groups:
            self.assertTrue(group.issubset(helper_constants))

        self.assertIn(
            'list_columns = st.columns(3, gap="large")',
            self.text,
        )

    def test_governance_actions_are_preserved(self) -> None:
        for marker in (
            "service.save_draft(",
            "service.approve(",
            "service.mark_needs_more_evidence(",
            "service.reject(",
            "service.reopen(",
        ):
            self.assertIn(marker, self.text)

    def test_three_column_layout_activates_before_legacy_tabs(self) -> None:
        call_position = self.text.find(
            "    _render_three_column_review_workspace(\n"
        )
        legacy_position = self.text.find(
            '    st.subheader(record.get("scheme_name")'
        )
        return_position = self.text.find(
            "    return\n",
            call_position,
        )

        self.assertGreaterEqual(call_position, 0)
        self.assertGreater(legacy_position, call_position)
        self.assertGreater(return_position, call_position)
        self.assertLess(return_position, legacy_position)

    def test_complete_stored_record_is_visible(self) -> None:
        self.assertIn("Complete stored record", self.text)
        self.assertIn("st.json(record, expanded=True)", self.text)


if __name__ == "__main__":
    unittest.main()
