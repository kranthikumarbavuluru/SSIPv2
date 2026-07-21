from pathlib import Path
import re
import shutil

project_root = Path(__file__).resolve().parents[1]

target = (
    project_root
    / "scripts"
    / "meity_manual_pilot_finalize_v3_4_2_0_1.py"
)

backup = (
    project_root
    / "scripts"
    / "meity_manual_pilot_finalize_v3_4_2_0_1_before_generic_tree_hash_fix.py"
)

text = target.read_text(encoding="utf-8-sig")
lines = text.splitlines(keepends=True)

start_index = None
end_index = None

for index, line in enumerate(lines):
    if re.match(r"^def\s+tree_hash\s*\(", line):
        start_index = index
        break

if start_index is None:
    raise RuntimeError(
        "Could not find the top-level tree_hash function."
    )

# Stop at the next top-level function or class.
for index in range(start_index + 1, len(lines)):
    if re.match(r"^(def|class)\s+", lines[index]):
        end_index = index
        break

# Fallback for a function near the end of the file.
if end_index is None:
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith('if __name__'):
            end_index = index
            break

if end_index is None:
    raise RuntimeError(
        "Could not determine the end of tree_hash safely."
    )

replacement = '''def tree_hash(root: Path) -> str:
    """Use the original PowerShell governed tree-hash algorithm."""
    if not root.exists():
        return "MISSING"

    import subprocess

    helper = (
        ROOT
        / "scripts"
        / "ssip_powershell_tree_hash_v1.ps1"
    )

    if not helper.exists():
        raise RuntimeError(
            f"Tree-hash helper is missing: {helper}"
        )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            str(root.resolve()),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    output_lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    if not output_lines:
        raise RuntimeError(
            "PowerShell tree-hash helper returned "
            f"no output for {root}"
        )

    value = output_lines[-1].lower()

    if value != "missing":
        valid = (
            len(value) == 64
            and all(
                character in "0123456789abcdef"
                for character in value
            )
        )

        if not valid:
            raise RuntimeError(
                f"Invalid tree hash returned for {root}: {value}"
            )

    return value


'''

shutil.copy2(target, backup)

updated = (
    lines[:start_index]
    + [replacement]
    + lines[end_index:]
)

target.write_text(
    "".join(updated),
    encoding="utf-8",
    newline="\n",
)

print("Python tree-hash patch: COMPLETE")
print(
    f"Replaced lines {start_index + 1} "
    f"through {end_index}"
)
print(f"Backup: {backup}")
