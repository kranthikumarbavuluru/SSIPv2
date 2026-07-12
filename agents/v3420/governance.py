from __future__ import annotations
from dataclasses import dataclass

@dataclass
class PublicationDecision:
    decision: str
    public_section: str
    reason: str

class GovernancePolicy:
    PUBLIC_ROLES = {"SCHEME_OR_PROGRAMME", "SUPPORT_SCHEME_OR_SERVICE"}

    def decide(self, role: str, relevance_class: str, relevance_score: int, is_call: bool) -> PublicationDecision:
        if is_call or role == "CALL_INSTANCE":
            return PublicationDecision("PUBLISH_CALL_SEPARATELY", "CALLS_AND_OPPORTUNITIES", "Call instance kept separate.")
        if role not in self.PUBLIC_ROLES:
            return PublicationDecision("QUARANTINE", "INTERNAL_REFERENCE", f"Role {role} is not a public scheme identity.")
        if relevance_class == "STARTUP_OR_MSME_RELEVANT" and relevance_score >= 60:
            return PublicationDecision("PUBLISH_SCHEME", "STARTUP_SCHEMES", "Startup/MSME relevance gate passed.")
        if relevance_class == "POSSIBLY_RELEVANT":
            return PublicationDecision("MANUAL_REVIEW", "INTERNAL_REVIEW", "Relevance evidence incomplete.")
        return PublicationDecision("QUARANTINE", "INTERNAL_REFERENCE", "Startup/innovator relevance gate failed.")
