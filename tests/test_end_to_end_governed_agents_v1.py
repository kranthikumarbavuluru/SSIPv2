import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agents.governed_v1.common import dashboard_public_ids, read_csv, sha256_file
from agents.governed_v1.orchestrator import GovernedAgentOrchestrator


ROOT = Path(__file__).resolve().parents[1]


class GovernedAgentsEndToEndTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        (root / "config").mkdir()
        for name in (
            "governed_agents_v1.json", "record_role_rules_v1.json",
            "startup_relevance_rules_v1.json", "sector_taxonomy_v1.json",
            "official_domain_allowlist_v1.json",
        ):
            shutil.copy2(ROOT / "config" / name, root / "config" / name)
        active = root / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
        active.parent.mkdir(parents=True)
        fields = [
            "master_id", "scheme_name", "normalized_record_kind", "official_page_url",
            "department", "ministry", "eligibility", "benefits", "application_process",
            "objectives", "closing_date",
        ]
        rows = [
            {"master_id": "sisfs", "scheme_name": "Startup India Seed Fund Scheme", "normalized_record_kind": "SCHEME_OR_PROGRAMME", "official_page_url": "https://startupindia.gov.in/sisfs", "department": "DPIIT", "ministry": "Commerce", "eligibility": "DPIIT-recognised startup", "benefits": "Seed funding and proof of concept grant", "application_process": "Apply through the application portal", "objectives": "Startup innovation support"},
            {"master_id": "nidhi-prayas", "scheme_name": "NIDHI-PRAYAS", "normalized_record_kind": "SCHEME_OR_PROGRAMME", "official_page_url": "https://dst.gov.in/nidhi-prayas", "department": "DST", "ministry": "Science", "eligibility": "Innovator or startup through an incubator", "benefits": "Prototype support grant", "application_process": "Apply through approved incubator", "objectives": "Innovation and entrepreneurship"},
            {"master_id": "round-2026", "scheme_name": "NIDHI-PRAYAS Application Round 2026", "normalized_record_kind": "APPLICATION_CALL", "official_page_url": "https://dst.gov.in/nidhi-prayas-call", "department": "DST", "ministry": "Science", "eligibility": "Innovator and startup", "benefits": "Prototype support", "application_process": "Call for applications", "closing_date": "2026-12-31"},
            {"master_id": "site-map", "scheme_name": "Sitemap.xml", "normalized_record_kind": "SCHEME_OR_PROGRAMME", "official_page_url": "https://dst.gov.in/sitemap.xml", "department": "DST", "ministry": "Science"},
            {"master_id": "university-only", "scheme_name": "University Research Infrastructure Support", "normalized_record_kind": "RESEARCH_SUPPORT", "official_page_url": "https://dst.gov.in/university-support", "department": "DST", "ministry": "Science", "eligibility": "Universities only and academic institutions only", "benefits": "Research infrastructure grant"},
        ]
        with active.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return active

    def test_preview_is_non_destructive_and_separates_calls_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = self._project(root)
            before = sha256_file(active)
            result = GovernedAgentOrchestrator(root).run_preview("test-preview")
            after = sha256_file(active)
            self.assertEqual(before, after)
            self.assertFalse(result["summary"]["active_catalogue_modified"])
            self.assertFalse(result["summary"]["published"])
            run_dir = root / "data/agent_runs/test-preview"
            expected = {
                "input_snapshot.csv", "classified_inventory.csv", "canonical_scheme_candidates.csv",
                "startup_relevant_schemes.csv", "call_instances.csv", "ecosystem_entities.csv",
                "supporting_documents.csv", "quarantined_records.csv", "manual_review_queue.csv",
                "sector_evidence.csv", "field_evidence.csv", "comparison_with_active.csv",
                "validation.json", "summary.json", "publication_candidate.csv",
                "deletion_approval_template.csv", "publication_approval_template.csv",
            }
            self.assertTrue(expected.issubset({path.name for path in run_dir.iterdir()}))
            calls, _ = read_csv(run_dir / "call_instances.csv")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["parent_scheme_id"], "nidhi-prayas")
            public, _ = read_csv(run_dir / "publication_candidate.csv")
            review, _ = read_csv(run_dir / "manual_review_queue.csv")
            public_ids = {row["scheme_master_id"] for row in public}
            review_ids = {row.get("scheme_master_id", "") for row in review}
            self.assertFalse(public_ids & {item for item in review_ids if item})
            self.assertFalse((root / "data/publication/current/public_catalogue.csv").exists())

    def test_nightly_task_installs_preview_only(self) -> None:
        text = (ROOT / "INSTALL_NIGHTLY_AGENT_PREVIEW_TASK_v1.ps1").read_text(encoding="utf-8")
        self.assertIn("RUN_GOVERNED_AGENTS_PREVIEW_v1.ps1", text)
        self.assertNotIn("PUBLISH_APPROVED_AGENT_RUN_v1.ps1", text)

    def test_current_51_record_population_is_recoverable(self) -> None:
        active = ROOT / "data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"
        self.assertEqual(len(dashboard_public_ids(ROOT, active)), 51)
        backups = sorted((ROOT / "backups/codex_governed_agents").glob("*/data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv"))
        self.assertTrue(backups)
        self.assertEqual(sha256_file(backups[-1]), sha256_file(active))


if __name__ == "__main__":
    unittest.main()
