# SSIP v3.4.3.7.1 — MeitY Admin Workspace Integration

This phase connects the existing v3.4.3.7 SASACT/GENESIS file-based admin gate to the existing Streamlit Admin workspace.

## Scope

- Registers `meity_v3_4_3_7` as a Department Agent Intake provider.
- Exposes exactly two permanent scheme records: SASACT and GENESIS.
- Uses the existing signed dry-run/import workflow.
- Imports only into `admin_review_queue` after a reviewed plan signature.
- Preserves existing APPROVED/REJECTED decisions.
- Performs no publication and writes nothing to `scheme_staging` during intake.
- Imports no MeitY calls, because v3.4.3.7 has zero verified current call instances.
- Converts application-route sentinels to `None`, preventing Apply actions.

## Admin workflow

1. Start the Admin workspace on port 8505.
2. Open **Department Agent Intake**.
3. Select **Ministry of Electronics and Information Technology — MeitY v3.4.3.7 Admin Gate**.
4. Click **Run comparison / dry run**.
5. Verify SASACT and GENESIS, counts, duplicates, and protected decisions.
6. Use the existing signed import control to import into `admin_review_queue`.
7. Open **Review Inbox** and filter Source = `MeitY Startup Hub`.
8. Review and decide each record individually.

No current MeitY call will appear in this phase. Calls require the separate v3.4.3.7A recovery and verification phase.
