from __future__ import annotations

import io
import re
from collections import defaultdict

from pypdf import PdfReader

from .models import SourceDocument
from .utils import normalize_space, sha256_bytes, utc_now_iso


_SECTION_HINTS = (
    "overview", "objective", "objectives", "eligibility", "eligible",
    "who can apply", "benefits", "financial assistance", "funding",
    "grant", "support", "application process", "how to apply",
    "documents required", "required documents", "selection process",
    "duration", "contact", "important dates", "guidelines",
)


def _is_heading(line: str) -> bool:
    cleaned = normalize_space(line).strip(" :-")
    if not cleaned or len(cleaned) > 140:
        return False

    lower = cleaned.casefold()
    if any(hint in lower for hint in _SECTION_HINTS):
        return True

    words = cleaned.split()
    if 1 <= len(words) <= 10 and cleaned.isupper() and len(cleaned) >= 4:
        return True

    if 1 <= len(words) <= 8 and cleaned.endswith(":"):
        return True

    return False


def _extract_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    current = "Overview"

    for raw_line in text.splitlines():
        line = normalize_space(raw_line)
        if not line:
            continue

        if _is_heading(line):
            current = line.strip(" :-")[:240]
            sections.setdefault(current, [])
            continue

        if len(line) >= 3:
            sections[current].append(line[:5000])

    return dict(sections)


def parse_pdf_document(
    *,
    url: str,
    content: bytes,
    title_hint: str = "",
    max_pages: int = 80,
    http_status: int | None = None,
    content_type: str = "application/pdf",
) -> SourceDocument:
    reader = PdfReader(io.BytesIO(content))
    page_count = len(reader.pages)
    extracted_pages: list[str] = []
    extraction_errors = 0

    for index, page in enumerate(reader.pages[:max_pages]):
        try:
            page_text = page.extract_text() or ""
            page_text = page_text.replace("\x00", " ")
            extracted_pages.append(page_text)
        except Exception:
            extraction_errors += 1

    raw_text = "\n".join(extracted_pages)
    text = normalize_space(raw_text)
    sections = _extract_sections(raw_text)

    metadata = reader.metadata or {}
    metadata_title = normalize_space(
        getattr(metadata, "title", None)
        or (metadata.get("/Title") if hasattr(metadata, "get") else "")
    )

    title = metadata_title or normalize_space(title_hint)
    if not title:
        title = url.rsplit("/", 1)[-1].replace("_", " ").replace("-", " ")

    return SourceDocument(
        url=url,
        kind="pdf",
        title=title,
        text=text,
        sections=sections,
        links=[],
        fetched_at=utc_now_iso(),
        http_status=http_status,
        content_type=content_type,
        source_hash=sha256_bytes(content),
        metadata={
            "page_count": page_count,
            "pages_extracted": min(page_count, max_pages),
            "page_extraction_errors": extraction_errors,
            "pdf_metadata": {
                "title": metadata_title,
                "author": normalize_space(
                    getattr(metadata, "author", None)
                    or (metadata.get("/Author") if hasattr(metadata, "get") else "")
                ),
            },
        },
    )
