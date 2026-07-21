from __future__ import annotations

from dataclasses import dataclass

from agents.shared.url_normalization import hostname

from .dpiit_identity_rules_v3_4_1_0_1 import CANONICAL_DEPARTMENT


@dataclass(frozen=True)
class OwnershipDecision:
    suspected_owner: str
    ownership_status: str
    reason: str


def determine_ownership(url: str, source: dict[str, str], ownership_proven: bool = False) -> OwnershipDecision:
    host = hostname(url)
    owner = source.get("owning_department", "").strip()
    evidence = source.get("ownership_evidence_url", "").strip()
    if ownership_proven and owner == CANONICAL_DEPARTMENT and evidence:
        return OwnershipDecision(owner, "VERIFIED_DPIIT", "SPECIFIC_OFFICIAL_OWNERSHIP_EVIDENCE")
    if host == "dpiit.gov.in" or host.endswith(".dpiit.gov.in"):
        return OwnershipDecision(CANONICAL_DEPARTMENT, "VERIFIED_DPIIT", "DPIIT_DEPARTMENT_PORTAL")
    if "startupindia.gov.in" in host:
        return OwnershipDecision(owner or "", "NEEDS_VERIFICATION", "STARTUP_INDIA_HOST_IS_NOT_OWNERSHIP_PROOF")
    if owner and evidence and ownership_proven:
        return OwnershipDecision(owner, "VERIFIED_IMPLEMENTING_AGENCY", "IMPLEMENTING_AGENCY_EVIDENCE")
    return OwnershipDecision(owner, "NEEDS_VERIFICATION", "OWNERSHIP_NOT_PROVEN")
