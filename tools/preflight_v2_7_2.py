from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "2.7.2-preflight.1"

EXPECTED_INPUT_FILES = [
    "extracted_records_v2_7_1.csv",
    "ready_for_validation_v2_7_1.csv",
]

IMPORTANT_COLUMNS = [
    "master_id",
    "source",
    "canonical_name",
    "programme_status",
    "deadline",
    "funding_min",
    "funding_max",
    "application_url",
    "final_url",
    "confidence",
    "quality_flags",
    "llm_status",
]

MODULE_KEYWORDS = (
    "valid",
    "database",
    "staging",
    "loader",
    "admin_review",
    "extract",
    "incremental",
)

DATABASE_TABLE_HINTS = (
    "scheme",
    "admin",
    "review",
    "source",
    "contact",
    "attribute",
    "audit",
    "action",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def inspect_csv(path: Path) -> dict[str, Any]:
    columns, rows = read_csv(path)

    master_ids = [
        normalized_text(row.get("master_id"))
        for row in rows
        if normalized_text(row.get("master_id"))
    ]

    duplicate_master_ids = {
        master_id: count
        for master_id, count in Counter(master_ids).items()
        if count > 1
    }

    blank_counts = {
        column: sum(
            1
            for row in rows
            if not normalized_text(row.get(column))
        )
        for column in IMPORTANT_COLUMNS
        if column in columns
    }

    value_counts: dict[str, dict[str, int]] = {}

    for column in (
        "source",
        "llm_status",
        "programme_status",
        "validation_decision",
    ):
        if column in columns:
            counter = Counter(
                normalized_text(row.get(column)) or "<blank>"
                for row in rows
            )
            value_counts[column] = dict(sorted(counter.items()))

    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "missing_important_columns": [
            column for column in IMPORTANT_COLUMNS
            if column not in columns
        ],
        "blank_counts": blank_counts,
        "duplicate_master_ids": duplicate_master_ids,
        "value_counts": value_counts,
    }


def find_relevant_python_files(project_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    ignored_parts = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
    }

    for path in project_root.rglob("*.py"):
        relative = path.relative_to(project_root)

        if any(part.lower() in ignored_parts for part in relative.parts):
            continue

        lowered = str(relative).lower()

        if not any(keyword in lowered for keyword in MODULE_KEYWORDS):
            continue

        results.append(
            {
                "path": str(relative),
                "size_bytes": path.stat().st_size,
                "modified_utc": datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(timespec="seconds"),
                "sha256": file_sha256(path),
            }
        )

    return sorted(results, key=lambda item: item["path"].lower())


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def inspect_database(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "path": str(db_path),
            "exists": False,
        }

    database_uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row

    try:
        table_rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        tables: dict[str, Any] = {}

        for table_row in table_rows:
            table_name = table_row["name"]
            table_identifier = quote_identifier(table_name)

            count = connection.execute(
                f"SELECT COUNT(*) AS row_count FROM {table_identifier}"
            ).fetchone()["row_count"]

            columns = [
                dict(row)
                for row in connection.execute(
                    f"PRAGMA table_info({table_identifier})"
                ).fetchall()
            ]

            indexes = [
                dict(row)
                for row in connection.execute(
                    f"PRAGMA index_list({table_identifier})"
                ).fetchall()
            ]

            foreign_keys = [
                dict(row)
                for row in connection.execute(
                    f"PRAGMA foreign_key_list({table_identifier})"
                ).fetchall()
            ]

            tables[table_name] = {
                "row_count": count,
                "create_sql": table_row["sql"],
                "columns": columns,
                "indexes": indexes,
                "foreign_keys": foreign_keys,
                "important_table": any(
                    hint in table_name.lower()
                    for hint in DATABASE_TABLE_HINTS
                ),
            }

        requested_tables = {}

        for table_name in (
            "scheme_staging",
            "admin_review_queue",
            "admin_review_actions",
            "scheme_sources",
            "scheme_source",
            "scheme_attributes",
            "scheme_attribute",
            "scheme_contacts",
            "scheme_contact",
        ):
            if table_name in tables:
                requested_tables[table_name] = {
                    "row_count": tables[table_name]["row_count"],
                    "columns": [
                        column["name"]
                        for column in tables[table_name]["columns"]
                    ],
                }

        return {
            "path": str(db_path),
            "exists": True,
            "size_bytes": db_path.stat().st_size,
            "sha256": file_sha256(db_path),
            "sqlite_version": sqlite3.sqlite_version,
            "table_count": len(tables),
            "requested_tables": requested_tables,
            "tables": tables,
        }

    finally:
        connection.close()


