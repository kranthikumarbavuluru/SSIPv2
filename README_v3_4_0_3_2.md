# SSIP v3.4.0.3.2 — DST Direct Target Matching and Provisional Inventory Quality Hotfix

## Purpose

This hotfix corrects the field interpretation used in v3.4.0.3.1:

- `CATEGORY_INDEX_DISCOVERY_GAP.source_url` is the **target page URL under review**.
- The source category/index page is recovered by reverse-matching `link_graph.to_url` to `link_graph.from_url`.

It also re-audits every provisional DST scheme/programme before v3.4.0.4 so that generic pages such as `Archive`, `About the Schemes`, and `Funding Mechanism` cannot become identity-lock candidates.

## Safety guarantees

- No network access.
- No DST recrawl.
- No source file modification.
- No canonical scheme/programme name creation.
- No identity locking.
- No call page can become a permanent entity.
- Generic/index/supporting pages are removed from the corrected provisional inventory.

## Required inputs

```text
data/departments/dst/v3_4_0_3/
  dst_identity_review_queue_v3_4_0_3.csv
  dst_provisional_scheme_inventory_v3_4_0_3.csv
  dst_provisional_programme_inventory_v3_4_0_3.csv
  dst_scheme_alias_candidates_v3_4_0_3.csv

data/departments/dst/v3_4_0_2/
  dst_classified_pages_v3_4_0_2.csv

data/departments/dst/v3_4_0_1/crawl/
  dst_link_graph_v3_4_0_1.csv
```

## Install

Extract the bundle into the SSIP project root:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Install test requirements:

```powershell
python -m pip install -r .\requirements-v3_4_0_3_2.txt
```

## Compile

```powershell
python -m py_compile `
  .\scripts\dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py
```

## Self-test

```powershell
python `
  .\scripts\dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py `
  --self-test
```

The final field must be:

```json
"self_test_passed": true
```

## Automated tests

```powershell
python -m pytest `
  .\tests\test_dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py `
  -q
```

Expected:

```text
5 passed
```

## Dry run

```powershell
python `
  .\scripts\dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_direct_target_quality_rules_v3_4_0_3_2.json `
  --dry-run
```

Expected input counts should include approximately:

```text
review_rows              : 476
category_gap_rows        : 443
unique_category_gaps     : 114
duplicate_gap_occurrences: 329
provisional_schemes      : 6
provisional_programmes   : 27
classified_pages         : 418
link_graph_rows          : 41086
```

The dry run also reports a `direct_target_match_preview`. This should be close to the number of unique category gaps.

## Production run

```powershell
python `
  .\scripts\dst_direct_target_inventory_quality_hotfix_v3_4_0_3_2.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_direct_target_quality_rules_v3_4_0_3_2.json `
  --strict
```

Strict mode exits with code `3` if the validation gate fails. Output files are still written for audit.

## Outputs

```text
data/departments/dst/v3_4_0_3_2/
  dst_direct_target_matches_v3_4_0_3_2.csv
  dst_recovered_category_lineage_v3_4_0_3_2.csv
  dst_existing_entity_gap_matches_v3_4_0_3_2.csv
  dst_possible_new_scheme_pages_v3_4_0_3_2.csv
  dst_possible_new_programme_pages_v3_4_0_3_2.csv
  dst_gap_non_entity_pages_v3_4_0_3_2.csv
  dst_true_broken_targets_v3_4_0_3_2.csv
  dst_gap_duplicates_v3_4_0_3_2.csv
  dst_corrected_provisional_schemes_v3_4_0_3_2.csv
  dst_corrected_provisional_programmes_v3_4_0_3_2.csv
  dst_provisional_entity_downgrades_v3_4_0_3_2.csv
  dst_identity_review_queue_v3_4_0_3_2.csv
  dst_hotfix_audit_v3_4_0_3_2.csv
  dst_hotfix_validation_v3_4_0_3_2.json
  dst_hotfix_summary_v3_4_0_3_2.json
```

## Category-gap decisions

```text
EXISTING_PROVISIONAL_ENTITY
POSSIBLE_NEW_SCHEME
POSSIBLE_NEW_PROGRAMME
CATEGORY_OR_INDEX_PAGE
SUPPORTING_PAGE
ACCESSIBILITY_OR_NAVIGATION_PAGE
CALL_OR_TEMPORARY_OPPORTUNITY
NEWS_EVENT_OR_RECRUITMENT
BROKEN_OFFICIAL_LINK
UNRESOLVED
```

## Provisional-entity quality decisions

```text
KEEP_AS_PROVISIONAL_SCHEME
KEEP_AS_PROVISIONAL_PROGRAMME
RECLASSIFY_SCHEME_TO_PROGRAMME
RECLASSIFY_PROGRAMME_TO_SCHEME
DOWNGRADE_TO_CATEGORY_INDEX
DOWNGRADE_TO_SUPPORTING_PAGE
DOWNGRADE_TO_ARCHIVE
DOWNGRADE_TO_CALL_OR_TEMPORARY_PAGE
DOWNGRADE_TO_NON_SCHEME_PAGE
ADMIN_REVIEW
```

## Validation gate

The default gate requires:

```text
Direct target match rate   >= 95%
Unresolved unique-gap rate <= 10%
All provisional entities audited
All gap occurrences accounted for
Generic corrected lock candidates = 0
Call contamination = 0
Forbidden identity fields = 0
Canonical identities created = 0
Identity locks created = 0
```

Successful validation ends with:

```json
{
  "hotfix_validation_passed": true,
  "ready_for_v3_4_0_4": true
}
```

## Review commands

Summary:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3_2\dst_hotfix_summary_v3_4_0_3_2.json `
  -Encoding UTF8
```

Validation:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3_2\dst_hotfix_validation_v3_4_0_3_2.json `
  -Encoding UTF8
```

Provisional downgrades:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_2\dst_provisional_entity_downgrades_v3_4_0_3_2.csv |
Select-Object `
  proposed_canonical_name,
  original_proposed_entity_type,
  quality_decision,
  quality_confidence,
  quality_reasons,
  official_source_url |
Format-List
```

Corrected scheme inventory:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_2\dst_corrected_provisional_schemes_v3_4_0_3_2.csv |
Select-Object `
  proposed_canonical_name,
  quality_decision,
  quality_confidence,
  quality_review_flags,
  official_source_url |
Format-Table -AutoSize
```

Corrected programme inventory:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_2\dst_corrected_provisional_programmes_v3_4_0_3_2.csv |
Select-Object `
  proposed_canonical_name,
  quality_decision,
  quality_confidence,
  quality_review_flags,
  official_source_url |
Format-Table -AutoSize
```

Possible missing schemes/programmes:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_2\dst_possible_new_scheme_pages_v3_4_0_3_2.csv |
Format-List target_page_title,target_page_role,classification_confidence,classification_reasons,target_url

Import-Csv `
  .\data\departments\dst\v3_4_0_3_2\dst_possible_new_programme_pages_v3_4_0_3_2.csv |
Format-List target_page_title,target_page_role,classification_confidence,classification_reasons,target_url
```

## Next phase

After the summary and validation are approved, proceed to:

```text
SSIP v3.4.0.4 — DST Canonical Identity Lock and Curated Review
```

v3.4.0.4 must consume the corrected scheme/programme inventories and the v3.4.0.3.2 identity review queue—not the original uncorrected 33-entity inventory.
