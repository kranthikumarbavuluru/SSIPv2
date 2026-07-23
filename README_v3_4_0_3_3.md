# SSIP v3.4.0.3.3 — DST Navigation-Aware Gap Filtering and Selective Target Crawl

## Purpose

This phase resolves the remaining DST category-discovery gaps without repeating the full department crawl.

It performs two controlled stages:

1. **Offline navigation-aware filtering** — closes global navigation, accessibility, supporting, call and existing-entity links without network access.
2. **Selective depth-0 crawl** — fetches only high-value internal DST targets that appeared in the main content of a scheme/programme category page and carry scheme/programme naming evidence.

The phase preserves the corrected v3.4.0.3.2 provisional inventory and never creates or locks canonical identities.

## Safety guarantees

- No recursive crawl; selective crawl depth is always `0`.
- Existing v3.4.0.1 through v3.4.0.3.2 files are not modified.
- Calls, years, rounds, deadline extensions and results cannot become permanent scheme/programme candidates.
- Generic navigation and supporting pages cannot enter the final corrected inventory.
- Existing corrected provisional schemes/programmes, downgrades and entity-quality review rows remain accounted for.
- `scheme_id`, `programme_id`, canonical names and identity-lock fields are prohibited.
- Selective crawl progress is resumable from the existing v3.4.0.3.3 crawled-target output.

## Inputs

The script reads:

```text
data/departments/dst/v3_4_0_3_2/
  dst_direct_target_matches_v3_4_0_3_2.csv
  dst_identity_review_queue_v3_4_0_3_2.csv
  dst_gap_duplicates_v3_4_0_3_2.csv
  dst_corrected_provisional_schemes_v3_4_0_3_2.csv
  dst_corrected_provisional_programmes_v3_4_0_3_2.csv
  dst_provisional_entity_downgrades_v3_4_0_3_2.csv
  dst_unresolved_target_link_context_audit.csv     # optional

data/departments/dst/v3_4_0_2/
  dst_classified_pages_v3_4_0_2.csv

data/departments/dst/v3_4_0_1/crawl/
  dst_link_graph_v3_4_0_1.csv
```

If `dst_unresolved_target_link_context_audit.csv` is absent, link-context statistics are rebuilt from the link graph.

## Installation

Extract the bundle into the SSIP project root:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Install dependencies:

```powershell
python -m pip install -r .\requirements-v3_4_0_3_3.txt
```

## Verification

Compile:

```powershell
python -m py_compile `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py
```

Self-test:

```powershell
python `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  --self-test
```

Automated tests:

```powershell
python -m pytest `
  .\tests\test_dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  -q
```

## Stage 1 — Dry run

```powershell
python `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_navigation_aware_gap_rules_v3_4_0_3_3.json `
  --dry-run
```

Review these preview values:

```text
global_navigation_gaps
supporting_information_gaps
selective_crawl_queue
offline_unresolved_review_rows
```

## Stage 2 — Prepare the queue without network access

```powershell
python `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_navigation_aware_gap_rules_v3_4_0_3_3.json `
  --prepare-only
```

Do not use `--strict` during queue preparation. A non-empty queue intentionally means the phase is not yet ready for v3.4.0.4.

Inspect the queue:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_3\dst_selective_crawl_queue_v3_4_0_3_3.csv |
Select-Object `
  proposed_name,
  target_url,
  main_content_occurrences,
  max_relevance_score,
  source_page_roles,
  crawl_reason |
Format-Table -AutoSize -Wrap
```

## Stage 3 — Controlled selective crawl

Fetch up to ten queue targets:

```powershell
python `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_navigation_aware_gap_rules_v3_4_0_3_3.json `
  --run-selective-crawl `
  --max-targets 10
```

This run may remain not-ready because unprocessed queue targets are intentionally left for the next run. Completed targets are saved and skipped on later runs.

Review fetched targets:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_3\dst_selectively_crawled_targets_v3_4_0_3_3.csv |
Select-Object `
  page_title,
  fetched_classification,
  fetched_confidence,
  http_status,
  final_url,
  crawl_error |
Format-Table -AutoSize -Wrap
```

## Stage 4 — Complete the selective crawl

```powershell
python `
  .\scripts\dst_navigation_aware_gap_selective_crawl_v3_4_0_3_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_navigation_aware_gap_rules_v3_4_0_3_3.json `
  --run-selective-crawl `
  --strict
```

The script reuses prior successful selective fetches and fetches only remaining queue targets.

## Outputs

```text
data/departments/dst/v3_4_0_3_3/
  dst_gap_link_context_v3_4_0_3_3.csv
  dst_global_navigation_gaps_v3_4_0_3_3.csv
  dst_supporting_information_gaps_v3_4_0_3_3.csv
  dst_selective_crawl_queue_v3_4_0_3_3.csv
  dst_selectively_crawled_targets_v3_4_0_3_3.csv
  dst_possible_new_scheme_pages_v3_4_0_3_3.csv
  dst_possible_new_programme_pages_v3_4_0_3_3.csv
  dst_non_entity_gap_resolutions_v3_4_0_3_3.csv
  dst_true_broken_targets_v3_4_0_3_3.csv
  dst_final_corrected_schemes_v3_4_0_3_3.csv
  dst_final_corrected_programmes_v3_4_0_3_3.csv
  dst_final_gap_review_queue_v3_4_0_3_3.csv
  dst_gap_resolution_audit_v3_4_0_3_3.csv
  dst_gap_resolution_validation_v3_4_0_3_3.json
  dst_gap_resolution_summary_v3_4_0_3_3.json
  snapshots/html/*.html.gz
```

## Validation gate

The phase is approved only when:

```text
All unique gaps are classified
All duplicate occurrences are accounted for
Global navigation is filtered without crawling
Every selective crawl target is processed
Final unresolved rate <= 5%
Gap resolution rate >= 95%
Call contamination = 0
Generic lock candidates = 0
Canonical identities created = 0
Identity locks created = 0
```

Successful validation contains:

```json
{
  "gap_resolution_validation_passed": true,
  "ready_for_v3_4_0_4": true
}
```

## Review commands

Summary:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3_3\dst_gap_resolution_summary_v3_4_0_3_3.json `
  -Encoding UTF8
```

Validation:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3_3\dst_gap_resolution_validation_v3_4_0_3_3.json `
  -Encoding UTF8
```

New provisional scheme discoveries:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_3\dst_possible_new_scheme_pages_v3_4_0_3_3.csv |
Format-List *
```

New provisional programme discoveries:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_3\dst_possible_new_programme_pages_v3_4_0_3_3.csv |
Format-List *
```

Final review queue:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3_3\dst_final_gap_review_queue_v3_4_0_3_3.csv |
Select-Object `
  review_type,
  proposed_name,
  confidence,
  review_flags,
  recommended_action,
  source_url |
Format-List
```

## Next phase

After successful validation, proceed to:

```text
SSIP v3.4.0.4 — DST Canonical Identity Lock and Curated Review
```
