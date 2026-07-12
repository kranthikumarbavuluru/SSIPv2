from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "2.7.2-manifest.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_key(value: Any) -> str:
    return normalize(value).casefold()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)

        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")

        rows = [
            {
                str(key): "" if value is None else str(value)
                for key, value in row.items()
            }
            for row in reader
        ]

        return list(reader.fieldnames), rows


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    field: "" if row.get(field) is None else row.get(field)
                    for field in fieldnames
                }
            )

    temporary_path.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def duplicate_values(
    rows: list[dict[str, str]],
    column: str,
) -> dict[str, int]:
    values = [
        normalize_key(row.get(column))
        for row in rows
        if normalize_key(row.get(column))
    ]

    return {
        value: count
        for value, count in Counter(values).items()
        if count > 1
    }


def distribution(
    rows: list[dict[str, str]],
    column: str,
) -> dict[str, int]:
    counts = Counter(
        normalize(row.get(column)) or "<blank>"
        for row in rows
    )

    return dict(
        sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    )


def build_manifest(
    extracted_columns: list[str],
    extracted_rows: list[dict[str, str]],
    ready_rows: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]], dict[str, Any]]:
    extracted_duplicates = duplicate_values(
        extracted_rows,
        "master_id",
    )
    ready_duplicates = duplicate_values(
        ready_rows,
        "master_id",
    )

    if extracted_duplicates:
        raise ValueError(
            "Duplicate master_id values found in full extraction: "
            + json.dumps(extracted_duplicates, ensure_ascii=False)
        )

    if ready_duplicates:
        raise ValueError(
            "Duplicate master_id values found in ready file: "
            + json.dumps(ready_duplicates, ensure_ascii=False)
        )

    extracted_by_id = {
        normalize_key(row.get("master_id")): row
        for row in extracted_rows
        if normalize_key(row.get("master_id"))
    }

    ready_by_id = {
        normalize_key(row.get("master_id")): row
        for row in ready_rows
        if normalize_key(row.get("master_id"))
    }

    blank_extracted_ids = [
        index + 2
        for index, row in enumerate(extracted_rows)
        if not normalize_key(row.get("master_id"))
    ]

    blank_ready_ids = [
        index + 2
        for index, row in enumerate(ready_rows)
        if not normalize_key(row.get("master_id"))
    ]

    if blank_extracted_ids:
        raise ValueError(
            "Blank master_id found in extracted CSV at lines: "
            + ", ".join(map(str, blank_extracted_ids))
        )

    if blank_ready_ids:
        raise ValueError(
            "Blank master_id found in ready CSV at lines: "
            + ", ".join(map(str, blank_ready_ids))
        )

    extra_ready_ids = sorted(
        set(ready_by_id) - set(extracted_by_id)
    )

    if extra_ready_ids:
        raise ValueError(
            "Ready file contains master_id values that are absent from "
            "the full extraction: "
            + ", ".join(extra_ready_ids)
        )

    added_columns = [
        "strict_validation_input",
        "upstream_ready_for_validation",
        "upstream_ready_position",
        "upstream_ready_next_decision",
        "upstream_handoff_status",
        "manifest_version",
    ]

    manifest_columns = list(extracted_columns)

    for column in added_columns:
        if column not in manifest_columns:
            manifest_columns.append(column)

    ready_positions = {
        normalize_key(row.get("master_id")): index + 1
        for index, row in enumerate(ready_rows)
    }

    manifest_rows: list[dict[str, str]] = []
    missing_from_ready: list[dict[str, str]] = []

    for extracted_row in extracted_rows:
        master_id_key = normalize_key(extracted_row.get("master_id"))
        ready_row = ready_by_id.get(master_id_key)
        included = ready_row is not None

        manifest_row = dict(extracted_row)
        manifest_row["strict_validation_input"] = "YES"
        manifest_row["upstream_ready_for_validation"] = (
            "YES" if included else "NO"
        )
        manifest_row["upstream_ready_position"] = (
            str(ready_positions[master_id_key])
            if included
            else ""
        )
        manifest_row["upstream_ready_next_decision"] = (
            normalize(ready_row.get("next_decision"))
            if ready_row
            else ""
        )
        manifest_row["upstream_handoff_status"] = (
            "INCLUDED_IN_V2_7_1_READY_FILE"
            if included
            else "EXCLUDED_FROM_V2_7_1_READY_FILE"
        )
        manifest_row["manifest_version"] = VERSION

        manifest_rows.append(manifest_row)

        if not included:
            missing_from_ready.append(
                {
                    "master_id": normalize(
                        extracted_row.get("master_id")
                    ),
                    "source": normalize(
                        extracted_row.get("source")
                    ),
                    "canonical_name": normalize(
                        extracted_row.get("canonical_name")
                    ),
                    "scheme_name": normalize(
                        extracted_row.get("scheme_name")
                    ),
                    "programme_status": normalize(
                        extracted_row.get("programme_status")
                    ),
                    "next_decision": normalize(
                        extracted_row.get("next_decision")
                    ),
                    "llm_status": normalize(
                        extracted_row.get("llm_status")
                    ),
                    "confidence": normalize(
                        extracted_row.get("confidence")
                    ),
                    "quality_flags": normalize(
                        extracted_row.get("quality_flags")
                    ),
                    "final_url": normalize(
                        extracted_row.get("final_url")
                    ),
                    "handoff_gap_reason": (
                        "MASTER_ID_NOT_PRESENT_IN_"
                        "READY_FOR_VALIDATION_V2_7_1"
                    ),
                }
            )

    summary = {
        "manifest_version": VERSION,
        "generated_at_utc": utc_now(),
        "extracted_record_count": len(extracted_rows),
        "ready_record_count": len(ready_rows),
        "manifest_record_count": len(manifest_rows),
        "included_in_ready_count": sum(
            1
            for row in manifest_rows
            if row["upstream_ready_for_validation"] == "YES"
        ),
        "excluded_from_ready_count": len(missing_from_ready),
        "all_extracted_records_preserved": (
            len(manifest_rows) == len(extracted_rows)
        ),
        "ready_is_subset_of_extracted": True,
        "extracted_duplicate_master_ids": extracted_duplicates,
        "ready_duplicate_master_ids": ready_duplicates,
        "extra_ready_master_ids": extra_ready_ids,
        "extracted_distributions": {
            "source": distribution(extracted_rows, "source"),
            "llm_status": distribution(extracted_rows, "llm_status"),
            "next_decision": distribution(
                extracted_rows,
                "next_decision",
            ),
            "programme_status": distribution(
                extracted_rows,
                "programme_status",
            ),
        },
        "ready_distributions": {
            "source": distribution(ready_rows, "source"),
            "llm_status": distribution(ready_rows, "llm_status"),
            "next_decision": distribution(
                ready_rows,
                "next_decision",
            ),
            "programme_status": distribution(
                ready_rows,
                "programme_status",
            ),
        },
        "missing_from_ready": missing_from_ready,
    }

    return manifest_columns, manifest_rows, summary


