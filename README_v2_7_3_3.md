# SSIP v2.7.3.3 — Foreign-Key-Aware Safe Loader

## Why v2.7.3.2a failed

The actual SSIP database contains one or more foreign keys in the existing
staging/import model. The previous loader generated `last_import_run_id` using
the new safe-load run ID, but that run may not exist in the older parent
`import_runs` table.

The database correctly rejected the insert and rolled back the transaction.

## v2.7.3.3 behavior

- Keeps `PRAGMA foreign_keys = ON`.
- Inspects and reports all relevant foreign keys.
- Checks parent rows before writing.
- For nullable loader-generated fields only:
  - `last_import_run_id`
  - `source_run_id`
- If the generated run does not exist in the legacy parent table:
  - New insert: stores `NULL`.
  - Existing update: preserves the existing value.
- Real business-field foreign-key violations remain fatal.
- Publication remains `STAGED` and `is_public = 0`.

## Install

Delete the previous executable loader:

```powershell
Remove-Item `
  .\scripts\load_approved_records_v2_7_3_2a.py `
  -Force `
  -ErrorAction SilentlyContinue
```

Extract this ZIP into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Use:

```text
scripts\load_approved_records_v2_7_3_3.py
```

## 1. Verify checksum

```powershell
(Get-FileHash `
  .\scripts\load_approved_records_v2_7_3_3.py `
  -Algorithm SHA256).Hash.ToLower()
```

Compare it with `SHA256SUMS.txt`.

## 2. Compile

```powershell
python -m py_compile `
  .\scripts\load_approved_records_v2_7_3_3.py
```

No output means success.

## 3. Self-test

```powershell
python .\scripts\load_approved_records_v2_7_3_3.py --self-test
```

Expected:

```text
"nullable_legacy_run_fk_safely_suppressed": true
"passed": true
```

## 4. Inspect schema and foreign keys

```powershell
python .\scripts\load_approved_records_v2_7_3_3.py `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --inspect-schema
```

The report includes:

```text
scheme_staging_foreign_keys
safe_load_record_audit_foreign_keys
database_load_runs_foreign_keys
```

## 5. Run the dry load

```powershell
python .\scripts\load_approved_records_v2_7_3_3.py `
  --input .\data\incremental\v2_7_2_1_strict_validation_hotfix\approved_for_database_v2_7_2_1.csv `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --dry-run `
  --initiated-by "Kranthi Kumar Bavuluru"
```

Required:

```text
"status": "DRY_RUN_ROLLED_BACK"
"failed_records": 0
"public_count_before": 0
"public_count_after": 0
```

The accepted record reason may include:

```text
NEW_APPROVED_RECORD_STAGED;LEGACY_RUN_FK_SUPPRESSED:last_import_run_id
```

This is expected and means the legacy FK was respected rather than disabled.

## 6. Inspect outputs

```powershell
Import-Csv `
  .\data\incremental\v2_7_3_safe_load\safe_load_audit_v2_7_3_3.csv |
Format-List
```

```powershell
Get-Content `
  .\data\incremental\v2_7_3_safe_load\safe_load_summary_v2_7_3_3.json
```

Do not commit until the dry run succeeds.
