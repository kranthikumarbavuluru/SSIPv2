from __future__ import annotations

import argparse
from pathlib import Path


NAV_IMPORT = (
    "from services.admin_workflow_navigation_v3_4_3_7_3 import (  # noqa: E402\n"
    "    guidance_for_route,\n"
    "    phase_for_route,\n"
    "    route_for_label,\n"
    "    workflow_snapshot,\n"
    "    workspace_labels,\n"
    ")\n"
)

IMPORT_MARKER = (
    "from services.department_review_intake_v1 import (  # noqa: E402\n"
    "    available_intakes,\n"
    "    get_intake,\n"
    ")\n"
)

OLD_AGENT_HEADER = (
    '    st.subheader("Department Agent Intake")\n'
    "    st.caption(\n"
    '        "Run a non-writing comparison first, inspect duplicates and exact queue changes, "\n'
    '        "then import only into admin_review_queue. Approval and publication remain separate."\n'
    "    )\n"
)

NEW_AGENT_HEADER = (
    '    st.subheader("Step 1 — Agent Intake & Dry Run")\n'
    "    st.caption(\n"
    '        "Start with the department agent. Run a non-writing comparison, inspect exact "\n'
    '        "queue changes and duplicates, then import only reviewed candidates as PENDING. "\n'
    '        "Human verification and publication remain separate later steps."\n'
    "    )\n"
)

OLD_PUBLICATION_HEADER = (
    '    st.subheader("Publication Queue")\n'
    "    st.caption(\n"
    '        "Curator approval and public publication are separate. Prepare approved staging records, "\n'
    '        "then publish only records that pass a fresh bulk preflight."\n'
    "    )\n"
)

NEW_PUBLICATION_HEADER = (
    '    st.subheader("Step 3 — Staging & Publication Control")\n'
    "    st.caption(\n"
    '        "Only human-approved records reach staging. Prepare them for release, run a fresh "\n'
    '        "bulk preflight and publish only through a separate confirmed decision."\n'
    "    )\n"
)

OLD_MAIN_BLOCK = (
    '    st.title("SSIP Scheme & Call Admin Verification")\n'
    "    st.caption(\n"
    '        "Verify department-agent evidence, relationships and application status; "\n'
    '        "then approve records into staging before a separate publication decision."\n'
    "    )\n"
    "\n"
    "    metric_columns = st.columns(5)\n"
    '    metric_columns[0].metric("Staged records", counts["staged_schemes"])\n'
    '    metric_columns[1].metric("Pending", counts["pending_reviews"])\n'
    '    metric_columns[2].metric("Approved reviews", counts["approved_reviews"])\n'
    '    metric_columns[3].metric("Rejected reviews", counts["rejected_reviews"])\n'
    '    metric_columns[4].metric("Audit actions", counts["review_actions"])\n'
    "\n"
    "    with st.sidebar:\n"
    '        st.header("Admin workspace")\n'
    "        workspace = st.radio(\n"
    '            "Workspace",\n'
    '            ["Review Inbox", "Publication Queue", "Historical Archive", "Department Agent Intake", "Ingestion Runs", "Audit Trail"],\n'
    "        )\n"
)

NEW_MAIN_BLOCK = (
    "    with st.sidebar:\n"
    '        st.header("Admin workflow")\n'
    "        st.caption(\n"
    '            "Follow the numbered sequence. Agent intake comes first; human verification "\n'
    '            "comes next; staging and publication are separate final controls."\n'
    "        )\n"
    "        workspace_label = st.radio(\n"
    '            "Workspace",\n'
    "            workspace_labels(),\n"
    "            index=0,\n"
    "        )\n"
    "        workspace = route_for_label(workspace_label)\n"
    "        st.caption(guidance_for_route(workspace))\n"
    "\n"
    '    st.title("SSIP Scheme & Call Admin Verification")\n'
    "    st.caption(\n"
    '        "Governed sequence: agent dry run → import pending candidates → human verification "\n'
    '        "→ non-public staging → separate publication decision."\n'
    "    )\n"
    "\n"
    '    st.markdown("### Governed workflow")\n'
    "    phase_columns = st.columns(4)\n"
    "    for column, phase in zip(\n"
    "        phase_columns,\n"
    "        workflow_snapshot(workspace, counts),\n"
    "        strict=True,\n"
    "    ):\n"
    '        marker = "▶" if phase["active"] else str(phase["step"])\n'
    '        column.markdown(f"**{marker}. {phase[\'title\']}**")\n'
    '        column.caption(phase["description"])\n'
    '        column.write(phase["status"])\n'
    "\n"
    "    current_phase = phase_for_route(workspace)\n"
    "    if current_phase is None:\n"
    "        st.info(\n"
    '            "This is a supporting oversight workspace. Return to Step 1 for a new agent "\n'
    '            "package, Step 2 for verification or Step 3 for staging/publication."\n'
    "        )\n"
    "    else:\n"
    "        st.info(\n"
    '            f"Current governed stage: {workspace_label}. "\n'
    '            f"{guidance_for_route(workspace)}"\n'
    "        )\n"
    "\n"
    "    metric_columns = st.columns(5)\n"
    '    metric_columns[0].metric("Staged records", counts["staged_schemes"])\n'
    '    metric_columns[1].metric("Pending verification", counts["pending_reviews"])\n'
    '    metric_columns[2].metric("Approved reviews", counts["approved_reviews"])\n'
    '    metric_columns[3].metric("Rejected reviews", counts["rejected_reviews"])\n'
    '    metric_columns[4].metric("Audit actions", counts["review_actions"])\n'
)

