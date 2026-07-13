# SSIP Emergency Catalogue Restore

This package restores the active catalogue from the newest larger backup created
before the governance filter reduced it to a small number of rows.

## Run

Extract this ZIP directly into:

`D:\WebSite\DASHBOARD\Code\SSIP`

Then run:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\RESTORE_PRE_GOVERNANCE_CATALOGUE.ps1
```

The script:

- preserves the current filtered catalogue;
- locates the backup associated with the governance run;
- falls back to other catalogue backups when necessary;
- restores only a backup with more rows than the active catalogue;
- verifies the restored row count;
- disables SSIP nightly tasks when permissions allow;
- clears Streamlit cache and restarts the dashboard.
