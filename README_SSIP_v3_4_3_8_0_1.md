# SSIP v3.4.3.8.0.1 — MeitY Candidate Purification

This phase corrects the broad v3.4.3.8.0 discovery output before any Admin
import or publication workflow.

## Source parser repair

The v3.4.3.8.0 manifest reported HTML parser `AttributeError` failures for
all static and browser-rendered MeitY pages. The defect occurred when a
`meta` element contained no `name`, `property`, or `itemprop` attribute.

This phase patches that parser, reruns the complete official live crawl,
and requires zero remaining `HTML_PARSE` errors before purification.

## Hard rejection gates

The following remain in the audit trail but cannot become programmes or
calls:

- Page Not Found and 404 content;
- Access Denied and Forbidden pages;
- generic portal and navigation titles;
- unparameterised listing routes;
- MeitYStartupHub as an entity title;
- non-success HTTP evidence.

## Date-role repair

Dates are retained as application dates only when supported by explicit
opening or deadline language. Footer dates such as `Last Updated On`,
copyright dates, page-update dates, and visitor counters are removed from
opening and closing date fields.

## Document-role repair

Raw filenames and PDF paths are never canonical scheme titles. Documents
are classified as evidence roles, including:

- administrative approval;
- programme guideline;
- brochure;
- selected-startup list;
- incubation-centre list;
- success story;
- implementation report;
- result notice;
- call document;
- supporting evidence.

## Canonical identity consolidation

Aliases and duplicate evidence are merged into programme and call families.
Known permanent families include GENESIS, SASACT, SAMRIDH, TIDE 2.0,
XR Startup Program, CREST Semiconductor Accelerator, and MathWorks Startup
Program.

Known challenge families such as BHUMI and DRISHTI are kept as calls or
historical challenge identities, not permanent schemes.

## Outputs

- purified programme families;
- purified calls and challenges;
- purified historical events;
- supporting documents;
- excluded and error pages;
- identity and role review queue;
- source-candidate disposition ledger;
- purified Admin-review CSV and JSON;
- signed purification manifest.

Every source candidate is assigned exactly one disposition. Consolidation
reduces duplicate review records without deleting source evidence.

## Governance

- No database write.
- No publication.
- No Apply actions.
- No Admin decision import.
- Existing public identities are preserved as evidence and reconciled.
