from __future__ import annotations

import argparse
from pathlib import Path


ADMIN_OLD_IMPORT = (
    "from services.admin_review_service_v3_4_3_7_2 import "
    "AdminReviewService  # noqa: E402"
)
ADMIN_NEW_IMPORT = (
    "from services.admin_review_service_v3_4_3_7_4 import "
    "AdminReviewService  # noqa: E402"
)

LOADER_IMPORT_MARKER = "from typing import Any, Iterable\n"
LOADER_IMPORT_BLOCK = """from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.organization_canonicalization_v3_4_3_7_4 import (
    canonical_payload_hash,
    canonicalize_organization_record,
)
"""


def patch_admin_ui(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if ADMIN_NEW_IMPORT in text:
        return False
    if ADMIN_OLD_IMPORT not in text:
        raise RuntimeError("Expected v3.4.3.7.2 Admin service import not found")
    path.write_text(text.replace(ADMIN_OLD_IMPORT, ADMIN_NEW_IMPORT, 1), encoding="utf-8")
    return True


def patch_loader(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if "import sys\n" not in text:
        text = text.replace("import sqlite3\n", "import sqlite3\nimport sys\n", 1)

    if "canonicalize_organization_record" not in text:
        if LOADER_IMPORT_MARKER not in text:
            raise RuntimeError("staging_loader import marker not found")
        text = text.replace(LOADER_IMPORT_MARKER, LOADER_IMPORT_BLOCK, 1)

    approved_marker = """def upsert_approved_scheme(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> dict[str, int]:
    master_id = str(record[\"master_id\"])
"""
    approved_replacement = """def upsert_approved_scheme(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> dict[str, int]:
    record = canonicalize_organization_record(record)
    master_id = str(record[\"master_id\"])
"""
    if "record = canonicalize_organization_record(record)" not in text:
        if approved_marker not in text:
            raise RuntimeError("approved scheme canonicalization marker not found")
        text = text.replace(approved_marker, approved_replacement, 1)

    # Only replace the first approved-record hash assignment.
    text = text.replace("rec_hash = record_hash(record)", "rec_hash = canonical_payload_hash(record)", 1)

    review_marker = """def upsert_review_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    validated_record = item.get(\"validated_record\") or {}
    rec_hash = record_hash(validated_record or item)
"""
    review_replacement = """def upsert_review_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    item = dict(item)
    validated_record = canonicalize_organization_record(
        item.get(\"validated_record\") or {}
    )
    item[\"validated_record\"] = validated_record
    rec_hash = canonical_payload_hash(validated_record or item)
"""
    if "item[\"validated_record\"] = validated_record" not in text:
        if review_marker not in text:
            raise RuntimeError("review item canonicalization marker not found")
        text = text.replace(review_marker, review_replacement, 1)

    rejected_marker = """def upsert_rejected_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    validation = item.get(\"validation\") or {}
"""
    rejected_replacement = """def upsert_rejected_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    item = canonicalize_organization_record(item)
    validation = item.get(\"validation\") or {}
"""
    if "item = canonicalize_organization_record(item)" not in text:
        if rejected_marker not in text:
            raise RuntimeError("rejected item canonicalization marker not found")
        text = text.replace(rejected_marker, rejected_replacement, 1)

    # The rejected-record hash occurs later and should also match stored JSON.
    rejected_hash_marker = "            record_hash(item),\n"
    if rejected_hash_marker in text:
        text = text.replace(
            rejected_hash_marker,
            "            canonical_payload_hash(item),\n",
            1,
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(project_root: Path) -> None:
    ui = (project_root / "ui/admin_review_app_v1.py").read_text(encoding="utf-8")
    loader = (project_root / "database/staging_loader_v1.py").read_text(encoding="utf-8")
    required_ui = ("admin_review_service_v3_4_3_7_4",)
    required_loader = (
        "organization_canonicalization_v3_4_3_7_4",
        "record = canonicalize_organization_record(record)",
        'item["validated_record"] = validated_record',
        "item = canonicalize_organization_record(item)",
        "canonical_payload_hash(record)",
        "canonical_payload_hash(validated_record or item)",
    )
    missing = [marker for marker in required_ui if marker not in ui]
    missing.extend(marker for marker in required_loader if marker not in loader)
    if missing:
        raise RuntimeError(f"Organization canonicalization patch incomplete: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if not args.check:
        ui_changed = patch_admin_ui(root / "ui/admin_review_app_v1.py")
        loader_changed = patch_loader(root / "database/staging_loader_v1.py")
        print(f"Admin UI service patch: {'APPLIED' if ui_changed else 'ALREADY_APPLIED'}")
        print(f"Staging loader patch: {'APPLIED' if loader_changed else 'ALREADY_APPLIED'}")
    validate(root)
    print("SSIP v3.4.3.7.4 organization canonicalization patches: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
