# SSIP v3.4.0.1.1 — DST Snapshot Text Recovery Hotfix

## Purpose

Repair the empty-text export produced by v3.4.0.1 by reading the existing compressed HTML snapshots. This tool does not access the network and does not recrawl DST.

## Safeguards

- No canonical scheme identity is created.
- No call title is promoted to a scheme name.
- Original v3.4.0.1 CSV files, snapshots and SQLite state are not modified.
- Enriched files are written to `data/departments/dst/v3_4_0_1_1`.

## Install

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
python -m pip install -r .\requirements-v3_4_0_1_1.txt
```

## Compile and self-test

```powershell
python -m py_compile `
  .\scripts\dst_snapshot_text_recovery_v3_4_0_1_1.py

python `
  .\scripts\dst_snapshot_text_recovery_v3_4_0_1_1.py `
  --self-test
```

## Dry run

```powershell
python `
  .\scripts\dst_snapshot_text_recovery_v3_4_0_1_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --dry-run
```

## Production run

```powershell
python `
  .\scripts\dst_snapshot_text_recovery_v3_4_0_1_1.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --minimum-success-rate 0.98 `
  --strict
```

## Outputs

The output directory is:

```text
data\departments\dst\v3_4_0_1_1\
```

It contains enriched pages, document metadata, external-link metadata, domain summaries, call-pattern audit, extraction failures, validation JSON and a hotfix summary.

## Approval gate

Proceed to v3.4.0.2 only when:

```json
"schema_validation_passed": true,
"ready_for_v3_4_0_2": true
```
