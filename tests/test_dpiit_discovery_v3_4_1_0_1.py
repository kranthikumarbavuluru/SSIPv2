from __future__ import annotations

import csv
import json
from pathlib import Path

from agents.dpiit.dpiit_discovery_agent_v3_4_1_0_1 import CANDIDATE_FIELDS, DPIITDiscoveryAgent
from agents.dpiit.dpiit_identity_rules_v3_4_1_0_1 import (
    CANONICAL_DEPARTMENT, canonical_department,
)
from agents.dpiit.dpiit_orchestrator_v3_4_1_0_1 import OUTPUT_NAMES, run
from agents.dpiit.dpiit_source_registry_v3_4_1_0_1 import (
    SOURCE_FIELDS, build_source_registry, seed_candidates,
)
from agents.shared.official_domain_policy import OfficialDomainPolicy
from agents.shared.page_role_classifier import ConservativePageRoleClassifier
from agents.shared.url_normalization import normalize_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/departments/dpiit/v3_4_1_0_1"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_only_official_allowed_domains_are_accepted() -> None:
    policy = OfficialDomainPolicy([row["official_domain"] for row in build_source_registry()])
    assert policy.accepts("https://www.dpiit.gov.in/offerings")
    assert policy.accepts("https://seedfund.startupindia.gov.in/about")
    assert not policy.accepts("https://example.com/dpiit-scheme")
    assert not policy.accepts("https://dpiit.gov.in.example.com/fake")


def test_url_normalization_removes_variants_and_tracking() -> None:
    first = normalize_url("HTTPS://SeedFund.StartupIndia.Gov.In/?utm_source=test#top")
    second = normalize_url("https://seedfund.startupindia.gov.in")
    assert first == second == "https://seedfund.startupindia.gov.in/"


def test_identity_query_parameters_are_preserved() -> None:
    url = normalize_url("https://www.dpiit.gov.in/documents/gazettes-notifications?utm_source=x&page=17&type=startup#top")
    assert url == "https://www.dpiit.gov.in/documents/gazettes-notifications?page=17&type=startup"


def test_call_award_and_challenge_roles_are_separate() -> None:
    classifier = ConservativePageRoleClassifier()
    assert classifier.classify(url="https://startupindia.gov.in/call", title="Call for Applications under SISFS").role == "APPLICATION_CALL"
    assert classifier.classify(url="https://startupindia.gov.in/nsa2025", title="National Startup Awards 5.0").role == "AWARD_EDITION"
    assert classifier.classify(url="https://startupindia.gov.in/gaming", title="Gaming for Good – Bharat Startup Grand Challenge").role == "CHALLENGE_INSTANCE"


def test_award_guideline_is_supporting_document() -> None:
    decision = ConservativePageRoleClassifier().classify(
        url="https://startupindia.gov.in/nsa2023-guidelines.pdf",
        title="National Startup Awards 2023 Guidelines",
    )
    assert decision.role == "GUIDELINE"


def test_startup_india_host_does_not_assign_dpiit_ownership() -> None:
    sources = build_source_registry()
    candidate = next(row for row in seed_candidates() if row["source_id"] == "DPIIT-SRC-005")
    rows, _ = DPIITDiscoveryAgent(sources).discover([candidate], "2026-07-12")
    assert rows[0]["ownership_status"] == "NEEDS_VERIFICATION"
    assert rows[0]["page_role"] == "OWNERSHIP_UNRESOLVED"
    assert rows[0]["review_required"] == "1"


def test_historical_dipp_alias_is_not_second_current_department() -> None:
    assert canonical_department("DIPP") == (CANONICAL_DEPARTMENT, "HISTORICAL_ALIAS")
    assert canonical_department("Department of Industrial Policy and Promotion") == (CANONICAL_DEPARTMENT, "HISTORICAL_ALIAS")
    assert canonical_department("DPIIT") == (CANONICAL_DEPARTMENT, "CURRENT_ALIAS")


def test_duplicate_urls_collapse_and_identity_duplicates_group() -> None:
    sources = build_source_registry()
    seeds = [
        {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/?utm_source=a", "title": "Startup India Seed Fund Scheme", "ownership_proven": True},
        {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/#top", "title": "SISFS", "ownership_proven": True},
        {"source_id": "DPIIT-SRC-007", "url": "https://seedfund.startupindia.gov.in/about", "title": "Startup India Seed Fund Scheme", "ownership_proven": True},
    ]
    rows, _ = DPIITDiscoveryAgent(sources).discover(seeds, "2026-07-12")
    assert len(rows) == 2
    assert len({row["normalized_url"] for row in rows}) == 2
    assert all(row["duplicate_group_id"] for row in rows)
    assert all(row["review_required"] == "1" for row in rows)


def test_output_schemas_roles_and_preservation() -> None:
    result = run(OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert result["validation"]["validation_passed"] is True
    sources = read_csv(OUTPUT_DIR / OUTPUT_NAMES["source_registry"])
    candidates = read_csv(OUTPUT_DIR / OUTPUT_NAMES["candidates"])
    assert list(sources[0]) == SOURCE_FIELDS
    assert list(candidates[0]) == CANDIDATE_FIELDS
    assert len(candidates) == len({row["normalized_url"] for row in candidates})
    assert any(row["page_role"] == "SCHEME_MASTER" for row in candidates)
    assert any(row["page_role"] == "UMBRELLA_PROGRAMME" for row in candidates)
    assert result["validation"]["checks"]["dst_outputs_unchanged"]
    assert result["validation"]["checks"]["publication_current_unchanged"]
    assert result["validation"]["checks"]["public_dashboard_unchanged"]


def test_deterministic_rerun_is_byte_identical() -> None:
    run(OUTPUT_DIR, project_root=PROJECT_ROOT)
    first = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    run(OUTPUT_DIR, project_root=PROJECT_ROOT)
    second = {name: (OUTPUT_DIR / name).read_bytes() for name in OUTPUT_NAMES.values()}
    assert first == second


def test_required_outputs_are_preview_only() -> None:
    result = run(OUTPUT_DIR, project_root=PROJECT_ROOT)
    assert set(path.name for path in OUTPUT_DIR.iterdir() if path.is_file()) == set(OUTPUT_NAMES.values())
    assert result["summary"]["publication_performed"] is False
    assert result["summary"]["full_scheme_extraction_performed"] is False
    assert all(row["http_status"] == "PREVIEW_NOT_FETCHED" for row in read_csv(OUTPUT_DIR / OUTPUT_NAMES["candidates"]))
    manifest = json.loads((OUTPUT_DIR / OUTPUT_NAMES["manifest"]).read_text(encoding="utf-8"))
    assert manifest["network_enabled"] is False
