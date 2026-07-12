-- SSIP DST historical archive v1
-- IMPORTANT: This migration is intentionally NOT applied automatically.
-- Review and approve it before execution against database/ssip_staging_v1.db.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS historical_archive_batches (
    batch_id TEXT PRIMARY KEY,
    department_code TEXT NOT NULL,
    service_version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    manifest_signature TEXT NOT NULL UNIQUE,
    normalized_count INTEGER NOT NULL,
    qualified_count INTEGER NOT NULL,
    current_excluded_count INTEGER NOT NULL,
    exception_count INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'PREVIEW'
        CHECK (approval_status IN ('PREVIEW','SAMPLE_REVIEWED','APPROVED','REJECTED')),
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_call_archive (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL REFERENCES historical_archive_batches(batch_id),
    call_id TEXT NOT NULL,
    department_code TEXT NOT NULL,
    call_title TEXT NOT NULL,
    closing_date TEXT NOT NULL,
    closing_year INTEGER NOT NULL,
    archive_state TEXT NOT NULL,
    relevance_group TEXT NOT NULL,
    applicant_layer TEXT,
    parent_master_id TEXT,
    primary_sector TEXT,
    secondary_sectors TEXT,
    detail_url TEXT NOT NULL,
    evidence_snapshot_path TEXT,
    evidence_hash TEXT,
    last_verified_at TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    record_payload_json TEXT NOT NULL,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(batch_id, call_id)
);

CREATE INDEX IF NOT EXISTS idx_historical_call_archive_year
    ON historical_call_archive(department_code, closing_year);
CREATE INDEX IF NOT EXISTS idx_historical_call_archive_relevance
    ON historical_call_archive(department_code, relevance_group);
CREATE INDEX IF NOT EXISTS idx_historical_call_archive_public
    ON historical_call_archive(is_public, department_code);

CREATE TABLE IF NOT EXISTS historical_archive_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL REFERENCES historical_archive_batches(batch_id),
    action TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    action_by TEXT NOT NULL,
    action_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    manifest_signature TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIEW IF NOT EXISTS public_historical_calls AS
SELECT h.*
FROM historical_call_archive h
JOIN historical_archive_batches b ON b.batch_id = h.batch_id
WHERE h.is_public = 1
  AND b.approval_status = 'APPROVED';

