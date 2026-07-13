# SSIP v3.4.0.3 — Permanent DST Scheme and Programme Inventory Builder

## Purpose

This phase converts the evidence-based page roles from v3.4.0.2 into a **provisional permanent inventory** of DST schemes and programmes.

It does **not** lock canonical names. Final approval and identity locking are reserved for **v3.4.0.4 — DST Canonical Identity Lock and Curated Review**.

## Critical identity rule

A time-bound call, application invitation, deadline extension, corrigendum, result, cohort, round or yearly opportunity cannot create or rename a permanent scheme.

Only pages classified as:

- `SCHEME_MASTER_CANDIDATE`
- `PROGRAMME_MASTER_CANDIDATE`

can seed provisional permanent entities.

A title such as:

```text
Call for Proposals under Technology Development Programme 2026
```

is blocked from the permanent inventory. It will later be linked as a call under the locked programme.

## Inputs

From v3.4.0.2:

```text
data\departments\dst\v3_4_0_2\
  dst_classified_pages_v3_4_0_2.csv
  dst_classified_documents_v3_4_0_2.csv
```

From v3.4.0.1:

```text
data\departments\dst\v3_4_0_1\crawl\
  dst_link_graph_v3_4_0_1.csv
```

## Outputs

```text
data\departments\dst\v3_4_0_3\
  dst_provisional_scheme_inventory_v3_4_0_3.csv
  dst_provisional_programme_inventory_v3_4_0_3.csv
  dst_scheme_alias_candidates_v3_4_0_3.csv
  dst_programme_hierarchy_candidates_v3_4_0_3.csv
  dst_master_source_evidence_v3_4_0_3.csv
  dst_rejected_master_candidates_v3_4_0_3.csv
  dst_identity_review_queue_v3_4_0_3.csv
  dst_inventory_audit_v3_4_0_3.csv
  dst_inventory_validation_v3_4_0_3.json
  dst_inventory_summary_v3_4_0_3.json
```

## Main behavior

The builder:

1. reads only local classification outputs;
2. selects scheme and programme master-page candidates;
3. proposes permanent names conservatively;
4. extracts official abbreviation candidates from titles or body evidence;
5. attaches category-index and official-document evidence;
6. detects exact normalized duplicates and merges them as additional sources;
7. creates unresolved programme-hierarchy candidates;
8. sends ambiguous identities and category discovery gaps to review;
9. rejects call-like and time-bound titles from the permanent inventory;
10. keeps every identity in `PROVISIONAL_NOT_LOCKED` state.

## Installation

Copy the bundle into:

```text
D:\WebSite\DASHBOARD\Code\SSIP
```

Install test requirements:

```powershell
python -m pip install -r .\requirements-v3_4_0_3.txt
```

## Compile

```powershell
python -m py_compile `
  .\scripts\dst_permanent_inventory_builder_v3_4_0_3.py
```

## Self-test

```powershell
python `
  .\scripts\dst_permanent_inventory_builder_v3_4_0_3.py `
  --self-test
```

Expected:

```json
{
  "self_test_passed": true
}
```

## Automated tests

```powershell
python -m pytest `
  .\tests\test_dst_permanent_inventory_builder_v3_4_0_3.py `
  -q
```

## Dry run

```powershell
python `
  .\scripts\dst_permanent_inventory_builder_v3_4_0_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_permanent_inventory_rules_v3_4_0_3.json `
  --dry-run
```

The dry run verifies input discovery and prints candidate counts without writing files.

## Production run

```powershell
python `
  .\scripts\dst_permanent_inventory_builder_v3_4_0_3.py `
  --project-root "D:\WebSite\DASHBOARD\Code\SSIP" `
  --config .\config\dst_permanent_inventory_rules_v3_4_0_3.json `
  --strict
```

Exit codes:

- `0`: completed and validation passed;
- `1`: execution or input error;
- `2`: self-test failure;
- `3`: outputs generated but strict validation failed.

## Review commands

Summary:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3\dst_inventory_summary_v3_4_0_3.json `
  -Encoding UTF8
```

Validation:

```powershell
Get-Content `
  .\data\departments\dst\v3_4_0_3\dst_inventory_validation_v3_4_0_3.json `
  -Encoding UTF8
```

Provisional schemes:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3\dst_provisional_scheme_inventory_v3_4_0_3.csv |
Select-Object `
  proposed_canonical_name,
  official_abbreviation_candidate,
  identity_confidence,
  review_flags,
  official_source_url |
Format-Table -AutoSize
```

Provisional programmes:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3\dst_provisional_programme_inventory_v3_4_0_3.csv |
Select-Object `
  proposed_canonical_name,
  proposed_subtype,
  official_abbreviation_candidate,
  identity_confidence,
  review_flags,
  official_source_url |
Format-Table -AutoSize
```

Rejected or merged candidates:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3\dst_rejected_master_candidates_v3_4_0_3.csv |
Select-Object `
  page_title,
  page_role,
  rejection_reason,
  details,
  final_url |
Format-List
```

Identity review queue:

```powershell
Import-Csv `
  .\data\departments\dst\v3_4_0_3\dst_identity_review_queue_v3_4_0_3.csv |
Select-Object `
  review_type,
  proposed_canonical_name,
  proposed_entity_type,
  identity_confidence,
  review_flags,
  recommended_action,
  source_url |
Format-List
```

## Approval gate

Proceed to v3.4.0.4 only when:

```json
{
  "inventory_validation_passed": true,
  "ready_for_v3_4_0_4": true
}
```

The number of provisional schemes/programmes is not yet the final public count. v3.4.0.4 will curate names, aliases, entity types, historical lineage and hierarchy before locking identities.
