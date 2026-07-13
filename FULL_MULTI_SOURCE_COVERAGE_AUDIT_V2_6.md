# SSIP Full Multi-Source Coverage Audit v2.6

## What was implemented

The audit is a read-only reconciliation across:

1. `data/discovery_results_v2.json`
2. `data/classified_candidates_v1.json`
3. `data/scheme_master_candidates_v1.json`
4. `data/extracted_scheme_records_v2_3.json` with v1 fallback
5. `data/validated_scheme_records_v2_4.json` with v1 fallback
6. `database/ssip_staging_v1.db`
7. Legacy discovery inventory in `database/ssip.db`

No staging, review, rejection, discovery, or master data is inserted, updated, or deleted.
SQLite databases are opened with `mode=ro` and `PRAGMA query_only = ON`.

## New implementation files

- `ssip_agents/coverage_audit_agent_v2_6.py`
- `tests/test_coverage_audit_v2_6.py`
- `FULL_MULTI_SOURCE_COVERAGE_AUDIT_V2_6.md`

## Generated audit reports

- `data/audit/multi_source_coverage_audit_v2_6.json`
- `data/audit/multi_source_coverage_audit_v2_6.csv`
- `data/audit/source_coverage_summary_v2_6.csv`
- `data/audit/missing_pipeline_records_v2_6.csv`
- `data/audit/master_pipeline_backlog_v2_6.csv`
- `data/audit/coverage_audit_summary_v2_6.json`
- `data/audit/coverage_audit_summary_v2_6.txt`

The `data/audit/current_v2_only/` folder contains the same reports without the legacy `discovered_links` backlog.

## Windows commands

From:

```bat
D:\WebSite\DASHBOARD\Code\SSIP
```

Run the self-test:

```bat
python -m tests.test_coverage_audit_v2_6
```

Run the complete audit, including legacy discovered URLs:

```bat
python -m ssip_agents.coverage_audit_agent_v2_6 --project-root .
```

Run only against the current Discovery Agent v2 inventory:

```bat
python -m ssip_agents.coverage_audit_agent_v2_6 --project-root . --no-legacy-discovery --output-dir data\audit\current_v2_only
```

Print machine-readable console JSON:

```bat
python -m ssip_agents.coverage_audit_agent_v2_6 --project-root . --json-console
```

## Current production audit result

### Master-level pipeline state

- Master candidates: **34**
- Extracted: **16**
- Validated: **16**
- Staged: **9**
- Rejected: **7**
- Awaiting admin review: **0**
- Unextracted master candidates: **18**
- Terminal master coverage: **47.06%**
- Publication coverage: **26.47%**

Coverage is calculated as:

```text
(staged masters + rejected masters) / all master candidates
```

A closed call is not marked missing merely because its deadline has passed. Historical calls and supporting documents can be attached to a scheme family without becoming separate dashboard schemes.

### Current v2 source coverage

| Source | Unique v2 URLs | Masters | Terminal Masters | Coverage |
|---|---:|---:|---:|---:|
| Startup India | 21 | 3 | 3 | 100.00% |
| MSME | 0 | 0 | 0 | 0.00% |
| DST | 34 | 8 | 5 | 62.50% |
| BIRAC | 101 | 17 | 2 | 11.76% |
| MeitY Startup Hub | 6 | 6 | 6 | 100.00% |

### Important interpretation

1. **MSME is not covered.** There is no MSME discovery URL, classification record, or master candidate in the current artifacts.
2. **BIRAC is the largest current pipeline gap.** Fifteen BIRAC masters remain unextracted.
3. **DST has three unextracted masters.**
4. **Four classified scheme-like URLs are not attached to a master candidate.** These require classification/grouping review before extraction.
5. **MeitY completed the technical pipeline, but all six MeitY records were rejected by admin review.** Technical coverage is 100%, while publication coverage is 0%.
6. **Startup India has complete terminal processing for its three current master candidates**, but one record was rejected, so only two are staged.
7. The legacy `ssip.db` contains hundreds of discovered URLs that were never migrated into the current classification pipeline. The full audit reports these separately as `legacy_only_urls` and primarily categorizes them as `CLASSIFICATION_UNCERTAIN`.

## Eighteen master candidates awaiting extraction

The exact list is in:

```text
data\audit\master_pipeline_backlog_v2_6.csv
```

Summary:

- BIRAC: 15 masters
- DST: 3 masters

The next extraction process should operate by `master_id`, not separately on all 98 member URLs. Each master can contain historical calls, guideline PDFs, result pages, and a current/core programme page.

## Four scheme-like URLs missing from a master

- BIRAC call: `https://birac.nic.in/cfp_view.php?id=14&scheme_type=1`
- BIRAC call: `https://birac.nic.in/cfp_view.php?id=75&scheme_type=37`
- DST fellowship: `https://dst.gov.in/callforproposals/bhaskara-advanced-solar-energy-fellowship-program`
- DST fellowship: `https://dst.gov.in/callforproposals/unescopoland-co-sponsored-fellowship-programme-engineering-cycle-2017`

These should be reviewed before automatically creating new masters because some may be historical calls or supporting evidence for an existing programme family.

## Database verification commands

Confirm final database counts:

```bat
python -c "import sqlite3; db=r'database\ssip_staging_v1.db'; con=sqlite3.connect(db); c=con.cursor(); print('Staged:',c.execute('SELECT COUNT(*) FROM scheme_staging').fetchone()[0]); print('Review statuses:',c.execute('SELECT review_status,COUNT(*) FROM admin_review_queue GROUP BY review_status').fetchall()); print('Rejected:',c.execute('SELECT COUNT(*) FROM rejected_scheme_records').fetchone()[0]); print('Actions:',c.execute('SELECT COUNT(*) FROM admin_review_actions').fetchone()[0]); con.close()"
```

Expected current result:

```text
Staged: 9
Review statuses: [('APPROVED', 5), ('REJECTED', 7)]
Rejected: 7
Actions: 16
```

Confirm source-level staged/rejected counts:

```bat
python -c "import sqlite3; con=sqlite3.connect(r'database\ssip_staging_v1.db'); c=con.cursor(); print('Staged:',c.execute('SELECT source,COUNT(*) FROM scheme_staging GROUP BY source ORDER BY source').fetchall()); print('Rejected:',c.execute('SELECT source,COUNT(*) FROM rejected_scheme_records GROUP BY source ORDER BY source').fetchall()); con.close()"
```

## Safest next step

Do **not** run a broad automatic database backfill yet.

The safest next implementation phase is:

```text
Multi-Source Incremental Extraction Backfill v2.7
```

It should:

1. Read only the 18 `AWAITING_EXTRACTION` masters from `master_pipeline_backlog_v2_6.csv`.
2. Process BIRAC first, then DST.
3. Select the best core/current URL per master while using historical calls and guideline PDFs only as supporting evidence.
4. Preserve all 16 already extracted/validated records.
5. Generate new extraction outputs without staging them automatically.
6. Run validation and admin review as separate explicit phases.
7. Add an official MSME seed/discovery phase separately; do not mix MSME discovery with the 18-master extraction backfill.
