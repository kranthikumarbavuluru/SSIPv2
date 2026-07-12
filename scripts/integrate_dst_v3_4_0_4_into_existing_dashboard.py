from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "3.4.0.4a"
DEFAULT_BASE_PREVIEW = Path("data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv")
DEFAULT_DST_PUBLICATION = Path("data/departments/dst/v3_4_0_4/dst_publication_catalogue_v3_4_0_4.csv")
DEFAULT_MERGED_OUTPUT = Path("data/catalogue_preview/v3_4_0_4/catalogue_preview_v3_4_0_4.csv")
DEFAULT_APP = Path("apps/public_dashboard_app_v2_9.py")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Required CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [{str(k): str(v or "") for k, v in row.items()} for row in reader]
    if not fields:
        raise ValueError(f"CSV has no header: {path}")
    return fields, rows


def write_csv(path: Path, fields: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_list, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: str(row.get(field, "") or "") for field in field_list})


def nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def is_existing_dst_row(row: Mapping[str, Any]) -> bool:
    source = str(row.get("source", "") or "").strip().casefold()
    department = str(row.get("department", "") or "").strip().casefold()
    ministry = str(row.get("ministry", "") or "").strip().casefold()
    url = str(row.get("official_page_url", "") or "").strip().casefold()
    return (
        source == "dst"
        or "department of science and technology" in source
        or "department of science and technology" in department
        or "dst.gov.in" in url
        or (source in {"science & technology", "science and technology"} and "science" in ministry)
    )


