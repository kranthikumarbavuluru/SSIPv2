# Startup Scheme Intelligence Platform (SSIP)

SSIP discovers, verifies, curates and publishes official government schemes,
programmes, grants, funds, challenges and application calls relevant to Indian
startups, innovators, researchers, MSMEs and ecosystem institutions.

The platform prioritises Central Government sources and the Government of Andhra
Pradesh, then expands to other states and union territories. DST is the first
department reference implementation; it is not the project boundary.

## Core principles

- Keep durable schemes/programmes separate from time-bound calls.
- Publish only from official evidence and governed admin approval.
- Keep closed and historical calls searchable without active Apply actions.
- Identify direct applicants separately from incubators and intermediaries.
- Never invent status, dates, sectors, eligibility or funding.
- Keep the public dashboard read-only against operational data.

Read [CODEX.md](CODEX.md) for the complete project objective and architecture.

## Applications

Public dashboard:

```powershell
python -m pip install -r .\requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\run_public_dashboard_v2_9.ps1 -CatalogueMode CATALOGUE_PREVIEW -Port 8502
```

Admin review workspace, after creating or supplying a local staging database:

```powershell
python -m streamlit run .\ui\admin_review_app_v1.py --server.port 8505
```

Admin entry page:

```text
http://localhost:8506/?page=admin/login
```

The query route is the reliable local Streamlit entry point. A reverse proxy
may expose the same page as `/admin/login` when it forwards the Streamlit
session and websocket correctly.

Provide the secret outside the repository before starting the dashboard and
review workspace. A plaintext value is supported for local development; a
PBKDF2-SHA256 value can be supplied through `SSIP_ADMIN_PASSWORD_HASH` for
deployment. Do not commit either value:

```powershell
$env:SSIP_ADMIN_PASSWORD = "replace-with-your-secret"
```

The public page links to the separate review workspace on port 8505, which
uses the same login gate. Set `SSIP_ADMIN_WORKSPACE_URL` when that workspace
is hosted elsewhere.

Operational databases are intentionally excluded from Git. In catalogue-preview
mode the public dashboard can load the governed preview CSV without a database.

## Main structure

| Path | Purpose |
|---|---|
| `apps/` | Public dashboard entry point |
| `ui/` | Admin verification workspace |
| `ssip_dashboard/` | Dashboard data access and business logic |
| `ssip_agents/` and `agents/` | Department and governance agents |
| `services/` | Review, publication and archive services |
| `config/` | Source registries, taxonomies and governance rules |
| `database/migrations/` | Explicitly approved schema migrations |
| `data/departments/dst/pilot_v1/` | Curated DST reference fixtures |
| `tests/` | Regression and workflow tests |

## Tests

```powershell
python -m pip install -r .\requirements-dev.txt
python -m unittest discover -s .\tests -p "test_public_dashboard_*.py"
python -m pytest .\tests\test_dst_historical_archive_v1.py -q
```

## Sensitive and generated data

Do not commit environment files, tokens, operational SQLite databases, reviewer
audit data, crawl snapshots, logs, backups, caches or generated output folders.
The repository contains source code, governed configurations, migrations and
explicitly selected public-data fixtures only.
