from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ssip_agents.discovery.source_registry_loader_v3_3 import (
    build_dry_run_report,
    duplicate_seed_urls,
    load_registry_sources,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class SourceRegistryV33Test(unittest.TestCase):
    def test_loads_base_registry_and_v33_additions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                root / "config" / "public_dashboard_official_sources_v3_0.json",
                {
                    "sources": [
                        {
                            "source_id": "base_source",
                            "name": "Base Source",
                            "scope": "Central",
                            "ministry": "Government of India",
                            "department": "Department",
                            "agency": "Base",
                            "source_type": "base",
                            "priority": "HIGH",
                            "official_url": "https://base.gov.in/",
                            "seed_urls": ["https://base.gov.in/"],
                            "coverage_note": "Base.",
                            "status": "DISCOVERY_SEED",
                        }
                    ]
                },
            )
            write_json(
                root / "config" / "official_source_registry_v3_3.json",
                {
                    "base_registry": "public_dashboard_official_sources_v3_0.json",
                    "defaults": {"enabled": True, "respect_robots": True, "rate_limit_per_domain_per_second": 0.5},
                    "discovery_batches": [],
                    "additional_sources": [
                        {
                            "source_id": "new_source",
                            "name": "New Source",
                            "scope": "State/UT",
                            "ministry": "Government of Andhra Pradesh",
                            "department": "Department",
                            "agency": "New",
                            "source_type": "state",
                            "priority": "MEDIUM",
                            "official_url": "https://new.ap.gov.in/",
                            "seed_urls": ["https://new.ap.gov.in/path/"],
                            "coverage_note": "New.",
                            "status": "DISCOVERY_SEED",
                        }
                    ],
                },
            )

            sources, _registry = load_registry_sources(root)

        self.assertEqual({source.source_id for source in sources}, {"base_source", "new_source"})
        new_source = next(source for source in sources if source.source_id == "new_source")
        self.assertEqual(new_source.seed_urls, ("https://new.ap.gov.in/path",))
        self.assertTrue(new_source.respect_robots)

    def test_duplicate_seed_urls_are_detected_after_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                root / "config" / "public_dashboard_official_sources_v3_0.json",
                {"sources": []},
            )
            write_json(
                root / "config" / "official_source_registry_v3_3.json",
                {
                    "base_registry": "public_dashboard_official_sources_v3_0.json",
                    "defaults": {"enabled": True, "respect_robots": True, "rate_limit_per_domain_per_second": 0.5},
                    "discovery_batches": [],
                    "additional_sources": [
                        {
                            "source_id": "one",
                            "name": "One",
                            "scope": "Central",
                            "ministry": "M",
                            "department": "D",
                            "agency": "A",
                            "source_type": "x",
                            "priority": "HIGH",
                            "official_url": "https://example.gov.in/path/",
                            "seed_urls": ["https://example.gov.in/path/"],
                            "coverage_note": "",
                            "status": "DISCOVERY_SEED",
                        },
                        {
                            "source_id": "two",
                            "name": "Two",
                            "scope": "Central",
                            "ministry": "M",
                            "department": "D",
                            "agency": "A",
                            "source_type": "x",
                            "priority": "HIGH",
                            "official_url": "https://example.gov.in/path",
                            "seed_urls": ["https://example.gov.in/path"],
                            "coverage_note": "",
                            "status": "DISCOVERY_SEED",
                        },
                    ],
                },
            )
            sources, _registry = load_registry_sources(root)

        duplicates = duplicate_seed_urls(sources)
        self.assertEqual(duplicates, [{"seed_url": "https://example.gov.in/path", "source_ids": ["one", "two"]}])

    def test_dry_run_report_includes_required_audit_fields(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        report = build_dry_run_report(project_root)

        self.assertGreaterEqual(report["total_enabled_sources"], 30)
        self.assertGreater(report["central_sources"], 0)
        self.assertGreater(report["state_ut_sources"], 0)
        self.assertIn("Ministry of Electronics and Information Technology", report["ministry_distribution"])
        self.assertIn("HIGH", report["priority_distribution"])
        self.assertGreater(report["seed_url_count"], 0)
        self.assertIsInstance(report["duplicate_seed_urls"], list)
        self.assertEqual(report["missing_authority_mappings"], [])
        self.assertEqual(report["missing_trusted_domain_mappings"], [])
        self.assertGreaterEqual(len(report["planned_discovery_batches"]), 3)
        self.assertEqual(report["network_requests_performed"], 0)
        self.assertEqual(report["database_writes_performed"], 0)
        sources, _registry = load_registry_sources(project_root)
        source_ids = {source.source_id for source in sources}
        self.assertIn("manage_agri_incubator_directory", source_ids)
        self.assertIn("angrau_poshan_call_source", source_ids)
        self.assertIn("pdkv_rif_startup_calls", source_ids)
        self.assertIn("afbic_iitkgp_startup_programmes", source_ids)
        self.assertIn("abif_iitkgp_startup_applications", source_ids)
        self.assertIn("msde_offerings_index", source_ids)
        self.assertIn("msde_whats_new", source_ids)
        self.assertIn("skill_india_digital_hub", source_ids)
        self.assertIn("nsdc_skill_programmes", source_ids)
        self.assertIn("moe_nep_innovation_index", source_ids)
        self.assertIn("moe_iic_industry_collaboration", source_ids)
        self.assertIn("aicte_mic_bootcamp_calls", source_ids)
        self.assertIn("pmrc_call_portal", source_ids)
        self.assertIn("moe_schemes_guidelines", source_ids)


if __name__ == "__main__":
    unittest.main()
