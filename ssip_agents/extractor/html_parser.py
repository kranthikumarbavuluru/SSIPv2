from __future__ import annotations

from collections import defaultdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import SourceDocument
from .utils import normalize_space, sha256_text, utc_now_iso


_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_CONTENT_TAGS = {"p", "li", "td", "th", "dd", "dt"}
_REMOVE_TAGS = {
    "script", "style", "noscript", "svg", "canvas", "template",
    "form", "button", "input", "select", "option",
}


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    links: list[dict[str, str]] = []

    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href"))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        absolute = urljoin(base_url, href)
        text = normalize_space(anchor.get_text(" ", strip=True))
        key = (absolute, text.casefold())

        if key not in seen:
            seen.add(key)
            links.append({"url": absolute, "text": text})

    return links


def _select_content_root(soup: BeautifulSoup) -> Tag:
    selectors = (
        "main",
        "article",
        "[role='main']",
        "#main-content",
        "#content",
        ".main-content",
        ".content",
        ".page-content",
        ".field--name-body",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag) and len(normalize_space(node.get_text(" ", strip=True))) >= 120:
            return node

    return soup.body if isinstance(soup.body, Tag) else soup


def _extract_sections(root: Tag) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    current_heading = "Overview"

    for element in root.find_all(list(_HEADING_TAGS | _CONTENT_TAGS)):
        if not isinstance(element, Tag):
            continue

        # Avoid double-counting nested list items and table cells.
        if element.name in _CONTENT_TAGS:
            if element.find_parent(_CONTENT_TAGS):
                continue
            if element.find_parent(list(_HEADING_TAGS)):
                continue

        text = normalize_space(element.get_text(" ", strip=True))
        if not text:
            continue

        if element.name in _HEADING_TAGS:
            current_heading = text[:240]
            sections.setdefault(current_heading, [])
            continue

        # Avoid navigation crumbs and tiny fragments.
        if len(text) < 3:
            continue
        if text not in sections[current_heading]:
            sections[current_heading].append(text[:5000])

    return dict(sections)


def parse_html_document(
    *,
    url: str,
    html: str,
    http_status: int | None = None,
    content_type: str = "text/html",
    rendered_with_browser: bool = False,
) -> SourceDocument:
    soup = BeautifulSoup(html, "html.parser")
    links = _extract_links(soup, url)

    title = ""
    if soup.title:
        title = normalize_space(soup.title.get_text(" ", strip=True))

    description = ""
    meta = soup.find("meta", attrs={"name": lambda value: value and value.lower() == "description"})
    if meta and meta.get("content"):
        description = normalize_space(meta.get("content"))

    canonical_url = ""
    canonical = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
    if canonical and canonical.get("href"):
        canonical_url = urljoin(url, normalize_space(canonical.get("href")))

    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    root = _select_content_root(soup)

    # Remove global chrome only after link extraction.
    for selector in ("nav", "footer", "header", ".breadcrumb", ".breadcrumbs", ".social-share"):
        for node in root.select(selector):
            node.decompose()

    sections = _extract_sections(root)
    text_parts: list[str] = []

    if description:
        text_parts.append(description)

    for heading, values in sections.items():
        if heading != "Overview":
            text_parts.append(heading)
        text_parts.extend(values)

    text = normalize_space(" ".join(text_parts))
    if not text:
        text = normalize_space(root.get_text(" ", strip=True))

    return SourceDocument(
        url=canonical_url or url,
        kind="html",
        title=title,
        text=text,
        sections=sections,
        links=links,
        fetched_at=utc_now_iso(),
        http_status=http_status,
        content_type=content_type,
        source_hash=sha256_text(html),
        metadata={
            "description": description,
            "canonical_url": canonical_url,
            "rendered_with_browser": rendered_with_browser,
        },
    )