def print_summary(summary: dict[str, Any]) -> None:
    print("=" * 76)
    print("SSIP v2.7.2 VALIDATION INPUT MANIFEST")
    print("=" * 76)
    print(
        f"Full extracted records       : "
        f"{summary['extracted_record_count']}"
    )
    print(
        f"Upstream ready records       : "
        f"{summary['ready_record_count']}"
    )
    print(
        f"Strict-validation manifest   : "
        f"{summary['manifest_record_count']}"
    )
    print(
        f"Included in ready file       : "
        f"{summary['included_in_ready_count']}"
    )
    print(
        f"Excluded from ready file     : "
        f"{summary['excluded_from_ready_count']}"
    )
    print(
        f"All extracted preserved      : "
        f"{summary['all_extracted_records_preserved']}"
    )

    print("\nFull extraction next_decision distribution:")

    for name, count in summary[
        "extracted_distributions"
    ]["next_decision"].items():
        print(f"  {count:>3}  {name}")

    if summary["missing_from_ready"]:
        print("\nRecords absent from the upstream ready file:")

        for record in summary["missing_from_ready"]:
            print(
                f"  {record['master_id']} | "
                f"{record['source']} | "
                f"{record['canonical_name']} | "
                f"{record['next_decision'] or '<blank>'}"
            )

    print("=" * 76)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the complete input manifest for SSIP v2.7.2 "
            "strict validation."
        )
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument(
        "--extracted",
        default=(
            "data/incremental/v2_7_1_full/"
            "extracted_records_v2_7_1.csv"
        ),
    )
    parser.add_argument(
        "--ready",
        default=(
            "data/incremental/v2_7_1_full/"
            "ready_for_validation_v2_7_1.csv"
        ),
    )
    parser.add_argument(
        "--output-directory",
        default=(
            "data/incremental/"
            "v2_7_2_strict_validation"
        ),
    )

    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    extracted_path = project_root / args.extracted
    ready_path = project_root / args.ready
    output_directory = project_root / args.output_directory

    try:
        extracted_columns, extracted_rows = read_csv(
            extracted_path
        )
        _, ready_rows = read_csv(ready_path)

        manifest_columns, manifest_rows, summary = build_manifest(
            extracted_columns=extracted_columns,
            extracted_rows=extracted_rows,
            ready_rows=ready_rows,
        )

        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest_path = (
            output_directory
            / "validation_input_manifest_v2_7_2.csv"
        )
        gap_path = (
            output_directory
            / "v2_7_1_handoff_gap_v2_7_2.csv"
        )
        summary_path = (
            output_directory
            / "validation_input_manifest_summary_v2_7_2.json"
        )

        write_csv(
            manifest_path,
            manifest_columns,
            manifest_rows,
        )

        gap_columns = [
            "master_id",
            "source",
            "canonical_name",
            "scheme_name",
            "programme_status",
            "next_decision",
            "llm_status",
            "confidence",
            "quality_flags",
            "final_url",
            "handoff_gap_reason",
        ]

        write_csv(
            gap_path,
            gap_columns,
            summary["missing_from_ready"],
        )

        summary["input_files"] = {
            "extracted_path": str(extracted_path),
            "extracted_sha256": sha256_file(extracted_path),
            "ready_path": str(ready_path),
            "ready_sha256": sha256_file(ready_path),
        }

        summary["output_files"] = {
            "manifest_path": str(manifest_path),
            "gap_path": str(gap_path),
            "summary_path": str(summary_path),
        }

        write_json(summary_path, summary)

        print_summary(summary)
        print(f"\nManifest:\n{manifest_path}")
        print(f"\nHandoff gap report:\n{gap_path}")
        print(f"\nSummary:\n{summary_path}")

        if len(manifest_rows) != len(extracted_rows):
            return 2

        return 0

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())