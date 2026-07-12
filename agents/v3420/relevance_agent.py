from __future__ import annotations
from dataclasses import dataclass
from .common import low

@dataclass
class RelevanceDecision:
    classification: str
    score: int
    publishable: bool
    reason: str
    beneficiary_hits: str
    access_hits: str

class StartupRelevanceAgent:
    BENEFICIARIES = (
        "startup", "start-up", "innovator", "entrepreneur", "incubatee",
        "micro enterprise", "small enterprise", "msme", "technology venture",
        "dpiit recognised", "dpiit-recognized", "industrial concern"
    )
    SUPPORT = (
        "grant", "funding", "loan", "credit", "guarantee", "seed support",
        "prototype", "proof of concept", "incubation", "accelerator",
        "commercialisation", "commercialization", "market access", "procurement",
        "mentoring", "financial assistance", "working capital"
    )
    ACCESS = (
        "apply", "application", "portal", "submit proposal", "through incubator",
        "approved incubator", "technology innovation hub", "applications invited",
        "registration", "enrolment", "enrollment"
    )
    PROGRAMME_FAMILIES = (
        "nidhi", "prayas", "startup india", "seed fund scheme",
        "credit guarantee scheme for startups", "technology development board",
        "entrepreneur-in-residence", "technology business incubator"
    )
    INSTITUTION_ONLY = (
        "universities only", "academic institutions only", "research institutions only",
        "host institution", "college and university only", "government laboratory only"
    )

    def classify(self, text: str) -> RelevanceDecision:
        t = low(text)
        b = [x for x in self.BENEFICIARIES if x in t]
        s = [x for x in self.SUPPORT if x in t]
        a = [x for x in self.ACCESS if x in t]
        families = [x for x in self.PROGRAMME_FAMILIES if x in t]
        neg = [x for x in self.INSTITUTION_ONLY if x in t]
        score = (
            min(45, len(b) * 20)
            + min(35, len(s) * 10)
            + min(20, len(a) * 10)
            + min(25, len(families) * 25)
            - len(neg) * 45
        )
        score = max(0, min(100, score))
        if neg and not b and not families:
            cls = "INSTITUTION_ONLY"
        elif score >= 55 and (b or families) and s:
            cls = "STARTUP_OR_MSME_RELEVANT"
        elif score >= 35:
            cls = "POSSIBLY_RELEVANT"
        else:
            cls = "NOT_STARTUP_RELEVANT"
        return RelevanceDecision(
            cls, score, cls == "STARTUP_OR_MSME_RELEVANT",
            f"beneficiary={len(b)}, support={len(s)}, access={len(a)}, family={len(families)}, institution_only={len(neg)}",
            "; ".join(b + families), "; ".join(a)
        )
