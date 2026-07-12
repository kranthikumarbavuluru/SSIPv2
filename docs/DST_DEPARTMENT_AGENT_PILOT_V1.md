# DST Department Agent Pilot v1

This pilot reconstructs Department of Science and Technology programme identities and calls without modifying the production staging database or public catalogue.

## Entity policy

- NIDHI is an umbrella programme.
- PRAYAS, EIR, SSP, TBI, iTBI, Accelerator and CoE are permanent NIDHI components.
- Every dated application/proposal row is a separate call instance.
- DST current/archive listing pages are containers and can never become call records.
- Calls to incubators or programme partners are labelled `INTERMEDIARY_IMPLEMENTER`; they are not direct founder opportunities.
- A call sector never changes its permanent parent's sector.
- Missing sector evidence produces `UNKNOWN`, not an inferred agnostic label.

## Run

```powershell
python .\scripts\run_dst_pilot_v1.py --verification-date 2026-07-11
```

The optional live refresh is bounded to the current DST call index, current call details and one level of allowlisted official evidence:

```powershell
python .\scripts\run_dst_pilot_v1.py --verification-date 2026-07-11 --live-refresh
```

If direct Python network access is unavailable, run without `--live-refresh`; curated current-call observations remain explicitly marked in the department profile.

## Outputs

Outputs are written to `data/departments/dst/pilot_v1`:

- `dst_evidence_pilot_v1.db` — isolated evidence and curation database
- `dst_programme_hierarchy_v1.csv` — permanent identities and hierarchy
- `dst_individual_calls_v1.csv` — one row per official call-list entry
- `dst_startup_call_candidates_v1.csv` — startup, ecosystem and review candidates
- `dst_curation_queue_v1.csv` — human review queue
- `dst_curation_preview_v1.html` — readable review preview
- `dst_pilot_summary_v1.json` — validation and run counts

## Open-status evidence policy

An opportunity can be classified as `OPEN` only when one of these evidence paths is satisfied:

1. The official source publishes a valid opening and closing date window containing the verification date.
2. A monitored official programme page exposes a trusted application route, and the record stores the status basis, evidence text, application URL and last verification date.

The second path is used for the first RDIF call implemented by TDB as Second-Level Fund Manager because the official page exposes an application route but does not publish a closing date. The permanent parent is RDIF; TDB is stored as the implementing entity, not as the parent scheme.

## Dashboard integration

The public preview exposes three separate DST views:

- `DST Schemes` for permanent programme identities.
- `Calls & Opportunities` for direct and review-required application opportunities, with open and closed filters.
- `Incubators & Ecosystem` for intermediary-implementer calls.

Call cards display the parent scheme, implementing entity, status evidence, verification date, applicants, technology stage, funding, sectors, application route and guidelines when officially evidenced.

## Publication policy

This version deliberately has no production publisher. A curator must approve programme identities, applicant layer, parent relationship, sector evidence, status and official URLs before a separately approved migration/publication step is implemented.
