from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ssip_agents.dst_pilot.admin_bridge import BridgePaths, DSTAdminBridge


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
    pilot = project_root / "data/departments/dst/pilot_v1/dst_curation_queue_v1.csv"
    output: list[IntakeDescriptor] = []
    if pilot.exists():
        output.append(IntakeDescriptor(
            provider_id="dst_pilot_v1",
            department="Department of Science and Technology",
            version="DST Pilot v1",
            source_path=str(pilot),
            description="Permanent DST identities plus startup-relevant direct, review and ecosystem calls.",
        ))
    return output


def get_intake(provider_id: str, project_root: Path, database_path: Path) -> IntakeProvider:
    if provider_id == "dst_pilot_v1":
        defaults = BridgePaths.defaults(project_root)
        return DSTAdminBridge(BridgePaths(
            project_root=defaults.project_root,
            pilot_dir=defaults.pilot_dir,
            database_path=database_path,
            report_dir=defaults.report_dir,
        ))
    raise KeyError(f"Unknown department intake provider: {provider_id}")
