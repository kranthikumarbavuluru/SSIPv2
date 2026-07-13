from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "meity_candidate_triage_agent_v3_4_3_2.py"
BACKUP = ROOT / "scripts" / "meity_candidate_triage_agent_v3_4_3_2_before_v3_4_3_2_1.py"

if not TARGET.exists():
    raise SystemExit(f"Target script not found: {TARGET}")

text = TARGET.read_text(encoding="utf-8-sig")

old = '''    for row in identity_rows:
        key = text(row["normalized_identity_name"])
        duplicate_groups.setdefault(key, []).append(row)
'''

new = '''    for row in identity_rows:
        key = normalize_identity_name(
            text(row.get("canonical_name", ""))
        )
        duplicate_groups.setdefault(key, []).append(row)
'''

count = text.count(old)
if count != 1:
    raise SystemExit(
        "Expected exactly one duplicate-detection block to patch; "
        f"found {count}."
    )

shutil.copy2(TARGET, BACKUP)
text = text.replace(old, new, 1)
TARGET.write_text(text, encoding="utf-8", newline="\n")

print("SSIP MeitY v3.4.3.2.1 triage patch: COMPLETE")
print(f"Backup: {BACKUP}")
