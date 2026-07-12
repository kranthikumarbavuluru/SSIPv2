from __future__ import annotations

from dataclasses import dataclass

from .common import first, low, row_text, stable_id


@dataclass(frozen=True)
class CallDecision:
    is_call: bool
    call_type: str
    reason: str


class CallDiscoveryAgent:
    TYPES = {
        "DEADLINE_EXTENSION": ("deadline extension", "date extended"),
        "EXPRESSION_OF_INTEREST": ("expression of interest", " eoi "),
        "CALL_FOR_PROPOSALS": ("call for proposals", "request for proposals"),
        "CALL_FOR_APPLICATIONS": ("call for applications", "applications invited", "application round"),
        "CHALLENGE": ("challenge", "hackathon"),
        "COHORT": ("cohort",),
        "ACCELERATOR_BATCH": ("accelerator batch", "accelerator applications"),
        "FELLOWSHIP_CALL": ("fellowship call", "fellowship applications"),
        "INCUBATOR_ENROLMENT": ("incubator enrolment", "incubator enrollment"),
    }

    def classify(self, row: dict[str, str], role: str) -> CallDecision:
        text = f" {low(first(row, 'scheme_name', 'call_title', 'title'))} {low(row_text(row))} "
        for call_type, phrases in self.TYPES.items():
            if any(phrase in text for phrase in phrases):
                if any(term in text for term in ("selected candidates", "results announced", "corrigendum")):
                    return CallDecision(False, "", "Result/corrigendum is not a call instance.")
                return CallDecision(True, call_type, f"Matched {call_type} evidence.")
        if role == "CALL_INSTANCE":
            return CallDecision(True, "CALL_FOR_APPLICATIONS", "Existing call role without a more specific type.")
        return CallDecision(False, "", "No call-instance evidence.")

    def build(self, row: dict[str, str], parent_scheme_id: str, call_type: str) -> dict[str, str]:
        title = first(row, "call_title", "scheme_name", "title")
        source_url = first(row, "source_url", "official_page_url", "announcement_url")
        return {
            "call_instance_id": first(row, "call_instance_id") or stable_id("call", title, source_url, first(row, "closing_date")),
            "parent_scheme_id": parent_scheme_id,
            "implementing_entity_id": first(row, "implementing_entity_id", "implementing_agency"),
            "call_title": title,
            "call_type": call_type,
            "opening_date": first(row, "opening_date"),
            "closing_date": first(row, "closing_date"),
            "application_status": first(row, "application_status"),
            "eligible_beneficiaries": first(row, "eligible_beneficiaries", "target_beneficiaries", "eligibility"),
            "application_url": first(row, "application_url"),
            "guidelines_url": first(row, "guidelines_url", "guideline_urls"),
            "announcement_url": first(row, "announcement_url", "official_page_url"),
            "source_url": source_url,
            "last_verified_at": first(row, "last_verified_at", "last_verified_date"),
        }
