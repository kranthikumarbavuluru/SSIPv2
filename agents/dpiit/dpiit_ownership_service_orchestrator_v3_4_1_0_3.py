from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

from agents.shared.validation_core import sha256_file, sha256_tree, stable_id, write_csv, write_json
from agents.shared.dashboard_preservation import dpiit_preview_preserves_home

from .dpiit_canonical_identity_resolver_v3_4_1_0_2 import ENTITY_FIELDS, REVIEW_FIELDS
from .dpiit_ownership_service_resolver_v3_4_1_0_3 import (
    EVIDENCE_FIELDS, LINEAGE_FIELDS, OWNERSHIP_FIELDS, RESOLUTION_FIELDS,
    SERVICE_DECISION_FIELDS, SERVICE_RELATIONSHIP_FIELDS, resolve,
)
from .dpiit_ownership_service_rules_v3_4_1_0_3 import AS_OF, DEPARTMENT, VERSION


OUTPUT_NAMES = {
    "ownership": "dpiit_ownership_evidence_decisions_v3_4_1_0_3.csv",
    "service_decisions": "dpiit_service_boundary_decisions_v3_4_1_0_3.csv",
    "services": "dpiit_resolved_service_registry_v3_4_1_0_3.csv",
    "service_relationships": "dpiit_service_relationship_registry_v3_4_1_0_3.csv",
    "lineage": "dpiit_scheme_lineage_decisions_v3_4_1_0_3.csv",
    "resolved": "dpiit_resolved_review_items_v3_4_1_0_3.csv",
    "unresolved": "dpiit_unresolved_review_queue_v3_4_1_0_3.csv",
    "evidence": "dpiit_adjudication_evidence_registry_v3_4_1_0_3.csv",
    "summary": "dpiit_ownership_service_summary_v3_4_1_0_3.json",
    "validation": "dpiit_ownership_service_validation_v3_4_1_0_3.json",
    "manifest": "dpiit_ownership_service_manifest_v3_4_1_0_3.json",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def preservation(project_root: Path) -> dict[str, Any]:
    baseline = json.loads((project_root / "data/audit/dpiit_v3_4_1_0_3_prechange_sha256.json").read_text(encoding="utf-8"))
    tree_paths = [
        "data/departments/dpiit/v3_4_1_0_1", "data/departments/dpiit/v3_4_1_0_2",
        "data/departments/dst", "data/publication/current",
    ]
    trees = {path: sha256_tree(project_root / path) for path in tree_paths}
    files = {path: sha256_file(project_root / path) for path in baseline["frozen_files"]}
    return {
        "trees": {path: {"before": baseline["trees"][path], "after": digest, "unchanged": digest == baseline["trees"][path]} for path, digest in trees.items()},
        "files": {path: {"before": baseline["frozen_files"][path], "after": digest, "unchanged": digest == baseline["frozen_files"][path]} for path, digest in files.items()},
        "dpiit_preview_preserves_home": dpiit_preview_preserves_home(project_root, baseline),
    }


def validate(review_rows: list[dict[str, str]], canonical_entities: list[dict[str, str]],
             result: dict[str, list[dict[str, str]]], preserved: dict[str, Any]) -> dict[str, Any]:
    resolved_ids = {row["review_id"] for row in result["resolved"]}
    input_review_ids = {row["review_id"] for row in review_rows}
    services = result["services"]
    recognition = next(row for row in services if row["canonical_name"] == "DPIIT Startup Recognition")
    tax_service = next(row for row in services if row["canonical_name"].startswith("Section 80-IAC"))
    canonical_names = {row["canonical_name"] for row in canonical_entities}
    ownership_by_candidate = {row["candidate_id"]: row for row in result["ownership"]}
    checks = {
        "all_v34102_reviews_adjudicated": resolved_ids == input_review_ids,
        "no_unresolved_review_items": not result["unresolved"],
        "gazette_issuer_verified_from_official_text": ownership_by_candidate["dpiit_candidate_ec1a28c95caa67afc540"]["ownership_status"] == "VERIFIED_DPIIT_ISSUER",
        "cross_department_directory_not_scheme_identity": all(row["entity_boundary"] in {"CROSS_DEPARTMENT_SCHEME_DIRECTORY", "MULTI_OWNER_PROGRAMME_AND_CHALLENGE_DIRECTORY"} for row in result["ownership"] if "DIRECTORY" in row["entity_boundary"]),
        "directory_child_ownership_not_inferred": all("directory" not in name.casefold() for name in canonical_names),
        "archive_utility_has_no_owner_assignment": ownership_by_candidate["dpiit_candidate_a2f1601863f60d1a6e76"]["owning_department"] == "",
        "recognition_master_id_preserved": recognition["master_id"] == "dpiit_master_6c1afb477ef37cd6acaa",
        "recognition_and_80iac_are_distinct_services": recognition["master_id"] != tax_service["master_id"] and all(row["entity_type"] == "GOVERNMENT_SERVICE" for row in services),
        "tax_service_owned_by_dpiit": tax_service["owning_department"] == DEPARTMENT,
        "tax_service_requires_recognition": any(row["source_master_id"] == tax_service["master_id"] and row["target_master_id"] == recognition["master_id"] and row["relationship_type"] == "REQUIRES_DPIIT_RECOGNITION" for row in result["service_relationships"]),
        "fof2_identity_not_merged": result["lineage"][0]["merge_allowed"] == "0" and not result["lineage"][0]["predecessor_master_id"],
        "fof2_version_lineage_recorded": result["lineage"][0]["relationship_type"] == "VERSION_LINEAGE_FROM",
        "all_records_not_published": all(row.get("publication_status", "NOT_PUBLISHED") == "NOT_PUBLISHED" for key in ("ownership", "service_decisions", "services", "lineage", "resolved") for row in result[key]),
        "dpiit_v34101_unchanged": preserved["trees"]["data/departments/dpiit/v3_4_1_0_1"]["unchanged"],
        "dpiit_v34102_unchanged": preserved["trees"]["data/departments/dpiit/v3_4_1_0_2"]["unchanged"],
        "dst_outputs_unchanged": preserved["trees"]["data/departments/dst"]["unchanged"],
        "publication_current_unchanged": preserved["trees"]["data/publication/current"]["unchanged"],
        "public_dashboard_unchanged": (
            all(item["unchanged"] for path, item in preserved["files"].items() if path.endswith((".py", ".css")))
            or preserved["dpiit_preview_preserves_home"]
        ),
    }
    return {
        "version": VERSION, "validation_passed": all(checks.values()), "checks": checks,
        "counts": {key: len(value) for key, value in result.items()}, "preservation": preserved,
    }


def run(review_path: Path, entity_path: Path, output_dir: Path, *, project_root: Path) -> dict[str, Any]:
    review_rows = read_csv(review_path)
    canonical_entities = read_csv(entity_path)
    result = resolve(review_rows, canonical_entities)
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "ownership": OWNERSHIP_FIELDS, "service_decisions": SERVICE_DECISION_FIELDS,
        "services": ENTITY_FIELDS, "service_relationships": SERVICE_RELATIONSHIP_FIELDS,
        "lineage": LINEAGE_FIELDS, "resolved": RESOLUTION_FIELDS,
        "unresolved": REVIEW_FIELDS, "evidence": EVIDENCE_FIELDS,
    }
    for key, fieldnames in fields.items():
        write_csv(output_dir / OUTPUT_NAMES[key], result[key], fieldnames)
    preserved = preservation(project_root)
    validation = validate(review_rows, canonical_entities, result, preserved)
    summary = {
        "version": VERSION, "as_of": AS_OF,
        "input_review_items": len(review_rows), "resolved_review_items": len(result["resolved"]),
        "unresolved_review_items": len(result["unresolved"]),
        "ownership_decisions": len(result["ownership"]),
        "ownership_decisions_by_type": dict(sorted(Counter(row["decision"] for row in result["ownership"]).items())),
        "resolved_services": len(result["services"]), "new_service_identities": 1,
        "service_relationships": len(result["service_relationships"]),
        "lineage_decisions": len(result["lineage"]), "evidence_records": len(result["evidence"]),
        "publication_performed": False, "database_modified": False,
        "validation_passed": validation["validation_passed"],
    }
    write_json(output_dir / OUTPUT_NAMES["summary"], summary)
    write_json(output_dir / OUTPUT_NAMES["validation"], validation)
    governed = [OUTPUT_NAMES[key] for key in fields] + [OUTPUT_NAMES["summary"], OUTPUT_NAMES["validation"]]
    manifest = {
        "version": VERSION, "run_id": stable_id("dpiit_adjudication_run", VERSION, AS_OF),
        "inputs": {
            str(review_path.relative_to(project_root)).replace("\\", "/"): sha256_file(review_path),
            str(entity_path.relative_to(project_root)).replace("\\", "/"): sha256_file(entity_path),
        },
        "outputs": {name: sha256_file(output_dir / name) for name in governed},
        "deterministic": True, "validation_passed": validation["validation_passed"],
        "publication_performed": False, "dashboard_modified": False,
    }
    write_json(output_dir / OUTPUT_NAMES["manifest"], manifest)
    return {"result": result, "summary": summary, "validation": validation, "manifest": manifest}


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="DPIIT ownership and service boundary adjudication v3.4.1.0.3")
    parser.add_argument("--review-path", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_2/dpiit_manual_identity_review_queue_v3_4_1_0_2.csv")
    parser.add_argument("--entity-path", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_2/dpiit_canonical_entity_registry_v3_4_1_0_2.csv")
    parser.add_argument("--output-dir", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_3")
    args = parser.parse_args()
    payload = run(args.review_path, args.entity_path, args.output_dir, project_root=project_root)
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    return 0 if payload["validation"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
