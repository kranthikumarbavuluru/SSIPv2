from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceDocument:
    url: str
    kind: str
    title: str
    text: str
    sections: dict[str, list[str]] = field(default_factory=dict)
    links: list[dict[str, str]] = field(default_factory=list)
    fetched_at: str = ""
    http_status: int | None = None
    content_type: str = ""
    source_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceDocument":
        return cls(
            url=str(payload.get("url", "")),
            kind=str(payload.get("kind", "html")),
            title=str(payload.get("title", "")),
            text=str(payload.get("text", "")),
            sections={
                str(key): [str(item) for item in value]
                for key, value in (payload.get("sections") or {}).items()
                if isinstance(value, list)
            },
            links=[
                {
                    "url": str(item.get("url", "")),
                    "text": str(item.get("text", "")),
                }
                for item in (payload.get("links") or [])
                if isinstance(item, dict)
            ],
            fetched_at=str(payload.get("fetched_at", "")),
            http_status=payload.get("http_status"),
            content_type=str(payload.get("content_type", "")),
            source_hash=str(payload.get("source_hash", "")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class FetchFailure:
    url: str
    error_type: str
    error_message: str
    attempted_at: str
    master_id: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
