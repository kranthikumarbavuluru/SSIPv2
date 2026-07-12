from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import first, load_json, low


@dataclass(frozen=True)
class SectorDecision:
    primary_sector: str
    secondary_sectors: str
    confidence: float
    method: str
    evidence: str
    evidence_url: str
    review_required: bool
    reason: str


class SectorVerificationAgent:
    def __init__(self, taxonomy_path: Path) -> None:
        payload = load_json(taxonomy_path)
        self.sectors = payload["sectors"]
        self.allowed = {item["name"] for item in self.sectors}

    def classify(self, row: dict[str, str]) -> SectorDecision:
        fields = [
            (first(row, "eligibility"), 5, "official eligibility"),
            (first(row, "objectives", "objective"), 4, "official objectives"),
            (first(row, "benefits"), 3, "official benefits"),
            (first(row, "application_process"), 2, "official application route"),
            (first(row, "scheme_name", "canonical_name"), 2, "official title"),
        ]
        combined = low(" ".join(text for text, _, _ in fields))
        source_url = first(row, "sector_evidence_url", "official_page_url", "official_master_url", "source_url")

        if any(term in combined for term in ("bio-ai", "bio ai", "bioe3")) and any(term in combined for term in ("artificial intelligence", "machine learning", "bio-ai", "bio ai")):
            return SectorDecision("Biotechnology & Life Sciences", "Artificial Intelligence & Data", 0.96, "EXPLICIT_MULTI_SECTOR_EVIDENCE", "Official text explicitly combines biotechnology and artificial intelligence.", source_url, False, "Bio-AI evidence supports biotechnology as primary and AI/data as secondary.")

        if any(term in combined for term in ("credit guarantee", "working capital", "bill discount", "startup loan", "msme finance")):
            return SectorDecision("Cross-sector MSME & Startup Finance", "", 0.94, "EXPLICIT_CROSS_SECTOR_FINANCE", "Official text describes cross-sector credit or guarantee support.", source_url, False, "Finance support is not restricted to an industry sector.")

        scored: list[tuple[int, str, list[str], str]] = []
        for sector in self.sectors:
            score = 0
            hits: list[str] = []
            evidence_level = ""
            for text, weight, level in fields:
                value = low(text)
                for phrase in sector.get("strong_phrases", []):
                    if phrase.casefold() in value:
                        score += 8 * weight
                        hits.append(phrase)
                        evidence_level = evidence_level or level
                for phrase in sector.get("weak_phrases", []):
                    if phrase.casefold() in value:
                        score += 2 * weight
                        hits.append(phrase)
                        evidence_level = evidence_level or level
            scored.append((score, sector["name"], sorted(set(hits)), evidence_level))
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0
        if top[0] >= 24 and top[0] - second_score >= 4:
            secondary = [name for score, name, _, _ in scored[1:4] if score >= 20 and score >= top[0] * 0.45]
            return SectorDecision(top[1], "; ".join(secondary), min(0.98, 0.72 + top[0] / 300), "DETERMINISTIC_OFFICIAL_EVIDENCE", f"{top[3]}: {', '.join(top[2][:8])}", source_url, False, "Controlled-taxonomy evidence threshold passed.")

        existing = first(row, "primary_sector", "sector")
        existing_evidence = first(row, "sector_evidence")
        if existing in self.allowed and existing_evidence and existing != "Sector Agnostic / Multi-sector":
            return SectorDecision(existing, first(row, "secondary_sectors"), 0.80, "PRESERVED_VERIFIED_EVIDENCE", existing_evidence, source_url, False, "Existing controlled-taxonomy decision includes evidence.")
        if any(term in combined for term in ("startup", "entrepreneur", "incubat", "innovator")):
            return SectorDecision("Cross-sector Innovation & Entrepreneurship", "", 0.78, "CROSS_SECTOR_INNOVATION", "Official text describes general startup, incubation or entrepreneurship support.", source_url, False, "No industry restriction found.")
        return SectorDecision("Sector Agnostic / Multi-sector", "", 0.40, "MANUAL_REVIEW", "Insufficient official sector evidence.", source_url, True, "A non-blank placeholder is retained but publication requires review.")
