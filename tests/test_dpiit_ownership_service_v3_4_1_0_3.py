from __future__ import annotations

import csv
from pathlib import Path

from agents.dpiit.dpiit_ownership_service_orchestrator_v3_4_1_0_3 import OUTPUT_NAMES, run
from agents.dpiit.dpiit_ownership_service_resolver_v3_4_1_0_3 import (
    OWNERSHIP_FIELDS, RESOLUTION_FIELDS, SERVICE_DECISION_FIELDS, resolve,
)
from agents.dpiit.dpiit_ownership_service_rules_v3_4_1_0_3 import DEPARTMENT


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "data/departments/dpiit/v3_4_1_0_2"
OUTPUT_DIR = PROJECT_ROOT / "data/departments/dpiit/v3_4_1_0_3"
REVIEW_PATH = V2_DIR / "dpiit_manual_identity_review_queue_v3_4_1_0_2.csv"
ENTITY_PATH = V2_DIR / "dpiit_canonical_entity_registry_v3_4_1_0_2.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def resolved():
    return resolve(read_csv(REVIEW_PATH), read_csv(ENTITY_PATH))


def test_all_six_review_items_are_adjudicated() -> None:
    result = resolved()
    assert len(result["resolved"]) == 6
    assert result["unresolved"] == []
    assert {row["review_id"] for row in result["resolved"]} == {row["review_id"] for row in read_csv(REVIEW_PATH)}


def test_gazette_issuer_is_verified_from_dpiit_notification() -> None:
    row = next(item for item in resolved()["ownership"] if item["candidate_id"] == "dpiit_candidate_ec1a28c95caa67afc540")
    assert row["ownership_status"] == "VERIFIED_DPIIT_ISSUER"
    assert row["owning_department"] == DEPARTMENT
    assert row["final_page_role"] == "NOTIFICATION"
    assert row["entity_boundary"] == "SUPPORTING_LEGAL_NOTIFICATION"


def test_directories_do_not_assign_child_scheme_ownership() -> None:
    directories = [row for row in resolved()["ownership"] if "DIRECTORY" in row["entity_boundary"]]
    assert len(directories) == 2
    assert all(row["ownership_status"] == "VERIFIED_PLATFORM_CONTEXT" for row in directories)
    assert all(row["final_page_role"] == "SOURCE_DIRECTORY" for row in directories)
    assert all("child" in row["evidence_basis"].casefold() or "listed" in row["evidence_basis"].casefold() for row in directories)


def test_generic_archive_gets_no_entity_owner() -> None:
    row = next(item for item in resolved()["ownership"] if item["candidate_name"] == "Archived Page")
    assert row["decision"] == "RESOLVED_AS_GENERIC_PLATFORM_UTILITY"
    assert row["owning_department"] == ""
    assert row["ownership_status"] == "NO_ENTITY_OWNERSHIP_ASSIGNED"


def test_recognition_and_80iac_are_separate_services() -> None:
    result = resolved()
    assert len(result["services"]) == 2
    recognition = next(row for row in result["services"] if row["canonical_name"] == "DPIIT Startup Recognition")
    tax = next(row for row in result["services"] if row["canonical_name"].startswith("Section 80-IAC"))
    assert recognition["master_id"] != tax["master_id"]
    assert recognition["entity_type"] == tax["entity_type"] == "GOVERNMENT_SERVICE"
    assert tax["owning_department"] == DEPARTMENT


def test_recognition_master_id_is_preserved() -> None:
    recognition = next(row for row in resolved()["services"] if row["canonical_name"] == "DPIIT Startup Recognition")
    assert recognition["master_id"] == "dpiit_master_6c1afb477ef37cd6acaa"


def test_80iac_service_requires_recognition() -> None:
    result = resolved()
    relationship = result["service_relationships"][0]
    tax = next(row for row in result["services"] if row["canonical_name"].startswith("Section 80-IAC"))
    recognition = next(row for row in result["services"] if row["canonical_name"] == "DPIIT Startup Recognition")
    assert relationship["source_master_id"] == tax["master_id"]
    assert relationship["target_master_id"] == recognition["master_id"]
    assert relationship["relationship_type"] == "REQUIRES_DPIIT_RECOGNITION"


def test_fund_of_funds_lineage_does_not_merge_versions() -> None:
    lineage = resolved()["lineage"][0]
    assert lineage["decision"] == "SEPARATE_VERSION_IDENTITY_CONFIRMED"
    assert lineage["relationship_type"] == "VERSION_LINEAGE_FROM"
    assert lineage["merge_allowed"] == "0"
    assert lineage["predecessor_master_id"] == ""


def test_evidence_registry_contains_only_official_sources() -> None:
    allowed = ("dpiit.gov.in", "startupindia.gov.in", "nsws.gov.in")
    assert len(resolved()["evidence"]) == 10
    assert all(any(domain in row["official_url"] for domain in allowed) for row in resolved()["evidence"])


def test_outputs_are_not_published_and_preservation_passes() -> None:
    payload = run(REVIEW_PATH, ENTITY_PATH, OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert payload["validation"]["validation_passed"] is True
    assert payload["summary"]["publication_performed"] is False
    assert payload["summary"]["database_modified"] is False
    for key in ("dpiit_v34101_unchanged", "dpiit_v34102_unchanged", "dst_outputs_unchanged", "publication_current_unchanged", "public_dashboard_unchanged"):
        assert payload["validation"]["checks"][key]


def test_output_schemas_are_exact() -> None:
    run(REVIEW_PATH, ENTITY_PATH, OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["ownership"])[0]) == OWNERSHIP_FIELDS
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["service_decisions"])[0]) == SERVICE_DECISION_FIELDS
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["resolved"])[0]) == RESOLUTION_FIELDS


def test_deterministic_rerun_is_byte_identical() -> None:
    run(REVIEW_PATH, ENTITY_PATH, OUTPUT_DIR, project_root=PROJECT_ROOT)
    first = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    run(REVIEW_PATH, ENTITY_PATH, OUTPUT_DIR, project_root=PROJECT_ROOT)
    second = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    assert first == second
