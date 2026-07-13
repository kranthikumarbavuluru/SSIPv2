# SSIP v3.4.0.6d — Complete Sector Repair Package

This complete drop-in package corrects the partial extraction that left the pytest file missing.

It includes:

- the active-catalogue repair agent;
- the dashboard source verifier;
- the controlled sector rules;
- the previously missing automated test;
- a preflight-enabled PowerShell runner.

## Install

Extract the ZIP directly into:

`D:\WebSite\DASHBOARD\Code\SSIP`

Allow Windows to merge folders and replace files.

## Run

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\RUN_SECTOR_REPAIR_v3_4_0_6b.ps1
```

The runner now checks every required file before starting and reports a clear extraction error if anything is absent.
