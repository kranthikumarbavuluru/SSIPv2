from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NAVIGATION_VERSION = "3.4.3.7.3"


@dataclass(frozen=True)
class WorkspaceItem:
    label: str
    route: str
    order: int
    category: str
    guidance: str
    primary_phase: int | None


@dataclass(frozen=True)
class WorkflowPhase:
    step: int
    title: str
    description: str


WORKFLOW_PHASES = (
    WorkflowPhase(1, "Agent intake", "Dry-run and import pending candidates"),
    WorkflowPhase(2, "Human verification", "Review evidence and decide each record"),
    WorkflowPhase(3, "Staging quality", "Approved records remain non-public"),
    WorkflowPhase(4, "Publication", "Separate preflight and release decision"),
)


WORKSPACE_ITEMS = (
    WorkspaceItem(
        label="1. Agent Intake & Dry Run",
        route="Department Agent Intake",
        order=1,
        category="PRIMARY",
        guidance=(
            "Start here. Select a department-agent package, run a non-writing "
            "comparison, inspect duplicates and import only the reviewed pending records."
        ),
        primary_phase=1,
    ),
    WorkspaceItem(
        label="2. Verify Pending Records",
        route="Review Inbox",
        order=2,
        category="PRIMARY",
        guidance=(
            "Review imported pending records, verify official evidence, correct fields "
            "and approve, reject or request more evidence."
        ),
        primary_phase=2,
    ),
    WorkspaceItem(
        label="3. Stage & Publish Approved Records",
        route="Publication Queue",
        order=3,
        category="PRIMARY",
        guidance=(
            "Prepare approved staging records, run a fresh publication preflight and "
            "publish only through a separate confirmed decision."
        ),
        primary_phase=4,
    ),
    WorkspaceItem(
        label="4. Ingestion History",
        route="Ingestion Runs",
        order=4,
        category="OVERSIGHT",
        guidance=(
            "Inspect loader, intake and decision runs. This page is evidence and history, "
            "not a workflow entry point."
        ),
        primary_phase=None,
    ),
    WorkspaceItem(
        label="5. Historical Archive",
        route="Historical Archive",
        order=5,
        category="OVERSIGHT",
        guidance=(
            "Review the separately governed historical-call archive. Historical records "
            "must not be confused with current application opportunities."
        ),
        primary_phase=None,
    ),
    WorkspaceItem(
        label="6. Audit Trail",
        route="Audit Trail",
        order=6,
        category="OVERSIGHT",
        guidance=(
            "Inspect immutable administrator actions and decision history across all "
            "departments and batches."
        ),
        primary_phase=None,
    ),
)


def workspace_labels() -> tuple[str, ...]:
    return tuple(item.label for item in WORKSPACE_ITEMS)


def route_for_label(label: str) -> str:
    for item in WORKSPACE_ITEMS:
        if item.label == label:
            return item.route
    raise KeyError(f"Unknown Admin workspace label: {label}")


def item_for_route(route: str) -> WorkspaceItem:
    for item in WORKSPACE_ITEMS:
        if item.route == route:
            return item
    raise KeyError(f"Unknown Admin workspace route: {route}")


def guidance_for_route(route: str) -> str:
    return item_for_route(route).guidance


def phase_for_route(route: str) -> int | None:
    return item_for_route(route).primary_phase


def workflow_snapshot(
    route: str,
    counts: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    current = phase_for_route(route)
    status = {
        1: "Start with a governed agent package",
        2: f"{int(counts.get('pending_reviews', 0))} pending",
        3: f"{int(counts.get('staged_schemes', 0))} staged",
        4: "Separate release decision",
    }
    return tuple(
        {
            "step": phase.step,
            "title": phase.title,
            "description": phase.description,
            "status": status[phase.step],
            "active": phase.step == current,
        }
        for phase in WORKFLOW_PHASES
    )
