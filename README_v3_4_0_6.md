# SSIP v3.4.0.6 — Sector Verification Agent

This package fixes the catalogue-level sector gap. It does not hard-code all
records to the ministry's subject and does not treat support type (grant, loan,
incubation) as an industry sector.

## What the agent does

1. Loads the active catalogue CSV, defaulting to:

   `data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv`

   If that file is absent, it automatically selects the newest CSV under
   `data\catalogue_preview`.

2. Verifies every record using:
   - existing structured scheme data;
   - official page, application page and guideline URLs;
   - controlled keyword/evidence scoring;
   - optional LM Studio verification for ambiguous records.

3. Writes only values from a controlled sector taxonomy.

4. Uses explicit broad classifications when no narrow industry is supported:
   - `Cross-sector Innovation & Entrepreneurship`
   - `Cross-sector MSME & Startup Finance`
   - `Sector Agnostic / Multi-sector`

5. Adds these fields without changing scheme identity:
   - `sector`
   - `primary_sector`
   - `secondary_sectors`
   - `sector_confidence`
   - `sector_classification_method`
   - `sector_evidence`
   - `sector_review_required`
   - `sector_verified_at`
   - `sector_agent_version`

The `sector` CSV column uses semicolon-separated values because that is the list format already consumed by the SSIP dashboard.

6. Patches the dashboard sector normalizer so verified detailed sectors are not collapsed into broad legacy labels.

7. Creates backups before replacing the active catalogue or dashboard normalizer.

## Installation

Extract the ZIP into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

## One-command execution

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

powershell -ExecutionPolicy Bypass `
  -File .\RUN_SECTOR_VERIFICATION_v3_4_0_6.ps1
```

LM Studio is optional. When its local server is available, the agent uses it to
review ambiguous classifications. When it is unavailable, deterministic
classification continues and the run does not fail.

## Expected validation

The important output is:

```json
{
  "all_visible_main_records_have_sector": true,
  "all_sector_values_in_taxonomy": true,
  "no_support_type_used_as_sector": true,
  "validation_passed": true
}
```

The dashboard should no longer show `Sector Not Specified` for public scheme
records. Broad programmes such as NIDHI should appear as cross-sector rather
than being assigned a fabricated industry.

## Outputs

```text
data\sector_verification\v3_4_0_6\
├── catalogue_with_verified_sectors_v3_4_0_6.csv
├── sector_verification_audit_v3_4_0_6.csv
├── sector_manual_review_queue_v3_4_0_6.csv
├── sector_distribution_v3_4_0_6.csv
├── sector_taxonomy_v3_4_0_6.csv
├── sector_validation_v3_4_0_6.json
└── sector_summary_v3_4_0_6.json
```

Backups are stored under:

```text
backups\sector_verification_v3_4_0_6\
```

## Manual run options

Audit without updating the active catalogue:

```powershell
python .\scripts\sector_verification_agent_v3_4_0_6.py `
  --project-root . `
  --allow-network `
  --lm-studio auto `
  --progress
```

Apply only after validation:

```powershell
python .\scripts\sector_verification_agent_v3_4_0_6.py `
  --project-root . `
  --allow-network `
  --lm-studio auto `
  --apply `
  --progress
```
