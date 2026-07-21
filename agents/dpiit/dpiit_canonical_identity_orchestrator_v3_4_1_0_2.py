from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

from agents.shared.validation_core import sha256_file, sha256_tree, stable_id, write_csv, write_json
from agents.shared.dashboard_preservation import dpiit_preview_preserves_home

from .dpiit_canonical_identity_resolver_v3_4_1_0_2 import (
    ALIAS_FIELDS, AUDIT_FIELDS, ENTITY_FIELDS, EVIDENCE_FIELDS, REJECTION_FIELDS,
    RELATIONSHIP_FIELDS, REVIEW_FIELDS, resolve,
)
from .dpiit_canonical_identity_rules_v3_4_1_0_2 import AS_OF, DEPARTMENT, VERSION


INPUT_NAME = "dpiit_discovery_candidates_v3_4_1_0_1.csv"
OUTPUT_NAMES = {
    "entities": "dpiit_canonical_entity_registry_v3_4_1_0_2.csv",
    "schemes": "dpiit_canonical_scheme_registry_v3_4_1_0_2.csv",
    "programmes": "dpiit_canonical_programme_registry_v3_4_1_0_2.csv",
    "platforms_services": "dpiit_canonical_platform_service_registry_v3_4_1_0_2.csv",
    "aliases": "dpiit_canonical_alias_registry_v3_4_1_0_2.csv",
    "relationships": "dpiit_canonical_relationship_registry_v3_4_1_0_2.csv",
    "evidence": "dpiit_canonical_evidence_map_v3_4_1_0_2.csv",
    "reviews": "dpiit_manual_identity_review_queue_v3_4_1_0_2.csv",
    "audits": "dpiit_identity_lock_audit_v3_4_1_0_2.csv",
    "rejections": "dpiit_identity_resolution_rejections_v3_4_1_0_2.csv",
    "summary": "dpiit_identity_resolution_summary_v3_4_1_0_2.json",
    "validation": "dpiit_identity_resolution_validation_v3_4_1_0_2.json",
    "manifest": "dpiit_identity_resolution_manifest_v3_4_1_0_2.json",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def preservation(project_root: Path) -> dict[str, Any]:
    baseline = json.loads((project_root / "data/audit/dpiit_v3_4_1_0_2_prechange_sha256.json").read_text(encoding="utf-8"))
    trees = {
        "data/departments/dpiit/v3_4_1_0_1": sha256_tree(project_root / "data/departments/dpiit/v3_4_1_0_1"),
        "data/departments/dst": sha256_tree(project_root / "data/departments/dst"),
        "data/publication/current": sha256_tree(project_root / "data/publication/current"),
    }
    files = {path: sha256_file(project_root / path) for path in baseline["frozen_files"]}
    return {
        "trees": {path: {"before": baseline["trees"][path], "after": digest, "unchanged": digest == baseline["trees"][path]} for path, digest in trees.items()},
        "files": {path: {"before": baseline["frozen_files"][path], "after": digest, "unchanged": digest == baseline["frozen_files"][path]} for path, digest in files.items()},
        "dpiit_preview_preserves_home": dpiit_preview_preserves_home(project_root, baseline),
    }


def validate(candidates: list[dict[str, str]], result: dict[str, list[dict[str, str]]], preserved: dict[str, Any]) -> dict[str, Any]:
    entities = result["entities"]
    master_ids = [row["master_id"] for row in entities]
    names = [(row["entity_type"], row["canonical_name"].casefold()) for row in entities]
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    temporary_roles = {"APPLICATION_CALL", "APPLICATION_PORTAL", "AWARD_EDITION", "CHALLENGE_INSTANCE"}
    alias_keys = [(row["master_id"], row["alias_text"].casefold()) for row in result["aliases"]]
    relationship_children = {row["child_candidate_id"] for row in result["relationships"]}
    expected_children = {row["candidate_id"] for row in candidates if row["parent_candidate_id"] and row["page_role"] in {"APPLICATION_CALL", "APPLICATION_PORTAL", "AWARD_EDITION", "CHALLENGE_INSTANCE", "GUIDELINE", "FAQ", "RESULTS_PAGE"}}
    checks = {
        "input_candidate_ids_unique": len(candidates) == len({row["candidate_id"] for row in candidates}),
        "canonical_master_ids_unique": len(master_ids) == len(set(master_ids)),
        "canonical_names_unique_within_type": len(names) == len(set(names)),
        "canonical_entity_schema_complete": all(list(row) == ENTITY_FIELDS for row in entities),
        "aliases_unique_within_master": len(alias_keys) == len(set(alias_keys)),
        "temporary_instances_not_canonical_entities": all(candidate_by_id[row["source_candidate_id"]]["page_role"] not in temporary_roles for row in entities),
        "call_award_challenge_children_preserved": expected_children == relationship_children,
        "national_startup_awards_edition_not_master": all("5.0" not in row["canonical_name"] for row in entities),
        "bharat_challenge_instance_not_master": all("Gaming for Good" not in row["canonical_name"] for row in entities),
        "sisfs_call_not_master": all("last date" not in row["canonical_name"].casefold() for row in entities),
        "fund_of_funds_2_identity_separate": any(row["canonical_name"] == "Startup India Fund of Funds 2.0" for row in entities),
        "fund_of_funds_lineage_held_for_review": any(row["review_type"] == "VERSION_AND_PREDECESSOR_LINEAGE" for row in result["reviews"]),
        "mixed_recognition_tax_service_held_for_review": any(row["review_type"] == "MIXED_SERVICE_IDENTITY" for row in result["reviews"]),
        "historical_dipp_not_current_department": all(row["owning_department"] == DEPARTMENT for row in entities),
        "all_outputs_not_published": all(row["publication_status"] == "NOT_PUBLISHED" for row in entities + result["reviews"]),
        "rejected_candidates_retained": {row["candidate_id"] for row in result["rejections"]} == {row["candidate_id"] for row in candidates if row["rejection_reason"]},
        "dpiit_v34101_unchanged": preserved["trees"]["data/departments/dpiit/v3_4_1_0_1"]["unchanged"],
        "dst_outputs_unchanged": preserved["trees"]["data/departments/dst"]["unchanged"],
        "publication_current_unchanged": preserved["trees"]["data/publication/current"]["unchanged"],
        "public_dashboard_unchanged": (
            all(item["unchanged"] for path, item in preserved["files"].items() if path.endswith((".py", ".css")))
            or preserved["dpiit_preview_preserves_home"]
        ),
    }
    return {
        "version": VERSION,
        "validation_passed": all(checks.values()),
        "checks": checks,
        "counts": {key: len(value) for key, value in result.items()},
        "preservation": preserved,
    }


def run(input_dir: Path, output_dir: Path, *, project_root: Path) -> dict[str, Any]:
    candidates = read_csv(input_dir / INPUT_NAME)
    result = resolve(candidates)
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "entities": ENTITY_FIELDS, "schemes": ENTITY_FIELDS, "programmes": ENTITY_FIELDS,
        "platforms_services": ENTITY_FIELDS, "aliases": ALIAS_FIELDS,
        "relationships": RELATIONSHIP_FIELDS, "evidence": EVIDENCE_FIELDS,
        "reviews": REVIEW_FIELDS, "audits": AUDIT_FIELDS, "rejections": REJECTION_FIELDS,
    }
    for key, fieldnames in fields.items():
        write_csv(output_dir / OUTPUT_NAMES[key], result[key], fieldnames)

    preserved = preservation(project_root)
    validation = validate(candidates, result, preserved)
    summary = {
        "version": VERSION, "as_of": AS_OF,
        "canonical_entities": len(result["entities"]),
        "canonical_entities_by_type": dict(sorted(Counter(row["entity_type"] for row in result["entities"]).items())),
        "aliases": len(result["aliases"]), "relationships": len(result["relationships"]),
        "relationships_by_type": dict(sorted(Counter(row["relationship_type"] for row in result["relationships"]).items())),
        "evidence_mappings": len(result["evidence"]), "manual_review": len(result["reviews"]),
        "manual_review_by_type": dict(sorted(Counter(row["review_type"] for row in result["reviews"]).items())),
        "rejections": len(result["rejections"]),
        "canonical_names": [row["canonical_name"] for row in result["entities"]],
        "publication_performed": False, "database_modified": False,
        "validation_passed": validation["validation_passed"],
    }
    write_json(output_dir / OUTPUT_NAMES["summary"], summary)
    write_json(output_dir / OUTPUT_NAMES["validation"], validation)
    governed = [OUTPUT_NAMES[key] for key in fields] + [OUTPUT_NAMES["summary"], OUTPUT_NAMES["validation"]]
    manifest = {
        "version": VERSION,
        "run_id": stable_id("dpiit_identity_run", VERSION, AS_OF),
        "input": str((input_dir / INPUT_NAME).relative_to(project_root)).replace("\\", "/"),
        "input_sha256": sha256_file(input_dir / INPUT_NAME),
        "outputs": {name: sha256_file(output_dir / name) for name in governed},
        "deterministic": True, "validation_passed": validation["validation_passed"],
        "publication_performed": False, "dashboard_modified": False,
    }
    write_json(output_dir / OUTPUT_NAMES["manifest"], manifest)
    return {"result": result, "summary": summary, "validation": validation, "manifest": manifest}


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="DPIIT canonical scheme identity resolution v3.4.1.0.2")
    parser.add_argument("--input-dir", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_1")
    parser.add_argument("--output-dir", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_2")
    args = parser.parse_args()
    payload = run(args.input_dir, args.output_dir, project_root=project_root)
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    return 0 if payload["validation"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
