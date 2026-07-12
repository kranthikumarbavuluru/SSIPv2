# SSIP — Codex Project Instructions

## Project

SSIP means Startup Scheme Intelligence Platform.

The platform helps startups, innovators, researchers, MSMEs,
incubators and institutions discover government schemes,
programmes, grants, funds, challenges and support opportunities.

Project root:

D:\WebSite\DASHBOARD\Code\SSIP

Primary database:

database\ssip_staging_v1.db

Current normalized catalogue:

data\audit\v2_8_1_catalogue_normalization\
catalogue_normalization_plan_v2_8_1.csv

## Public dashboard requirements

The public dashboard must be dynamic, responsive and user-friendly.

It must show:

- total catalogue records
- total ministries
- total departments and agencies
- total sectors
- total grant and support types
- open schemes
- upcoming or status-unverified schemes
- closed and historical schemes
- minimum and maximum funding amounts
- manuals and guidelines
- application portals
- latest verified schemes
- department-wise scheme counts
- sector-wise scheme counts
- funding-type distribution

Required public sections:

- Home
- Scheme Explorer
- Departments
- Smart Match
- Resources
- Scheme Details

Required filters:

- keyword
- ministry
- department
- implementing agency
- sector
- applicant type
- startup stage
- scheme type
- grant/support type
- application status
- minimum funding
- maximum funding
- opening date
- closing date

## Intelligence requirements

Smart Match must be explainable.

Never display a fake AI score.

Every match score must be calculated from identifiable fields such as:

- applicant type
- eligibility
- sector
- startup stage
- geographic scope
- funding requirement
- application status

Show the reasons behind each recommendation.

## Data rules

- Never hardcode dashboard totals.
- Calculate all totals from database or catalogue records.
- Never invent ministries, departments, sectors, funding or dates.
- Never classify a scheme as open without official evidence.
- Closed schemes must remain available as reference records.
- Separate schemes, application calls, umbrella programmes,
  indirect funding support and historical records.
- Display the last verified or updated date.
- Official URLs must open in a new tab.
- Clearly identify missing or unverified information.

## Safety rules

- Do not delete existing scripts.
- Do not delete existing database tables.
- Do not alter production data without explicit permission.
- Open the SQLite database read-only for dashboard operations.
- Never modify anything inside backups/.
- Create database migrations separately and obtain approval before running them.
- Preserve existing discovery, extraction, validation,
  admin-review and publication workflows.

## Engineering rules

- Inspect the existing project before selecting an architecture.
- Prefer reusable modules rather than one very large Python file.
- Keep frontend, services, database access and business logic separate.
- Add error handling and logging.
- Add tests for filtering, totals, status classification,
  funding parsing and Smart Match.
- Support Windows PowerShell commands.
- Do not mark work complete until syntax checks and tests pass.

## UI requirements

The approved visual direction is:

- light government-portal interface
- blue and white theme
- clean navigation header
- responsive desktop and mobile layouts
- polished scheme cards
- readable typography
- analytics and coverage visualisations
- accessible status badges
- no Streamlit default appearance in the finished public portal

The finished interface should closely follow the supplied reference image,
but all displayed numbers must come from real SSIP data.

## Completion requirements

Before completion:

1. Run all tests.
2. Start the application locally.
3. Verify every page.
4. Test filters.
5. test official links.
6. Test mobile responsiveness.
7. Report files changed.
8. Report commands used.
9. Report known data gaps separately from software defects.