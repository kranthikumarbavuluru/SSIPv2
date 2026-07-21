# SSIP v3.4.3.7.2 — Legacy Rejected Identity Reconciliation

This phase reconciles two old rejected discovery identities with the
governed canonical SASACT and GENESIS permanent-scheme identities.

| Legacy rejected ID | Canonical ID | Scheme |
|---|---|---|
| `190830c31088c57ffdbc` | `94f8ab0a070a6ff15fce` | GENESIS |
| `e3abff4124f05a31f188` | `194b7ba77d6b53f30b91` | SASACT |

Governance controls:

- Old `REJECTED` rows remain unchanged.
- Existing `admin_review_actions` history remains unchanged.
- The explicit mapping is recorded in `identity_reconciliations`.
- New canonical IDs enter `admin_review_queue` as `PENDING` only after a
  reviewed signed dry run.
- Approval duplicate checks ignore only mapped legacy aliases that remain
  `REJECTED`; any additional duplicate still blocks approval.
- No publication is performed.
- No public Apply route is created.
- No current MeitY call is asserted.
