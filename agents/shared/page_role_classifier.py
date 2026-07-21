from __future__ import annotations

from dataclasses import dataclass
import re


PAGE_ROLES = (
    "SCHEME_MASTER", "UMBRELLA_PROGRAMME", "APPLICATION_CALL",
    "CHALLENGE_INSTANCE", "AWARD_EDITION", "APPLICATION_PORTAL", "GUIDELINE",
    "NOTIFICATION", "FAQ", "RESULTS_PAGE", "ECOSYSTEM_PLATFORM",
    "SOURCE_DIRECTORY", "ARCHIVED_PAGE", "NON_SCHEME", "OWNERSHIP_UNRESOLVED",
)


@dataclass(frozen=True)
class PageRoleDecision:
    role: str
    confidence: float
    reasons: tuple[str, ...]


class ConservativePageRoleClassifier:
    """Department-neutral ordering that prevents temporary pages becoming masters."""

    EDITION = re.compile(r"\b(?:award|awards)\s+(?:edition\s+)?(?:\d{4}|\d+(?:\.\d+)?)\b", re.I)
    YEAR_EDITION = re.compile(r"\bnational startup awards\s+(?:20\d{2}|\d+(?:\.\d+)?)\b", re.I)

    @staticmethod
    def _has(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    def classify(self, *, url: str, title: str, candidate_name: str = "",
                 ownership_status: str = "VERIFIED", source_type: str = "") -> PageRoleDecision:
        text = f"{title} {candidate_name} {url}".casefold()
        path = url.casefold()
        if self._has(text, ("contact us", "recruitment", "vacancy", "speech", "event gallery", "tender")):
            return PageRoleDecision("NON_SCHEME", 0.97, ("EXPLICIT_NON_SCHEME_PAGE",))
        if self._has(text, ("archived page", "/archive", "archive-notice")):
            return PageRoleDecision("ARCHIVED_PAGE", 0.96, ("ARCHIVE_EVIDENCE",))
        if ownership_status == "NEEDS_VERIFICATION":
            return PageRoleDecision("OWNERSHIP_UNRESOLVED", 0.99, ("OWNERSHIP_NOT_PROVEN",))
        if self._has(text, ("result", "winner", "selected startup", "selected incubator")):
            return PageRoleDecision("RESULTS_PAGE", 0.96, ("RESULTS_LANGUAGE",))
        if self._has(text, ("guideline", "manual", "handbook")) or path.endswith(".pdf"):
            return PageRoleDecision("GUIDELINE", 0.96, ("GUIDANCE_OR_DOCUMENT_EVIDENCE",))
        if self.YEAR_EDITION.search(text) or self.EDITION.search(text):
            return PageRoleDecision("AWARD_EDITION", 0.99, ("EDITION_SPECIFIC_TITLE",))
        if self._has(text, ("gazette", "notification", "order and notice", "orders-and-notices")):
            return PageRoleDecision("NOTIFICATION", 0.96, ("OFFICIAL_NOTIFICATION_EVIDENCE",))
        if self._has(text, ("faq", "frequently asked")):
            return PageRoleDecision("FAQ", 0.96, ("FAQ_EVIDENCE",))
        if self._has(text, ("login", "sign-in", "signin", "apply-now", "application portal")):
            return PageRoleDecision("APPLICATION_PORTAL", 0.95, ("PORTAL_OR_LOGIN_EVIDENCE",))
        if self._has(text, (
            "applications invited", "call for application", "call for proposal",
            "application window", "deadline extension", "last date", "cohort",
        )):
            return PageRoleDecision("APPLICATION_CALL", 0.97, ("TIME_BOUND_CALL_EVIDENCE",))
        if self._has(text, ("gaming for good", "individual challenge", "problem statement")):
            return PageRoleDecision("CHALLENGE_INSTANCE", 0.95, ("INDIVIDUAL_CHALLENGE_EVIDENCE",))
        if self._has(text, (
            "national startup awards", "bharat startup grand challenge", "startup india initiative",
        )):
            return PageRoleDecision("UMBRELLA_PROGRAMME", 0.93, ("PERMANENT_PROGRAMME_IDENTITY",))
        if (title.strip() or candidate_name.strip()).casefold() in {"sisfs", "ffs", "cgss"}:
            return PageRoleDecision("SCHEME_MASTER", 0.90, ("GOVERNED_SCHEME_ACRONYM",))
        if self._has(text, (
            "seed fund scheme", "fund of funds", "credit guarantee scheme", "sipp",
            "startup recognition", "intellectual property protection",
        )):
            return PageRoleDecision("SCHEME_MASTER", 0.93, ("PERMANENT_SCHEME_OR_SERVICE_IDENTITY",))
        if self._has(text, ("bhaskar", "maarg", "investor connect")):
            return PageRoleDecision("ECOSYSTEM_PLATFORM", 0.92, ("NAMED_ECOSYSTEM_PLATFORM",))
        if source_type.endswith("DIRECTORY") or self._has(text, ("schemes and services", "programs and challenges")):
            return PageRoleDecision("SOURCE_DIRECTORY", 0.91, ("OFFICIAL_DIRECTORY_EVIDENCE",))
        return PageRoleDecision("NON_SCHEME", 0.55, ("INSUFFICIENT_SCHEME_EVIDENCE",))
