from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .common import low, clean

@dataclass
class SectorDecision:
    primary: str
    secondary: str
    confidence: float
    method: str
    evidence: str
    review_required: bool

class EvidenceSectorAgent:
    def __init__(self, taxonomy_path: Path):
        raw = json.loads(taxonomy_path.read_text(encoding="utf-8"))
        self.sectors = raw["sectors"]
        self.names = {x["name"] for x in self.sectors}

    def classify(self, name: str, objective: str, eligibility: str, benefits: str, page_text: str = "") -> SectorDecision:
        weighted = [
            (low(name), 6),
            (low(objective), 4),
            (low(eligibility), 3),
            (low(benefits), 3),
            (low(page_text), 1),
        ]
        scored = []
        for item in self.sectors:
            score = 0
            hits = []
            for phrase in item.get("strong_phrases", []):
                for text, weight in weighted:
                    if phrase.casefold() in text:
                        score += 8 * weight
                        hits.append(phrase)
            for phrase in item.get("weak_phrases", []):
                for text, weight in weighted:
                    if phrase.casefold() in text:
                        score += 2 * weight
                        hits.append(phrase)
            scored.append((score, item["name"], sorted(set(hits))))
        scored.sort(reverse=True)
        top = scored[0]
        second = scored[1] if len(scored) > 1 else (0, "", [])
        margin = top[0] - second[0]

        if top[0] >= 30 and margin >= 10:
            secondary = [name for score, name, hits in scored[1:4] if score >= max(24, top[0] * 0.55)]
            evidence = ", ".join(top[2][:8]) or clean(name)
            confidence = min(0.99, 0.72 + top[0] / 300 + margin / 300)
            return SectorDecision(top[1], "; ".join(secondary), round(confidence, 3),
                                  "WEIGHTED_EVIDENCE", evidence, False)

        t = " ".join([low(name), low(objective), low(eligibility), low(benefits)])
        finance = ("loan", "credit", "guarantee", "bill discount", "working capital", "financial assistance")
        innovation = ("startup", "entrepreneur", "innovation", "incubat", "accelerator", "nidhi", "prayas")
        if any(x in t for x in finance):
            return SectorDecision("Cross-sector MSME & Startup Finance", "", 0.88,
                                  "CROSS_SECTOR_FINANCE", "General finance support without industry restriction.", False)
        if any(x in t for x in innovation):
            return SectorDecision("Cross-sector Innovation & Entrepreneurship", "", 0.86,
                                  "CROSS_SECTOR_INNOVATION", "General startup/innovation support without industry restriction.", False)

        return SectorDecision("Sector Agnostic / Multi-sector", "", 0.55,
                              "MANUAL_SECTOR_REVIEW", "No defensible sector evidence.", True)
