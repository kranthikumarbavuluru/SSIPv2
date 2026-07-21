# SSIP v3.4.3.8.0.3 — MeitY Decision-Safety Gate

This phase repairs the practical safety issues visible in the compressed
family-level Admin review.

## Temporal validation

A call is retained as current or upcoming only when all of the following are
available:

1. explicit official open/application language;
2. a current or future closing date;
3. an official MeitY application route;
4. a recent verification timestamp;
5. no conflicting historical year in the title, unless official reopened
   evidence is present.

A title such as `Google Appscale Academy 2023` is historical in 2026 unless
the official source explicitly proves that the opportunity was reopened.

Incomplete current evidence becomes `VERIFICATION_REQUIRED`. It does not
become `OPEN`.

## Parent-link repair

Parent programmes are inferred only from:

- an explicit parent field supported by the title or URL; or
- a unique programme alias in the direct title or official URL.

Evidence excerpts, footer text and unrelated programme mentions are not used
for parent inference.

Standalone calls such as Google Appscale Academy, BHUMI and DRISHTI do not
inherit GENESIS or another permanent programme from incidental text.

## Safe Admin decisions

Ambiguous `ACCEPT_RECOMMENDATION` wording is removed.

Safe positive decisions include:

- `CONFIRM_HISTORICAL`;
- `CONFIRM_PROGRAMME_IDENTITY`;
- `CONFIRM_NEW_PROGRAMME_FOR_STAGING_REVIEW`;
- `CONFIRM_CALL_AND_PARENT`;
- `CONFIRM_CURRENT_CALL_EVIDENCE_COMPLETE`;
- `CONFIRM_REVIEW_CLASSIFICATION`.

All decisions remain separate from database staging, publication and OPEN
status.

## Deep-review controls

For deep-review bundles:

- at least one child record must be selected;
- an Admin note is mandatory;
- a non-pending decision must be selected;
- the Save button remains disabled until all conditions are satisfied.

## Evidence at a glance

The safe workspace displays together:

- official evidence page;
- application route;
- opening and closing dates;
- safe application status;
- temporal classification;
- last verified timestamp;
- repaired parent;
- parent-link resolution;
- current-status evidence;
- safety flags.

## Session invalidation

Each bundle has a deterministic evidence signature. Browser-session decisions
are cleared automatically when the evidence or bundle signature changes.
Downloaded decision worksheets include the bundle signature.

## Outputs

- `meity_safe_admin_decision_bundles_v3_4_3_8_0_3.csv`
- `meity_safe_decision_children_v3_4_3_8_0_3.csv`
- `meity_temporal_downgrades_v3_4_3_8_0_3.csv`
- `meity_parent_link_repairs_v3_4_3_8_0_3.csv`
- `meity_temporal_parent_safety_manifest_v3_4_3_8_0_3.json`

## Governance

- No database write.
- No publication.
- No Apply action.
- No automatic OPEN confirmation.
- No automatic Admin approval.
- Source decision bundles reconcile exactly.
