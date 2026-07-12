from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .common import sha256_text, utc_now


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS programme_master (
    master_id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    parent_master_id TEXT,
    public_classification TEXT NOT NULL,
    sector_scope TEXT NOT NULL CHECK(sector_scope IN ('AGNOSTIC','SPECIFIC','MULTI_SECTOR','UNKNOWN')),
    primary_sector TEXT,
    secondary_sectors TEXT,
    official_master_url TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    review_status TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    FOREIGN KEY(parent_master_id) REFERENCES programme_master(master_id)
);
CREATE TABLE IF NOT EXISTS call_instance (
    call_id TEXT PRIMARY KEY,
    call_title TEXT NOT NULL,
    parent_master_id TEXT,
    parent_resolution TEXT NOT NULL,
    opening_date TEXT,
    closing_date TEXT,
    application_status TEXT NOT NULL,
    startup_relevance TEXT NOT NULL,
    sector_scope TEXT NOT NULL,
    primary_sector TEXT,
    secondary_sectors TEXT,
    detail_url TEXT,
    attachment_url TEXT,
    source_container_url TEXT NOT NULL,
    source_fetched_at TEXT,
    raw_json TEXT NOT NULL,
    call_type TEXT NOT NULL DEFAULT 'OPPORTUNITY_NOTICE',
    applicant_layer TEXT NOT NULL DEFAULT 'UNKNOWN',
    applicant_layer_reason TEXT,
    implementing_entity TEXT,
    implementation_role TEXT,
    status_basis TEXT,
    status_evidence TEXT,
    last_verified_at TEXT,
    startup_stage TEXT,
    guideline_url TEXT,
    FOREIGN KEY(parent_master_id) REFERENCES programme_master(master_id)
);
CREATE TABLE IF NOT EXISTS field_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS curation_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    proposed_action TEXT NOT NULL,
    priority TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, proposed_action)
);
CREATE TABLE IF NOT EXISTS pilot_run (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
"""


class EvidenceRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(call_instance)")}
        for name, definition in (
            ("call_type", "TEXT NOT NULL DEFAULT 'OPPORTUNITY_NOTICE'"),
            ("applicant_layer", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
            ("applicant_layer_reason", "TEXT"),
            ("implementing_entity", "TEXT"),
            ("implementation_role", "TEXT"),
            ("status_basis", "TEXT"),
            ("status_evidence", "TEXT"),
            ("last_verified_at", "TEXT"),
            ("startup_stage", "TEXT"),
            ("guideline_url", "TEXT"),
        ):
            if name not in columns:
                self.connection.execute(f"ALTER TABLE call_instance ADD COLUMN {name} {definition}")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def replace_programmes(self, programmes: Iterable[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM call_instance")
        self.connection.execute("DELETE FROM programme_master")
        rows = list(programmes)
        pending = {str(row["master_id"]): row for row in rows}
        while pending:
            progressed = False
            for master_id, row in list(pending.items()):
                parent = str(row.get("parent_master_id", ""))
                if parent and parent in pending:
                    continue
                self.connection.execute(
                    "INSERT INTO programme_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        master_id, row["code"], row["canonical_name"], row["entity_type"], parent or None,
                        row["public_classification"], row["sector_scope"], row.get("primary_sector", ""),
                        "; ".join(row.get("secondary_sectors", [])), row["official_master_url"],
                        row["evidence_text"], row.get("review_status", "CURATED_BASELINE"),
                        json.dumps(row, ensure_ascii=False, sort_keys=True),
                    ),
                )
                del pending[master_id]
                progressed = True
            if not progressed:
                raise ValueError("Programme hierarchy contains a cycle or missing parent ordering.")
        self.connection.commit()

    def replace_calls(self, calls: Iterable[dict[str, str]]) -> None:
        self.connection.execute("DELETE FROM call_instance")
        for row in calls:
            self.connection.execute(
                """INSERT INTO call_instance(
                    call_id,call_title,parent_master_id,parent_resolution,opening_date,closing_date,
                    application_status,startup_relevance,sector_scope,primary_sector,secondary_sectors,
                    detail_url,attachment_url,source_container_url,source_fetched_at,raw_json,
                    call_type,applicant_layer,applicant_layer_reason,implementing_entity,
                    implementation_role,status_basis,status_evidence,last_verified_at,startup_stage,guideline_url
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["call_id"], row["call_title"], row.get("parent_master_id") or None,
                    row["parent_resolution"], row.get("opening_date", ""), row.get("closing_date", ""),
                    row["application_status"], row["startup_relevance"], row["sector_scope"],
                    row.get("primary_sector", ""), row.get("secondary_sectors", ""), row.get("detail_url", ""),
                    row.get("attachment_url", ""), row["source_container_url"], row.get("source_fetched_at", ""),
                    json.dumps(row, ensure_ascii=False, sort_keys=True),
                    row.get("call_type", "OPPORTUNITY_NOTICE"), row.get("applicant_layer", "UNKNOWN"),
                    row.get("applicant_layer_reason", ""),
                    row.get("implementing_entity", ""), row.get("implementation_role", ""),
                    row.get("status_basis", ""), row.get("status_evidence", ""),
                    row.get("last_verified_at", ""), row.get("startup_stage", ""),
                    row.get("guideline_url", ""),
                ),
            )
        self.connection.commit()

    def replace_evidence(self, evidence: Iterable[dict[str, str]]) -> None:
        self.connection.execute("DELETE FROM field_evidence")
        now = utc_now()
        for row in evidence:
            text = str(row.get("evidence_text", ""))
            if not text:
                continue
            self.connection.execute(
                "INSERT INTO field_evidence(entity_type,entity_id,field_name,source_url,evidence_text,evidence_sha256,observed_at) VALUES (?,?,?,?,?,?,?)",
                (row["entity_type"], row["entity_id"], row["field_name"], row["source_url"], text, sha256_text(text), now),
            )
        self.connection.commit()

    def replace_queue(self, items: Iterable[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM curation_queue")
        now = utc_now()
        for item in items:
            self.connection.execute(
                "INSERT INTO curation_queue(entity_type,entity_id,proposed_action,priority,reasons_json,created_at) VALUES (?,?,?,?,?,?)",
                (item["entity_type"], item["entity_id"], item["proposed_action"], item["priority"], json.dumps(item["reasons"], ensure_ascii=False), now),
            )
        self.connection.commit()

    def record_run(self, run_id: str, summary: dict[str, Any]) -> None:
        self.connection.execute("INSERT OR REPLACE INTO pilot_run VALUES (?,?,?)", (run_id, utc_now(), json.dumps(summary, ensure_ascii=False, sort_keys=True)))
        self.connection.commit()
