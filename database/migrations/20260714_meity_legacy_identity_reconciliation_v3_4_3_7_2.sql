CREATE TABLE IF NOT EXISTS identity_reconciliations (
    reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_master_id TEXT NOT NULL,
    canonical_master_id TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    legacy_table TEXT NOT NULL,
    legacy_status TEXT NOT NULL,
    official_page_url TEXT NOT NULL,
    reconciliation_reason TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    legacy_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    import_run_id TEXT,
    UNIQUE(legacy_master_id, canonical_master_id),
    FOREIGN KEY(canonical_master_id) REFERENCES admin_review_queue(master_id),
    FOREIGN KEY(import_run_id) REFERENCES import_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_identity_reconciliations_canonical
    ON identity_reconciliations(canonical_master_id);

CREATE INDEX IF NOT EXISTS idx_identity_reconciliations_legacy
    ON identity_reconciliations(legacy_master_id);
