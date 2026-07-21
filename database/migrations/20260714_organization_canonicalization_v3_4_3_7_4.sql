CREATE TABLE IF NOT EXISTS organization_canonicalization_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    master_id TEXT NOT NULL,
    scheme_name TEXT,
    old_ministry TEXT,
    new_ministry TEXT,
    old_department TEXT,
    new_department TEXT,
    old_hash TEXT NOT NULL,
    new_hash TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    version TEXT NOT NULL,
    UNIQUE(run_id, table_name, master_id)
);

CREATE INDEX IF NOT EXISTS idx_org_canonicalization_master
    ON organization_canonicalization_audit(master_id, applied_at DESC);
