from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import first, load_json, low, row_text


@dataclass(frozen=True)
class RelevanceDecision:
    classification: str
    confidence: float
    beneficiary_evidence: str
    access_evidence: str
    reason: str
    review_required: bool


class StartupRelevanceAgent:
    def __init__(self, rules_path: Path) -> None:
        self.rules = load_json(rules_path)

    def _hits(self, key: str, text: str) -> list[str]:
        return [term for term in self.rules.get(key, []) if term.casefold() in text]

    def classify(self, row: dict[str, str], role: str) -> RelevanceDecision:
        text = low(row_text(row))
        beneficiary = self._hits("beneficiary_terms", text)
        support = self._hits("support_terms", text)
        access = self._hits("access_terms", text)
        institution = self._hits("institution_only_terms", text)
        research = self._hits("research_only_terms", text)
        mission = self._hits("ecosystem_mission_terms", text)
        family = self._hits("known_direct_families", text)
        beneficiary_evidence = "; ".join(beneficiary + family)
        access_evidence = "; ".join(support + access)

        if role == "CALL_INSTANCE" and (beneficiary or family) and (support or access):
            return RelevanceDecision("CALL_FOR_STARTUPS", 0.94, beneficiary_evidence, access_evidence, "Startup-facing call evidence.", False)
        if institution and not beneficiary and not family:
            return RelevanceDecision("INSTITUTION_ONLY", 0.96, "; ".join(institution), access_evidence, "Eligibility is restricted to institutions.", False)
        if research and not beneficiary and not family:
            return RelevanceDecision("RESEARCH_ONLY", 0.94, "; ".join(research), access_evidence, "Evidence is research-only.", False)
        if mission and not support:
            return RelevanceDecision("STARTUP_ECOSYSTEM_MISSION", 0.90, "; ".join(mission), access_evidence, "Ecosystem mission without direct beneficiary support.", False)
        if any(term in text for term in ("msme", "micro enterprise", "small enterprise", "industrial concern")) and support:
            return RelevanceDecision("MSME_SUPPORT_RELEVANT", 0.91, beneficiary_evidence, access_evidence, "MSME beneficiary and support evidence.", False)
        if (beneficiary or family) and support and access:
            return RelevanceDecision("DIRECT_STARTUP_SCHEME", 0.95, beneficiary_evidence, access_evidence, "Direct beneficiary, support and access evidence.", False)
        if (beneficiary or family) and support:
            return RelevanceDecision("STARTUP_ACCESS_PROGRAMME", 0.87, beneficiary_evidence, access_evidence, "Startup beneficiary and support evidence; access route may be indirect.", False)
        existing_class = first(row, "startup_relevance_classification").upper()
        existing_beneficiary = first(row, "startup_beneficiary_evidence")
        existing_access = first(row, "startup_access_evidence")
        if existing_class in {"DIRECT_STARTUP_SCHEME", "STARTUP_ACCESS_PROGRAMME", "MSME_SUPPORT_RELEVANT"} and existing_beneficiary and existing_access:
            return RelevanceDecision(existing_class, 0.82, existing_beneficiary, existing_access, "Existing evidence-bearing relevance decision preserved.", False)
        if beneficiary or family or support:
            return RelevanceDecision("POSSIBLY_RELEVANT", 0.55, beneficiary_evidence, access_evidence, "Partial evidence requires manual relevance review.", True)
        return RelevanceDecision("NOT_STARTUP_RELEVANT", 0.88, "", "", "No startup beneficiary and support evidence.", False)
