# SSIP v3.4.3.8.1
## Unified MeitY Main Dashboard and Embedded Admin Intelligence Workflow

This release removes the need to use separate MeitY preview applications during
normal operation.

## Final application layout

### Public dashboard

Use only:

`http://localhost:8502`

The existing MeitY menu in the main SSIP public dashboard now renders the
integrated public MeitY page with:

- Schemes & Programmes
- Current Calls & Challenges
- Historical Archive

Only records already published through the governed publication workflow appear
publicly.

Permanent schemes and programmes are rendered without an Apply button.
Only published OPEN or UPCOMING calls with a verified application URL can show
an Apply action. Unverified, closed and historical records never show Apply.

### Admin Review

Use only:

`http://localhost:8505`

The Admin sidebar now contains:

1. Agent Intake & Dry Run
2. Verify Pending Records
3. Quick Editor
4. MeitY Intelligence Review
5. Stage & Publish Approved Records
6. Historical Archive
7. Ingestion History
8. Audit Trail

The earlier standalone MeitY applications on ports 8510–8514 are retained only
as developer diagnostics. They are not required for normal Admin review.

## Embedded MeitY Intelligence Review

The MeitY Admin workspace contains:

- Overview
- Classification & Type Correction
- Links, Dates & Parent
- Dashboard & Projection
- Audit

The Admin can:

- see why a record is a programme, call, challenge, cohort or historical item;
- correct the classification;
- correct the parent programme;
- review official information and application links;
- distinguish call identity from current OPEN status;
- preview effective dashboard groups;
- project eligible records into the normal Admin Review Inbox as PENDING;
- inspect classification and projection audit history.

Projection uses the exact confirmation:

`PROJECT TO ADMIN REVIEW`

Projection does not approve, stage or publish records.

## Quick Editor

The Quick Editor lists all available schemes, programmes, calls and challenges
from the Admin Review Queue and staged catalogue.

Filters:

- Ministry
- Department
- Search by name or type

The Admin selects one record and edits only:

### Category

Category is selected with checkboxes. Exactly one must be selected:

- Scheme
- Programme
- Application call
- Challenge / hackathon
- Cohort / application window
- Historical reference
- Supporting document
- Not a catalogue record

### Status

For Scheme or Programme:

- Open
- Closed

For Call, Challenge or Cohort:

- Open
- Upcoming
- Closed
- Verification Required

Exactly one status checkbox must be selected.

### Funding

- Minimum fund value
- Maximum fund value
- Minimum not available
- Maximum not available

The editor validates that minimum funding does not exceed maximum funding.

The exact save confirmation is:

`SAVE QUICK EDIT`

## Quick-edit write behaviour

For a pending or non-public staged record, the editor updates the governed Admin
record and creates an audit entry.

For a published record, the public data is not changed live. The edit is saved
as `PENDING_PUBLICATION_REVIEW` so that the separate publication workflow must
review and release the change.

Every confirmed edit:

- creates a consistent SQLite backup;
- runs in a transaction;
- records before and after JSON;
- creates a quick-edit audit row;
- reports the exact write result;
- performs no publication action.

Tables:

- `admin_quick_edit_requests_v3_4_3_8_1`
- `admin_quick_edit_audit_v3_4_3_8_1`

## MeitY projection behaviour

Eligible MeitY records are imported into `admin_review_queue` as PENDING only.

The projection protects:

- existing APPROVED decisions;
- existing REJECTED decisions;
- already staged records;
- historical Apply suppression;
- unresolved call-parent relationships;
- unverified current application routes.

Tables:

- `meity_unified_projection_v3_4_3_8_1`
- `meity_unified_projection_audit_v3_4_3_8_1`

## Governance boundaries

Installation:

- Database modified: No
- Publication action: No
- Public visibility changed: No

Normal Quick Editor write:

- Database backup: Yes
- Audit: Yes
- Direct publication: No

MeitY projection:

- Creates PENDING Admin-review records only
- Direct staging: No
- Direct publication: No

## Normal launch commands

Public dashboard:

```powershell
cd "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

python -m streamlit run `
  ".\apps\public_dashboard_app_v2_9.py" `
  --server.port 8502 `
  --server.address localhost
```

Admin Review:

```powershell
cd "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

python -m streamlit run `
  ".\ui\admin_review_app_v1.py" `
  --server.port 8505 `
  --server.address localhost
```
