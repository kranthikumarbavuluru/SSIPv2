from __future__ import annotations
from dataclasses import dataclass
from .common import low

@dataclass
class CallDecision:
    is_call: bool
    call_type: str
    reason: str

class CallAgent:
    TYPES = {
        "CALL_FOR_PROPOSALS": ("call for proposals", "call for applications", "applications invited"),
        "CHALLENGE": ("challenge", "hackathon"),
        "COHORT": ("cohort", "batch"),
        "EOI": ("expression of interest", " eoi "),
        "ACCELERATOR": ("accelerator applications",),
    }
    def classify(self, name: str, text: str) -> CallDecision:
        hay = f" {low(name)} {low(text)} "
        for label, phrases in self.TYPES.items():
            if any(p in hay for p in phrases):
                return CallDecision(True, label, f"Matched {label} phrase.")
        return CallDecision(False, "", "No call evidence.")
