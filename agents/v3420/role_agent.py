from __future__ import annotations
import re
from dataclasses import dataclass
from .common import clean, low

@dataclass
class RoleDecision:
    role: str
    confidence: float
    reason: str

class RecordRoleAgent:
    NAVIGATION = (
        "sitemap", "about", "contact", "accessibility statement", "disclaimer",
        "screen reader", "terms conditions", "terms and conditions", "dashboard",
        "search", "myscheme", "homepage", "privacy policy"
    )
    GENERIC_INDEX = (
        "schemes", "government schemes", "existing schemes", "new schemes",
        "schemes for starters", "funding", "international", "view challenge",
        "register challenge", "official sources", "directory"
    )
    REPORT = (
        "report", "handbook", "playbook", "framework", "discussion paper",
        "trendbook", "study", "whitepaper", "white paper", "certificate",
        "annexure", "calendar", "booklet", "manual", "guidelines", "guidlines"
    )
    FACILITY = (
        "technical services centre", "ntsc", "testing laboratory", "material testing lab",
        "space available on hire", "exhibition complex", "event management cell"
    )
    CALL = (
        "call for proposals", "call for applications", "applications invited",
        "expression of interest", "eoi", "cohort", "challenge", "hackathon",
        "applications open", "apply now"
    )
    STRONG_SCHEME = (
        "scheme", "programme", "program", "fund", "credit guarantee",
        "seed support", "seed fund", "financial assistance", "incubator",
        "accelerator", "nidhi", "entrepreneur-in-residence", "prayas",
        "technology business incubator"
    )
    SUPPORT_SERVICE = (
        "marketing intelligence", "public procurement", "single point registration",
        "e-marketing services", "credit facilitation", "bill discounting",
        "international cooperation activities", "participation of msmes in exhibitions",
        "assistance to wholesalers and retail traders"
    )

    def classify(self, name: str, text: str, url: str = "") -> RoleDecision:
        n = low(name)
        combined = f" {n} {low(text)} {low(url)} "

        if any(term in n for term in self.NAVIGATION):
            return RoleDecision("NAVIGATION_OR_UTILITY", 0.99, "Navigation/utility title.")
        if n.endswith(".xml") or "sitemap" in n:
            return RoleDecision("NAVIGATION_OR_UTILITY", 0.99, "XML/sitemap record.")
        if n in self.GENERIC_INDEX or any(n == term for term in self.GENERIC_INDEX):
            return RoleDecision("CATEGORY_OR_INDEX_PAGE", 0.98, "Generic category/index title.")
        if n.endswith(".pdf"):
            return RoleDecision("SUPPORTING_DOCUMENT", 0.98, "PDF is evidence/supporting material, not a canonical scheme identity.")
        if any(term in n for term in self.FACILITY):
            return RoleDecision("FACILITY_OR_DIRECTORY", 0.96, "Facility/laboratory/centre title.")
        if any(term in combined for term in self.CALL):
            return RoleDecision("CALL_INSTANCE", 0.92, "Application/call language.")
        if n.endswith(".pdf") and any(term in n for term in self.REPORT):
            return RoleDecision("SUPPORTING_DOCUMENT", 0.97, "Report/guideline/document title.")
        if any(term in n for term in self.REPORT):
            return RoleDecision("SUPPORTING_DOCUMENT", 0.90, "Document/resource title.")
        if any(term in n for term in self.SUPPORT_SERVICE):
            return RoleDecision("SUPPORT_SCHEME_OR_SERVICE", 0.85, "Named MSME/startup support service.")
        if any(term in combined for term in self.STRONG_SCHEME):
            return RoleDecision("SCHEME_OR_PROGRAMME", 0.83, "Scheme/programme identity terms.")
        if n.endswith((".html", ".htm", ".aspx", ".aspx")):
            return RoleDecision("GENERIC_WEB_PAGE", 0.80, "Generic page without scheme identity.")
        if len(clean(name)) < 5:
            return RoleDecision("UNKNOWN_OR_NOISE", 0.90, "Name too short.")
        return RoleDecision("MANUAL_ROLE_REVIEW", 0.50, "No reliable role evidence.")
