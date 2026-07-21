# SSIP v3.4.0.4a — Existing Public Dashboard Integration

## Why the dashboard remained unchanged

The v3.4.0.4 builder created a separate DST publication CSV and preview database. The existing dashboard on port 8502 continued loading:

```text
data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv
apps/public_dashboard_app_v2_9.py
```

Therefore it continued showing the old 42-record catalogue and only two DST matches.

## What this hotfix does

- backs up the active v3.3.2 preview CSV;
- removes prior DST rows from that preview;
- merges the 23 canonical v3.4.0.4 DST identities;
- preserves all non-DST rows;
- writes a versioned merged copy under `data/catalogue_preview/v3_4_0_4/`;
- updates the dashboard footer version to `3.4.0.4`;
- stops the old process on port 8502;
- clears Streamlit cache and restarts the existing dashboard.

## Installation

Extract the ZIP directly into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

This ZIP has no wrapper folder; the files merge directly into the SSIP project root.

## Run

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

powershell -ExecutionPolicy Bypass `
  -File .\RUN_DST_DASHBOARD_INTEGRATION_v3_4_0_4a.ps1
```

## Expected console result

```text
DST rows: 23
Unique DST IDs: 23
```

The browser should show:

```text
SSIP Public Dashboard v3.4.0.4
```

Search for:

```text
dst
```

Expected search results: **23**.

The overall catalogue count should normally increase from 42 to approximately 63 because two old DST rows are replaced by 23 canonical DST rows. The exact headline count depends on the existing dashboard population rules.

## Verification only

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\VERIFY_DST_DASHBOARD_v3_4_0_4a.ps1
```
