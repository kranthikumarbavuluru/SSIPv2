# SSIP v3.4.3.8.0.8 — MeitY Dashboard Preview and Staging Projection

This phase applies the active v3.4.3.8.0.7 classification overrides to the
MeitY source records and displays the effective result in a dashboard-style
preview.

## Dashboard preview

The preview separates records into:

- MeitY Programmes
- Calls & Challenges
- Historical Archive
- Excluded & Supporting
- Classification Review, when an effective type remains unresolved

The preview uses the active classification override when one exists. It shows
the corrected type, corrected parent programme, verified source and projection
status.

It does not alter the live public dashboard.

## Projection eligibility

A record is eligible for the dedicated staging projection only when:

- its effective type is cataloguable;
- a verified official information source exists;
- a call, challenge or cohort has a parent programme;
- a current opportunity has complete application-route integrity;
- a historical record does not retain an application route.

Supporting documents and invalid non-catalogue records remain excluded.

A call identity may be retained without an OPEN status. Call identity and
current application status remain separate.

## Staging projection write

The governed write requires the exact phrase:

`PROJECT TO STAGING`

The write action:

1. regenerates the signed projection plan;
2. verifies the projection signature;
3. creates a consistent SQLite backup;
4. starts an immediate transaction;
5. writes eligible rows only to
   `meity_classification_staging_projection_v3_4_3_8_0_8`;
6. writes audit events to
   `meity_classification_staging_projection_audit_v3_4_3_8_0_8`;
7. supersedes an older active projection for the same child when the effective
   classification changed;
8. verifies that core staging, review and publication table counts remain
   unchanged;
9. commits only after every check passes.

## Important boundary

The projection does not modify:

- `scheme_staging`
- `admin_review_queue`
- `public_schemes`
- publication status
- public visibility
- public Apply actions

The dedicated projection layer is an intermediate governed dataset. A later
phase can review and promote eligible rows to the operational Admin staging
workflow.

## Preview outputs

- `meity_effective_dashboard_preview_v3_4_3_8_0_8.csv`
- `meity_staging_projection_eligible_v3_4_3_8_0_8.csv`
- `meity_staging_projection_blocked_v3_4_3_8_0_8.csv`
- `meity_classification_projection_manifest_v3_4_3_8_0_8.json`
- `meity_signed_staging_projection_plan_v3_4_3_8_0_8.json`

## Workspace

Launch the dashboard-style preview on:

`http://localhost:8514`

## Governance

- Preview generation: read-only.
- Projection write: dedicated projection and audit tables only.
- Database backup: mandatory before projection write.
- Public dashboard publication: No.
- Public visibility change: No.
- Apply action exposure: No.