def adapt_dst_row(source: Mapping[str, Any], target_fields: list[str]) -> dict[str, str]:
    entity_type = nonempty(source.get("entity_type"), "PROGRAMME").upper()
    scheme_type = "Scheme" if entity_type == "SCHEME" else "Programme"
    row = {field: "" for field in target_fields}

    values = {
        "master_id": source.get("master_id", ""),
        "normalized_scheme_id": source.get("master_id", ""),
        "scheme_name": source.get("scheme_name", ""),
        "canonical_name": source.get("scheme_name", ""),
        "short_name": source.get("official_abbreviation", ""),
        "source": "DST",
        "ministry": nonempty(source.get("ministry"), "Ministry of Science and Technology"),
        "department": nonempty(source.get("department"), "Department of Science and Technology (DST)"),
        "implementing_agency": nonempty(source.get("department"), "Department of Science and Technology (DST)"),
        "normalized_record_kind": "SCHEME_OR_PROGRAMME",
        "record_kind": "SCHEME_OR_PROGRAMME",
        "current_record_kind": "SCHEME_OR_PROGRAMME",
        "programme_status": nonempty(source.get("programme_status"), "SCHEME_INFORMATION_AVAILABLE"),
        "application_status": nonempty(source.get("application_status"), "REFERENCE"),
        "scheme_status": nonempty(source.get("application_status"), "REFERENCE"),
        "status_evidence": "Canonical identity locked from official DST source in SSIP v3.4.0.4; active calls are tracked separately.",
        "sector": "Science & Technology",
        "sectors": "Science & Technology",
        "scheme_type": scheme_type,
        "scheme_types": scheme_type,
        "catalogue_inclusion": "INCLUDED",
        "catalogue_section": "REFERENCE_SCHEMES",
        "current_decision": "APPROVED_FOR_DATABASE",
        "validation_decision": "APPROVED_FOR_DATABASE",
        "publication_status": "PUBLISHED_LIMITED_INFORMATION",
        "official_page_url": source.get("official_page_url", ""),
        "application_url": source.get("application_url", ""),
        "guideline_urls": source.get("guideline_url", ""),
        "guideline_url": source.get("guideline_url", ""),
        "opening_date": "",
        "closing_date": "",
        "funding_minimum": "",
        "funding_maximum": "",
        "currency": "INR",
        "objective": source.get("objective", ""),
        "objectives": source.get("objective", ""),
        "eligibility": source.get("eligibility", ""),
        "benefits": source.get("benefits", ""),
        "funding_summary": source.get("funding_summary", ""),
        "application_process": source.get("application_process", ""),
        "required_documents": source.get("required_documents", ""),
        "contact_details": source.get("contact_information", ""),
        "contact_information": source.get("contact_information", ""),
        "last_verified_date": source.get("last_verified_date", ""),
        "last_updated": source.get("last_verified_date", ""),
        "verification_status": source.get("verification_status", "IDENTITY_VERIFIED_ATTRIBUTES_PENDING"),
        "information_completeness": source.get("information_completeness", "0.00"),
        "field_evidence": json.dumps(
            {
                "identity_lock_version": source.get("identity_lock_version", "3.4.0.4"),
                "public_status": source.get("public_status", ""),
                "verification_status": source.get("verification_status", ""),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }

    for field in target_fields:
        if field in values:
            row[field] = str(values[field] or "")
    return row


def unique_by_master_id(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    positions: dict[str, int] = {}
    for row in rows:
        master_id = str(row.get("master_id", "") or "").strip()
        if master_id and master_id in positions:
            output[positions[master_id]] = row
        else:
            if master_id:
                positions[master_id] = len(output)
            output.append(row)
    return output


def patch_app_version(app_path: Path) -> dict[str, Any]:
    if not app_path.exists():
        return {"app_exists": False, "patched": False, "path": str(app_path)}
    original = app_path.read_text(encoding="utf-8")
    backup = app_path.with_name(f"{app_path.stem}_before_v3_4_0_4a_{datetime.now().strftime('%Y%m%d_%H%M%S')}{app_path.suffix}")
    shutil.copy2(app_path, backup)
    updated, count = re.subn(
        r'(?m)^(APP_VERSION\s*=\s*)["\'][^"\']+["\']',
        r'\1"3.4.0.4"',
        original,
        count=1,
    )
    if count == 0:
        return {"app_exists": True, "patched": False, "backup": str(backup), "reason": "APP_VERSION assignment not found", "path": str(app_path)}
    app_path.write_text(updated, encoding="utf-8")
    return {"app_exists": True, "patched": True, "backup": str(backup), "path": str(app_path)}


def integrate(root: Path, base_preview: Path, dst_publication: Path, merged_output: Path, app_path: Path) -> dict[str, Any]:
    base_path = root / base_preview
    dst_path = root / dst_publication
    merged_path = root / merged_output
    app_full_path = root / app_path

    fields, base_rows = read_csv(base_path)
    _, dst_rows = read_csv(dst_path)

    if len(dst_rows) != 23:
        raise ValueError(f"Expected exactly 23 DST publication rows, found {len(dst_rows)} in {dst_path}")
    dst_ids = [str(row.get("master_id", "") or "").strip() for row in dst_rows]
    if any(not item for item in dst_ids) or len(set(dst_ids)) != 23:
        raise ValueError("DST publication rows must contain 23 unique non-empty master_id values")

    removed_dst = [row for row in base_rows if is_existing_dst_row(row)]
    retained = [row for row in base_rows if not is_existing_dst_row(row)]
    adapted = [adapt_dst_row(row, fields) for row in dst_rows]
    merged_rows = unique_by_master_id(retained + adapted)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "backups" / "v3_4_0_4a_dashboard_integration"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"catalogue_preview_v3_3_2_before_dst_merge_{timestamp}.csv"
    shutil.copy2(base_path, backup_path)

    write_csv(merged_path, fields, merged_rows)
    # Existing dashboard configuration currently reads the v3.3.2 path.
    # Replace that file only after the versioned merged output is safely written.
    write_csv(base_path, fields, merged_rows)

    re_fields, reloaded = read_csv(base_path)
    if re_fields != fields:
        raise RuntimeError("Catalogue header changed during write")
    final_dst = [row for row in reloaded if is_existing_dst_row(row)]
    final_ids = {str(row.get("master_id", "") or "").strip() for row in final_dst}
    if len(final_dst) != 23 or final_ids != set(dst_ids):
        raise RuntimeError(f"Post-write DST validation failed: rows={len(final_dst)}, unique_ids={len(final_ids)}")

    app_patch = patch_app_version(app_full_path)
    summary = {
        "service_version": VERSION,
        "generated_at": utc_now(),
        "base_preview": str(base_path),
        "dst_publication": str(dst_path),
        "versioned_merged_output": str(merged_path),
        "backup": str(backup_path),
        "counts": {
            "base_rows_before": len(base_rows),
            "old_dst_rows_removed": len(removed_dst),
            "non_dst_rows_preserved": len(retained),
            "dst_rows_added": len(adapted),
            "merged_rows_after": len(merged_rows),
            "validated_dst_rows_after": len(final_dst),
        },
        "removed_dst_names": [row.get("scheme_name", "") for row in removed_dst],
        "dst_entity_types": dict(Counter(str(row.get("entity_type", "") or "") for row in dst_rows)),
        "app_patch": app_patch,
        "checks": {
            "exactly_23_dst_rows_loaded": len(dst_rows) == 23,
            "all_dst_ids_unique": len(set(dst_ids)) == 23,
            "old_dst_rows_replaced": len(final_dst) == 23,
            "non_dst_rows_preserved": len(retained) == len([row for row in reloaded if not is_existing_dst_row(row)]),
            "merged_file_written": merged_path.exists(),
            "active_preview_replaced": base_path.exists(),
        },
    }
    summary["integration_passed"] = all(summary["checks"].values())

    summary_path = root / "data" / "catalogue_preview" / "v3_4_0_4" / "dst_dashboard_integration_summary_v3_4_0_4a.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def self_test() -> dict[str, Any]:
    fields = [
        "master_id", "scheme_name", "source", "ministry", "department",
        "implementing_agency", "normalized_record_kind", "record_kind",
        "programme_status", "application_status", "status_evidence", "sector",
        "scheme_type", "catalogue_inclusion", "catalogue_section", "current_decision",
        "official_page_url", "application_url", "guideline_urls", "eligibility",
        "benefits", "application_process", "required_documents", "contact_details",
        "last_verified_date", "field_evidence",
    ]
    sample = {
        "master_id": "dst_test_1",
        "scheme_name": "Test DST Programme",
        "entity_type": "PROGRAMME",
        "ministry": "Ministry of Science and Technology",
        "department": "Department of Science and Technology",
        "programme_status": "SCHEME_INFORMATION_AVAILABLE",
        "application_status": "REFERENCE",
        "official_page_url": "https://dst.gov.in/test",
        "verification_status": "IDENTITY_VERIFIED_ATTRIBUTES_PENDING",
        "last_verified_date": "2026-07-10",
    }
    adapted = adapt_dst_row(sample, fields)
    checks = {
        "dst_detection_by_source": is_existing_dst_row({"source": "DST"}),
        "dst_detection_by_url": is_existing_dst_row({"official_page_url": "https://dst.gov.in/a"}),
        "non_dst_preserved": not is_existing_dst_row({"source": "BIRAC", "official_page_url": "https://birac.nic.in/x"}),
        "master_id_mapped": adapted["master_id"] == "dst_test_1",
        "record_kind_mapped": adapted["record_kind"] == "SCHEME_OR_PROGRAMME",
        "source_searchable_as_dst": adapted["source"] == "DST",
        "publication_included": adapted["catalogue_inclusion"] == "INCLUDED",
        "temporary_call_not_created": adapted["application_status"] == "REFERENCE",
    }
    return {"service_version": VERSION, "tests": checks, "self_test_passed": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge the 23 DST v3.4.0.4 canonical identities into the existing SSIP public dashboard catalogue.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--base-preview", default=str(DEFAULT_BASE_PREVIEW))
    parser.add_argument("--dst-publication", default=str(DEFAULT_DST_PUBLICATION))
    parser.add_argument("--merged-output", default=str(DEFAULT_MERGED_OUTPUT))
    parser.add_argument("--app", default=str(DEFAULT_APP))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        result = self_test()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["self_test_passed"] else 1

    try:
        result = integrate(
            Path(args.project_root).resolve(),
            Path(args.base_preview),
            Path(args.dst_publication),
            Path(args.merged_output),
            Path(args.app),
        )
    except Exception as exc:
        print(json.dumps({"service_version": VERSION, "integration_passed": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["integration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
