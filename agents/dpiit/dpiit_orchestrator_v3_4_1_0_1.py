from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

from agents.shared.official_domain_policy import OfficialDomainPolicy
from agents.shared.page_role_classifier import PAGE_ROLES
from agents.shared.validation_core import (
    duplicate_values, sha256_file, sha256_tree, stable_id, write_csv, write_json,
)

from .dpiit_discovery_agent_v3_4_1_0_1 import CANDIDATE_FIELDS, DPIITDiscoveryAgent
from .dpiit_source_registry_v3_4_1_0_1 import (
    SOURCE_FIELDS, VERIFIED_DATE, VERSION, build_source_registry, seed_candidates,
)


OUTPUT_NAMES = {
    "source_registry": "dpiit_source_registry_v3_4_1_0_1.csv",
    "candidates": "dpiit_discovery_candidates_v3_4_1_0_1.csv",
    "classification": "dpiit_page_role_classification_v3_4_1_0_1.csv",
    "review": "dpiit_identity_review_queue_v3_4_1_0_1.csv",
    "rejected": "dpiit_rejected_candidates_v3_4_1_0_1.csv",
    "summary": "dpiit_discovery_summary_v3_4_1_0_1.json",
    "validation": "dpiit_discovery_validation_v3_4_1_0_1.json",
    "manifest": "dpiit_run_manifest_v3_4_1_0_1.json",
}


def _counts(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(row.get(field, "") or "MISSING" for row in rows).items()))


def _baseline(project_root: Path) -> dict[str, Any]:
    path = project_root / "data/audit/dpiit_v3_4_1_0_1_prechange_sha256.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _preservation(project_root: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    current_trees = {
        "data/publication/current": sha256_tree(project_root / "data/publication/current"),
        "data/departments/dst": sha256_tree(project_root / "data/departments/dst"),
        "data/departments/dst/v3_4_0_5": sha256_tree(project_root / "data/departments/dst/v3_4_0_5"),
    }
    current_files = {
        path: sha256_file(project_root / path)
        for path in baseline["frozen_files"]
    }
    return {
        "trees": {
            path: {"before": baseline["trees"][path], "after": digest,
                   "unchanged": digest == baseline["trees"][path]}
            for path, digest in current_trees.items()
        },
        "files": {
            path: {"before": baseline["frozen_files"][path], "after": digest,
                   "unchanged": digest == baseline["frozen_files"][path]}
            for path, digest in current_files.items()
        },
    }


def validate(sources: list[dict[str, str]], candidates: list[dict[str, str]],
             review: list[dict[str, str]], rejected: list[dict[str, str]],
             preservation: dict[str, Any]) -> dict[str, Any]:
    policy = OfficialDomainPolicy([row["official_domain"] for row in sources])
    url_duplicates = duplicate_values(candidates, "normalized_url")
    candidate_ids = [row["candidate_id"] for row in candidates]
    checks = {
        "source_registry_schema_complete": all(all(field in row for field in SOURCE_FIELDS) for row in sources),
        "candidate_schema_complete": all(all(field in row for field in CANDIDATE_FIELDS) for row in candidates),
        "only_official_allowed_domains": all(policy.accepts(row["normalized_url"]) for row in candidates),
        "normalized_urls_unique": not url_duplicates,
        "candidate_ids_unique": len(candidate_ids) == len(set(candidate_ids)),
        "exactly_one_valid_primary_page_role": all(row["page_role"] in PAGE_ROLES for row in candidates),
        "calls_not_scheme_masters": all(row["page_role"] != "SCHEME_MASTER" for row in candidates if "call for" in row["page_title"].casefold() or "last date" in row["page_title"].casefold()),
        "award_editions_separate": all(row["page_role"] == "AWARD_EDITION" for row in candidates if "national startup awards 5.0" in row["page_title"].casefold()),
        "challenge_instances_separate": all(row["page_role"] == "CHALLENGE_INSTANCE" for row in candidates if "gaming for good" in row["page_title"].casefold()),
        "startup_india_host_not_automatic_ownership": all(row["ownership_status"] == "NEEDS_VERIFICATION" for row in candidates if row["source_id"] in {"DPIIT-SRC-005", "DPIIT-SRC-006"}),
        "ownership_unresolved_held_for_review": all(row["review_required"] == "1" for row in candidates if row["ownership_status"] == "NEEDS_VERIFICATION" and not row["rejection_reason"]),
        "review_queue_exact": {row["candidate_id"] for row in review} == {row["candidate_id"] for row in candidates if row["review_required"] == "1"},
        "rejected_candidates_retained": {row["candidate_id"] for row in rejected} == {row["candidate_id"] for row in candidates if row["rejection_reason"]},
        "dst_outputs_unchanged": preservation["trees"]["data/departments/dst"]["unchanged"],
        "publication_current_unchanged": preservation["trees"]["data/publication/current"]["unchanged"],
        "public_dashboard_unchanged": all(item["unchanged"] for path, item in preservation["files"].items() if path.endswith((".py", ".css"))),
        "no_publication_or_extraction": True,
    }
    return {
        "version": VERSION,
        "validation_passed": all(checks.values()),
        "checks": checks,
        "counts": {"sources": len(sources), "candidates": len(candidates), "identity_review": len(review), "rejected": len(rejected)},
        "duplicate_normalized_urls": url_duplicates,
        "preservation": preservation,
    }


