from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.meity_url_integrity_v3_4_3_8_0_4 import (
    ROLE_ABOUT,
    ROLE_APPLICATION,
    ROLE_HISTORICAL,
    ROLE_SCHEME,
    STATUS_WITHHELD,
    STATUS_VERIFIED,
    FetchResult,
    IntegrityPaths,
    URLIntegrityGate,
    inspect_link,
    load_config,
    page_role,
)


class FakeFetcher:
    def __init__(self, results: dict[str, FetchResult]) -> None:
        self.results = results

    def fetch(self, url: str) -> FetchResult:
        return self.results[url]


def result(
    url: str,
    *,
    final_url: str | None = None,
    status: int = 200,
    title: str = "",
    text: str = "",
    content_type: str = "text/html",
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        http_status=status,
        content_type=content_type,
        page_title=title,
        page_text=text,
        fetch_method="TEST",
        error="" if 200 <= status < 400 else f"HTTP:{status}",
        checked_at="2026-07-15T10:00:00+00:00",
    )


class MeitYURLIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_path = (
            Path(__file__).resolve().parents[1]
            / "config/meity_url_integrity_v3_4_3_8_0_4.json"
        )
        self.config = load_config(self.config_path)

    def test_apply_for_logo_is_about_page_not_application(self) -> None:
        url = "https://msh.meity.gov.in/about/applyforthelogo"
        child = {
            "child_id": "child_genesis",
            "bundle_id": "bundle_genesis",
            "canonical_name": "GENESIS",
            "entity_type": "PERMANENT_PROGRAMME",
            "temporal_validation": "CURRENT_STATUS_NOT_PROVEN",
        }
        fetch = result(
            url,
            title="Apply for the Logo | MeitY Startup Hub",
            text="About us. Apply for the logo and brand usage.",
        )
        role, flags = page_role(
            child,
            "application_url",
            fetch,
            self.config,
        )
        self.assertEqual(role, ROLE_ABOUT)
        self.assertIn("BLOCKED_APPLICATION_PATH", flags)

        inspected = inspect_link(
            child,
            "application_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=0,
        )
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_WITHHELD,
        )
        self.assertFalse(inspected["verified_application_link"])
        self.assertEqual(
            inspected["withheld_reason"],
            "GLOBAL_CURRENT_EVIDENCE_INCOMPLETE",
        )

    def test_historical_application_link_is_withheld(self) -> None:
        url = "https://msh.meity.gov.in/apply/old-cohort"
        child = {
            "child_id": "historical_child",
            "bundle_id": "historical_bundle",
            "canonical_name": "Old Cohort 2023",
            "entity_type": "ACCELERATOR_COHORT",
            "temporal_validation": "HISTORICAL_BY_TITLE_OR_DEADLINE",
        }
        fetch = result(
            url,
            title="Old Cohort 2023 Application Form",
            text="Apply now for Old Cohort 2023.",
        )
        inspected = inspect_link(
            child,
            "application_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=1,
        )
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_WITHHELD,
        )
        self.assertEqual(
            inspected["withheld_reason"],
            "CHILD_NOT_CURRENT_EVIDENCE_COMPLETE",
        )
        self.assertFalse(inspected["verified_application_link"])

    def test_official_domain_alone_is_insufficient(self) -> None:
        url = "https://msh.meity.gov.in/about"
        child = {
            "child_id": "child_xr",
            "bundle_id": "bundle_xr",
            "canonical_name": "XR Startup Program",
            "entity_type": "ACCELERATOR_PROGRAMME",
            "temporal_validation": "NOT_APPLICABLE",
        }
        fetch = result(
            url,
            title="About MeitY Startup Hub",
            text="About us and contact details.",
        )
        inspected = inspect_link(
            child,
            "official_page_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=0,
        )
        self.assertEqual(inspected["page_role"], ROLE_ABOUT)
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_WITHHELD,
        )
        self.assertFalse(inspected["verified_information_link"])

    def test_cross_entity_application_link_is_withheld(self) -> None:
        url = "https://msh.meity.gov.in/apply/samridh"
        child = {
            "child_id": "child_genesis",
            "bundle_id": "bundle_genesis",
            "canonical_name": "GENESIS",
            "entity_type": "APPLICATION_CALL",
            "temporal_validation": "CURRENT_STATUS_EVIDENCE_COMPLETE",
        }
        fetch = result(
            url,
            title="SAMRIDH Application Form",
            text="Apply now for SAMRIDH accelerator.",
        )
        inspected = inspect_link(
            child,
            "application_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=1,
        )
        self.assertEqual(inspected["page_role"], ROLE_APPLICATION)
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_WITHHELD,
        )
        self.assertEqual(
            inspected["withheld_reason"],
            "APPLICATION_ENTITY_MATCH_INSUFFICIENT",
        )

    def test_verified_current_application_route_can_pass(self) -> None:
        url = "https://msh.meity.gov.in/apply/genesis"
        child = {
            "child_id": "child_genesis",
            "bundle_id": "bundle_genesis",
            "canonical_name": "GENESIS",
            "entity_type": "APPLICATION_CALL",
            "temporal_validation": "CURRENT_STATUS_EVIDENCE_COMPLETE",
        }
        fetch = result(
            url,
            title="GENESIS Application Form",
            text="Apply now. Submit your application for GENESIS.",
        )
        inspected = inspect_link(
            child,
            "application_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=1,
        )
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_VERIFIED,
        )
        self.assertTrue(inspected["verified_application_link"])

    def test_official_information_page_can_pass(self) -> None:
        url = "https://msh.meity.gov.in/schemes/genesis"
        child = {
            "child_id": "child_genesis",
            "bundle_id": "bundle_genesis",
            "canonical_name": "GENESIS",
            "entity_type": "PERMANENT_PROGRAMME",
            "temporal_validation": "NOT_APPLICABLE",
        }
        fetch = result(
            url,
            title="GENESIS | MeitY Startup Hub",
            text="GENESIS is a startup support programme.",
        )
        inspected = inspect_link(
            child,
            "official_page_url",
            url,
            FakeFetcher({url: fetch}),
            self.config,
            global_current_complete_count=0,
        )
        self.assertEqual(inspected["page_role"], ROLE_SCHEME)
        self.assertEqual(
            inspected["link_integrity_status"],
            STATUS_VERIFIED,
        )
        self.assertTrue(inspected["verified_information_link"])

    def test_end_to_end_withholds_bad_route_and_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = self._fixture_project(Path(temporary))
            database = project / "database/ssip_staging_v1.db"
            before = hashlib.sha256(database.read_bytes()).hexdigest()

            about_url = "https://msh.meity.gov.in/about/applyforthelogo"
            info_url = "https://msh.meity.gov.in/schemes/genesis"
            historical_url = "https://msh.meity.gov.in/results/genesis-2023"
            fetcher = FakeFetcher(
                {
                    about_url: result(
                        about_url,
                        title="Apply for the Logo",
                        text="About us. Apply for the logo.",
                    ),
                    info_url: result(
                        info_url,
                        title="GENESIS",
                        text="GENESIS startup support programme.",
                    ),
                    historical_url: result(
                        historical_url,
                        title="GENESIS 2023 Results",
                        text="Selected startups and winners.",
                    ),
                }
            )
            gate = URLIntegrityGate(
                IntegrityPaths.defaults(project),
                load_config(
                    project
                    / "config/meity_url_integrity_v3_4_3_8_0_4.json"
                ),
                fetcher=fetcher,
            )
            summary = gate.run()
            after = hashlib.sha256(database.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertEqual(summary["verified_application_routes"], 0)
            self.assertGreaterEqual(summary["withheld_application_routes"], 1)
            self.assertEqual(
                summary["historical_application_links_exposed"],
                0,
            )
            self.assertEqual(
                summary["about_page_application_links_exposed"],
                0,
            )
            self.assertEqual(
                summary["cross_entity_link_contamination_count"],
                0,
            )
            self.assertTrue(summary["global_application_routes_withheld"])
            self.assertFalse(summary["database_write_performed"])
            self.assertFalse(summary["publication_performed"])

            children = self._read_csv(
                project
                / "data/departments/meity/v3_4_3_8_0_4/"
                "meity_link_safe_decision_children_v3_4_3_8_0_4.csv"
            )
            genesis = next(
                row
                for row in children
                if row["child_id"] == "child_genesis"
            )
            self.assertEqual(genesis["verified_application_url"], "")
            self.assertEqual(genesis["application_url"], "")
            self.assertEqual(
                genesis["application_route_withheld_reason"],
                "GLOBAL_CURRENT_EVIDENCE_INCOMPLETE",
            )
            self.assertEqual(
                genesis["verified_information_url"],
                info_url,
            )

    def _fixture_project(self, project: Path) -> Path:
        source = project / "data/departments/meity/v3_4_3_8_0_3"
        ledger = project / "data/departments/meity/v3_4_3_8_0_2"
        source.mkdir(parents=True)
        ledger.mkdir(parents=True)
        (project / "config").mkdir()
        (project / "database").mkdir()

        (
            project / "config/meity_url_integrity_v3_4_3_8_0_4.json"
        ).write_text(
            self.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        database = project / "database/ssip_staging_v1.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('unchanged')")
        connection.commit()
        connection.close()

        bundle_fields = [
            "bundle_id",
            "bundle_signature",
            "lane",
            "priority",
            "bundle_title",
            "original_recommended_action",
            "recommended_action",
            "rationale",
            "child_record_count",
            "source_evidence_weight",
            "families",
            "entity_types",
            "temporal_states",
            "parent_link_states",
            "requires_child_selection",
            "requires_admin_note",
            "allowed_decisions",
            "reversible",
            "publication_eligible",
            "apply_action_allowed",
            "database_action",
            "publication_action",
        ]
        bundles = [
            {
                "bundle_id": "bundle_genesis",
                "bundle_signature": "sig_genesis",
                "lane": "BATCH_CONFIRMATION",
                "priority": "HIGH",
                "bundle_title": "Historical evidence — GENESIS",
                "original_recommended_action": "CONFIRM_HISTORICAL_GROUP",
                "recommended_action": "CONFIRM_HISTORICAL_CLASSIFICATION",
                "rationale": "Confirm historical classification.",
                "child_record_count": "1",
                "source_evidence_weight": "2",
                "families": "GENESIS",
                "entity_types": "RESULT_ANNOUNCEMENT",
                "temporal_states": "CURRENT_STATUS_NOT_PROVEN",
                "parent_link_states": "UNRESOLVED",
                "requires_child_selection": "False",
                "requires_admin_note": "False",
                "allowed_decisions": (
                    "PENDING;CONFIRM_HISTORICAL;"
                    "NEEDS_MORE_EVIDENCE;DEFER;REJECT_CLASSIFICATION"
                ),
                "reversible": "True",
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "database_action": "NONE",
                "publication_action": "NONE",
            },
            {
                "bundle_id": "bundle_old",
                "bundle_signature": "sig_old",
                "lane": "BATCH_CONFIRMATION",
                "priority": "MEDIUM",
                "bundle_title": "Historical/status review — Old Cohort 2023",
                "original_recommended_action": "REVIEW_CURRENT_CALL",
                "recommended_action": "CONFIRM_HISTORICAL_CLASSIFICATION",
                "rationale": "Historical title.",
                "child_record_count": "1",
                "source_evidence_weight": "1",
                "families": "",
                "entity_types": "ACCELERATOR_COHORT",
                "temporal_states": "HISTORICAL_BY_TITLE_OR_DEADLINE",
                "parent_link_states": "UNRESOLVED",
                "requires_child_selection": "False",
                "requires_admin_note": "False",
                "allowed_decisions": (
                    "PENDING;CONFIRM_HISTORICAL;"
                    "NEEDS_MORE_EVIDENCE;DEFER;REJECT_CLASSIFICATION"
                ),
                "reversible": "True",
                "publication_eligible": "False",
                "apply_action_allowed": "False",
                "database_action": "NONE",
                "publication_action": "NONE",
            },
        ]
        self._write_csv(
            source
            / "meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv",
            bundles,
            bundle_fields,
        )

        child_fields = [
            "bundle_id",
            "bundle_lane",
            "bundle_action",
            "bundle_title",
            "bundle_child_order",
            "child_id",
            "canonical_name",
            "original_canonical_name",
            "entity_type",
            "source_entity_type",
            "application_status",
            "safe_application_status",
            "temporal_validation",
            "opening_date",
            "closing_date",
            "official_page_url",
            "application_url",
            "repaired_parent_scheme_name",
            "parent_link_resolution",
            "evidence_excerpt",
            "status_evidence",
            "source_urls",
            "publication_eligible",
            "apply_action_allowed",
        ]
        children = [
            {
                "bundle_id": "bundle_genesis",
                "bundle_lane": "BATCH_CONFIRMATION",
                "bundle_action": "CONFIRM_HISTORICAL_GROUP",
                "bundle_title": "Historical evidence — GENESIS",
                "bundle_child_order": "1",
                "child_id": "child_genesis",
                "canonical_name": "GENESIS",
                "entity_type": "PERMANENT_PROGRAMME",
                "source_entity_type": "PERMANENT_PROGRAMME",
                "application_status": "VERIFICATION_REQUIRED",
                "safe_application_status": "VERIFICATION_REQUIRED",
                "temporal_validation": "CURRENT_STATUS_NOT_PROVEN",
                "official_page_url": (
                    "https://msh.meity.gov.in/schemes/genesis"
                ),
                "application_url": (
                    "https://msh.meity.gov.in/about/applyforthelogo"
                ),
                "repaired_parent_scheme_name": "",
                "parent_link_resolution": "NOT_APPLICABLE",
                "evidence_excerpt": "GENESIS startup support programme.",
                "status_evidence": "No current route proven.",
                "source_urls": (
                    "https://msh.meity.gov.in/schemes/genesis"
                ),
                "publication_eligible": "False",
                "apply_action_allowed": "False",
            },
            {
                "bundle_id": "bundle_old",
                "bundle_lane": "BATCH_CONFIRMATION",
                "bundle_action": "REVIEW_CURRENT_CALL",
                "bundle_title": "Historical/status review — Old Cohort 2023",
                "bundle_child_order": "1",
                "child_id": "child_old",
                "canonical_name": "Old Cohort 2023",
                "entity_type": "ACCELERATOR_COHORT",
                "source_entity_type": "ACCELERATOR_COHORT",
                "application_status": "HISTORICAL_CLOSED",
                "safe_application_status": "HISTORICAL_CLOSED",
                "temporal_validation": "HISTORICAL_BY_TITLE_OR_DEADLINE",
                "official_page_url": (
                    "https://msh.meity.gov.in/results/genesis-2023"
                ),
                "application_url": "",
                "repaired_parent_scheme_name": "",
                "parent_link_resolution": "UNRESOLVED",
                "evidence_excerpt": "Selected startups and winners.",
                "status_evidence": "Historical result.",
                "source_urls": (
                    "https://msh.meity.gov.in/results/genesis-2023"
                ),
                "publication_eligible": "False",
                "apply_action_allowed": "False",
            },
        ]
        self._write_csv(
            source / "meity_safe_decision_children_v3_4_3_8_0_3.csv",
            children,
            child_fields,
        )
        (
            source
            / "meity_temporal_parent_safety_manifest_v3_4_3_8_0_3.json"
        ).write_text(
            json.dumps(
                {
                    "version": "3.4.3.8.0.3",
                    "signature": "source-safety-signature",
                    "session_state_signature": "source-session-signature",
                    "current_status_evidence_complete_count": 0,
                    "database_write_performed": False,
                    "publication_performed": False,
                }
            ),
            encoding="utf-8",
        )

        ledger_fields = [
            "child_id",
            "source_candidate_id",
            "source_evidence_id",
        ]
        self._write_csv(
            ledger
            / "meity_decision_bundle_children_v3_4_3_8_0_2.csv",
            [
                {
                    "child_id": "child_genesis",
                    "source_candidate_id": "candidate_genesis",
                    "source_evidence_id": "evidence_genesis",
                },
                {
                    "child_id": "child_old",
                    "source_candidate_id": "candidate_old",
                    "source_evidence_id": "evidence_old",
                },
            ],
            ledger_fields,
        )
        return project

    @staticmethod
    def _write_csv(
        path: Path,
        rows: list[dict[str, str]],
        fields: list[str],
    ) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
