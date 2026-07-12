# SSIP Public Dashboard v2.9

The v2.9 public dashboard is an additive Streamlit application. It does not modify the SSIP production database and does not call LM Studio, Ollama, OpenAI, or any other LLM runtime.

## Catalogue Modes

`CATALOGUE_PREVIEW`

- Uses the v2.8.1 normalization catalogue joined with SQLite data.
- Intended for development while `public_schemes` is empty.
- Displays a visible Catalogue Preview indicator.

`PUBLISHED_ONLY`

- Uses only rows published through the publication workflow.
- Intended as the production mode after records are published.

Set the mode with:

```powershell
$env:SSIP_PUBLIC_CATALOGUE_MODE = "CATALOGUE_PREVIEW"
```

## Start

```powershell
.\scripts\run_public_dashboard_v2_9.ps1 -CatalogueMode CATALOGUE_PREVIEW -Port 8501
```

## Data Sources

- `database\ssip_staging_v1.db`
- `data\audit\v2_8_1_catalogue_normalization\catalogue_normalization_plan_v2_8_1.csv`

SQLite is opened with URI `mode=ro` and `PRAGMA query_only=ON`.

## Smart Match

Explainable Smart Match is deterministic. It scores records using only structured catalogue fields:

- applicant type
- eligibility
- sector
- startup stage
- geographic scope
- funding requirement
- application status

No model-generated or fake AI score is displayed.
