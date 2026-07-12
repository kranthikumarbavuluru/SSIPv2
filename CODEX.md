# SSIP Project Guide for Codex

## 1. Mission

SSIP is the **Startup Scheme Intelligence Platform**.

The project goal is to continuously discover, understand, verify, curate and
publish government opportunities relevant to:

- startups;
- innovators and technology developers;
- researchers and research-led ventures;
- MSMEs where the opportunity is relevant to innovation or startup growth;
- incubators, accelerators and entrepreneurship-support institutions; and
- academic or research institutions participating in the startup ecosystem.

The platform must cover:

1. **Central Government of India** ministries, departments, agencies, boards,
   missions, public bodies and official programme portals.
2. **State Governments**, with **Andhra Pradesh as the first state priority**.
3. Other Indian states and union territories as the platform expands.

The opportunities include schemes, programmes, grants, funds, subsidies,
fellowships, challenges, competitions, innovation programmes, procurement or
pilot opportunities, incubation support and time-bound application calls.

**DST is the first reference implementation. It is not the limit of SSIP.**
The DST workflow must become a reusable pattern for every relevant ministry,
department and state-government organisation.

## 2. Primary Outcome

The public dashboard should help a user answer four questions accurately:

1. What government support programme exists for me?
2. Is there a live application call under that programme?
3. Am I or my organisation likely to be eligible?
4. Where is the official evidence and application page?

No record should be published merely because an automated crawler found a page.
Publication requires verified identity, official evidence, correct record type,
application status and human-governed approval.

## 3. Geographic and Institutional Priorities

Work in the following order unless the user changes the priority:

1. Central Government startup and innovation ecosystem.
2. Government of Andhra Pradesh startup and innovation ecosystem.
3. Remaining state and union-territory ecosystems.

Likely Central Government coverage includes, but is not limited to, DST, MeitY,
DPIIT, DBT, BIRAC, TDB, DSIR, MSME, AIM/NITI Aayog, MoE, AICTE, MoHUA, MoAFW,
MoFPI, MNRE, defence innovation bodies, space-sector bodies and other official
agencies that publish startup or innovator support.

Likely Andhra Pradesh coverage includes official state departments, missions,
corporations, innovation bodies, startup portals, incubator networks and
challenge or procurement portals. Organisation names must be confirmed from
official evidence before entering the catalogue.

These examples are discovery directions, not permission to invent catalogue
records or assume that an organisation currently operates a live opportunity.

## 4. Canonical Record Model

The following entities must remain separate.

### 4.1 Scheme or Programme

A durable government support mechanism with a stable purpose and identity.
Examples include an umbrella programme, recurring funding mechanism or ongoing
support framework.

### 4.2 Application Call

A time-bound invitation to apply under a scheme, programme, challenge or fund.
A call has its own identity, opening/closing dates, status and application URL.

Multiple annual, quarterly or thematic calls may point to one parent programme.
They must not be incorrectly stored as duplicate schemes.

### 4.3 Challenge or Competition

A time-bound problem statement, prize, hackathon, grand challenge, innovation
contest or similar opportunity. It may be linked to a parent programme but must
retain its own call identity.

### 4.4 Indirect Ecosystem Support

Funding or support where the direct applicant is an incubator, fund manager,
academic institution, accelerator, state body or other intermediary. These
records must not be presented as direct startup applications.

### 4.5 Historical Call

A genuine, official, closed call retained for research, trend analysis and
programme history. Historical calls must never display a live Apply action.

### 4.6 Supporting Document

Guidelines, manuals, PDFs, reports, results, notices and FAQs are evidence or
resources. They are not automatically schemes or calls.

### 4.7 Non-catalogue Page

Navigation pages, contact pages, laboratories, news indexes, generic archive
containers, search results and unrelated reports must be quarantined rather
than published as opportunities.

## 5. Department-Agent Strategy

Create a separate governed agent configuration for each ministry, department,
agency or state organisation. Shared framework code is preferred, but each
agent must have organisation-specific source knowledge.

Each department agent should define:

- official domains and allowed subdomains;
- organisation hierarchy and implementing bodies;
- authoritative scheme/programme index pages;
- current-call, archive, results and announcement pages;
- application portals and known redirects;
- crawl rules, pagination rules and document handling;
- programme aliases and stable programme identities;
- applicant terminology used by that organisation;
- sector vocabulary and organisation-specific technology themes;
- status and date evidence rules;
- expected update frequency;
- exclusions and common false positives; and
- escalation rules for ambiguous records.

The agent pipeline should be reusable:

1. Source Registry Agent
2. Discovery/Crawler Agent
3. Page Role Agent
4. Scheme and Call Identity Agent
5. Parent-Child Relationship Agent
6. Startup Relevance Agent
7. Eligibility and Applicant-Layer Agent
8. Sector Evidence Agent
9. Status and Date Verification Agent
10. Duplicate and Version Resolution Agent
11. Evidence Quality Agent
12. Admin Review and Publication Workflow

An agent may prepare a record, but it must not independently make the final
public publication decision.

## 6. Official-Source and Evidence Policy

Accuracy is more important than catalogue size.

