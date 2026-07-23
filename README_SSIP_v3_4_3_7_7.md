# SSIP v3.4.3.7.7 — Emergency MeitY Publication Withdrawal and Clean Rebuild

This phase responds to 16 MeitY records that were published with
`application_status=VERIFICATION_REQUIRED`.

## Governed sequence

1. Install code and generate a read-only signed plan.
2. Review the exact 16-record plan and reclassification queue.
3. Create a consistent SQLite backup.
4. Apply `withdraw-publication` transactionally.
5. Preserve master IDs, Admin decisions and historical audit records.
6. Add one `WITHDRAW_PUBLICATION` audit entry per affected record.
7. Keep all 16 records non-public until they are rebuilt correctly.

## Reclassification categories

- `VALID_CALL_INSTANCE`
- `PERMANENT_SCHEME_PAGE`
- `EVENT_OR_CONFERENCE`
- `PRESS_RELEASE_OR_NEWS`
- `NAVIGATION_OR_DIRECTORY`
- `RAW_DOCUMENT`
- `UNRESOLVED`

`VALID_CALL_INSTANCE` means identity evidence exists. It does not authorize
republication. Dates, applicant layer, parent relationship, page role and
application status must still be verified.

## Public dashboard

A dedicated MeitY menu is added. It displays only records with
`PUBLISHED + is_public=1`. Withdrawn and verification-required calls remain
hidden. The page separates permanent schemes from time-bound calls and
includes status metrics and a simple chart.

## Publication safety

Call publication is blocked when the status remains unverified, the title
is generic or filename-derived, the official page is a directory, the
applicant layer is unknown, the parent relationship is unresolved, or
required dates/evidence are missing.
