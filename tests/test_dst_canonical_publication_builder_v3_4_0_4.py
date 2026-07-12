from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dst_canonical_publication_builder_v3_4_0_4.py"
spec = importlib.util.spec_from_file_location("dst_v3404", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["record_status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_self_test_passes() -> None:
    result = mod.self_test()
    assert result["self_test_passed"] is True


def test_call_and_generic_names_are_blocked() -> None:
    config = dict(mod.DEFAULT_CONFIG)
    rows = [
        {"provisional_entity_id": "a", "proposed_canonical_name": "Call for Proposals 2026", "official_source_url": "https://dst.gov.in/call-for-proposals/2026", "identity_confidence": "0.9"},
        {"provisional_entity_id": "b", "proposed_canonical_name": "Archive", "official_source_url": "https://dst.gov.in/archive", "identity_confidence": "0.9"},
    ]
    result = mod.build(rows, [], [], [], [], [], config, {}, {})
    assert not result.entities
    assert len(result.rejected) == 2


def test_stable_identity_is_based_on_provisional_id() -> None:
    config = dict(mod.DEFAULT_CONFIG)
    row1 = {"provisional_entity_id": "same-id", "proposed_canonical_name": "Name One", "official_source_url": "https://dst.gov.in/name-one", "identity_confidence": "0.9"}
    row2 = {"provisional_entity_id": "same-id", "proposed_canonical_name": "Renamed Curated Name", "official_source_url": "https://dst.gov.in/name-one", "identity_confidence": "0.9"}
    r1 = mod.build([row1], [], [], [], [], [], config, {}, {})
    r2 = mod.build([row2], [], [], [], [], [], config, {}, {})
    assert r1.entities[0]["master_id"] == r2.entities[0]["master_id"]


def test_manual_review_never_enters_publication() -> None:
    config = dict(mod.DEFAULT_CONFIG)
    scheme = {"provisional_entity_id": "p1", "proposed_canonical_name": "Research Grant Scheme", "official_source_url": "https://dst.gov.in/research-grant", "identity_confidence": "0.9"}
    manual = {"review_id": "m1", "proposed_name": "Ambiguous Target", "source_url": "https://dst.gov.in/ambiguous"}
    result = mod.build([scheme], [], [manual], [], [], [], config, {}, {})
    assert len(result.publication) == 1
    assert len(result.manual_review) == 1
    assert result.manual_review[0]["publication_status"] == "NOT_PUBLISHED"


def test_override_can_rename_without_changing_stable_id() -> None:
    config = dict(mod.DEFAULT_CONFIG)
    scheme = {"provisional_entity_id": "p1", "proposed_canonical_name": "Old Name", "official_source_url": "https://dst.gov.in/old-name", "identity_confidence": "0.9"}
    override = {"p1": {"provisional_entity_id": "p1", "action": "LOCK", "canonical_name": "Official Curated Name"}}
    result = mod.build([scheme], [], [], [], [], [], config, override, {})
    assert result.entities[0]["canonical_name"] == "Official Curated Name"
    assert result.entities[0]["master_id"] == mod.stable_id("dst_scheme", "p1")


def test_sqlite_database_integrity(tmp_path: Path) -> None:
    config = dict(mod.DEFAULT_CONFIG)
    result = mod.build(
        [{"provisional_entity_id": "p1", "proposed_canonical_name": "Research Grant Scheme", "official_source_url": "https://dst.gov.in/research-grant", "identity_confidence": "0.9"}],
        [{"provisional_entity_id": "p2", "proposed_canonical_name": "Technology Programme", "official_source_url": "https://dst.gov.in/technology-programme", "identity_confidence": "0.9"}],
        [], [], [], [], config, {}, {},
    )
    validation = mod.validate(result, {**config, "require_upstream_ready": False}, {}, partial_run=True)
    db = tmp_path / "preview.db"
    mod.write_database(db, result, validation)
    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT COUNT(*) FROM publication_catalogue").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM canonical_entities WHERE identity_locked=1").fetchone()[0] == 2
    finally:
        con.close()


def test_full_execute_produces_3_schemes_20_programmes(tmp_path: Path) -> None:
    upstream = tmp_path / "data/departments/dst/v3_4_0_3_3_1"
    inventory = tmp_path / "data/departments/dst/v3_4_0_3"
    config_dir = tmp_path / "config"
    upstream.mkdir(parents=True)
    inventory.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    schemes = [
        {"provisional_entity_id": f"s{i}", "proposed_canonical_name": f"Verified Scheme {i}", "official_source_url": f"https://dst.gov.in/verified-scheme-{i}", "identity_confidence": "0.9"}
        for i in range(1, 4)
    ]
    programmes = [
        {"provisional_entity_id": f"p{i}", "proposed_canonical_name": f"Verified Programme {i}", "official_source_url": f"https://dst.gov.in/verified-programme-{i}", "identity_confidence": "0.9"}
        for i in range(1, 21)
    ]
    write_csv(upstream / mod.SCHEMES_INPUT, schemes)
    write_csv(upstream / mod.PROGRAMMES_INPUT, programmes)
    write_csv(upstream / mod.MANUAL_REVIEW_INPUT, [{"review_id": "r1", "review_type": "MANUAL_ENTITY_REVIEW", "proposed_name": "Ambiguous", "source_url": "https://dst.gov.in/ambiguous"}])
    write_csv(upstream / mod.FINAL_REVIEW_INPUT, [{"record_status": "NO_RECORDS"}])
    (upstream / mod.UPSTREAM_VALIDATION_INPUT).write_text(json.dumps({"ready_for_v3_4_0_4": True}), encoding="utf-8")
    (upstream / mod.UPSTREAM_SUMMARY_INPUT).write_text(json.dumps({"calibration_validation_passed": True}), encoding="utf-8")
    write_csv(inventory / mod.ALIASES_INPUT, [{"provisional_entity_id": "s1", "alias_text": "VS1"}])
    write_csv(inventory / mod.HIERARCHY_INPUT, [{"child_provisional_entity_id": "p1", "parent_name_text": "Parent Programme"}])
    write_csv(inventory / mod.EVIDENCE_INPUT, [{"provisional_entity_id": "s1", "evidence_type": "OFFICIAL_PAGE"}])
    (config_dir / "rules.json").write_text(json.dumps(mod.DEFAULT_CONFIG), encoding="utf-8")
    (config_dir / mod.OVERRIDES_INPUT).write_text("provisional_entity_id,official_source_url,action,canonical_name,entity_type,official_abbreviation,public_status,notes\n", encoding="utf-8")

    args = mod.parse_args([
        "--project-root", str(tmp_path),
        "--config", "config/rules.json",
        "--strict",
    ])
    result, validation, summary = mod.execute(args)
    assert validation["canonical_validation_passed"] is True
    assert validation["counts"]["canonical_schemes"] == 3
    assert validation["counts"]["canonical_programmes"] == 20
    assert validation["counts"]["publication_records"] == 23
    assert summary["ready_for_dashboard_preview"] is True
    output = tmp_path / mod.OUTPUT_DIR
    assert (output / mod.DATABASE_OUTPUT).exists()
    assert (output / mod.PUBLICATION_OUTPUT).exists()
