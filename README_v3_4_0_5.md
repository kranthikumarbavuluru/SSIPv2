# SSIP v3.4.0.5 — Startup-Focused DST Catalogue and Official Deep Search

## Purpose

This release corrects the main catalogue objective. The public **Startup Scheme Explorer** will no longer publish every DST programme merely because it belongs to the Department of Science and Technology.

A DST record is now public only when official evidence establishes:

1. a startup, innovator, entrepreneur, company or incubatee beneficiary; and
2. a direct or centre-mediated application/access route.

University-only, institution-only, infrastructure-only and general research programmes are moved to a quarantine file and are not counted as startup schemes.

## What changes immediately

The script removes the broad DST set currently visible in the Startup Scheme Explorer and publishes seven verified startup-relevant scheme/access records:

1. NIDHI – PRAYAS
2. NIDHI – Entrepreneur-in-Residence
3. NIDHI Seed Support Program
4. NIDHI – Technology Business Incubators
5. NIDHI – Inclusive Technology Business Incubators
6. NIDHI – Accelerator
7. Technology Development Board Core Funding

The records include explicit sectors, startup stages, beneficiary evidence and application routes.

## What is shown separately

The dashboard receives two additional navigation pages:

- **Calls & Opportunities** — time-bound calls, cohorts, challenges and proposal windows.
- **Incubators & Ecosystem** — NIDHI umbrella, NSTEDB, NM-ICPS and ecosystem/hub records.

Calls never rename or replace permanent schemes. Umbrella missions are not counted as direct startup schemes.

## Official deep search

The bounded crawler searches official sources under:

- `dst.gov.in`
- `nidhi.dst.gov.in`
- `nmicps.in`
- `tdb.gov.in`
- `nidhi-prayas.org` as an implementing programme portal

It classifies discovered pages into direct startup schemes, startup-access programmes, ecosystem missions, calls, review candidates, supporting documents and rejected non-startup pages.

Newly discovered pages are not automatically promoted merely because their titles contain “innovation” or “technology.” Ambiguous pages are written to the manual-review queue.

## Installation

Extract the ZIP directly into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Allow Windows to merge the `scripts`, `config` and `tests` folders.

## Run

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

powershell -ExecutionPolicy Bypass `
  -File .\RUN_v3_4_0_5.ps1
```

The runner:

1. installs dependencies;
2. compiles and tests the pipeline;
3. backs up the active catalogue and dashboard app;
4. quarantines all existing DST public rows;
5. publishes the seven verified startup-focused records;
6. runs the official deep search;
7. writes calls, ecosystem, evidence and review outputs;
8. patches the current dashboard navigation;
9. restarts Streamlit on port 8502.

## Expected verification

```text
PublishedDSTStartupSchemes : 7
NonStartupDSTRowsRemaining : 0
MissingSector               : 0
WrongCatalogueSection       : 0
EcosystemRecords            : 4
VALIDATION PASSED
```

The total catalogue count will decrease because broad DST programmes are being removed from the startup-facing count. That decrease is intentional and correct.

Search `dst` in the Scheme Explorer: the expected result is seven focused DST scheme/access records rather than 23 broad department programmes.

## Outputs

Created under:

```text
data\departments\dst\v3_4_0_5
```

Main outputs:

- `dst_verified_startup_scheme_registry_v3_4_0_5.csv`
- `dst_quarantined_department_programmes_v3_4_0_5.csv`
- `dst_startup_ecosystem_registry_v3_4_0_5.csv`
- `dst_startup_calls_v3_4_0_5.csv`
- `dst_startup_deep_search_pages_v3_4_0_5.csv`
- `dst_startup_manual_review_queue_v3_4_0_5.csv`
- `dst_startup_supporting_documents_v3_4_0_5.csv`
- `dst_startup_focus_summary_v3_4_0_5.json`

## Safety rules

- Existing files are backed up before modification.
- Calls are stored separately from permanent scheme identities.
- Ecosystem missions and hubs are not counted as direct schemes.
- Institutional programmes do not enter the Startup Scheme Explorer.
- Newly discovered ambiguous pages go to review instead of automatic publication.
- The production staging database is not modified by this release.
