from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .common import clean, first, load_json, low, row_text


@dataclass(frozen=True)
class RoleDecision:
    role: str
    confidence: float
    reason: str


class RecordRoleAgent:
    def __init__(self, rules_path: Path) -> None:
        self.rules = load_json(rules_path)

    def _contains(self, key: str, text: str) -> bool:
        for term in self.rules.get(key, []):
            value = term.casefold()
            if " " in value or any(character in value for character in ("-", ".")):
                if value in text:
                    return True
            elif re.search(rf"\b{re.escape(value)}\b", text):
                return True
        return False

    def classify(self, row: dict[str, str]) -> RoleDecision:
        name = first(row, "scheme_name", "canonical_name", "title", "name")
        url = first(row, "official_page_url", "official_master_url", "source_url")
        normalized_kind = first(row, "normalized_record_kind", "record_kind").upper()
        name_low = low(name)
        combined = low(f"{name} {row_text(row)} {url}")

        if not name and not url:
            return RoleDecision("BROKEN_OR_INACCESSIBLE", 0.99, "No title or source URL.")
        if name_low.endswith(".xml") or "sitemap" in combined:
            return RoleDecision("NAVIGATION_OR_UTILITY", 0.99, "Sitemap/XML navigation record.")
        if self._contains("navigation_terms", name_low):
            return RoleDecision("NAVIGATION_OR_UTILITY", 0.99, "Navigation or utility title.")
        if self._contains("call_terms", combined) or normalized_kind in {"APPLICATION_CALL", "CHALLENGE"}:
            return RoleDecision("CALL_INSTANCE", 0.96, "Call, cohort, challenge or application-window evidence.")
        if self._contains("report_terms", name_low):
            return RoleDecision("REPORT_OR_PUBLICATION", 0.97, "Report/publication title.")
        if self._contains("guideline_terms", name_low):
            return RoleDecision("GUIDELINE_OR_NOTIFICATION", 0.96, "Guideline, notification or manual title.")
        if name_low.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            return RoleDecision("SUPPORTING_DOCUMENT", 0.96, "Document filename cannot define a canonical scheme.")
        if self._contains("news_terms", name_low):
            return RoleDecision("NEWS_OR_PRESS_RELEASE", 0.94, "News or press-release title.")
        if self._contains("index_terms", name_low) or self._contains("directory_terms", name_low):
            return RoleDecision("CATEGORY_OR_INDEX_PAGE", 0.94, "Generic index or directory page.")
        if self._contains("facility_terms", name_low):
            return RoleDecision("FACILITY_OR_LABORATORY", 0.94, "Facility or laboratory, not a scheme identity.")
        if normalized_kind in {"INCUBATOR_OR_HUB", "IMPLEMENTING_ENTITY"}:
            return RoleDecision(normalized_kind, 0.97, "Existing normalized entity role.")
        if normalized_kind in {
            "SCHEME_OR_PROGRAMME", "GRANT", "FUND", "CREDIT_SUPPORT", "CREDIT_GUARANTEE",
            "SUBSIDY", "INCENTIVE", "FELLOWSHIP", "INCUBATION_SUPPORT", "ACCELERATOR_SUPPORT",
            "INFRASTRUCTURE_SUPPORT", "RESEARCH_SUPPORT", "PROCUREMENT_SUPPORT",
        }:
            role = "PROGRAMME_MASTER" if self._contains("programme_terms", combined) else "SCHEME_MASTER"
            return RoleDecision(role, 0.90, "Existing scheme/programme kind with no disqualifying page-role evidence.")
        if self._contains("scheme_terms", combined):
            return RoleDecision("SCHEME_MASTER", 0.82, "Named scheme/support identity evidence.")
        if self._contains("programme_terms", combined):
            return RoleDecision("PROGRAMME_MASTER", 0.82, "Named programme identity evidence.")
        if self._contains("incubator_terms", name_low):
            return RoleDecision("INCUBATOR_OR_HUB", 0.82, "Named incubator or hub entity.")
        if "department" in name_low or "ministry" in name_low or "agency" in name_low:
            return RoleDecision("IMPLEMENTING_ENTITY", 0.75, "Government implementing-entity title.")
        if not url:
            return RoleDecision("BROKEN_OR_INACCESSIBLE", 0.75, "Missing official source URL.")
        return RoleDecision("MANUAL_ROLE_REVIEW", 0.50, "Insufficient deterministic role evidence.")
