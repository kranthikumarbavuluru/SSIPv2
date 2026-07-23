# SSIP v3.4.3.8.0.4 — MeitY URL Integrity

This phase repairs inaccurate and cross-contaminated links in the MeitY
decision workspace.

The v3.4.3.8.0.3 screenshot exposed an `/about/applyforthelogo` route as an
application link. An official-domain check alone is therefore not sufficient.

## URL provenance

Every displayed link is tied to:

- decision bundle ID;
- exact child ID;
- source field;
- source candidate and evidence IDs when available;
- requested URL;
- final redirected URL;
- HTTP status;
- content type;
- page title;
- classified page role;
- entity-match confidence;
- fetch method;
- last checked timestamp;
- withholding reason and integrity flags.

## Page roles

Each inspected page is assigned one of:

- `SCHEME_INFORMATION_PAGE`
- `CALL_INFORMATION_PAGE`
- `APPLICATION_ROUTE`
- `REGISTRATION_ROUTE`
- `GUIDELINE_DOCUMENT`
- `RESULT_NOTICE`
- `HISTORICAL_SOURCE`
- `SUPPORTING_DOCUMENT`
- `LOGIN_ROUTE`
- `NAVIGATION_PAGE`
- `ABOUT_PAGE`
- `CONTACT_PAGE`
- `UNRELATED_ROUTE`
- `BROKEN_OR_UNVERIFIED`

Only verified `APPLICATION_ROUTE` or `REGISTRATION_ROUTE` records may become
clickable application links.

## Application-route gate

An application route must satisfy all of these:

1. the URL originates directly from the selected child’s `application_url`;
2. the child is `CURRENT_STATUS_EVIDENCE_COMPLETE`;
3. at least one current MeitY record passes the global current-evidence gate;
4. the final redirected page remains on an allowed official domain;
5. the page is reachable;
6. the page contains application or registration markers;
7. the page role is application or registration;
8. the page matches the selected entity above the configured threshold;
9. the record is not historical;
10. the path is not About, Contact, Logo, Login, Search or navigation.

Failure of any condition withholds the link.

## Historical protection

Historical records may expose only verified historical, result, information or
supporting-document links. They never expose an Apply or Register route.

## Global withholding

When `current_status_evidence_complete_count` is zero, every application and
registration route is withheld globally. This matches the current governed
MeitY state.

## Decision safety

Positive confirmation options are removed from a bundle when required
information or application link integrity is incomplete. Admins can still
choose `NEEDS_MORE_EVIDENCE`, `DEFER` or `REJECT_CLASSIFICATION`.

Session decisions are cleared automatically when link provenance or final-page
validation changes.

## Outputs

- `meity_url_provenance_ledger_v3_4_3_8_0_4.csv`
- `meity_link_safe_decision_children_v3_4_3_8_0_4.csv`
- `meity_link_safe_admin_bundles_v3_4_3_8_0_4.csv`
- `meity_withheld_application_routes_v3_4_3_8_0_4.csv`
- `meity_url_integrity_manifest_v3_4_3_8_0_4.json`

## Governance

- No database write.
- No publication.
- No Apply action.
- No automatic OPEN status.
- No automatic Admin approval.
- Raw withheld URLs appear only in the audit tab.
