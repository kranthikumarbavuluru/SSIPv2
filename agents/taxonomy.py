from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import lower, norm

@dataclass
class TaxonomySector:
    name: str
    description: str
    strong_phrases: list[str]
    weak_phrases: list[str]
    negative_phrases: list[str]

class SectorTaxonomy:
    def __init__(self, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.version = raw["version"]
        self.sectors = [
            TaxonomySector(
                name=item["name"],
                description=item["description"],
                strong_phrases=item.get("strong_phrases", []),
                weak_phrases=item.get("weak_phrases", []),
                negative_phrases=item.get("negative_phrases", []),
            )
            for item in raw["sectors"]
        ]
        names = [s.name for s in self.sectors]
        if len(names) != len(set(names)):
            raise ValueError("Sector taxonomy contains duplicate names.")
        self.names = names
        self.by_name = {s.name: s for s in self.sectors}
        self.cross_sector_names = set(raw.get("cross_sector_names", []))

    @staticmethod
    def phrase_count(text: str, phrase: str) -> int:
        text = lower(text)
        phrase = lower(phrase)
        if not phrase:
            return 0
        return len(re.findall(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))

    def score(self, text: str) -> list[dict[str, Any]]:
        results = []
        for sector in self.sectors:
            strong_hits = []
            weak_hits = []
            negative_hits = []
            score = 0
            for phrase in sector.strong_phrases:
                count = self.phrase_count(text, phrase)
                if count:
                    strong_hits.append(phrase)
                    score += min(count, 3) * 8
            for phrase in sector.weak_phrases:
                count = self.phrase_count(text, phrase)
                if count:
                    weak_hits.append(phrase)
                    score += min(count, 3) * 2
            for phrase in sector.negative_phrases:
                count = self.phrase_count(text, phrase)
                if count:
                    negative_hits.append(phrase)
                    score -= min(count, 2) * 5
            results.append({
                "sector": sector.name,
                "score": score,
                "strong_hits": strong_hits,
                "weak_hits": weak_hits,
                "negative_hits": negative_hits,
            })
        return sorted(results, key=lambda x: (-x["score"], x["sector"]))

    def validate_labels(self, labels: list[str]) -> bool:
        return all(label in self.by_name for label in labels)
