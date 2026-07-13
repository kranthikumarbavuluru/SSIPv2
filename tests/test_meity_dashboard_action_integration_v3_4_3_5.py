from __future__ import annotations

import csv
import hashlib
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.config import DashboardConfig


EXPECTED_NAMES = {"GENESIS", "SAMRIDH", "SASACT", "TIDE 2.0"}
EXPECTED_SOURCE_HASH = (
    "ef43bd7e27df2ead5fe88ab8bf2751a80eac6c4e13e8894173a6625b57650a8c"
)
EXPECTED_ACTIONS_HASH = (
    "28f6174ebf4313394f205682dc1735451f14f060f346264c84d857d6cee0836e"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_v3435_governed_scheme_details_integration() -> None:
    v3434 = (
        ROOT
        / "data/catalogue_preview/v3_4_3_4/"
        "catalogue_preview_v3_4_3_4.csv"
    )
    v3435 = (
        ROOT
        / "data/catalogue_preview/v3_4_3_5/"
        "catalogue_preview_v3_4_3_5.csv"
    )
    actions_path = (
        ROOT
        / "data/departments/meity/v3_4_3_5/"
        "meity_verified_public_actions_v3_4_3_5.csv"
    )

    assert sha256(v3434) == EXPECTED_SOURCE_HASH
    assert sha256(actions_path) == EXPECTED_ACTIONS_HASH

    base = DashboardConfig.from_env(ROOT)
    bundle_3434 = load_catalogue(
        replace(
            base,
            normalization_path=v3434.resolve(),
            preview_path_configured=True,
        )
    )
    bundle_3435 = load_catalogue(
        replace(
            base,
            normalization_path=v3435.resolve(),
            preview_path_configured=True,
        )
    )

    pop_3434 = split_catalogue_populations(bundle_3434.records)
    pop_3435 = split_catalogue_populations(bundle_3435.records)

    assert len(bundle_3434.records) == len(bundle_3435.records) == 168
    assert len(pop_3434.main_scheme_records) == len(pop_3435.main_scheme_records) == 55
    assert len(pop_3434.application_call_records) == len(pop_3435.application_call_records) == 38
    assert all(not record.verified_public_actions for record in bundle_3434.records)

    with actions_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        expected = {
            row["master_id"]: row
            for row in csv.DictReader(handle)
        }

    records = {record.master_id: record for record in bundle_3435.records}
    targets = [records[master_id] for master_id in expected]

    assert {record.scheme_name for record in targets} == EXPECTED_NAMES
    assert all(not record.application_url for record in targets)
    assert all(len(record.verified_public_actions) == 1 for record in targets)

    for record in targets:
        action = record.verified_public_actions[0]
        assert action["action_type"] == "SCHEME_DETAILS"
        assert action["link_role"] == "SCHEME_MASTER"
        assert action["verification_status"] == "VERIFIED_INFORMATION_PAGE"
        assert action["is_active"] is True
        assert action["is_time_bound"] is False
        assert action["resolved_url"] == expected[record.master_id]["resolved_url"]


def test_renderer_uses_governed_scheme_details_without_new_apply_action() -> None:
    app_text = (
        ROOT / "apps/public_dashboard_app_v2_9.py"
    ).read_text(encoding="utf-8-sig")

    assert "def verified_scheme_details_action(" in app_text
    assert "governed_details = verified_scheme_details_action(record)" in app_text
    assert app_text.count(">Scheme Details") >= 2