def inspect_project(project_root: Path) -> dict[str, Any]:
    input_dir = (
        project_root
        / "data"
        / "incremental"
        / "v2_7_1_full"
    )

    csv_reports: dict[str, Any] = {}

    for filename in EXPECTED_INPUT_FILES:
        path = input_dir / filename

        if path.exists():
            csv_reports[filename] = inspect_csv(path)
        else:
            csv_reports[filename] = {
                "path": str(path),
                "exists": False,
            }

    database_path = (
        project_root
        / "database"
        / "ssip_staging_v1.db"
    )

    report = {
        "preflight_version": VERSION,
        "generated_at_utc": utc_now(),
        "python_version": sys.version,
        "project_root": str(project_root),
        "input_directory": str(input_dir),
        "inputs": csv_reports,
        "relevant_python_files": find_relevant_python_files(project_root),
        "database": inspect_database(database_path),
    }

    input_ready = csv_reports.get(
        "ready_for_validation_v2_7_1.csv",
        {},
    )

    report["preflight_checks"] = {
        "ready_for_validation_exists": input_ready.get("exists", False),
        "ready_for_validation_row_count": input_ready.get("row_count"),
        "expected_18_records": input_ready.get("row_count") == 18,
        "no_duplicate_master_ids": not bool(
            input_ready.get("duplicate_master_ids")
        ),
        "database_exists": report["database"].get("exists", False),
        "database_opened_read_only": report["database"].get("exists", False),
    }

    report["preflight_passed"] = all(
        [
            report["preflight_checks"]["ready_for_validation_exists"],
            report["preflight_checks"]["expected_18_records"],
            report["preflight_checks"]["no_duplicate_master_ids"],
            report["preflight_checks"]["database_exists"],
        ]
    )

    return report


def print_summary(report: dict[str, Any]) -> None:
    print("=" * 72)
    print("SSIP v2.7.2 STRICT VALIDATION PREFLIGHT")
    print("=" * 72)

    checks = report["preflight_checks"]

    print(f"Project root              : {report['project_root']}")
    print(
        "Input exists             : "
        f"{checks['ready_for_validation_exists']}"
    )
    print(
        "Input row count          : "
        f"{checks['ready_for_validation_row_count']}"
    )
    print(
        "Exactly 18 records       : "
        f"{checks['expected_18_records']}"
    )
    print(
        "No duplicate master_id   : "
        f"{checks['no_duplicate_master_ids']}"
    )
    print(
        "Database exists          : "
        f"{checks['database_exists']}"
    )
    print(
        "Relevant Python files    : "
        f"{len(report['relevant_python_files'])}"
    )

    database = report["database"]

    if database.get("exists"):
        print(
            "Database table count    : "
            f"{database.get('table_count', 0)}"
        )

        print("\nImportant database tables:")

        important_tables = [
            (name, details["row_count"])
            for name, details in database.get("tables", {}).items()
            if details.get("important_table")
        ]

        for table_name, row_count in important_tables:
            print(f"  {table_name:<35} {row_count:>6}")

    print("\nRelevant existing modules:")

    for item in report["relevant_python_files"]:
        print(f"  {item['path']}")

    print("\nPreflight result:")
    print(
        "  PASS"
        if report["preflight_passed"]
        else "  ATTENTION REQUIRED"
    )
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only preflight for SSIP v2.7.2 strict validation."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="SSIP project root directory.",
    )
    parser.add_argument(
        "--output",
        default=(
            "data/incremental/"
            "v2_7_2_preflight_report.json"
        ),
        help="JSON report path relative to the project root.",
    )

    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if not project_root.exists():
        print(
            f"ERROR: Project root does not exist: {project_root}",
            file=sys.stderr,
        )
        return 1

    report = inspect_project(project_root)

    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print_summary(report)
    print(f"\nFull report written to:\n{output_path}")

    return 0 if report["preflight_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())