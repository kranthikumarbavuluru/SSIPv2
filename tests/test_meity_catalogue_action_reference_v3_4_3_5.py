from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.catalogue_action_reference_builder_v3_4_3_5 import (
    APPENDED_COLUMNS,
    EXPECTED_ACTIONS_SHA256,
    EXPECTED_SOURCE_SHA256,
    run_catalogue_action_merge,
    sha256_file,
)


def test_catalogue_action_reference_preview() -> None:
    summary = run_catalogue_action_merge(PROJECT_ROOT)

    assert summary["release_readiness_status"] == "PASS"
    assert summary["source_catalogue_rows"] == 141
    assert summary["output_catalogue_rows"] == 141
    assert summary["verified_public_action_count"] == 4
    assert summary["action_enriched_row_count"] == 4
    assert summary["apply_now_reference_count"] == 0
    assert summary["open_call_reference_count"] == 0
    assert summary["sasact_action_reference_present"] is True
    assert summary["genesis_action_reference_present"] is True
    assert summary["source_sha256"] == EXPECTED_SOURCE_SHA256
    assert summary["actions_sha256"] == EXPECTED_ACTIONS_SHA256
    assert all(summary["safety"].values())

    output_path = PROJECT_ROOT / summary["output_path"]
    validation_path = PROJECT_ROOT / summary["validation_path"]

    with output_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames is not None
        assert reader.fieldnames[-len(APPENDED_COLUMNS):] == APPENDED_COLUMNS

    enriched = [
        row for row in rows
        if row["verified_public_action_count"] != "0"
    ]
    assert len(enriched) == 4
    assert all(
        row["verified_public_action_types"] == "SCHEME_DETAILS"
        for row in enriched
    )
    assert all(
        row["verified_public_action_status"] == "VERIFIED"
        for row in enriched
    )

    for row in enriched:
        payload = json.loads(row["verified_public_actions_json"])
        assert len(payload) == 1
        assert payload[0]["action_type"] == "SCHEME_DETAILS"
        assert payload[0]["is_active"] is True
        assert payload[0]["is_time_bound"] is False

    validation = json.loads(
        validation_path.read_text(encoding="utf-8")
    )
    assert validation["passed"] is True
    assert all(validation["safety"].values())

    source_path = (
        PROJECT_ROOT
        / "data/catalogue_preview/v3_4_3_4/"
        "catalogue_preview_v3_4_3_4.csv"
    )
    actions_path = (
        PROJECT_ROOT
        / "data/departments/meity/v3_4_3_5/"
        "meity_verified_public_actions_v3_4_3_5.csv"
    )
    assert sha256_file(source_path) == EXPECTED_SOURCE_SHA256
    assert sha256_file(actions_path) == EXPECTED_ACTIONS_SHA256
