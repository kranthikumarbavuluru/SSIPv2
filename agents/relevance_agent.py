from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .common import lower, norm

@dataclass
class RelevanceDecision:
    classification: str
    score: int
    beneficiary_evidence: str
    access_evidence: str
    publishable: bool
    reason: str

class StartupRelevanceAgent:
    BENEFICIARY_TERMS = (
        "startup", "start-up", "innovator", "entrepreneur", "incubatee",
        "technology venture", "dpiit recognised", "dpiit-recognized",
        "company", "industrial concern", "msme"
    )
    ACCESS_TERMS = (
        "apply", "application", "portal", "call for applications", "incubator",
        "technology innovation hub", "prayas centre", "implementing agency",
        "submit proposal", "online application"
    )
    INSTITUTION_ONLY = (
        "universities only", "academic institutions only", "research institutions only",
        "host institution", "college and university", "government laboratories only"
    )

    def classify(self, text: str) -> RelevanceDecision:
        t = lower(text)
        beneficiaries = [x for x in self.BENEFICIARY_TERMS if x in t]
        access = [x for x in self.ACCESS_TERMS if x in t]
        negative = [x for x in self.INSTITUTION_ONLY if x in t]
        score = min(60, len(beneficiaries) * 30) + min(40, len(access) * 10) - len(negative) * 35
        score = max(0, min(100, score))
        if negative and not beneficiaries:
            cls = "RESEARCH_OR_INSTITUTION_ONLY"
        elif beneficiaries and access:
            cls = "DIRECT_OR_MEDIATED_STARTUP_SUPPORT"
        elif beneficiaries:
            cls = "STARTUP_ECOSYSTEM_REFERENCE"
        else:
            cls = "RELEVANCE_REVIEW_REQUIRED"
        return RelevanceDecision(
            classification=cls,
            score=score,
            beneficiary_evidence="; ".join(beneficiaries),
            access_evidence="; ".join(access),
            publishable=score >= 70 and cls == "DIRECT_OR_MEDIATED_STARTUP_SUPPORT",
            reason=f"beneficiary_hits={len(beneficiaries)}, access_hits={len(access)}, institution_only_hits={len(negative)}"
        )