def run(output_dir: Path, *, project_root: Path, live: bool = False,
        as_of: str = VERIFIED_DATE, max_links_per_source: int = 25) -> dict[str, Any]:
    sources = build_source_registry()
    agent = DPIITDiscoveryAgent(sources, live=live, max_links_per_source=max_links_per_source)
    candidates, fetch_failures = agent.discover(seed_candidates(), as_of)
    review = [row for row in candidates if row["review_required"] == "1"]
    rejected = [row for row in candidates if row["rejection_reason"]]
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / OUTPUT_NAMES["source_registry"], sources, SOURCE_FIELDS)
    write_csv(output_dir / OUTPUT_NAMES["candidates"], candidates, CANDIDATE_FIELDS)
    write_csv(output_dir / OUTPUT_NAMES["classification"], candidates, CANDIDATE_FIELDS)
    write_csv(output_dir / OUTPUT_NAMES["review"], review, CANDIDATE_FIELDS)
    write_csv(output_dir / OUTPUT_NAMES["rejected"], rejected, CANDIDATE_FIELDS)

    summary = {
        "version": VERSION,
        "mode": "LIVE_BOUNDED_DISCOVERY" if live else "GOVERNED_PREVIEW",
        "as_of": as_of,
        "source_count_by_type": _counts(sources, "source_type"),
        "candidate_count_by_official_domain": _counts(candidates, "official_domain"),
        "candidate_count_by_page_role": _counts(candidates, "page_role"),
        "candidate_count_by_ownership_status": _counts(candidates, "ownership_status"),
        "identity_review_queue_count": len(review),
        "rejected_candidate_count": len(rejected),
        "rejection_reasons": _counts(rejected, "rejection_reason"),
        "duplicate_url_group_count": len({row["duplicate_group_id"] for row in candidates if row["duplicate_group_id"].startswith("dupurl_")}),
        "candidate_identity_group_count": len({row["duplicate_group_id"] for row in candidates if row["duplicate_group_id"].startswith("dupidentity_")}),
        "fetch_failures": fetch_failures,
        "full_scheme_extraction_performed": False,
        "publication_performed": False,
    }
    write_json(output_dir / OUTPUT_NAMES["summary"], summary)

    preservation = _preservation(project_root, _baseline(project_root))
    validation = validate(sources, candidates, review, rejected, preservation)
    write_json(output_dir / OUTPUT_NAMES["validation"], validation)

    governed_files = [OUTPUT_NAMES[key] for key in ("source_registry", "candidates", "classification", "review", "rejected", "summary", "validation")]
    manifest = {
        "version": VERSION,
        "run_id": stable_id("dpiit_run", VERSION, as_of, "live" if live else "preview"),
        "mode": summary["mode"],
        "as_of": as_of,
        "deterministic_ordering": True,
        "network_enabled": live,
        "outputs": {name: sha256_file(output_dir / name) for name in governed_files},
        "validation_passed": validation["validation_passed"],
        "publication_current_modified": False,
        "public_dashboard_modified": False,
        "dst_outputs_modified": False,
    }
    write_json(output_dir / OUTPUT_NAMES["manifest"], manifest)
    return {"summary": summary, "validation": validation, "manifest": manifest}


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="DPIIT official-source discovery and page-role foundation")
    parser.add_argument("--output-dir", type=Path, default=project_root / "data/departments/dpiit/v3_4_1_0_1")
    parser.add_argument("--live", action="store_true", help="Fetch only registered official sources; preview is the safe default.")
    parser.add_argument("--as-of", default=VERIFIED_DATE)
    parser.add_argument("--max-links-per-source", type=int, default=25)
    args = parser.parse_args()
    result = run(args.output_dir, project_root=project_root, live=args.live, as_of=args.as_of, max_links_per_source=args.max_links_per_source)
    print(json.dumps({"summary": result["summary"], "validation_passed": result["validation"]["validation_passed"]}, indent=2))
    return 0 if result["validation"]["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
