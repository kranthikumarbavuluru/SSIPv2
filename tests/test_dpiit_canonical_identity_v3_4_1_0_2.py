from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path

from agents.dpiit.dpiit_canonical_identity_orchestrator_v3_4_1_0_2 import (
    OUTPUT_NAMES, run,
)
from agents.dpiit.dpiit_canonical_identity_resolver_v3_4_1_0_2 import (
    ENTITY_FIELDS, RELATIONSHIP_FIELDS, REVIEW_FIELDS, resolve,
)
from agents.dpiit.dpiit_identity_rules_v3_4_1_0_1 import (
    CANONICAL_DEPARTMENT, canonical_department,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data/departments/dpiit/v3_4_1_0_1"
OUTPUT_DIR = PROJECT_ROOT / "data/departments/dpiit/v3_4_1_0_2"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def candidates() -> list[dict[str, str]]:
    return read_csv(INPUT_DIR / "dpiit_discovery_candidates_v3_4_1_0_1.csv")


def test_canonical_entity_counts_and_types() -> None:
    result = resolve(candidates())
    assert len(result["entities"]) == 11
    assert len(result["schemes"]) == 4
    assert len(result["programmes"]) == 3
    assert len(result["platforms_services"]) == 4


def test_call_award_and_challenge_instances_never_become_masters() -> None:
    result = resolve(candidates())
    names = {row["canonical_name"] for row in result["entities"]}
    assert not any("last date" in name.casefold() for name in names)
    assert "National Startup Awards 5.0" not in names
    assert not any("Gaming for Good" in name for name in names)
    roles = {row["child_role"] for row in result["relationships"]}
    assert {"APPLICATION_CALL", "AWARD_EDITION", "CHALLENGE_INSTANCE"} <= roles


def test_parent_child_relationships_are_explicit_and_complete() -> None:
    result = resolve(candidates())
    assert len(result["relationships"]) == 7
    assert all(row["parent_master_id"] for row in result["relationships"])
    assert all(row["status"] == "LOCKED_EVIDENCE_RELATIONSHIP" for row in result["relationships"])
    nsa = next(row for row in result["entities"] if row["canonical_name"] == "National Startup Awards")
    edition = next(row for row in result["relationships"] if row["child_name"] == "National Startup Awards 5.0")
    assert edition["parent_master_id"] == nsa["master_id"]


def test_aliases_do_not_create_second_entities() -> None:
    result = resolve(candidates())
    sisfs = next(row for row in result["entities"] if row["canonical_name"] == "Startup India Seed Fund Scheme")
    aliases = {row["alias_text"] for row in result["aliases"] if row["master_id"] == sisfs["master_id"]}
    assert {"Startup India Seed Fund", "SISFS"} <= aliases
    assert sum(row["master_id"] == sisfs["master_id"] for row in result["entities"]) == 1


def test_master_id_is_stable_when_candidate_title_changes() -> None:
    original = candidates()
    renamed = deepcopy(original)
    target = next(row for row in renamed if row["normalized_url"] == "https://seedfund.startupindia.gov.in/")
    target["candidate_name"] = "Curated display title"
    target["page_title"] = "Curated display title"
    original_id = next(row["master_id"] for row in resolve(original)["entities"] if row["canonical_name"] == "Startup India Seed Fund Scheme")
    renamed_id = next(row["master_id"] for row in resolve(renamed)["entities"] if row["canonical_name"] == "Startup India Seed Fund Scheme")
    assert original_id == renamed_id


def test_fund_of_funds_2_is_separate_and_lineage_is_reviewed() -> None:
    result = resolve(candidates())
    fof = next(row for row in result["entities"] if row["canonical_name"] == "Startup India Fund of Funds 2.0")
    assert fof["entity_type"] == "SCHEME"
    review = next(row for row in result["reviews"] if row["review_type"] == "VERSION_AND_PREDECESSOR_LINEAGE")
    assert review["proposed_master_id"] == fof["master_id"]


def test_mixed_recognition_tax_page_is_not_auto_merged() -> None:
    result = resolve(candidates())
    service = next(row for row in result["entities"] if row["canonical_name"] == "DPIIT Startup Recognition")
    review = next(row for row in result["reviews"] if row["review_type"] == "MIXED_SERVICE_IDENTITY")
    assert review["proposed_master_id"] == service["master_id"]
    assert not any(row["alias_text"] == "DPIIT Startup Recognition and Tax Exemption" for row in result["aliases"])


def test_unresolved_ownership_is_never_canonicalized() -> None:
    result = resolve(candidates())
    entity_candidates = {row["source_candidate_id"] for row in result["entities"]}
    unresolved = {row["candidate_id"] for row in candidates() if row["ownership_status"] == "NEEDS_VERIFICATION"}
    assert not entity_candidates & unresolved
    assert unresolved - {row["candidate_id"] for row in result["rejections"]} <= {row["candidate_id"] for row in result["reviews"]}


def test_historical_dipp_alias_is_not_a_current_department() -> None:
    assert canonical_department("DIPP") == (CANONICAL_DEPARTMENT, "HISTORICAL_ALIAS")
    result = resolve(candidates())
    assert {row["owning_department"] for row in result["entities"]} == {CANONICAL_DEPARTMENT}


def test_outputs_are_not_published_and_preservation_passes() -> None:
    payload = run(INPUT_DIR, OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert payload["validation"]["validation_passed"] is True
    assert payload["summary"]["publication_performed"] is False
    assert payload["summary"]["database_modified"] is False
    assert all(row["publication_status"] == "NOT_PUBLISHED" for row in payload["result"]["entities"])
    assert payload["validation"]["checks"]["dpiit_v34101_unchanged"]
    assert payload["validation"]["checks"]["dst_outputs_unchanged"]
    assert payload["validation"]["checks"]["publication_current_unchanged"]
    assert payload["validation"]["checks"]["public_dashboard_unchanged"]


def test_output_schemas_are_exact() -> None:
    run(INPUT_DIR, OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["entities"])[0]) == ENTITY_FIELDS
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["relationships"])[0]) == RELATIONSHIP_FIELDS
    assert list(read_csv(OUTPUT_DIR / OUTPUT_NAMES["reviews"])[0]) == REVIEW_FIELDS


def test_deterministic_rerun_is_byte_identical() -> None:
    run(INPUT_DIR, OUTPUT_DIR, project_root=PROJECT_ROOT)
    first = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    run(INPUT_DIR, OUTPUT_DIR, project_root=PROJECT_ROOT)
    second = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    assert first == second
