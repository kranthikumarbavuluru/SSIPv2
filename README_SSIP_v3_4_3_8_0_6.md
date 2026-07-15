# SSIP v3.4.3.8.0.6 — MeitY Signed Decision Import

This phase converts the worksheet downloaded from the guided review page into a
signed, read-only Admin-bridge preview.

It does not apply the bridge and does not modify the database.

## Required input

Use the CSV downloaded from the v3.4.3.8.0.5 guided review page on port 8511.

The worksheet contains:

- bundle ID;
- bundle title;
- link-integrity signature;
- exact governed decision code;
- plain-language decision label;
- selected child IDs;
- Admin note.

## Validation

Every row is checked against the current v3.4.3.8.0.4 governed outputs.

The importer rejects:

- missing headers;
- unknown bundle IDs;
- duplicate bundle decisions;
- stale or changed link-integrity signatures;
- decisions not allowed for the bundle;
- unknown selected child IDs;
- missing child selection for deep review;
- missing required notes;
- positive decisions blocked by link safety;
- current-call confirmation without complete application integrity;
- pending or empty decisions;
- unknown decision codes.

## Strict mode

Strict mode is the default.

When one row is invalid, the entire plan is marked `BLOCKED`. The Admin must
correct the decision in the guided review page and download a new worksheet.

An optional valid-subset mode exists for diagnosis, but it should not be used
for a final governed plan.

## Bridge action mapping

Validated decisions become proposed actions only:

- Confirm historical → `PROPOSE_HISTORICAL_REFERENCE`
- Confirm programme → `PROPOSE_PROGRAMME_IDENTITY`
- Confirm new programme → `PROPOSE_NEW_PROGRAMME_STAGING_REVIEW`
- Confirm call and parent → `PROPOSE_CALL_AND_PARENT`
- Confirm current opportunity evidence →
  `PROPOSE_CURRENT_CALL_STAGING_REVIEW`
- Needs more evidence → `PROPOSE_NEEDS_MORE_EVIDENCE`
- Defer → `NO_OPERATION_DEFERRED`
- Reject → `PROPOSE_CLASSIFICATION_REJECTION`

Every action has:

- `database_action = NONE`
- `publication_action = NONE`

## Outputs

- `meity_validated_admin_decisions_v3_4_3_8_0_6.csv`
- `meity_rejected_decision_rows_v3_4_3_8_0_6.csv`
- `meity_admin_bridge_preview_v3_4_3_8_0_6.csv`
- `meity_decision_import_summary_v3_4_3_8_0_6.json`
- `meity_signed_admin_bridge_plan_v3_4_3_8_0_6.json`

## Preview workspace

The import page runs at:

`http://localhost:8512`

Workflow:

1. Upload the worksheet downloaded from port 8511.
2. Validate it.
3. Review accepted decisions, rejected rows and proposed Admin-bridge actions.
4. Download the signed plan.

## Governance

- No database write.
- No publication.
- No Admin-bridge application.
- No automatic staging.
- No automatic OPEN status.
- No automatic rejection or approval.
