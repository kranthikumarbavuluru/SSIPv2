from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ssip_dashboard.source_directory import filter_sources, load_official_sources, source_summary


class PublicDashboardSourceDirectoryTest(unittest.TestCase):
    def test_loads_official_sources_without_database_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "public_dashboard_official_sources_v3_0.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "startup_india",
                                "name": "Startup India",
                                "scope": "Central",
                                "ministry": "Ministry of Commerce and Industry",
                                "department": "DPIIT",
                                "agency": "Startup India",
                                "source_type": "startup_scheme_directory",
                                "priority": "HIGH",
                                "official_url": "https://www.startupindia.gov.in/",
                                "seed_urls": ["https://www.startupindia.gov.in/"],
                                "coverage_note": "Central startup source.",
                                "status": "DISCOVERY_SEED",
                            },
                            {
                                "source_id": "state_policy",
                                "name": "State Startup Policies",
                                "scope": "State/UT",
                                "ministry": "Government of India",
                                "department": "DPIIT",
                                "agency": "Startup India",
                                "source_type": "state_policy_directory",
                                "priority": "MEDIUM",
                                "official_url": "https://www.startupindia.gov.in/content/sih/en/state-startup-policies.html",
                                "seed_urls": [],
                                "coverage_note": "State policy source.",
                                "status": "DISCOVERY_SEED",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            sources = load_official_sources(root)

        stats = source_summary(sources)
        self.assertEqual(stats["total_sources"], 2)
        self.assertEqual(stats["central_sources"], 1)
        self.assertEqual(stats["state_sources"], 1)
        self.assertEqual(stats["departments"], 1)
        self.assertEqual(sources[0].official_url, "https://www.startupindia.gov.in/")

    def test_filter_sources_by_keyword_scope_and_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "public_dashboard_official_sources_v3_0.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "birac",
                                "name": "BIRAC Support",
                                "scope": "Central",
                                "ministry": "Ministry of Science and Technology",
                                "department": "DBT",
                                "agency": "BIRAC",
                                "source_type": "biotech_grant_directory",
                                "priority": "HIGH",
                                "official_url": "https://birac.nic.in/",
                                "seed_urls": ["https://birac.nic.in/"],
                                "coverage_note": "Biotechnology startup grants.",
                                "status": "DISCOVERY_SEED",
                            },
                            {
                                "source_id": "kerala",
                                "name": "Kerala Startup Mission",
                                "scope": "State/UT",
                                "ministry": "Government of Kerala",
                                "department": "Electronics and IT Department",
                                "agency": "Kerala Startup Mission",
                                "source_type": "state_startup_portal",
                                "priority": "MEDIUM",
                                "official_url": "https://startupmission.kerala.gov.in/",
                                "seed_urls": ["https://startupmission.kerala.gov.in/"],
                                "coverage_note": "State startup programmes.",
                                "status": "DISCOVERY_SEED",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            sources = load_official_sources(root)

        filtered = filter_sources(sources, keyword="biotech", scope="Central", priority="HIGH")
        self.assertEqual([source.source_id for source in filtered], ["birac"])


if __name__ == "__main__":
    unittest.main()
