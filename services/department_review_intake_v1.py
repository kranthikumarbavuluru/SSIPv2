from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ssip_agents.dst_pilot.admin_bridge import BridgePaths, DSTAdminBridge
from services.meity_admin_bridge_v3_4_3_7_1 import MeitYAdminBridge, MeitYBridgePaths
from services.meity_identity_reconciliation_v3_4_3_7_2 import (
    MeitYLegacyIdentityReconciliationBridge,
    MeitYReconciliationPaths,
)


class IntakeProvider(Protocol):
    def plan(self) -> dict[str, Any]: ...
    def run(self, *, apply: bool = False, expected_signature: str | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class IntakeDescriptor:
    provider_id: str
    department: str
    version: str
    source_path: str
    description: str


def available_intakes(project_root: Path, database_path: Path) -> list[IntakeDescriptor]:
    output: list[IntakeDescriptor] = []

    pilot = project_root / "data/departments/dst/pilot_v1/dst_curation_queue_v1.csv"
    if pilot.exists():
        output.append(
            IntakeDescriptor(
                provider_id="dst_pilot_v1",
                department="Department of Science and Technology",
                version="DST Pilot v1",
                source_path=str(pilot),
                description="Permanent DST identities plus startup-relevant direct, review and ecosystem calls.",
            )
        )

    meity_queue = (
        project_root
        / "data/departments/meity/v3_4_3_7/meity_admin_review_queue_v3_4_3_7.csv"
    )
    if meity_queue.exists():
        output.append(
            IntakeDescriptor(
                provider_id="meity_v3_4_3_7",
                department="Ministry of Electronics and Information Technology",
                version="MeitY v3.4.3.7 Admin Gate",
                source_path=str(meity_queue),
                description=(
                    "Governed permanent-scheme review for SASACT and GENESIS. "
                    "No current MeitY call or public Apply route is asserted in this package."
                ),
            )
        )


    reconciliation_map = (
        project_root
        / "data/departments/meity/v3_4_3_7_2/"
        "meity_legacy_identity_reconciliation_v3_4_3_7_2.csv"
    )
    if meity_queue.exists() and reconciliation_map.exists():
        output.append(
            IntakeDescriptor(
                provider_id="meity_v3_4_3_7_2",
                department=(
                    "Ministry of Electronics and Information Technology"
                ),
                version=(
                    "MeitY v3.4.3.7.2 Identity Reconciliation"
                ),
                source_path=str(reconciliation_map),
                description=(
                    "Reconciles the legacy rejected SASACT and GENESIS "
                    "aliases with their governed permanent-scheme "
                    "canonical identities. Legacy rejection history is "
                    "preserved; no current call or Apply route is asserted."
                ),
            )
        )
    return output


def get_intake(provider_id: str, project_root: Path, database_path: Path) -> IntakeProvider:
    if provider_id == "dst_pilot_v1":
        defaults = BridgePaths.defaults(project_root)
        return DSTAdminBridge(
            BridgePaths(
                project_root=defaults.project_root,
                pilot_dir=defaults.pilot_dir,
                database_path=database_path,
                report_dir=defaults.report_dir,
            )
        )
    if provider_id == "meity_v3_4_3_7":
        return MeitYAdminBridge(MeitYBridgePaths.defaults(project_root, database_path))
    if provider_id == "meity_v3_4_3_7_2":
        return MeitYLegacyIdentityReconciliationBridge(
            MeitYReconciliationPaths.defaults(project_root, database_path)
        )
    raise KeyError(f"Unknown department intake provider: {provider_id}")

