# SSIP v3.4.0.4 — DST Canonical Identity Lock and Public Dashboard Preview

## Outcome

This phase converts the publication-safe DST inventories from v3.4.0.3.3.1 into:

- stable canonical permanent identities;
- a public catalogue containing schemes and programmes only;
- a SQLite publication database;
- a public Streamlit dashboard preview;
- separate internal queues for unresolved entity and hierarchy review.

Expected production result from the approved upstream run:

```text
Canonical schemes    : 3
Canonical programmes : 20
Public preview total : 23
Manual entity reviews: 4 (not published)
```

## Critical identity rule

A call, application window, cohort, round, deadline extension, result, recruitment notice, policy, archive, category page or supporting document cannot create or rename a permanent scheme/programme.

Only the corrected permanent inventories are eligible for identity locking. The four manual entity-review targets remain outside the public catalogue.

## Installation

Extract the ZIP directly into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Allow Windows to merge the `scripts`, `apps`, `config`, and `tests` folders.

## One-command execution

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

powershell -ExecutionPolicy Bypass `
  -File .\RUN_v3_4_0_4.ps1
```

This command:

1. installs v3.4.0.4 requirements;
2. compiles the builder and dashboard;
3. runs the internal self-test;
4. runs the automated tests;
5. builds the locked DST canonical registry;
6. validates the 3 + 20 expected counts;
7. creates the publication SQLite database;
8. opens the public dashboard at `http://localhost:8502`.

## Build without opening the dashboard

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\BUILD_v3_4_0_4.ps1
```

## Open an already-built dashboard

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\OPEN_DASHBOARD_v3_4_0_4.ps1
```

## Main outputs

```text
data\departments\dst\v3_4_0_4\
├── dst_canonical_entity_registry_v3_4_0_4.csv
├── dst_canonical_scheme_registry_v3_4_0_4.csv
├── dst_canonical_programme_registry_v3_4_0_4.csv
├── dst_canonical_alias_registry_v3_4_0_4.csv
├── dst_relationship_review_queue_v3_4_0_4.csv
├── dst_manual_entity_review_queue_v3_4_0_4.csv
├── dst_identity_lock_rejections_v3_4_0_4.csv
├── dst_publication_catalogue_v3_4_0_4.csv
├── dst_publication_catalogue_v3_4_0_4.json
├── ssip_public_preview_v3_4_0_4.db
├── dst_identity_lock_audit_v3_4_0_4.csv
├── dst_canonical_validation_v3_4_0_4.json
└── dst_canonical_summary_v3_4_0_4.json
```

## Required validation result

```json
{
  "canonical_validation_passed": true,
  "ready_for_dashboard_preview": true,
  "ready_for_v3_4_0_5": true
}
```

The count block must show:

```json
{
  "canonical_entities": 23,
  "canonical_schemes": 3,
  "canonical_programmes": 20,
  "publication_records": 23
}
```

## Public dashboard behavior

The dashboard displays:

- Department of Science and Technology;
- verified scheme and programme counts;
- search and entity-type filters;
- public scheme/programme cards;
- official source links;
- detail pages with `Not yet verified` for missing attributes;
- no internal review records;
- no expired call title presented as a permanent scheme.

## Optional curated overrides

The file below is intentionally empty by default:

```text
config\dst_identity_curation_overrides_v3_4_0_4.csv
```

Supported actions:

- `LOCK` — lock using the supplied canonical name/type;
- `EXCLUDE` — remove from identity lock and publication;
- `REVIEW` — hold outside publication.

The stable `master_id` remains based on the upstream provisional identity, so a curated name correction does not create a new scheme identity.

## Next phase

After the dashboard is visually confirmed, proceed to **v3.4.0.5 — DST attribute extraction, active-call linking and dashboard detail completion**.