Use primary official sources wherever possible:

- government ministry or department websites;
- official agency, board, mission or programme portals;
- official application portals;
- official government notifications and guidelines; and
- official state-government domains and authorised programme portals.

Secondary sources may help discover an opportunity but cannot be the sole basis
for publishing identity, eligibility, dates, funding or application status.

Every publishable record should preserve:

- canonical official URL;
- application URL, if separately available;
- guideline/manual URL, if available;
- source organisation;
- ministry and department relationship;
- evidence excerpts or structured evidence references;
- last verified date/time;
- extraction and verification method; and
- confidence or unresolved-field indicators.

Never invent a missing ministry, agency, sector, amount, date or eligibility
condition. Display missing information as missing or unverified.

## 7. Status Intelligence

Application status belongs to the **call**, not automatically to the parent
scheme or programme.

Use these status principles:

- **OPEN**: official evidence confirms applications are currently accepted.
- **UPCOMING**: official evidence provides a future opening window.
- **CLOSED**: the official deadline passed or the source explicitly says closed.
- **STATUS_UNVERIFIED**: evidence is insufficient, conflicting or undated.

An Apply button alone is a useful signal but should be reconciled with closing
dates, official notices and portal behaviour. A recurring scheme can remain an
active programme while its latest call is closed.

Store every recurring call separately. Do not overwrite an older call with a
new year or quarter. Link all calls to the stable parent programme.

## 8. Startup Relevance and Applicant Layer

Classify both relevance and who can directly apply.

Suggested relevance classes:

- `STARTUP_RELEVANT`
- `STARTUP_ECOSYSTEM_CALL`
- `REVIEW_REQUIRED`
- `GENERAL_GOVERNMENT_RDI`
- `NOT_RELEVANT`

Suggested applicant layers:

- startup or founder;
- innovator or individual;
- researcher or research team;
- MSME or company;
- incubator or accelerator;
- academic/research institution;
- fund manager or financial intermediary;
- government/state implementation partner; and
- unverified.

Do not label an incubator, fund-manager or institutional implementation call as
a direct startup opportunity. Preserve it in the ecosystem section when it is
relevant to the startup-support system.

## 9. Sector Intelligence

First determine whether an opportunity is:

- sector agnostic;
- multi-sector;
- sector specific; or
- not yet verified.

For sector-specific records, map sectors only from identifiable evidence such
as programme objectives, eligible technology areas, problem statements or
official priority themes. Preserve the source evidence behind the mapping.

Do not infer a sector only from a ministry name. For example, a department may
operate both broad innovation programmes and highly specialised thematic calls.

Sector mappings should use a controlled SSIP vocabulary while retaining the
original official terminology for audit and search.

## 10. Identity, Deduplication and Relationships

Build stable identities for organisations, programmes and calls.

Deduplication must consider:

- canonical URL and official identifiers;
- normalised title and aliases;
- parent programme;
- call year, round, quarter or cohort;
- opening and closing dates;
- problem statement or thematic scope;
- implementing agency; and
- supporting-document versus canonical-page role.

Similar titles do not always mean duplicates. The same programme may have many
valid call instances, and the same call may appear on an announcement page, PDF
guideline and application portal.

Use explicit relationships:

```text
Ministry
  -> Department / Agency / State Body
      -> Scheme or Umbrella Programme
          -> Application Call / Challenge / Cohort
              -> Guidelines, Notices, Results and Other Evidence
```

## 11. Governance and Publication

The governed lifecycle is:

```text
Discover -> Extract -> Classify -> Validate -> Curate -> Admin Review
         -> Approved Staging -> Publication Decision -> Public Dashboard
```

Review approval and publication are separate decisions.

- Review approval confirms that the identity, classification, relationships and
  evidence are acceptable for staging.
- Publication approval confirms that the staged record may appear publicly.
- Rejection and needs-more-evidence decisions must retain reasons and audit data.
- Bulk approval is appropriate only for a governed, deterministic batch with a
  signed manifest, exception checks and an approved sampling policy.

The admin must remain the final publication authority. Automated agents can
recommend, prioritise and detect anomalies but cannot silently publish records.

## 12. Historical Archive Governance

Large historical collections should use exception-based verification rather
than requiring an administrator to manually approve every clean record.

Required controls:

- supported official domains;
- individual-call identity;
- past closing date;
- confirmed closed status;
- duplicate detection;
- exclusion of current calls;
- exception queue;
- deterministic stratified human sample;
- signed qualification manifest;
- separate sample-review and publication actions; and
- complete audit trail.

The DST historical archive is the reference implementation. Its rules should be
generalised carefully for other departments because archive structures and date
evidence differ across organisations.

## 13. Public Dashboard Rules

The public interface must clearly separate:

- schemes and programmes;
- open and upcoming calls;
- closed startup calls;
- challenges and competitions;
- indirect ecosystem opportunities;
- historical calls; and
- manuals, guidelines and other resources.

Dashboard totals must be computed from governed data. Never hardcode metrics.

Every visible record should show, where available:

