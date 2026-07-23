# SSIP v3.4.3.8.0 — MeitY Complete Intelligence

This phase builds one consolidated MeitY inventory instead of adding
programmes one by one.

## Discovery coverage

The governed agent starts from:

- MeitY Startup Hub home
- `/schemes`
- `/whatsnew`
- `/challenges`

It also:

- probes candidate API paths;
- scans JavaScript bundles for API, scheme, challenge and document URLs;
- uses installed Chrome or Edge in headless mode when a page is only an
  application shell;
- follows official-domain programme, challenge, call and PDF links;
- imports prior governed MeitY CSV evidence so earlier work is not lost.

## Entity model

Permanent identities:

- permanent scheme;
- permanent programme;
- accelerator programme;
- grant programme;
- incubation programme;
- ecosystem or implementation programme.

Time-bound identities:

- application call;
- challenge or grand challenge;
- hackathon;
- accelerator cohort;
- EOI or RFP;
- implementation-partner call.

Evidence events:

- result or winner announcement;
- extension notice;
- corrigendum;
- selected cohort.

Directories, event pages, organisation profiles and generic news listings
remain evidence-only exclusions.

## Status gate

`OPEN` requires all three:

1. explicit official open/application language;
2. a current or future closing date;
3. an official application route.

Anything incomplete remains `VERIFICATION_REQUIRED`. Result notices are
historical and never expose an Apply action.

## Outputs

The pipeline writes:

- complete programme inventory;
- current calls and challenges inventory;
- historical calls and results inventory;
- relationship-review queue;
- exclusions;
- page and document evidence;
- Admin-review preview CSV and JSON;
- fetch log;
- signed manifest.

## Admin preview

Run the preview workspace on port 8506. It displays programme, call,
challenge, result, relationship and evidence queues in a three-column
read-only review layout.

## Nightly readiness

The included task-registration script schedules the same preview agent at
midnight. It discovers and compares records, but never writes to the database
or publishes automatically.

## Governance

- Preview-only.
- No database writes.
- No publication.
- Existing GENESIS and SASACT records are reconciled, not replaced.
- Calls, cohorts and challenges remain separate from permanent programmes.
- Filename-derived document identities are not publication-ready.
