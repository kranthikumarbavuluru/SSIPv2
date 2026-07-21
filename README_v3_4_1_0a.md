# SSIP v3.4.1.0a Complete Extraction Hotfix

This package repairs incomplete extraction of the governed agent platform.

Extract the ZIP directly into:

`D:\WebSite\DASHBOARD\Code\SSIP`

Choose **Replace/Merge files**.

Then run:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\VERIFY_AGENT_INSTALL_v3_4_1_0a.ps1
.\RUN_AGENTS_NOW_v3_4_1_0.ps1
```

The runner now checks every required file before executing.
