# SSIP v2.7.3.4 — Publication Control Service

## Current database state before this step

After the v2.7.3.3a safe load:

```text
scheme_staging: 10 records expected
new DST record: STAGED, is_public=0
public_schemes: 0
```

## Install

Extract into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

## 1. Verify the committed safe load

```powershell
python -c "import sqlite3; db=r'database\ssip_staging_v1.db'; con=sqlite3.connect(db); con.row_factory=sqlite3.Row; c=con.cursor(); print('Scheme count:',c.execute('SELECT COUNT(*) FROM scheme_staging').fetchone()[0]); print('States:',c.execute('SELECT publication_status,is_public,COUNT(*) FROM scheme_staging GROUP BY publication_status,is_public').fetchall()); print('Public:',c.execute('SELECT COUNT(*) FROM public_schemes').fetchone()[0]); r=c.execute(\"SELECT master_id,scheme_name,official_page_url,application_url,validation_decision,publication_status,is_public,record_version,last_import_run_id FROM scheme_staging WHERE master_id='23290a8aab541138ab07'\").fetchone(); print(dict(r) if r else None); con.close()"
```

Expected:

```text
Scheme count: 10
STAGED + is_public=0: 10
Public: 0
last_import_run_id: None
```

## 2. Self-test

```powershell
python .\scripts\publication_control_service_v2_7_3_4.py --self-test
```

Expected:

```text
"passed": true
```

## 3. View publication status

```powershell
python .\scripts\publication_control_service_v2_7_3_4.py status `
  --database .\database\ssip_staging_v1.db `
  --master-id 23290a8aab541138ab07
```

## 4. Mark the DST scheme ready — dry run

```powershell
python .\scripts\publication_control_service_v2_7_3_4.py mark-ready `
  --database .\database\ssip_staging_v1.db `
  --master-id 23290a8aab541138ab07 `
  --expected-status STAGED `
  --reason "Validated official scheme and application URLs; ready for publication review." `
  --action-by "Kranthi Kumar Bavuluru" `
  --dry-run
```

Required:

```text
new_publication_status: READY_FOR_PUBLICATION
new_is_public: 0
public_count_before: 0
public_count_after: 0
status: DRY_RUN_ROLLED_BACK
```

## 5. Commit readiness

Run the same command with `--commit`.

## 6. Preview publication quality gate

After readiness is committed:

```powershell
python .\scripts\publication_control_service_v2_7_3_4.py status `
  --database .\database\ssip_staging_v1.db `
  --master-id 23290a8aab541138ab07
```

The `quality_gate_preview` must show:

```text
passed: true
```

## 7. Publish — always dry-run first

```powershell
python .\scripts\publication_control_service_v2_7_3_4.py publish `
  --database .\database\ssip_staging_v1.db `
  --master-id 23290a8aab541138ab07 `
  --expected-status READY_FOR_PUBLICATION `
  --reason "Approved for display in the SSIP public schemes portal." `
  --action-by "Kranthi Kumar Bavuluru" `
  --dry-run
```

A publish dry run should temporarily show:

```text
new_publication_status: PUBLISHED
new_is_public: 1
public_count_before: 0
public_count_after: 1
status: DRY_RUN_ROLLED_BACK
```

Do not commit publication until the public portal query layer is ready.
