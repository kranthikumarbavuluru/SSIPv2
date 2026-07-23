# SSIP v3.4.0.2 — DST Evidence-Based Page-Role Classifier

## Purpose

This phase classifies the DST pages and documents prepared by v3.4.0.1.1. It uses:

- URL and page title;
- recovered main page text;
- crawler source and page-role hints;
- the v3.4.0.1.1 call-pattern audit;
- the v3.4.0.1 link graph;
- document filename, anchor text, source page and enriched document hints.

It does **not** create permanent scheme records. The following fields are forbidden in all outputs:

```text
scheme_id
canonical_scheme_name
locked_scheme_name
canonical_programme_name
programme_id
```

A time-bound call remains a call. The classifier may extract `possible_parent_name_text` only when the source explicitly states that the call is under a scheme or programme.

## Files

```text
scripts/
  dst_evidence_page_role_classifier_v3_4_0_2.py
config/
  dst_page_role_classifier_rules_v3_4_0_2.json
tests/
  test_dst_evidence_page_role_classifier_v3_4_0_2.py
requirements-v3_4_0_2.txt
README_v3_4_0_2.md
```

## Inputs

From v3.4.0.1.1:

```text
data/departments/dst/v3_4_0_1_1/
  dst_crawled_pages_enriched_v3_4_0_1_1.csv
  dst_documents_enriched_v3_4_0_1_1.csv
  dst_call_pattern_audit_v3_4_0_1_1.csv
```

From v3.4.0.1:

```text
data/departments/dst/v3_4_0_1/crawl/
  dst_link_graph_v3_4_0_1.csv
```

## Page roles

```text
SCHEME_MASTER_CANDIDATE
PROGRAMME_MASTER_CANDIDATE
SCHEME_CATEGORY_INDEX
PROGRAMME_CATEGORY_INDEX
CALL_FOR_PROPOSALS
APPLICATION_INVITATION
EXPRESSION_OF_INTEREST
DEADLINE_EXTENSION
CALL_CORRIGENDUM
CALL_RESULT
CALL_ARCHIVE_INDEX
CURRENT_CALL_INDEX
GUIDELINE_PAGE
APPLICATION_GUIDANCE
SANCTIONED_PROJECT_EVIDENCE
NOTIFICATION
OFFICE_MEMORANDUM
NEWS
EVENT
RECRUITMENT
CONTACT_PAGE
GENERAL_INFORMATION
BROKEN_OFFICIAL_LINK
NON_SCHEME
UNKNOWN
```

## Classification method

The classifier uses two layers.

### 1. Structural rules

High-certainty structures are classified first:

- HTTP failures → `BROKEN_OFFICIAL_LINK`;
- archived call index → `CALL_ARCHIVE_INDEX`;
- current call index → `CURRENT_CALL_INDEX`;
- root scheme/programme index → `SCHEME_CATEGORY_INDEX`;
- contact and recruitment pages → their explicit roles.

### 2. Evidence scoring

Remaining pages are scored using:

- crawler hints;
- explicit call language;
- call URL paths;
- proposal dates and submission language;
- objective, eligibility, assistance, application, beneficiaries, duration and scope sections;
- scheme/programme terms in titles and paths;
- number and type of internal links;
- guideline, notification, office memorandum and sanctioned-project language;
- news, event, procurement and general-information indicators.

The output stores:

```text
page_role
page_role_confidence
page_role_score
second_best_role
second_best_score
scheme_evidence_score
call_evidence_score
possible_parent_name_text
classification_reasons
review_flags
requires_admin_review
```

Low-confidence and close-score cases are retained in the review queue rather than silently discarded.

## Installation

Extract the bundle into the SSIP project root:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Install the optional test dependency:

```powershell
python -m pip install -r .\requirements-v3_4_0_2.txt
```

The production classifier itself uses only the Python standard library.

## Compile

```powershell
python -m py_compile `
  .\scripts\dst_evidence_page_role_classifier_v3_4_0_2.py
```

## Self-test

```powershell
python `
  .\scripts\dst_evidence_page_role_classifier_v3_4_0_2.py `
  --self-test
```

Expected:

```json
{
  "service_version": "3.4.0.2",
  "department": "DST",
  "self_test_passed": true
}
```

## Pytest

```powershell
python -m pytest `
  .\tests\test_dst_evidence_page_role_classifier_v3_4_0_2.py `
  -q
```

Expected:

```text
4 passed
```

## Dry run

```powershell
python `
  .\scripts\dst_evidence_page_role_classifier_v3_4_0_2.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_page_role_classifier_rules_v3_4_0_2.json `
  --dry-run
```

The dry run verifies that all required inputs exist and reports input counts. It writes no files.

## Production run

```powershell
python `
  .\scripts\dst_evidence_page_role_classifier_v3_4_0_2.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_page_role_classifier_rules_v3_4_0_2.json `
  --strict
```

No network access is used. Existing v3.4.0.1 and v3.4.0.1.1 files are not modified.

## Outputs

```text
data/departments/dst/v3_4_0_2/
  dst_classified_pages_v3_4_0_2.csv
  dst_classified_documents_v3_4_0_2.csv
  dst_scheme_master_page_candidates_v3_4_0_2.csv
  dst_programme_master_page_candidates_v3_4_0_2.csv
  dst_call_pages_v3_4_0_2.csv
  dst_supporting_pages_v3_4_0_2.csv
  dst_non_scheme_pages_v3_4_0_2.csv
  dst_unknown_review_queue_v3_4_0_2.csv
  dst_classifier_audit_v3_4_0_2.csv
  dst_classifier_validation_v3_4_0_2.json
  dst_classifier_summary_v3_4_0_2.json
```

## Validation gates

The strict run returns exit code `3` when any required gate fails. Gates include:

- all page and document rows preserved;
- every page has a valid role and confidence;
- every document has a role;
- unknown-page rate does not exceed the configured limit;
- no forbidden scheme-identity fields are produced;
- no crawler `CALL_CANDIDATE` is promoted to a master-page candidate.

A successful validation contains:

```json
{
  "classifier_validation_passed": true,
  "ready_for_v3_4_0_3": true
}
```

## Review commands

Summary:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_2\dst_classifier_summary_v3_4_0_2.json `
  -Encoding UTF8
```

Validation:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_2\dst_classifier_validation_v3_4_0_2.json `
  -Encoding UTF8
```

Review queue:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_2\dst_unknown_review_queue_v3_4_0_2.csv |
Select-Object `
  page_id,
  page_title,
  page_role,
  page_role_confidence,
  second_best_role,
  classification_reasons,
  review_flags,
  final_url |
Format-List
```

Master-page candidates:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_2\dst_scheme_master_page_candidates_v3_4_0_2.csv |
Select-Object page_title,page_role_confidence,scheme_evidence_score,review_flags,final_url |
Format-Table -AutoSize

Import-Csv `
  .\data\departments\dst\v3_4_0_2\dst_programme_master_page_candidates_v3_4_0_2.csv |
Select-Object page_title,page_role_confidence,scheme_evidence_score,review_flags,final_url |
Format-Table -AutoSize
```

Call pages and explicit parent-name evidence:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_2\dst_call_pages_v3_4_0_2.csv |
Select-Object `
  page_title,
  page_role,
  possible_parent_name_text,
  page_role_confidence,
  review_flags,
  final_url |
Format-Table -AutoSize
```

## Next phase

Only after this phase passes should SSIP start:

```text
v3.4.0.3 — Permanent DST Scheme Inventory Builder
```

That later phase may propose permanent scheme entities. It must continue to keep time-bound calls separate from permanent scheme identity.
