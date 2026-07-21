# SSIP v2.7.3 — Step 1

## Files

Place the files in the existing SSIP project:

```text
D:\WebSite\DASHBOARD\Code\SSIP\
├── scripts\
│   └── migrate_publication_control_v2_7_3.py
└── tests\
    └── test_publication_migration_v2_7_3.py
```

## 1. Run the isolated self-test

```powershell
python .\scripts\migrate_publication_control_v2_7_3.py --self-test
```

Alternative test launcher:

```powershell
python .\tests\test_publication_migration_v2_7_3.py
```

Expected final value:

```text
"passed": true
```

## 2. Run a dry migration against the real staging database

```powershell
python .\scripts\migrate_publication_control_v2_7_3.py `
  --database .\database\ssip_staging_v1.db `
  --dry-run `
  --summary-output .\data\incremental\v2_7_3_safe_load\migration_dry_run_summary_v2_7_3.json
```

The dry run verifies the migration and then rolls back all changes.

## 3. Apply the migration

```powershell
python .\scripts\migrate_publication_control_v2_7_3.py `
  --database .\database\ssip_staging_v1.db `
  --apply `
  --applied-by "Kranthi Kumar Bavuluru" `
  --summary-output .\data\incremental\v2_7_3_safe_load\migration_apply_summary_v2_7_3.json
```

A consistent SQLite backup is automatically written under:

```text
database\backups\
```

## 4. Verify the publication boundary

```powershell
python -c "import sqlite3; db=r'database\ssip_staging_v1.db'; con=sqlite3.connect(db); c=con.cursor(); print('Publication states:',c.execute('SELECT publication_status,is_public,COUNT(*) FROM scheme_staging GROUP BY publication_status,is_public').fetchall()); print('Public schemes:',c.execute('SELECT COUNT(*) FROM public_schemes').fetchone()[0]); print('Migration:',c.execute(\"SELECT migration_version,applied_at,applied_by FROM schema_migrations WHERE migration_version='2.7.3'\").fetchone()); con.close()"
```

Expected safety condition after migration:

```text
Public schemes: 0
```

Existing records should normally appear as:

```text
('STAGED', 0, <count>)
```

## Safety behavior

The migration stops and rolls back when:

- `scheme_staging` does not exist.
- `master_id` is missing.
- Any existing record has a blank `master_id`.
- Duplicate `master_id` values exist.
- Post-migration verification fails.

The database also rejects:

- `is_public = 1` for a non-published record.
- `publication_status = 'PUBLISHED'` with `is_public = 0`.
- Publishing without `published_at` and `published_by`.
- Duplicate `master_id` insertion.
