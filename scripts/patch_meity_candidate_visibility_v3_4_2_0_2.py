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
    / "meity_catalogue_candidate_builder_v3_4_2_0_2_before_visibility_fix_v3.py"
)

text = target.read_text(encoding="utf-8-sig")
lines = text.splitlines(keepends=True)

start_index = None
end_index = None

# Find only the candidate-path visibility calculation.
for index, line in enumerate(lines):
    compact = line.replace(" ", "")

    if (
        "visible_after" in compact
        and "dashboard_public_ids" in compact
        and "CANDIDATE_PATH" in compact
    ):
        start_index = index
        break

if start_index is None:
    raise RuntimeError(
        "Could not locate the candidate visibility calculation."
    )

# Replace everything from visible_after until the next validation check.
for index in range(start_index + 1, len(lines)):
    if lines[index].strip().startswith("check("):
        end_index = index
        break

if end_index is None:
    raise RuntimeError(
        "Could not locate the next validation check "
        "after the candidate visibility calculation."
    )

replacement = '''    # Evaluate the candidate through the real dashboard loader.
    # dashboard_public_ids() uses a broad fallback for any path
    # other than the exact active catalogue filename.
    previous_public_catalogue = os.environ.get(
        "SSIP_PUBLIC_CATALOGUE"
    )

    os.environ["SSIP_PUBLIC_CATALOGUE"] = str(
        CANDIDATE_PATH
    )

    try:
        from ssip_dashboard.catalogue import (
            load_catalogue,
        )
        from ssip_dashboard.catalogue_populations import (
            split_catalogue_populations,
        )
        from ssip_dashboard.config import (
            DashboardConfig,
        )

        candidate_config = DashboardConfig.from_env(
            ROOT
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
    finally:
        if previous_public_catalogue is None:
            os.environ.pop(
                "SSIP_PUBLIC_CATALOGUE",
                None,
            )
        else:
            os.environ[
                "SSIP_PUBLIC_CATALOGUE"
            ] = previous_public_catalogue

    new_visible_ids = EXPECTED_IDS & visible_after

'''

shutil.copy2(target, backup)

updated_lines = (
    lines[:start_index]
    + [replacement]
    + lines[end_index:]
)

target.write_text(
    "".join(updated_lines),
    encoding="utf-8",
    newline="\n",
)

print("Candidate visibility patch: COMPLETE")
print(
    f"Replaced lines {start_index + 1} "
    f"through {end_index}"
)
print(f"Backup: {backup}")
