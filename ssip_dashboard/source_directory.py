from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OfficialSource:
    source_id: str
    name: str
    scope: str
    ministry: str
    department: str
    agency: str
    source_type: str
    priority: str
    official_url: str
    seed_urls: tuple[str, ...]
    coverage_note: str
    status: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def source_directory_path(project_root: Path) -> Path:
    return project_root / "config" / "public_dashboard_official_sources_v3_0.json"


def load_official_sources(project_root: Path) -> list[OfficialSource]:
    path = source_directory_path(project_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources: list[OfficialSource] = []
    for item in payload.get("sources", []):
        sources.append(
            OfficialSource(
                source_id=_clean(item.get("source_id")),
                name=_clean(item.get("name")),
                scope=_clean(item.get("scope")),
                ministry=_clean(item.get("ministry")),
                department=_clean(item.get("department")),
                agency=_clean(item.get("agency")),
                source_type=_clean(item.get("source_type")),
                priority=_clean(item.get("priority")),
                official_url=_clean(item.get("official_url")),
                seed_urls=tuple(_clean(url) for url in item.get("seed_urls", []) if _clean(url)),
                coverage_note=_clean(item.get("coverage_note")),
                status=_clean(item.get("status")),
            )
        )
    return sources


def source_summary(sources: list[OfficialSource]) -> dict[str, int]:
    return {
        "total_sources": len(sources),
        "central_sources": sum(1 for source in sources if source.scope.casefold() == "central"),
        "state_sources": sum(1 for source in sources if source.scope.casefold() == "state/ut"),
        "high_priority_sources": sum(1 for source in sources if source.priority.casefold() == "high"),
        "ministries": len({source.ministry for source in sources if source.ministry}),
        "departments": len({source.department for source in sources if source.department}),
        "source_types": len({source.source_type for source in sources if source.source_type}),
    }


def source_counter(sources: list[OfficialSource], field_name: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for source in sources:
        value = _clean(getattr(source, field_name, ""))
        if value:
            counter[value] += 1
    return counter


def filter_sources(
    sources: list[OfficialSource],
    *,
    keyword: str = "",
    scope: str = "",
    priority: str = "",
) -> list[OfficialSource]:
    keyword_text = keyword.casefold().strip()
    output: list[OfficialSource] = []
    for source in sources:
        if scope and source.scope != scope:
            continue
        if priority and source.priority != priority:
            continue
        searchable = " ".join(
            [
                source.name,
                source.ministry,
                source.department,
                source.agency,
                source.source_type,
                source.coverage_note,
            ]
        ).casefold()
        if keyword_text and keyword_text not in searchable:
            continue
        output.append(source)
    return output
