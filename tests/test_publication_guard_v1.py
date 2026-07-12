import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agents.governed_v1.publication_guard_agent import PublicationGuardAgent
import scripts.publish_approved_agent_run_v1 as publication


TAXONOMY = {"Cross-sector Innovation & Entrepreneurship"}


def valid_public_row(master_id: str = "scheme-1") -> dict[str, str]:
    return {
        "scheme_master_id": master_id,
        "master_id": master_id,
        "canonical_name": "Startup Support Scheme",
        "official_master_url": "https://startupindia.gov.in/scheme",
        "startup_beneficiary_evidence": "startup",
        "startup_access_evidence": "grant; apply",
        "startup_relevance_classification": "DIRECT_STARTUP_SCHEME",
        "record_role": "SCHEME_MASTER",
        "sector": "Cross-sector Innovation & Entrepreneurship",
        "primary_sector": "Cross-sector Innovation & Entrepreneurship",
        "manual_review_required": "false",
        "sector_review_required": "false",
    }


class PublicationGuardTests(unittest.TestCase):
    def test_publication_without_approval_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "config/governed_agents_v1.json").write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(PermissionError):
                publication.publish(root, "run-1", None)

    def test_publication_that_reduces_count_fails(self) -> None:
        result = PublicationGuardAgent().validate(
            [valid_public_row("scheme-1")], [], {"scheme-1", "scheme-2"}, True, True, TAXONOMY,
        )
        self.assertFalse(result.passed)
        self.assertFalse(result.checks["all_deletions_require_manual_approval"])

    def test_publication_with_invalid_sector_fails(self) -> None:
        row = valid_public_row()
        row["sector"] = row["primary_sector"] = "Invented Sector"
        result = PublicationGuardAgent().validate([row], [], {"scheme-1"}, True, True, TAXONOMY)
        self.assertFalse(result.checks["all_sector_values_in_taxonomy"])

    def test_sector_and_primary_sector_must_match(self) -> None:
        row = valid_public_row()
        row["sector"] = "Different Sector"
        result = PublicationGuardAgent().validate([row], [], {"scheme-1"}, True, True, TAXONOMY)
        self.assertFalse(result.checks["sector_and_primary_sector_match"])

    def test_post_publication_failure_restores_previous_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "data/active").mkdir(parents=True)
            (root / "data/agent_runs/run-1").mkdir(parents=True)
            (root / "data/publication/current").mkdir(parents=True)
            (root / "backups/governed_publication").mkdir(parents=True)
            config = {
                "active_catalogue": "data/active/catalogue.csv",
                "run_root": "data/agent_runs",
                "publication_root": "data/publication",
                "approved_manifest": "data/agent_state/current_approved_manifest.json",
                "publication": {"maximum_change_percent_without_override": 10},
            }
            (root / "config/governed_agents_v1.json").write_text(json.dumps(config), encoding="utf-8")
            fields = list(valid_public_row())
            for path in (root / "data/active/catalogue.csv", root / "data/agent_runs/run-1/publication_candidate.csv"):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow(valid_public_row())
            for name in ("call_instances.csv", "ecosystem_entities.csv"):
                (root / f"data/agent_runs/run-1/{name}").write_text("id\n", encoding="utf-8")
            previous = "old-current-catalogue\n"
            (root / "data/publication/current/public_catalogue.csv").write_text(previous, encoding="utf-8")
            approval = root / "approval.csv"
            approval.write_text("run_id,proposed_action,approved_by,approval_date\nrun-1,APPROVE_PUBLICATION,Reviewer,2026-07-10\n", encoding="utf-8")
            with patch.object(publication, "validate_run", return_value={"passed": True}), patch.object(publication, "dashboard_public_ids", return_value={"scheme-1"}), patch.object(publication, "verify", return_value={"valid": False}):
                with self.assertRaises(RuntimeError):
                    publication.publish(root, "run-1", approval)
            self.assertEqual((root / "data/publication/current/public_catalogue.csv").read_text(encoding="utf-8"), previous)
            self.assertFalse((root / "data/publication/current/publication_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
