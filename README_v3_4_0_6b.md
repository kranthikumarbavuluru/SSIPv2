# SSIP v3.4.0.6b — Active Catalogue Sector Repair

This is a corrective replacement for v3.4.0.6. It targets the exact CSV read by the public dashboard:

`data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv`

It does not auto-detect another CSV. It verifies every visible record and refuses to update the active catalogue unless:

- row count and ID order are preserved;
- every visible record has a controlled primary sector;
- `Sector Not Specified` count is zero;
- every sector belongs to the controlled taxonomy.

When no defensible industry restriction exists, the record is classified explicitly as one of:

- Cross-sector Innovation & Entrepreneurship
- Cross-sector MSME & Startup Finance
- Sector Agnostic / Multi-sector

This is preferable to leaving the record blank or inventing a narrow industry.

## Run

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\RUN_SECTOR_REPAIR_v3_4_0_6b.ps1
```

## Outputs

`data/sector_verification/v3_4_0_6b/`

- `sector_scheme_mapping_v3_4_0_6b.csv`
- `sector_manual_review_queue_v3_4_0_6b.csv`
- `sector_distribution_v3_4_0_6b.csv`
- `sector_validation_v3_4_0_6b.json`
- `sector_summary_v3_4_0_6b.json`

A timestamped backup is created before the active catalogue is replaced.
