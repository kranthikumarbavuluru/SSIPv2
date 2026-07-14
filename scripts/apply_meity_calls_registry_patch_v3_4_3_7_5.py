from __future__ import annotations

import argparse
from pathlib import Path

IMPORT_LINE = (
    "from services.meity_calls_admin_bridge_v3_4_3_7_5 import "
    "MeitYCallsAdminBridge, MeitYCallsBridgePaths\n"
)

DESCRIPTOR_BLOCK = """
    meity_calls_queue = (
        project_root
        / "data/departments/meity/v3_4_3_7_5/"
        "meity_admin_review_queue_v3_4_3_7_5.csv"
    )
    if meity_calls_queue.exists():
        output.append(
            IntakeDescriptor(
                provider_id="meity_calls_v3_4_3_7_5",
                department=(
                    "Ministry of Electronics and Information "
                    "Technology (MeitY)"
                ),
                version="MeitY v3.4.3.7.5 Calls Recovery",
                source_path=str(meity_calls_queue),
                description=(
                    "Recovered time-bound MeitY calls, challenges, "
                    "cohorts and application windows. Permanent "
                    "scheme identities remain separate. OPEN and "
                    "Apply require current official evidence."
                ),
            )
        )
"""

RESOLVER_BLOCK = """
    if provider_id == "meity_calls_v3_4_3_7_5":
        return MeitYCallsAdminBridge(
            MeitYCallsBridgePaths.defaults(
                project_root,
                database_path,
            )
        )
"""


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    original = text

    if IMPORT_LINE.strip() not in text:
        marker = "from typing import Any, Protocol\n"
        if marker not in text:
            raise RuntimeError("Registry import marker not found")
        text = text.replace(marker, marker + "\n" + IMPORT_LINE, 1)

    if 'provider_id="meity_calls_v3_4_3_7_5"' not in text:
        marker = "    return output\n"
        index = text.find(marker)
        if index < 0:
            raise RuntimeError("Registry descriptor insertion marker not found")
        text = text[:index] + DESCRIPTOR_BLOCK + text[index:]

    if 'provider_id == "meity_calls_v3_4_3_7_5"' not in text:
        marker = (
            '    raise KeyError('
            'f"Unknown department intake provider: {provider_id}"'
            ')\n'
        )
        if marker not in text:
            raise RuntimeError("Registry resolver insertion marker not found")
        text = text.replace(marker, RESOLVER_BLOCK + marker, 1)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    required = (
        "MeitYCallsAdminBridge",
        'provider_id="meity_calls_v3_4_3_7_5"',
        'provider_id == "meity_calls_v3_4_3_7_5"',
        "meity_admin_review_queue_v3_4_3_7_5.csv",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError(
            f"MeitY calls registry validation failed: {missing}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = (
        Path(args.project_root).resolve()
        / "services/department_review_intake_v1.py"
    )
    if not args.check:
        changed = patch(path)
        print(
            "MeitY calls registry patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print("MeitY calls registry validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
