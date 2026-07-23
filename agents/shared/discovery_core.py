from __future__ import annotations

import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from .official_domain_policy import OfficialDomainPolicy
from .url_normalization import normalize_url


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._anchor: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "title":
            self.in_title = True
        if tag.casefold() == "a":
            self._href = dict(attrs).get("href") or ""
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self.in_title = False
        if tag.casefold() == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor).strip()))
            self._href = ""
            self._anchor = []

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data.strip())
        if self._href and data.strip():
            self._anchor.append(data.strip())


@dataclass(frozen=True)
class FetchPage:
    requested_url: str
    final_url: str
    http_status: str
    content_type: str
    title: str
    links: tuple[tuple[str, str], ...]
    error: str = ""


class DiscoveryCore:
    """Small bounded fetcher; preview mode remains network-free by default."""

    def __init__(self, policy: OfficialDomainPolicy, enabled: bool = False,
                 delay_seconds: float = 1.0, timeout_seconds: int = 20) -> None:
        self.policy = policy
        self.enabled = enabled
        self.delay_seconds = max(0.0, delay_seconds)
        self.timeout_seconds = timeout_seconds
        self._last_request = 0.0

    def fetch(self, url: str) -> FetchPage:
        normalized = normalize_url(url)
        decision = self.policy.evaluate(normalized)
        if not decision.accepted:
            return FetchPage(url, normalized, "DOMAIN_REJECTED", "", "", (), decision.reason)
        if not self.enabled:
            return FetchPage(url, normalized, "PREVIEW_NOT_FETCHED", "", "", ())
        remaining = self.delay_seconds - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        request = Request(normalized, headers={"User-Agent": "SSIPDiscoveryBot/3.4.1.0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = str(getattr(response, "status", 200))
                content_type = response.headers.get_content_type()
                final_url = normalize_url(response.geturl())
                raw = response.read(2_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
            self._last_request = time.monotonic()
            if content_type != "text/html":
                return FetchPage(normalized, final_url, status, content_type, "", ())
            parser = _PageParser()
            parser.feed(raw.decode(charset, errors="replace"))
            title = " ".join(part for part in parser.title_parts if part).strip()
            links = []
            for href, anchor in parser.links:
                target = normalize_url(href, final_url)
                if target and self.policy.accepts(target):
                    links.append((target, anchor))
            return FetchPage(normalized, final_url, status, content_type, title, tuple(sorted(set(links))))
        except Exception as exc:  # failed sources must not abort a governed batch
            return FetchPage(normalized, normalized, "FETCH_FAILED", "", "", (), f"{type(exc).__name__}:{exc}")
