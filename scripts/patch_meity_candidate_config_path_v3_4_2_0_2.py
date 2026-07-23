from pathlib import Path
import shutil

project_root = Path(__file__).resolve().parents[1]

target = (
    project_root
    / "scripts"
    / "meity_catalogue_candidate_builder_v3_4_2_0_2.py"
)

backup = (
    project_root
    / "scripts"
    / "meity_catalogue_candidate_builder_v3_4_2_0_2_before_direct_config_fix.py"
)

text = target.read_text(
    encoding="utf-8-sig"
)

lines = text.splitlines(
    keepends=True
)

start_index = None
end_index = None

for index, line in enumerate(lines):
    if (
        "previous_public_catalogue"
        in line
        and "os.environ.get"
        in line
    ):
        start_index = index
        break

if start_index is None:
    raise RuntimeError(
        "Could not locate the current candidate "
        "configuration block."
    )

for index in range(
    start_index + 1,
    len(lines),
):
    if (
        "new_visible = EXPECTED_IDS & visible_after"
        in lines[index]
    ):
        end_index = index
        break

if end_index is None:
    raise RuntimeError(
        "Could not locate the end of the current "
        "visibility block."
    )

replacement = '''    # Load the candidate through the actual dashboard pipeline.
    # DashboardConfig does not use SSIP_PUBLIC_CATALOGUE, so create
    # an explicit candidate configuration using the candidate path.
    from dataclasses import replace as dataclass_replace

    from ssip_dashboard.catalogue import load_catalogue
    from ssip_dashboard.catalogue_populations import (
        split_catalogue_populations,
    )
    from ssip_dashboard.config import DashboardConfig

    base_candidate_config = DashboardConfig.from_env(
        ROOT
    )

    candidate_config = dataclass_replace(
        base_candidate_config,
        normalization_path=CANDIDATE.resolve(),
        preview_path_configured=True,
    )

    candidate_catalogue = load_catalogue(
        candidate_config
    )

    candidate_populations = (
        split_catalogue_populations(
            candidate_catalogue.records
        )
    )

    visible_after = {
        record.master_id
        for record in (
            candidate_populations.main_scheme_records
        )
        if record.master_id
    }

    new_visible = EXPECTED_IDS & visible_after
'''

shutil.copy2(
    target,
    backup,
)

updated_lines = (
    lines[:start_index]
    + [replacement]
    + lines[end_index + 1:]
)

target.write_text(
    "".join(updated_lines),
    encoding="utf-8",
    newline="\n",
)

print(
    "Candidate configuration-path patch: COMPLETE"
)

print(
    f"Replaced lines {start_index + 1} "
    f"through {end_index + 1}"
)

print(
    f"Backup: {backup}"
)
