from __future__ import annotations

import ast
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from services.dpiit_governed_pilot_v3_4_4_0 import (
    DPIITGovernedPilot,
    OUTPUT_NAMES,
    PipelinePaths,
    classify_page_role,
    load_config,
)
from ssip_dashboard.dpiit_preview import filter_dpiit_preview, load_dpiit_preview


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class DPIITGovernedPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = PipelinePaths.defaults(PROJECT_ROOT)
        cls.service = DPIITGovernedPilot(cls.paths, load_config(cls.paths.config_path))
        cls.result = cls.service.run(live_network=False)

    def test_source_registry_and_official_domain_enforcement(self) -> None:
        sources = read_csv(self.paths.output_dir / OUTPUT_NAMES["sources"])
        self.assertGreaterEqual(len(sources), 20)
        self.assertTrue(all(row["allowed_for_discovery"] == "1" for row in sources))
        self.assertTrue(self.result["validation"]["checks"]["official_domains_enforced"])

    def test_page_roles_exclude_directories_and_support_documents(self) -> None:
        self.assertEqual(classify_page_role("", "https://startupindia.gov.in/government-schemes.html"), "DIRECTORY")
        self.assertEqual(classify_page_role("Guidelines", "https://startupindia.gov.in/file.pdf"), "SUPPORTING_DOCUMENT")
        excluded = read_csv(self.paths.output_dir / OUTPUT_NAMES["excluded"])
        self.assertEqual({row["page_role"] for row in excluded}, {"DIRECTORY"})

    def test_recognition_and_80iac_identity_boundary_is_preserved(self) -> None:
        permanent = read_csv(self.paths.output_dir / OUTPUT_NAMES["permanent"])
        by_id = {row["record_id"]: row for row in permanent}
        self.assertIn("dpiit_master_6c1afb477ef37cd6acaa", by_id)
        self.assertIn("dpiit_master_3b767c3b91080149015f", by_id)
        self.assertEqual(by_id["dpiit_master_6c1afb477ef37cd6acaa"]["record_type"], "GOVERNMENT_SERVICE")
        resolutions = read_csv(self.paths.output_dir / OUTPUT_NAMES["duplicates"])
        boundary = next(row for row in resolutions if row["resolution_id"] == "dpiit_service_boundary_80iac")
        self.assertEqual(boundary["relationship_type"], "REQUIRES_DPIIT_RECOGNITION")
        self.assertEqual(boundary["merge_allowed"], "0")

    def test_programmes_calls_and_parents_are_separate(self) -> None:
        permanent = read_csv(self.paths.output_dir / OUTPUT_NAMES["permanent"])
        calls = read_csv(self.paths.output_dir / OUTPUT_NAMES["calls"])
        permanent_ids = {row["record_id"] for row in permanent}
        self.assertTrue(calls)
        self.assertTrue(all(row["record_id"] not in permanent_ids for row in calls))
        self.assertTrue(all(row["parent_record_id"] in permanent_ids for row in calls))

    def test_historical_and_unpublished_records_never_expose_apply(self) -> None:
        historical = read_csv(self.paths.output_dir / OUTPUT_NAMES["historical"])
        preview = read_csv(self.paths.output_dir / OUTPUT_NAMES["preview"])
        self.assertGreaterEqual(len(historical), 3)
        self.assertTrue(all(row["application_status"] == "CLOSED" for row in historical))
        self.assertTrue(all(not row["application_url"] for row in historical))
        self.assertTrue(all(row["publication_status"] == "PREVIEW_NOT_PUBLISHED" for row in preview))

    def test_applicant_layer_and_ownership_are_explicit(self) -> None:
        applicants = read_csv(self.paths.output_dir / OUTPUT_NAMES["applicants"])
        ownership = read_csv(self.paths.output_dir / OUTPUT_NAMES["ownership"])
        self.assertTrue(all(row["direct_applicant_layer"] for row in applicants))
        fof = next(row for row in applicants if row["record_id"] == "dpiit_master_c89f3d410e746f1594dc")
        self.assertEqual(fof["direct_applicant_layer"], "fund manager/intermediary")
        self.assertTrue(all(row["ownership_status"].startswith("VERIFIED") for row in ownership))

    def test_manifest_is_signed_and_preview_only(self) -> None:
        manifest = self.result["manifest"]
        self.assertEqual(len(manifest["content_signature_sha256"]), 64)
        self.assertFalse(manifest["database_write_performed"])
        self.assertFalse(manifest["publication_performed"])
        self.assertEqual(manifest["counts"]["current_calls"], 0)

    def test_database_and_publication_are_not_mutated(self) -> None:
        before = self.result["validation"]["protected_hashes_before"]
        after = self.result["validation"]["protected_hashes_after"]
        for key in ("database", "publication_current", "dst", "meity"):
            self.assertEqual(before[key], after[key])

    def test_deterministic_offline_rerun(self) -> None:
        self.service.run(live_network=False)
        first = {name: (self.paths.output_dir / name).read_bytes() for name in OUTPUT_NAMES.values()}
        self.service.run(live_network=False)
        second = {name: (self.paths.output_dir / name).read_bytes() for name in OUTPUT_NAMES.values()}
        self.assertEqual(
            {name: hashlib.sha256(data).hexdigest() for name, data in first.items()},
            {name: hashlib.sha256(data).hexdigest() for name, data in second.items()},
        )

    def test_preview_loader_and_filters(self) -> None:
        bundle = load_dpiit_preview(PROJECT_ROOT)
        result = filter_dpiit_preview(bundle.records, keyword="Recognition", record_type="GOVERNMENT_SERVICE")
        self.assertEqual([row.record_id for row in result], ["dpiit_master_6c1afb477ef37cd6acaa"])
        historical = filter_dpiit_preview(bundle.records, status="CLOSED")
        self.assertTrue(historical)
        self.assertTrue(all(row.record_type == "HISTORICAL_CALL" for row in historical))

    def test_route_exists_and_home_function_has_no_dpiit_dependency(self) -> None:
        app_path = PROJECT_ROOT / "apps/public_dashboard_app_v2_9.py"
        text = app_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(text)
        home = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_home")
        home_text = ast.get_source_segment(text, home) or ""
        self.assertNotIn("dpiit", home_text.casefold())
        self.assertIn('"DPIIT": "dpiit-programmes"', text)
        self.assertIn("render_dpiit_page()", text)


if __name__ == "__main__":
    unittest.main()
