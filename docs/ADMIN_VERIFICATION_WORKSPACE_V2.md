# SSIP Multi-Department Admin Verification Workspace

The preserved entry point is `ui/admin_review_app_v1.py`. It continues to use:

- `database/ssip_staging_v1.db`
- `admin_review_queue` for curator decisions
- `admin_review_actions` for immutable before/after audit actions
- `scheme_staging` for approved but not automatically published records
- `import_runs` for agent intake and admin decision traceability

## Why the legacy method was extended

The legacy workflow already had safe transactional approval, rejection, reopen and audit behavior. It was designed around individual records, however, and did not expose the controls needed for many department agents.

The workspace now separates five operational concerns:

1. **Review Inbox** — department, ministry, record type, applicant layer and ingestion-batch filtering; evidence readiness and duplicate checks; individual edit and decision actions.
2. **Publication Queue** — approved staging readiness, individual or bulk selection, signed preflight, publisher identity, confirmation phrase and audited publication transitions.
3. **Department Agent Intake** — provider-based dry run, exact inserts/updates/duplicates, signed plan confirmation and pending-queue import only.
4. **Ingestion Runs** — loader and admin-decision run history from `import_runs`.
5. **Audit Trail** — cross-department review actions from `admin_review_actions`.

## Publication controls

The publication state machine remains:

`STAGED → READY_FOR_PUBLICATION → PUBLISHED`

Bulk operation does not weaken the controls applied to individual records:

- only records with an `APPROVED` admin review and `APPROVED_FOR_DATABASE` validation decision are eligible;
- every record must pass the identifiable evidence-readiness checklist;
- excluded records and blockers are displayed before selection;
- the exact selection receives a signature during preflight;
- publisher identity, publication notes and an exact confirmation phrase are mandatory;
- every transition is atomic—one failure rolls back the whole selected batch;
- every committed record creates a `publication_audit_log` entry;
- only `PUBLISHED` plus `is_public=1` enters `public_schemes`.

## Verification contract

Approval readiness is calculated only from identifiable fields, not an AI score. Required checks include:

- stable identity and name
- government authority
- official primary URL
- stored official source evidence
- explicit scheme/programme/call classification
- status evidence for open or upcoming calls
- direct-beneficiary versus intermediary applicant layer
- permanent parent relationship or explicit standalone-call basis
- application route for open calls

Sector evidence and last-verification date are also surfaced. Unknown sectors remain unknown rather than being inferred as agnostic.

Possible official-URL or normalized-name duplicates block the UI approval button until resolved. A changed intake plan cannot be applied using an older dry-run confirmation because every plan has a content signature.

## Adding another department agent

Each department adapter must implement the intake provider contract:

- `plan()` returns exact proposed queue actions without database writes.
- `run(apply=False)` produces the reviewed dry-run report and plan signature.
- `run(apply=True, expected_signature=...)` imports only records permitted by that same reviewed plan.

Register the adapter in `services/department_review_intake_v1.py`. The Admin UI then discovers it without department-specific UI changes.

Intake never approves or publishes records. Curator approval writes to staging, and publication remains a separate controlled workflow.
