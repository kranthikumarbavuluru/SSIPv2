from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DepartmentProfile:
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "DepartmentProfile":
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        required = {"department", "official_domains", "entities", "call_relevance"}
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"DST profile is missing required keys: {', '.join(missing)}")
        return cls(payload)

    @property
    def entities(self) -> list[dict[str, Any]]:
        return list(self.payload["entities"])

    @property
    def entity_by_code(self) -> dict[str, dict[str, Any]]:
        return {str(item["code"]): item for item in self.entities}

    @property
    def official_domains(self) -> set[str]:
        return {str(item).casefold() for item in self.payload["official_domains"]}

    @property
    def call_relevance(self) -> dict[str, list[str]]:
        return dict(self.payload["call_relevance"])
