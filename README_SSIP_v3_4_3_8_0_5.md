# SSIP v3.4.3.8.0.5 — MeitY Guided Admin Review

This phase simplifies the v3.4.3.8.0.4 link-integrity workspace.

It does not change link validation, temporal validation, parent repair,
database records or publication state. It changes only how the Admin completes
the review.

## Simplified workflow

The page shows one record at a time.

### Step 1 — Check the official source

The Admin sees only:

- a verified official information-page button, when available;
- a verified application-route button, only when it passed every gate; or
- a plain explanation that the application route is withheld.

Raw and rejected URLs are not shown as action buttons.

### Step 2 — Check the system summary

The page explains in plain language:

- what type of record it appears to be;
- whether a matching official source was verified;
- whether an application route was verified or withheld;
- what the Admin should check next.

Technical codes are hidden under an optional Advanced evidence section.

### Step 3 — Choose one action

Only decisions allowed by the v3.4.3.8.0.4 safety gate are shown.

Examples:

- Confirm as a historical reference
- Confirm the programme identity
- Needs more official evidence
- Review this later
- Reject this classification

`ACCEPT_RECOMMENDATION` is never displayed.

## Queue views

The Admin can show:

- Remaining records
- All records
- Ready to confirm
- Need more evidence
- Current opportunity checks
- Reviewed this session

After saving a decision, the default Remaining view automatically moves to the
next record.

## Note requirements

A reason is required for:

- Needs more official evidence
- Reject this classification
- every deep-review bundle

A note is optional for routine confirmations and deferrals unless the upstream
bundle requires one.

## Progress and export

The page shows:

- total records;
- completed in the current browser session;
- remaining records;
- records needing evidence.

The Admin can download a session decision worksheet containing exact governed
decision codes and link-integrity signatures.

## Governance

- Decisions remain browser-session only.
- No database write.
- No publication.
- No public Apply action.
- No safety gate is bypassed.
- Positive confirmation remains disabled when link integrity is incomplete.

## Port

The guided workspace runs at:

`http://localhost:8511`
