from __future__ import annotations

import argparse
from pathlib import Path


OLD_BLOCK = '''            key = (
                attr.get("property")
                or attr.get("name")
                or attr.get("itemprop")
            ).casefold()
'''

NEW_BLOCK = '''            key = clean(
                attr.get("property")
                or attr.get("name")
                or attr.get("itemprop")
                or ""
            ).casefold()
'''


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    if NEW_BLOCK in text:
        return False
    if OLD_BLOCK not in text:
        raise RuntimeError(
            "The expected v3.4.3.8.0 HTML meta-key block was not found."
        )
    path.write_text(
        text.replace(OLD_BLOCK, NEW_BLOCK, 1),
        encoding="utf-8",
    )
    return True


def validate(path: Path) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if NEW_BLOCK not in text:
        raise RuntimeError("The safe HTML meta-key parser is missing.")
    if OLD_BLOCK in text:
        raise RuntimeError("The unsafe HTML meta-key parser remains.")
    if text.count(NEW_BLOCK) != 1:
        raise RuntimeError(
            "The safe HTML meta-key parser must occur exactly once."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = (
        Path(args.project_root).resolve()
        / "services/meity_complete_intelligence_v3_4_3_8_0.py"
    )
    if not args.check:
        changed = patch(path)
        print(
            "MeitY v3.4.3.8.0 HTML parser repair: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print("MeitY source HTML parser validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
