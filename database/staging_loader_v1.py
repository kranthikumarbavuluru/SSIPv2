from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.organization_canonicalization_v3_4_3_7_4 import (
    canonical_payload_hash,
    canonicalize_organization_record,
)


LOADER_VERSION = "1.0.0"
ATTRIBUTE_GROUPS = (
    "scheme_type",
    "target_beneficiaries",
    "startup_stage",
    "sector",
    "states_or_uts",
    "objectives",
    "eligibility",
    "benefits",
    "application_process",
    "selection_process",
    "required_documents",
    "guideline_urls",
    "quality_flags",
)


@dataclass(frozen=True)
class LoaderPaths:
    approved_path: Path
    review_path: Path
    rejected_path: Path
    audit_path: Path
    database_path: Path
    schema_path: Path
    summary_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def record_hash(record: dict[str, Any]) -> str:
    validation = record.get("validation") or {}
    existing = validation.get("record_hash")
    if existing:
        return str(existing)
    return hashlib.sha256(stable_json(record).encode("utf-8")).hexdigest()


def load_json_list(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{label} must contain a JSON list: {path}")
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] must be a JSON object")
    return payload


def ensure_unique_master_ids(records: Iterable[dict[str, Any]], label: str) -> set[str]:
    seen: set[str] = set()
    for index, record in enumerate(records):
        master_id = str(record.get("master_id") or "").strip()
        if not master_id:
            raise ValueError(f"{label}[{index}] has no master_id")
        if master_id in seen:
            raise ValueError(f"Duplicate master_id in {label}: {master_id}")
        seen.add(master_id)
    return seen


