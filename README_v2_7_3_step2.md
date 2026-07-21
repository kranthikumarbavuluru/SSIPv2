# SSIP v2.7.3 — Step 2: Safe Approved-Record Loader

## Install

Extract this package into:

```text
D:\WebSite\DASHBOARD\Code\SSIP\
```

Result:

```text
SSIP
├── scripts
│   └── load_approved_records_v2_7_3.py
└── tests
    └── test_safe_loader_v2_7_3.py
```

## 1. Self-test

```powershell
python .\scripts\load_approved_records_v2_7_3.py --self-test
```

Expected:

```text
"passed": true
```

## 2. Dry-run the v2.7.2.1 approved record

```powershell
python .\scripts\load_approved_records_v2_7_3.py `
  --input .\data\incremental\v2_7_2_1_strict_validation_hotfix\approved_for_database_v2_7_2_1.csv `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --dry-run `
  --initiated-by "Kranthi Kumar Bavuluru"
```

Expected safety conditions:

```text
"status": "DRY_RUN_ROLLED_BACK"
"failed_records": 0
"public_count_before": 0
"public_count_after": 0
```

For the new DST record, the likely dry-run result is:

```text
"inserted_records": 1
```

If that master_id is already present, the result may instead be an update or a no-change skip.

## 3. Inspect dry-run reports

```powershell
Import-Csv .\data\incremental\v2_7_3_safe_load\safe_load_audit_v2_7_3.csv |
Format-List
```

```powershell
Get-Content .\data\incremental\v2_7_3_safe_load\safe_load_summary_v2_7_3.json
```

## 4. Commit only after dry-run passes

```powershell
python .\scripts\load_approved_records_v2_7_3.py `
  --input .\data\incremental\v2_7_2_1_strict_validation_hotfix\approved_for_database_v2_7_2_1.csv `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --commit `
  --initiated-by "Kranthi Kumar Bavuluru"
```

Every newly inserted record is forced to:

```text
publication_status = STAGED
is_public = 0
record_version = 1
```

## 5. Verify database state

```powershell
python -c "import sqlite3; db=r'database\ssip_staging_v1.db'; con=sqlite3.connect(db); c=con.cursor(); print('Publication states:',c.execute('SELECT publication_status,is_public,COUNT(*) FROM scheme_staging GROUP BY publication_status,is_public').fetchall()); print('Public schemes:',c.execute('SELECT COUNT(*) FROM public_schemes').fetchone()[0]); print('Recent loads:',c.execute('SELECT run_id,status,total_records,inserted_records,updated_records,skipped_records,failed_records FROM database_load_runs ORDER BY started_at DESC LIMIT 3').fetchall()); con.close()"
```

Expected after one new record is committed:

```text
Publication states: [('STAGED', 0, 10)]
Public schemes: 0
```

The exact staged count depends on whether the approved master_id already exists.

## Idempotency test

Run the same `--commit` command again. Expected:

```text
inserted_records = 0
updated_records = 0
skipped_records = 1
unchanged_records = 1
```

## Important behavior

- A bad input row stops the complete load before the database transaction.
- A database error rolls back the complete load.
- Publication status is never copied from CSV.
- New records never become public.
- Existing published records are skipped by default.
- Unknown CSV columns are retained in the audit payload but are written to `scheme_staging` only when a matching database column exists.
