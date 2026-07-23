# SSIP v3.4.3.7.3 — Admin Workflow Sequence and Navigation Clarity

This phase changes only Admin workspace navigation and explanatory UI.

## Primary sequence

1. Agent Intake & Dry Run
2. Verify Pending Records
3. Stage & Publish Approved Records

Supporting workspaces follow:

4. Ingestion History
5. Historical Archive
6. Audit Trail

A four-stage visual guide is displayed on every page:

`Agent intake → Human verification → Staging quality → Publication`

## Governance preserved

- Agent comparison remains non-writing.
- Intake still imports only pending review records.
- Human approval still moves records into non-public staging.
- Publication still requires a separate preflight and confirmation.
- Existing decisions, database records and audit history are unchanged.
- No scheme or call data is added or removed.
