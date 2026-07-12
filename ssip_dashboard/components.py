from __future__ import annotations

import html
from collections import Counter
from typing import Any

from .funding import format_inr
from .status import status_css_class, status_label


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def mode_banner(mode: str, record_count: int, public_count: int) -> str:
    if mode == "CATALOGUE_PREVIEW":
        return (
            '<div class="preview-banner"><strong>Catalogue Preview</strong>'
            f"<span>{record_count} normalized records loaded for development. "
            f"{public_count} records are currently published.</span></div>"
        )
    return (
        '<div class="published-banner"><strong>Published Only</strong>'
        f"<span>{record_count} public records loaded from the publication workflow.</span></div>"
    )


def metric_card(label: str, value: Any, hint: str = "", tone: str = "blue") -> str:
    value_text = str(value)
    is_counting_number = value_text.isdigit()
    value_class = "metric-value is-counting" if is_counting_number else "metric-value"
    count_style = f' style="--ssip-count: {value_text}"' if is_counting_number else ""
    return (
        f'<div class="metric-card tone-{tone}">'
        f'<div class="{value_class}"{count_style} aria-label="{esc(value)}">{esc(value)}</div>'
        f'<div class="metric-label">{esc(label)}</div>'
        f'<div class="metric-hint">{esc(hint)}</div>'
        "</div>"
    )


def nav_header() -> str:
    return """
    <div class="gov-strip">
      <span>Government of India scheme intelligence</span>
      <span>Official sources &middot; Evidence reviewed &middot; Publication controlled</span>
    </div>
    <div class="top-shell">
      <div class="brand">
        <div class="brand-mark">SSIP</div>
        <div>
          <div class="brand-title">SSIP</div>
          <div class="brand-subtitle">Startup Scheme Intelligence Platform</div>
        </div>
      </div>
      <div class="nav-note"><span class="trust-dot"></span>Curated government schemes, programmes and live calls</div>
    </div>
    """


def scheme_card(record: Any, *, compact: bool = False) -> str:
    agency = (
        getattr(record, "department", "")
        or getattr(record, "implementing_agency", "")
        or getattr(record, "source", "")
        or "Agency / Source not recorded"
    )
    description = " ".join(
        (getattr(record, "objectives", []) or getattr(record, "benefits", []) or ["Information available in official sources."])[:2]
    )
    tags = [
        *getattr(record, "sectors", [])[:3],
        *getattr(record, "scheme_types", [])[:2],
    ]
    tag_html = "".join(f'<span class="tag">{esc(tag)}</span>' for tag in tags)
    links = []
    if getattr(record, "official_page_url", ""):
        links.append(f'<a target="_blank" href="{esc(record.official_page_url)}">Official Page</a>')
    if getattr(record, "application_url", ""):
        links.append(f'<a target="_blank" href="{esc(record.application_url)}">Application Portal</a>')
    if getattr(record, "guideline_urls", []):
        links.append(f'<a target="_blank" href="{esc(record.guideline_urls[0])}">Manual / Guideline</a>')
    link_html = "".join(f'<span class="link-pill">{link}</span>' for link in links)
    date_line = esc(getattr(record, "closing_date", "") or "Closing date not recorded")
    funding = format_inr(getattr(record, "funding_maximum", None))
    compact_class = " scheme-card-compact" if compact else ""
    return (
        f'<article class="scheme-card{compact_class}">'
        f'<div class="scheme-card-head"><span class="status-badge {status_css_class(record)}">{esc(status_label(record))}</span>'
        f'<span class="record-kind">{esc(getattr(record, "record_kind", "") or "Catalogue Record")}</span></div>'
        f'<h3>{esc(record.scheme_name)}</h3>'
        f'<div class="agency-line">Agency / Source: {esc(agency)}</div>'
        f'<p>{esc(description[:420])}</p>'
        f'<div class="scheme-meta"><span>Closing: {date_line}</span><span>Max recorded support: {esc(funding)}</span></div>'
        f'<div class="tag-row">{tag_html}</div>'
        f'<div class="link-row">{link_html}</div>'
        "</article>"
    )


def horizontal_bars(counter: Counter[str], *, limit: int = 8) -> str:
    if not counter:
        return '<div class="empty-note">No structured data recorded.</div>'
    max_value = max(counter.values()) or 1
    rows = []
    for label, value in counter.most_common(limit):
        width = max(6, int((value / max_value) * 100))
        rows.append(
            '<div class="bar-row">'
            f'<span class="bar-label">{esc(label)}</span>'
            '<span class="bar-track">'
            f'<span class="bar-fill" style="width:{width}%"></span>'
            "</span>"
            f'<span class="bar-value">{value}</span>'
            "</div>"
        )
    return '<div class="bar-panel">' + "".join(rows) + "</div>"


def warning_box(title: str, items: list[str]) -> str:
    if not items:
        return ""
    body = "".join(f"<li>{esc(item)}</li>" for item in items[:6])
    return f'<div class="warning-box"><strong>{esc(title)}</strong><ul>{body}</ul></div>'
