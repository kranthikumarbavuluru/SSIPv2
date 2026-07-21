# SSIP v3.4.3.7.5 — MeitY Calls, Challenges and Application Windows Recovery

This phase recovers time-bound MeitY opportunity instances without changing
permanent scheme identities.

## Official evidence policy

Accepted hosts:

- `msh.meity.gov.in`
- `api.meity.gov.in`
- `meity.gov.in`
- `www.meity.gov.in`

The recovery combines a fresh official-domain crawl with existing governed
MeitY discovery evidence. Off-domain and generic navigation records are
rejected.

## OPEN policy

`OPEN_VERIFIED` requires all four conditions:

1. a current or future closing date;
2. explicit open or active official status;
3. an official application or registration route;
4. successful live network verification.

Without all four, the application route is suppressed and the record is sent
for Admin review.

## Identity policy

- SASACT and GENESIS remain permanent schemes.
- Calls, cohorts, challenges and windows are separate `CALL_INSTANCE` records.
- Parent links use explicit official evidence only.
- A clear official call without a verified parent may be reviewed as a
  standalone official call.
- No publication occurs in this phase.

## Admin sequence

1. Install and review the recovery report.
2. Restart Admin workspace.
3. Select `MeitY v3.4.3.7.5 Calls Recovery`.
4. Run comparison / dry run.
5. Inspect the signed plan.
6. Import pending call reviews only.
7. Verify each call individually.