- name and record type;
- ministry, department and implementing agency;
- parent scheme/programme for calls;
- direct applicant layer;
- eligibility summary;
- sector classification;
- funding/support type and verified amount;
- opening and closing dates;
- application status and status basis;
- last verified date; and
- official evidence links.

Official links must open in a new tab. Historical records must not show active
application actions. Smart Match scores must be explainable from actual fields;
never display a fabricated AI score.

## 14. Current Project Structure

Important locations:

| Purpose | Location |
|---|---|
| Primary database | `database/ssip_staging_v1.db` |
| Public dashboard | `apps/public_dashboard_app_v2_9.py` |
| Admin review UI | `ui/admin_review_app_v1.py` |
| Dashboard modules | `ssip_dashboard/` |
| Department agents | `ssip_agents/` and `agents/` |
| Governance services | `services/` |
| Agent/source configuration | `config/` |
| Database migrations | `database/migrations/` |
| Department data | `data/departments/` |
| Tests | `tests/` |
| Public theme | `assets/dashboard_theme.css` |

Important database workflow tables include:

- `admin_review_queue` — records awaiting or undergoing review;
- `admin_review_actions` — review audit actions;
- `scheme_staging` — approved staged records; and
- historical archive batch, record and action tables installed by approved
  migrations.

Confirm the live schema before depending on any table or column. Do not assume
that documentation alone reflects the current database state.

## 15. DST Reference Implementation

The DST pilot currently demonstrates:

- programme-versus-call separation;
- parent programme mapping;
- current call detection;
- startup relevance and applicant-layer classification;
- sector evidence mapping;
- historical archive qualification;
- deterministic sample review;
- signed batch manifests; and
- separate admin review and publication decisions.

Relevant implementation areas include:

- `ssip_agents/dst_pilot/`
- `config/dst_department_agent_v1.json`
- `scripts/run_dst_pilot_v1.py`
- `ssip_dashboard/dst_pilot.py`
- `ssip_dashboard/dst_history.py`
- `services/dst_historical_archive_approval_v1.py`
- `scripts/build_dst_historical_archive_v1.py`
- `scripts/apply_dst_historical_archive_migration_v1.py`
- `data/departments/dst/`

Future department agents should reuse the governed design, not copy DST-specific
assumptions blindly.

## 16. Safe Development Rules

These rules are mandatory:

- Read `AGENTS.md` before making project changes.
- Inspect the current implementation before choosing an architecture.
- Keep database access read-only for public dashboard operations.
- Do not alter production/staging data without explicit user permission.
- Create migrations as separate files and obtain explicit approval before
  applying them.
- Never modify `backups/`.
- Do not delete existing scripts or database tables.
- Preserve discovery, extraction, validation, review and publication workflows.
- Prefer reusable modules over expanding a single large application file.
- Keep evidence, business rules, persistence and UI concerns separated.
- Preserve unrelated user changes in a dirty worktree.
- Use Windows PowerShell-compatible commands.

## 17. Working Procedure for a New Department

For every new Central or state department:

1. Identify the official organisation hierarchy.
2. Build and approve an official-source registry.
3. Crawl a bounded pilot and retain crawl provenance.
4. Classify page roles before extracting catalogue records.
5. Establish stable scheme/programme identities.
6. Extract calls separately and map them to parents.
7. Verify applicant layer, startup relevance and sector evidence.
8. Resolve status using official dates and status evidence.
9. Deduplicate pages, documents and call versions.
10. Route uncertain items to manual review.
11. Run dry-run validation and produce a signed manifest.
12. Review and approve records into staging.
13. Make a separate publication decision.
14. Verify public dashboard counts, filters, cards and official links.
15. Schedule incremental monitoring only after the pilot is accepted.

For Andhra Pradesh, record both the state-government ownership and the specific
department, agency, corporation or mission responsible for implementation.

## 18. Testing and Completion Standard

Changes are not complete until proportionate verification succeeds.

At minimum:

- run Python syntax checks for changed modules;
- run focused tests for the changed workflow;
- run relevant public-dashboard and admin-service regression tests;
- start or reload the affected application;
- verify every affected page and filter;
- test official links without changing external state;
- test desktop and mobile layouts for UI changes;
- confirm database writes are transactional and audited;
- report files changed and commands used; and
- report data gaps separately from software defects.

Useful commands include:

```powershell
cd D:\WebSite\DASHBOARD\Code\SSIP

# Public dashboard
powershell -ExecutionPolicy Bypass -File .\scripts\run_public_dashboard_v2_9.ps1

# Focused test examples
python -m pytest .\tests\test_dst_historical_archive_v1.py -q
python -m unittest discover -s .\tests -p "test_public_dashboard_*.py"

# Syntax check example
python -m py_compile .\apps\public_dashboard_app_v2_9.py
```

Use the repository's current versioned runbooks and requirements files when a
newer governed workflow supersedes these examples.

## 19. Definition of Success

SSIP succeeds when it becomes a trustworthy, auditable and continuously updated
national discovery platform where a startup or innovator can find relevant
Central and state-government support without confusing a programme with a call,
a historical notice with a live opportunity, or an institutional implementation
grant with a direct startup application.

Coverage matters, but **verified correctness, clear evidence and controlled
publication take precedence over volume**.

