from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

from agents.dbt_birac.source_registry_v3_4_5_0 import BIRAC, DEPARTMENT, MINISTRY, build_source_registry
from services.dbt_birac_governed_pilot_v3_4_5_0 import (
    CALLS,
    DBTBIRACGovernedPilot,
    OUTPUT_NAMES,
    PipelinePaths,
    classify_page_role,
    load_config,
    protected_hashes,
)
from ssip_dashboard.dbt_birac_preview import filter_dbt_birac_preview, load_dbt_birac_preview, public_apply_url


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/departments/dbt_birac/v3_4_5_0"


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class DBTBIRACGovernedPilotTests(unittest.TestCase):
    def test_registry_is_official_bounded_and_unique(self) -> None:
        registry = build_source_registry()
        self.assertEqual(len(registry), len({row["source_id"] for row in registry}))
        self.assertTrue(all(row["official_url"].startswith("https://") for row in registry))
        self.assertTrue(all(row["permitted_domain"].endswith(("birac.nic.in", "dbtindia.gov.in")) for row in registry))
        config = load_config(ROOT / "config/dbt_birac_governed_pilot_v3_4_5_0.json")
        self.assertLessEqual(len(registry), config["max_pages"])
        self.assertEqual(config["max_depth"], 1)

    def test_page_roles_exclude_directories_and_keep_documents(self) -> None:
        self.assertEqual(classify_page_role("Calls", "https://birac.nic.in/cfp.php"), "DIRECTORY")
        self.assertEqual(classify_page_role("PACE Guidelines", "https://birac.nic.in/x.pdf"), "SUPPORTING_DOCUMENT")

    def test_ownership_separates_ministry_department_and_agency(self) -> None:
        rows = read_csv(OUTPUT_NAMES["permanent"])
        self.assertTrue(all(row["ministry"] == MINISTRY for row in rows))
        self.assertTrue(all(row["department"] == DEPARTMENT for row in rows))
        birac = next(row for row in rows if row["canonical_name"] == "Biotechnology Ignition Grant (BIG)")
        biocare = next(row for row in rows if row["canonical_name"].startswith("Biotechnology Career Advancement"))
        self.assertEqual(birac["implementing_agency"], BIRAC)
        self.assertNotEqual(biocare["implementing_agency"], BIRAC)

    def test_programme_call_and_recurring_round_identities_are_separate(self) -> None:
        permanent = read_csv(OUTPUT_NAMES["permanent"])
        history = read_csv(OUTPUT_NAMES["historical"])
        big = next(row for row in permanent if row["canonical_name"] == "Biotechnology Ignition Grant (BIG)")
        rounds = [row for row in history if row["canonical_name"] in {"BIG Call 24", "BIG Call 25"}]
        self.assertEqual(len(rounds), 2)
        self.assertEqual(len({row["record_id"] for row in rounds}), 2)
        self.assertTrue(all(row["parent_record_id"] == big["record_id"] for row in rounds))
        self.assertNotIn("Call", big["canonical_name"])

    def test_current_status_is_evidence_gated_and_historical_apply_is_suppressed(self) -> None:
        self.assertEqual(read_csv(OUTPUT_NAMES["calls"]), [])
        history = read_csv(OUTPUT_NAMES["historical"])
        self.assertTrue(all(row["application_status"] == "CLOSED" for row in history))
        self.assertTrue(all(not row["application_url"] for row in history))
        self.assertTrue(any(row["closing_date"] == "2026-07-15" for row in history))

    def test_challenge_and_intermediary_layers_are_separate(self) -> None:
        challenges = read_csv(OUTPUT_NAMES["challenges"])
        intermediary = read_csv(OUTPUT_NAMES["intermediary"])
        self.assertEqual({row["record_type"] for row in challenges}, {"CHALLENGE"})
        self.assertTrue(all(row["record_type"] == "IMPLEMENTATION_PARTNER_OPPORTUNITY" for row in intermediary))
        self.assertTrue(all(row["startup_relevance"] == "INTERMEDIARY_OR_INSTITUTION_LAYER" for row in intermediary))

    def test_extensions_resolve_to_existing_call_and_duplicates_to_canonical_url(self) -> None:
        extensions = read_csv(OUTPUT_NAMES["extensions"])
        duplicates = read_csv(OUTPUT_NAMES["duplicates"])
        self.assertTrue(all(row["resolution"] == "MERGED_WITH_EXISTING_CALL" for row in extensions))
        self.assertEqual(len({row["notice_id"] for row in extensions}), 3)
        self.assertTrue(all(row["resolution"].startswith("DUPLICATE") for row in duplicates))

    def test_sector_support_and_applicant_mappings_cite_official_evidence(self) -> None:
        for name in (OUTPUT_NAMES["sectors"], OUTPUT_NAMES["support"], OUTPUT_NAMES["applicants"]):
            rows = read_csv(name)
            self.assertTrue(rows)
            self.assertTrue(all(row["evidence_url"].startswith("https://") for row in rows))

    def test_public_loader_hides_review_records_and_suppresses_unverified_apply_actions(self) -> None:
        bundle = load_dbt_birac_preview(ROOT)
        self.assertTrue(bundle.records)
        self.assertTrue(all(row.publication_status == "PUBLIC_DEPARTMENT_PAGE" for row in bundle.records))
        self.assertNotIn("REVIEW_REQUIRED", {row.record_type for row in bundle.records})
        self.assertTrue(bundle.review_items)
        self.assertTrue(all(public_apply_url(row) == "" and row.application_url == "" for row in bundle.records))
        filtered = filter_dbt_birac_preview(bundle.records, sector="healthcare")
        self.assertTrue(filtered)
        self.assertTrue(all("healthcare" in row.sector.split(";") for row in filtered))

    def test_reconciliation_preserves_existing_master_ids_and_admin_state(self) -> None:
        rows = read_csv(OUTPUT_NAMES["reconciliation"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["mutation_performed"] == "0" for row in rows))
        self.assertTrue(any(row["existing_admin_review_status"] for row in rows))

    def test_signed_manifest_is_deterministic_and_matches_files(self) -> None:
        manifest = json.loads((DATA / OUTPUT_NAMES["manifest"]).read_text(encoding="utf-8"))
        for name, expected in manifest["signed_files"].items():
            self.assertEqual(hashlib.sha256((DATA / name).read_bytes()).hexdigest(), expected)
        payload = json.dumps(
            {"counts": manifest["counts"], "files": manifest["signed_files"], "version": manifest["version"]},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["signature"])

    def test_required_outputs_and_validation_exist(self) -> None:
        self.assertTrue(all((DATA / name).exists() for name in OUTPUT_NAMES.values()))
        validation = json.loads((DATA / OUTPUT_NAMES["validation"]).read_text(encoding="utf-8"))
        self.assertEqual(validation["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
