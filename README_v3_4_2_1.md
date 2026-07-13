# SSIP v3.4.2.1 — Intelligent Catalogue Governance

## Why this release exists

The previous sector agent processed 137 mixed rows that included sitemaps,
reports, handbooks, contact pages, laboratories, generic web pages and genuine
schemes. Sector classification cannot be reliable until catalogue sanitation is
performed first.

This release disables LM Studio by default and uses governed deterministic
agents.

## Agent order

1. Record Role Agent
2. Startup Relevance Agent
3. Call Agent
4. Evidence Sector Agent
5. Governance Policy
6. Publication and Validation

## Public catalogue policy

Only genuine scheme/programme or support-service identities that pass the
startup/MSME relevance gate are written to the active dashboard catalogue.

Calls are written separately to:

`data\governance\current_calls_and_opportunities.csv`

Documents, reports, navigation pages, laboratories and directories are
quarantined in the run folder.

## Install and run

Extract directly into:

`D:\WebSite\DASHBOARD\Code\SSIP`

Then:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
python -m pip install -r .\requirements-v3_4_2_1.txt
.\RUN_GOVERNANCE_AGENTS_v3_4_2_1.ps1
```

## Install the midnight task

Open PowerShell as Administrator:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\INSTALL_NIGHTLY_GOVERNANCE_TASK_v3_4_2_1.ps1
```

## Outputs

Each run creates:

`data\governance\<run_id>\`

with:

- `public_startup_schemes.csv`
- `calls_and_opportunities.csv`
- `manual_review_queue.csv`
- `quarantine.csv`
- `governance_audit.csv`
- `summary.json`
- `validation.json`

The previous active catalogue is backed up under:

`backups\governance\<run_id>\`

## Dashboard sector compatibility

The publisher writes the same controlled value to both:

- `sector`
- `primary_sector`

This avoids the previous mismatch where the agent populated one field while the
dashboard read another.


## v3.4.2.1 hardening

- LM Studio remains disabled by default.
- All PDF records are treated as supporting evidence, never canonical schemes.
- Generic scheme/index pages are quarantined.
- Any scheme with unresolved sector evidence is routed to manual review and cannot enter the public catalogue.
- The active public catalogue is rebuilt from governed scheme identities only.
