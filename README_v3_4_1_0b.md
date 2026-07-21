# SSIP v3.4.1.0b — PowerShell Logging Hotfix

## Problem fixed

Windows PowerShell 5.1 treated Python logging written to stderr as a
`NativeCommandError` because the runner used:

`$ErrorActionPreference = "Stop"`

The agent process had already started correctly and detected LM Studio.

## Changes

- `agents/common.py` now sends console logging to stdout.
- `RUN_AGENTS_NOW_v3_4_1_0.ps1` temporarily allows native stderr for each
  Python process and validates the real process exit code.
- Real Python failures still stop the run.
- Normal INFO/WARNING log lines no longer terminate the runner.

## Install

Extract directly into the SSIP root and replace both files.

Then run:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\RUN_AGENTS_NOW_v3_4_1_0.ps1
```
