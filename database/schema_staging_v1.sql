PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    approved_input_count INTEGER NOT NULL DEFAULT 0,
    review_input_count INTEGER NOT NULL DEFAULT 0,
    rejected_input_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS scheme_staging (
    master_id TEXT PRIMARY KEY,
    scheme_name TEXT NOT NULL,
    short_name TEXT,
    source TEXT,
    ministry TEXT,
    department TEXT,
    implementing_agency TEXT,
    record_kind TEXT,
    programme_status TEXT,
    application_status TEXT,
    scheme_status TEXT,
    geographic_scope TEXT,
    official_page_url TEXT,
    application_url TEXT,
    opening_date TEXT,
    closing_date TEXT,
    validation_score REAL,
    validation_decision TEXT NOT NULL,
    publication_status TEXT NOT NULL DEFAULT 'STAGED',
    funding_minimum INTEGER,
    funding_maximum INTEGER,
    currency TEXT,
    beneficiary_support_minimum INTEGER,
    beneficiary_support_maximum INTEGER,
    intermediary_support_maximum INTEGER,
    scheme_corpus INTEGER,
    record_hash TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    first_loaded_at TEXT NOT NULL,
    last_loaded_at TEXT NOT NULL,
    last_import_run_id TEXT,
    FOREIGN KEY(last_import_run_id) REFERENCES import_runs(run_id)
);

CREATE TABLE IF NOT EXISTS scheme_attributes (
    master_id TEXT NOT NULL,
    attribute_group TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(master_id, attribute_group, sort_order),
    FOREIGN KEY(master_id) REFERENCES scheme_staging(master_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scheme_attributes_group_value
    ON scheme_attributes(attribute_group, value);

CREATE TABLE IF NOT EXISTS scheme_contacts (
    master_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    contact_type TEXT,
    contact_value TEXT NOT NULL,
    PRIMARY KEY(master_id, sort_order),
    FOREIGN KEY(master_id) REFERENCES scheme_staging(master_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scheme_sources (
    master_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT,
    content_kind TEXT,
    source_hash TEXT,
    fetched_at TEXT,
    rendered_with_browser INTEGER NOT NULL DEFAULT 0,
    text_length INTEGER,
    PRIMARY KEY(master_id, sort_order),
    FOREIGN KEY(master_id) REFERENCES scheme_staging(master_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_review_queue (
    master_id TEXT PRIMARY KEY,
    scheme_name TEXT NOT NULL,
    source TEXT,
    record_kind TEXT,
    programme_status TEXT,
    application_status TEXT,
    official_page_url TEXT,
    application_url TEXT,
    decision TEXT NOT NULL,
    validation_score REAL,
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    priority TEXT NOT NULL,
    decision_reasons_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    critical_flags_json TEXT NOT NULL,
    recommended_actions_json TEXT NOT NULL,
    validated_record_json TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    first_queued_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_import_run_id TEXT,
    FOREIGN KEY(last_import_run_id) REFERENCES import_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_review_status_priority
    ON admin_review_queue(review_status, priority, validation_score);

CREATE TABLE IF NOT EXISTS rejected_scheme_records (
    master_id TEXT PRIMARY KEY,
    scheme_name TEXT,
    source TEXT,
    decision TEXT,
    validation_score REAL,
    rejection_reasons_json TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    first_rejected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_import_run_id TEXT,
    FOREIGN KEY(last_import_run_id) REFERENCES import_runs(run_id)
);

CREATE TABLE IF NOT EXISTS validation_audit (
    master_id TEXT PRIMARY KEY,
    scheme_name TEXT,
    source TEXT,
    decision TEXT,
    validation_score REAL,
    warnings_json TEXT NOT NULL,
    critical_flags_json TEXT NOT NULL,
    corrections_json TEXT NOT NULL,
    audit_record_json TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_import_run_id TEXT,
    FOREIGN KEY(last_import_run_id) REFERENCES import_runs(run_id)
);