def validate_input_sets(
    approved: list[dict[str, Any]],
    review: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> None:
    approved_ids = ensure_unique_master_ids(approved, "approved records")
    review_ids = ensure_unique_master_ids(review, "review queue")
    rejected_ids = ensure_unique_master_ids(rejected, "rejected records")

    overlap = (approved_ids & review_ids) | (approved_ids & rejected_ids) | (review_ids & rejected_ids)
    if overlap:
        raise ValueError(f"master_id appears in more than one input stream: {sorted(overlap)}")

    for record in approved:
        decision = ((record.get("validation") or {}).get("decision") or "").strip()
        if decision != "APPROVED_FOR_DATABASE":
            raise ValueError(
                f"Approved input contains non-approved record {record.get('master_id')}: {decision!r}"
            )

    for item in review:
        decision = str(item.get("decision") or "").strip()
        if decision not in {"NEEDS_ADMIN_REVIEW", "NEEDS_MORE_EVIDENCE"}:
            raise ValueError(
                f"Review input contains unsupported decision {item.get('master_id')}: {decision!r}"
            )


def open_database(database_path: Path, schema_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if not schema_path.exists():
        raise FileNotFoundError(f"Database schema not found: {schema_path}")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    return connection


def _funding_values(record: dict[str, Any]) -> tuple[Any, ...]:
    funding = record.get("funding_amount") or {}
    beneficiary = funding.get("beneficiary_support") or {}
    return (
        funding.get("minimum"),
        funding.get("maximum"),
        funding.get("currency"),
        beneficiary.get("minimum"),
        beneficiary.get("maximum"),
        funding.get("intermediary_support_maximum"),
        funding.get("scheme_corpus"),
    )


def upsert_approved_scheme(
    connection: sqlite3.Connection,
    record: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> dict[str, int]:
    record = canonicalize_organization_record(record)
    master_id = str(record["master_id"])
    validation = record.get("validation") or {}
    funding_values = _funding_values(record)
    raw_json = stable_json(record)
    rec_hash = canonical_payload_hash(record)

    connection.execute(
        """
        INSERT INTO scheme_staging (
            master_id, scheme_name, short_name, source, ministry, department,
            implementing_agency, record_kind, programme_status, application_status,
            scheme_status, geographic_scope, official_page_url, application_url,
            opening_date, closing_date, validation_score, validation_decision,
            publication_status, funding_minimum, funding_maximum, currency,
            beneficiary_support_minimum, beneficiary_support_maximum,
            intermediary_support_maximum, scheme_corpus, record_hash, raw_record_json,
            first_loaded_at, last_loaded_at, last_import_run_id
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            'STAGED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(master_id) DO UPDATE SET
            scheme_name=excluded.scheme_name,
            short_name=excluded.short_name,
            source=excluded.source,
            ministry=excluded.ministry,
            department=excluded.department,
            implementing_agency=excluded.implementing_agency,
            record_kind=excluded.record_kind,
            programme_status=excluded.programme_status,
            application_status=excluded.application_status,
            scheme_status=excluded.scheme_status,
            geographic_scope=excluded.geographic_scope,
            official_page_url=excluded.official_page_url,
            application_url=excluded.application_url,
            opening_date=excluded.opening_date,
            closing_date=excluded.closing_date,
            validation_score=excluded.validation_score,
            validation_decision=excluded.validation_decision,
            funding_minimum=excluded.funding_minimum,
            funding_maximum=excluded.funding_maximum,
            currency=excluded.currency,
            beneficiary_support_minimum=excluded.beneficiary_support_minimum,
            beneficiary_support_maximum=excluded.beneficiary_support_maximum,
            intermediary_support_maximum=excluded.intermediary_support_maximum,
            scheme_corpus=excluded.scheme_corpus,
            record_hash=excluded.record_hash,
            raw_record_json=excluded.raw_record_json,
            last_loaded_at=excluded.last_loaded_at,
            last_import_run_id=excluded.last_import_run_id
        """,
        (
            master_id,
            record.get("scheme_name") or "",
            record.get("short_name"),
            record.get("source"),
            record.get("ministry"),
            record.get("department"),
            record.get("implementing_agency"),
            record.get("record_kind"),
            record.get("programme_status"),
            record.get("application_status"),
            record.get("scheme_status"),
            record.get("geographic_scope"),
            record.get("official_page_url"),
            record.get("application_url"),
            record.get("opening_date"),
            record.get("closing_date"),
            validation.get("validation_score"),
            validation.get("decision") or "APPROVED_FOR_DATABASE",
            *funding_values,
            rec_hash,
            raw_json,
            loaded_at,
            loaded_at,
            run_id,
        ),
    )

    connection.execute("DELETE FROM scheme_attributes WHERE master_id = ?", (master_id,))
    attribute_count = 0
    for group in ATTRIBUTE_GROUPS:
        values = record.get(group) or []
        if not isinstance(values, list):
            values = [values]
        for sort_order, value in enumerate(values):
            if isinstance(value, (dict, list)):
                stored = stable_json(value)
            else:
                stored = str(value).strip()
            if not stored:
                continue
            connection.execute(
                """
                INSERT INTO scheme_attributes(master_id, attribute_group, sort_order, value)
                VALUES (?, ?, ?, ?)
                """,
                (master_id, group, sort_order, stored),
            )
            attribute_count += 1

    connection.execute("DELETE FROM scheme_contacts WHERE master_id = ?", (master_id,))
    contact_count = 0
    for sort_order, contact in enumerate(record.get("contact_details") or []):
        if not isinstance(contact, dict):
            continue
        value = str(contact.get("value") or "").strip()
        if not value:
            continue
        connection.execute(
            """
            INSERT INTO scheme_contacts(master_id, sort_order, contact_type, contact_value)
            VALUES (?, ?, ?, ?)
            """,
            (master_id, sort_order, contact.get("type"), value),
        )
        contact_count += 1

    connection.execute("DELETE FROM scheme_sources WHERE master_id = ?", (master_id,))
    source_count = 0
    for sort_order, source in enumerate(record.get("source_evidence") or []):
        if not isinstance(source, dict):
            continue
        source_url = str(source.get("url") or "").strip()
        if not source_url:
            continue
        connection.execute(
            """
            INSERT INTO scheme_sources(
                master_id, sort_order, source_url, title, content_kind,
                source_hash, fetched_at, rendered_with_browser, text_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                master_id,
                sort_order,
                source_url,
                source.get("title"),
                source.get("content_kind"),
                source.get("source_hash"),
                source.get("fetched_at"),
                1 if source.get("rendered_with_browser") else 0,
                source.get("text_length"),
            ),
        )
        source_count += 1

    return {
        "attributes": attribute_count,
        "contacts": contact_count,
        "sources": source_count,
    }


def review_priority(item: dict[str, Any]) -> str:
    explicit = str(item.get("priority") or "").strip().upper()
    if explicit in {"HIGH", "MEDIUM", "NORMAL"}:
        return explicit
    decision = str(item.get("decision") or "")
    application_status = str(item.get("application_status") or "")
    if application_status == "OPEN":
        return "HIGH"
    if decision == "NEEDS_MORE_EVIDENCE":
        return "MEDIUM"
    return "NORMAL"


def upsert_review_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    item = dict(item)
    validated_record = canonicalize_organization_record(
        item.get("validated_record") or {}
    )
    item["validated_record"] = validated_record
    rec_hash = canonical_payload_hash(validated_record or item)
    connection.execute(
        """
        INSERT INTO admin_review_queue (
            master_id, scheme_name, source, record_kind, programme_status,
            application_status, official_page_url, application_url, decision,
            validation_score, review_status, priority, decision_reasons_json,
            warnings_json, critical_flags_json, recommended_actions_json,
            validated_record_json, record_hash, first_queued_at, updated_at,
            last_import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(master_id) DO UPDATE SET
            scheme_name=excluded.scheme_name,
            source=excluded.source,
            record_kind=excluded.record_kind,
            programme_status=excluded.programme_status,
            application_status=excluded.application_status,
            official_page_url=excluded.official_page_url,
            application_url=excluded.application_url,
            decision=excluded.decision,
            validation_score=excluded.validation_score,
            priority=excluded.priority,
            decision_reasons_json=excluded.decision_reasons_json,
            warnings_json=excluded.warnings_json,
            critical_flags_json=excluded.critical_flags_json,
            recommended_actions_json=excluded.recommended_actions_json,
            validated_record_json=excluded.validated_record_json,
            record_hash=excluded.record_hash,
            updated_at=excluded.updated_at,
            last_import_run_id=excluded.last_import_run_id
        """,
        (
            item["master_id"],
            item.get("scheme_name") or "",
            item.get("source"),
            item.get("record_kind"),
            item.get("programme_status"),
            item.get("application_status"),
            item.get("official_page_url"),
            item.get("application_url"),
            item.get("decision"),
            item.get("validation_score"),
            review_priority(item),
            stable_json(item.get("decision_reasons") or []),
            stable_json(item.get("warnings") or []),
            stable_json(item.get("critical_flags") or []),
            stable_json(item.get("recommended_admin_actions") or []),
            stable_json(validated_record),
            rec_hash,
            loaded_at,
            loaded_at,
            run_id,
        ),
    )


def upsert_rejected_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    item = canonicalize_organization_record(item)
    validation = item.get("validation") or {}
    decision = item.get("decision") or validation.get("decision") or "REJECTED"
    reasons = item.get("rejection_reasons") or item.get("decision_reasons") or validation.get("decision_reasons") or []
    connection.execute(
        """
        INSERT INTO rejected_scheme_records (
            master_id, scheme_name, source, decision, validation_score,
            rejection_reasons_json, raw_record_json, record_hash,
            first_rejected_at, updated_at, last_import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(master_id) DO UPDATE SET
            scheme_name=excluded.scheme_name,
            source=excluded.source,
            decision=excluded.decision,
            validation_score=excluded.validation_score,
            rejection_reasons_json=excluded.rejection_reasons_json,
            raw_record_json=excluded.raw_record_json,
            record_hash=excluded.record_hash,
            updated_at=excluded.updated_at,
            last_import_run_id=excluded.last_import_run_id
        """,
        (
            item["master_id"],
            item.get("scheme_name"),
            item.get("source"),
            decision,
            item.get("validation_score") or validation.get("validation_score"),
            stable_json(reasons),
            stable_json(item),
            canonical_payload_hash(item),
            loaded_at,
            loaded_at,
            run_id,
        ),
    )


def upsert_audit_item(
    connection: sqlite3.Connection,
    item: dict[str, Any],
    run_id: str,
    loaded_at: str,
) -> None:
    validation = item.get("validation") or {}
    connection.execute(
        """
        INSERT INTO validation_audit (
            master_id, scheme_name, source, decision, validation_score,
            warnings_json, critical_flags_json, corrections_json,
            audit_record_json, record_hash, updated_at, last_import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(master_id) DO UPDATE SET
            scheme_name=excluded.scheme_name,
            source=excluded.source,
            decision=excluded.decision,
            validation_score=excluded.validation_score,
            warnings_json=excluded.warnings_json,
            critical_flags_json=excluded.critical_flags_json,
            corrections_json=excluded.corrections_json,
            audit_record_json=excluded.audit_record_json,
            record_hash=excluded.record_hash,
            updated_at=excluded.updated_at,
            last_import_run_id=excluded.last_import_run_id
        """,
        (
            item["master_id"],
            item.get("scheme_name"),
            item.get("source"),
            validation.get("decision"),
            validation.get("validation_score"),
            stable_json(validation.get("warnings") or []),
            stable_json(validation.get("critical_flags") or []),
            stable_json(validation.get("corrections") or []),
            stable_json(item),
            record_hash(item),
            loaded_at,
            run_id,
        ),
    )


def scalar(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = connection.execute(sql, params).fetchone()
    return int(row[0] if row and row[0] is not None else 0)


def load_to_staging(paths: LoaderPaths, dry_run: bool = False) -> dict[str, Any]:
    approved = load_json_list(paths.approved_path, "approved records")
    review = load_json_list(paths.review_path, "review queue")
    rejected = load_json_list(paths.rejected_path, "rejected records")
    audit = load_json_list(paths.audit_path, "validation audit")
    validate_input_sets(approved, review, rejected)
    ensure_unique_master_ids(audit, "validation audit")

    run_id = uuid.uuid4().hex
    started_at = utc_now()
    counters = {"attributes": 0, "contacts": 0, "sources": 0}

    connection = open_database(paths.database_path, paths.schema_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO import_runs(
                run_id, started_at, status, approved_input_count,
                review_input_count, rejected_input_count
            ) VALUES (?, ?, 'RUNNING', ?, ?, ?)
            """,
            (run_id, started_at, len(approved), len(review), len(rejected)),
        )

        for record in approved:
            inserted = upsert_approved_scheme(connection, record, run_id, started_at)
            for key in counters:
                counters[key] += inserted[key]

        for item in review:
            upsert_review_item(connection, item, run_id, started_at)

        for item in rejected:
            upsert_rejected_item(connection, item, run_id, started_at)

        for item in audit:
            upsert_audit_item(connection, item, run_id, started_at)

        summary = {
            "run_id": run_id,
            "loader_version": LOADER_VERSION,
            "dry_run": dry_run,
            "input_approved_count": len(approved),
            "input_review_count": len(review),
            "input_rejected_count": len(rejected),
            "input_audit_count": len(audit),
            "staged_scheme_count": scalar(connection, "SELECT COUNT(*) FROM scheme_staging"),
            "pending_review_count": scalar(
                connection,
                "SELECT COUNT(*) FROM admin_review_queue WHERE review_status = 'PENDING'",
            ),
            "review_queue_total_count": scalar(connection, "SELECT COUNT(*) FROM admin_review_queue"),
            "rejected_table_count": scalar(connection, "SELECT COUNT(*) FROM rejected_scheme_records"),
            "validation_audit_count": scalar(connection, "SELECT COUNT(*) FROM validation_audit"),
            "scheme_attribute_rows_written": counters["attributes"],
            "scheme_contact_rows_written": counters["contacts"],
            "scheme_source_rows_written": counters["sources"],
            "database_path": str(paths.database_path.resolve()),
            "generated_at": utc_now(),
        }

        connection.execute(
            """
            UPDATE import_runs
            SET completed_at = ?, status = 'COMPLETED', summary_json = ?
            WHERE run_id = ?
            """,
            (summary["generated_at"], stable_json(summary), run_id),
        )

        if dry_run:
            connection.rollback()
        else:
            connection.commit()
            paths.summary_path.parent.mkdir(parents=True, exist_ok=True)
            paths.summary_path.write_text(pretty_json(summary), encoding="utf-8")
        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parents[1]


def default_paths(project_root: Path | None = None) -> LoaderPaths:
    root = project_root or project_root_from_file()
    return LoaderPaths(
        approved_path=root / "data" / "validated_scheme_records_v1.json",
        review_path=root / "data" / "admin_review_queue_v1.json",
        rejected_path=root / "data" / "rejected_scheme_records_v1.json",
        audit_path=root / "data" / "validation_audit_v1.json",
        database_path=Path(os.environ.get("SSIP_DB_PATH", root / "database" / "ssip_staging_v1.db")),
        schema_path=root / "database" / "schema_staging_v1.sql",
        summary_path=root / "data" / "database_load_summary_v1.json",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load validated SSIP records into the staging database.")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate and execute in a rolled-back transaction.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    paths = default_paths(args.project_root)
    summary = load_to_staging(paths, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
