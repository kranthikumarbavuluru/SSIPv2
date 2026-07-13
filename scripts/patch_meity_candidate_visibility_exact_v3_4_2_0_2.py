from pathlib import Path

project_root = Path(__file__).resolve().parents[1]

target = (
    project_root
    / "scripts"
    / "meity_catalogue_candidate_builder_v3_4_2_0_2.py"
)

text = target.read_text(
    encoding="utf-8-sig"
)

old = '''    visible_after = set(dashboard_public_ids(ROOT, CANDIDATE))
    new_visible = EXPECTED_IDS & visible_after
'''

new = '''    # Validate the candidate using the actual dashboard loader.
    # dashboard_public_ids() uses a broad fallback for non-active paths,
    # which incorrectly includes pending and review-only catalogue rows.
    previous_public_catalogue = os.environ.get(
        "SSIP_PUBLIC_CATALOGUE"
    )

    os.environ["SSIP_PUBLIC_CATALOGUE"] = str(
        CANDIDATE
    )

    try:
        from ssip_dashboard.catalogue import load_catalogue
        from ssip_dashboard.catalogue_populations import (
            split_catalogue_populations,
        )
        from ssip_dashboard.config import DashboardConfig

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

    new_visible = EXPECTED_IDS & visible_after
'''

occurrences = text.count(old)

if occurrences != 1:
    raise RuntimeError(
        "Expected exactly one visibility block; "
        f"found {occurrences}."
    )

updated = text.replace(
    old,
    new,
    1,
)

# Ensure os is imported.
if "import os\n" not in updated:
    lines = updated.splitlines(
        keepends=True
    )

    insert_at = 0

    for index, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = index + 1
        elif insert_at > 0:
            break

    lines.insert(
        insert_at,
        "import os\n",
    )

    updated = "".join(lines)

target.write_text(
    updated,
    encoding="utf-8",
    newline="\n",
)

print(
    "Exact dashboard visibility patch: COMPLETE"
)