OLD_EMPTY_QUEUE = (
    "    if not reviews:\n"
    '        st.info("No records match the selected filters.")\n'
    "        return\n"
)

NEW_EMPTY_QUEUE = (
    "    if not reviews:\n"
    '        if status_filter == "PENDING" and counts["pending_reviews"] == 0:\n'
    "            st.success(\n"
    '                "Verification queue complete: there are no pending records."\n'
    "            )\n"
    "            st.info(\n"
    '                "Next governed step: open 3. Stage & Publish Approved Records. "\n'
    '                "Approved records remain non-public until the separate publication controls are completed."\n'
    "            )\n"
    "        else:\n"
    '            st.info("No records match the selected filters.")\n'
    "        return\n"
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Patch marker not found: {label}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if NAV_IMPORT not in text:
        if IMPORT_MARKER not in text:
            raise RuntimeError("Navigation import insertion marker not found.")
        text = text.replace(
            IMPORT_MARKER,
            IMPORT_MARKER + NAV_IMPORT,
            1,
        )

    text = replace_once(
        text,
        OLD_AGENT_HEADER,
        NEW_AGENT_HEADER,
        "agent intake header",
    )
    text = replace_once(
        text,
        OLD_PUBLICATION_HEADER,
        NEW_PUBLICATION_HEADER,
        "publication header",
    )
    text = replace_once(
        text,
        OLD_MAIN_BLOCK,
        NEW_MAIN_BLOCK,
        "main workflow and sidebar",
    )
    text = replace_once(
        text,
        OLD_EMPTY_QUEUE,
        NEW_EMPTY_QUEUE,
        "empty verification queue",
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def validate(path: Path) -> None:
    ui_text = path.read_text(encoding="utf-8")
    navigation_path = (
        path.resolve().parents[1]
        / "services/admin_workflow_navigation_v3_4_3_7_3.py"
    )
    if not navigation_path.exists():
        raise RuntimeError(
            f"Admin workflow navigation service not found: {navigation_path}"
        )
    navigation_text = navigation_path.read_text(encoding="utf-8")

    ui_required = (
        "services.admin_workflow_navigation_v3_4_3_7_3",
        "workspace_labels()",
        "route_for_label(workspace_label)",
        "workflow_snapshot(workspace, counts)",
        "index=0",
        "Governed sequence:",
        "Verification queue complete:",
        "Step 1 — Agent Intake & Dry Run",
        "Step 3 — Staging & Publication Control",
    )
    navigation_required = (
        'label="1. Agent Intake & Dry Run"',
        'label="2. Verify Pending Records"',
        'label="3. Stage & Publish Approved Records"',
        'label="4. Ingestion History"',
        'label="5. Historical Archive"',
        'label="6. Audit Trail"',
    )

    missing_ui = [
        marker
        for marker in ui_required
        if marker not in ui_text
    ]
    missing_navigation = [
        marker
        for marker in navigation_required
        if marker not in navigation_text
    ]

    if missing_ui or missing_navigation:
        raise RuntimeError(
            "Admin workflow clarity validation failed. "
            f"UI missing: {missing_ui}; "
            f"navigation service missing: {missing_navigation}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = (
        Path(args.project_root).resolve()
        / "ui/admin_review_app_v1.py"
    )
    if not args.check:
        changed = patch(path)
        print(
            "Admin workflow clarity patch: "
            + ("APPLIED" if changed else "ALREADY_APPLIED")
        )
    validate(path)
    print("SSIP v3.4.3.7.3 Admin workflow validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
