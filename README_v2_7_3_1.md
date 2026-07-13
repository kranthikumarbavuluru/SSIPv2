# SSIP v2.7.3.1 — Safe Loader Schema Compatibility Hotfix

The v2.7.3 loader expected database columns named `canonical_name` and
`final_url`. Your existing `scheme_staging` table uses legacy names, so the
loader stopped safely before creating reports.

This hotfix resolves legacy column names automatically and does not rename or
delete existing columns.

## Install

Extract into:

```text
D:\WebSite\DASHBOARD\Code\SSIP\
```

This adds:

```text
scripts\load_approved_records_v2_7_3_1.py
tests\test_safe_loader_v2_7_3_1.py
```

## 1. Self-test

```powershell
python .\scripts\load_approved_records_v2_7_3_1.py --self-test
```

Expected:

```text
"passed": true
```

## 2. Inspect your real schema

```powershell
python .\scripts\load_approved_records_v2_7_3_1.py `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --inspect-schema
```

Expected:

```text
"database_ready": true
```

The output will show mappings such as:

```text
"canonical_name": "scheme_name"
"final_url": "official_url"
```

The exact legacy names depend on your database.

## 3. Dry run

```powershell
python .\scripts\load_approved_records_v2_7_3_1.py `
  --input .\data\incremental\v2_7_2_1_strict_validation_hotfix\approved_for_database_v2_7_2_1.csv `
  --database .\database\ssip_staging_v1.db `
  --output-dir .\data\incremental\v2_7_3_safe_load `
  --dry-run `
  --initiated-by "Kranthi Kumar Bavuluru"
```

Required results:

```text
"status": "DRY_RUN_ROLLED_BACK"
"failed_records": 0
"public_count_before": 0
"public_count_after": 0
```

## 4. Inspect outputs

```powershell
Import-Csv `
  .\data\incremental\v2_7_3_safe_load\safe_load_audit_v2_7_3_1.csv |
Format-List
```

```powershell
Get-Content `
  .\data\incremental\v2_7_3_safe_load\safe_load_summary_v2_7_3_1.json
```

The hotfix now writes failure and schema reports even if database compatibility
checks fail.

Do not commit until the dry run succeeds.
