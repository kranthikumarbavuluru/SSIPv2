from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from .common import norm, lower

@dataclass
class CallCandidate:
    parent_master_id: str
    title: str
    url: str
    call_type: str
    status: str
    evidence: str

class CallDiscoveryAgent:
    CALL_TERMS = {
        "CALL_FOR_PROPOSALS": ("call for proposals", "call for applications", "applications invited"),
        "COHORT": ("cohort", "batch"),
        "CHALLENGE": ("challenge", "hackathon", "grand challenge"),
        "EOI": ("expression of interest", " eoi "),
        "ACCELERATOR": ("accelerator applications", "accelerator programme"),
    }
    EXCLUDE_TERMS = ("result", "selected candidates", "corrigendum", "extension notice", "archive")

    def discover_links(self, html: str, base_url: str, parent_master_id: str) -> list[CallCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[CallCandidate] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            title = norm(a.get_text(" ", strip=True))
            url = urljoin(base_url, a["href"])
            hay = f" {lower(title)} {lower(url)} "
            if not title or any(x in hay for x in self.EXCLUDE_TERMS):
                continue
            call_type = ""
            for label, phrases in self.CALL_TERMS.items():
                if any(p in hay for p in phrases):
                    call_type = label
                    break
            if not call_type or url in seen:
                continue
            seen.add(url)
            out.append(CallCandidate(
                parent_master_id=parent_master_id,
                title=title,
                url=url,
                call_type=call_type,
                status="VERIFICATION_REQUIRED",
                evidence=title,
            ))
        return out
