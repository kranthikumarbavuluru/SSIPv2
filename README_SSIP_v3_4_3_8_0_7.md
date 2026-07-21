# SSIP v3.4.3.8.0.7 — Transparent Entity Classification and Write Gate

This phase makes the programme-versus-call classification visible and
correctable.

## Transparent classification

Each record shows:

- the effective classification;
- the upstream entity type;
- the suggested classification and confidence;
- positive and missing evidence;
- whether a deadline exists;
- whether a verified application route exists;
- the verified page role;
- temporal status;
- parent-link status.

The page explains the distinction in plain language:

- **Permanent programme or scheme** — a durable government-support identity.
  Calls, cohorts and challenges must remain separate.
- **Application call** — a time-bound application opportunity.
- **Challenge or hackathon** — a time-bound challenge identity.
- **Cohort or application window** — a dated intake linked to a permanent
  programme when supported.
- **Historical reference or result** — past evidence with no Apply action.
- **Supporting document** — evidence that must not become a catalogue title.
- **Invalid non-catalogue** — unrelated or unusable material.

## Admin type correction

The Admin can correct a record to one of the governed types:

- `PERMANENT_PROGRAMME`
- `PERMANENT_SCHEME`
- `APPLICATION_CALL`
- `CHALLENGE_CALL`
- `ACCELERATOR_COHORT`
- `HISTORICAL_REFERENCE`
- `RESULT_ANNOUNCEMENT`
- `SUPPORTING_DOCUMENT`
- `INVALID_NON_CATALOGUE`

Call-like records can be linked to a known permanent programme. Permanent,
historical, supporting and invalid records cannot receive a call-parent
relationship.

A note is mandatory when the correction changes the semantic classification.
Normalisation such as `ACCELERATOR_PROGRAMME` to `PERMANENT_PROGRAMME` is
treated as a confirmation, not a semantic correction.

## Save modes

### Preview only

Validates the proposed classification and shows the exact record kind, parent
and write scope. It does not change the database.

### Governed database write

Requires:

1. selecting `Governed database write`;
2. acknowledging that the action does not publish;
3. entering the exact phrase `WRITE CLASSIFICATION`;
4. pressing `Write governed classification`.

The write action:

- creates a consistent SQLite backup;
- starts an immediate transaction;
- writes one active override to
  `meity_entity_classification_overrides_v3_4_3_8_0_7`;
- writes an audit event to
  `meity_entity_classification_write_audit_v3_4_3_8_0_7`;
- supersedes the prior active override for the same child, if present;
- verifies that core staging, Admin-review and publication table counts remain
  unchanged;
- commits only after all checks pass.

## Write scope

The write mode does **not**:

- update `scheme_staging`;
- update `admin_review_queue`;
- update `public_schemes`;
- publish a record;
- create an Apply action;
- change public visibility;
- delete or replace a master identity.

The dedicated override layer is the governed source for later staging and
publication preparation.

## Outputs

Preview inventory:

- `meity_transparent_classification_inventory_v3_4_3_8_0_7.csv`
- `meity_transparent_classification_manifest_v3_4_3_8_0_7.json`

Operational write tables are created only after the first confirmed write.

## Workspace

Run on:

`http://localhost:8513`
