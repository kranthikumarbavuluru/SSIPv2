# SSIP v3.4.3.7.4 — Ministry and Department Canonicalization

This governed phase removes duplicate ministry/department labels without changing scheme identity, review decisions, application status, publication state or audit history.

## Canonical hierarchy

### DST
- Ministry: `Ministry of Science and Technology`
- Department: `Department of Science and Technology (DST)`

### MeitY
- Ministry: `Ministry of Electronics and Information Technology (MeitY)`
- Department stored as `null`
- Admin display label: `Ministry-level programme`
- Implementing agency remains `MeitY Startup Hub`

### DPIIT
- Ministry: `Ministry of Commerce and Industry`
- Department: `Department for Promotion of Industry and Internal Trade (DPIIT)`

### DBT
- Ministry: `Ministry of Science and Technology`
- Department: `Department of Biotechnology (DBT)`

## Governance

1. Installation changes code only and performs a read-only live plan.
2. The operational database is not changed during installation.
3. A separate signed apply script creates a database backup and applies the reviewed plan transactionally.
4. `master_id`, review status, application URLs and publication status are never changed.
5. Every changed operational row is recorded in `organization_canonicalization_audit`.
6. Future review/staging imports are canonicalized before storage.
7. Unknown organization names are preserved rather than guessed.
