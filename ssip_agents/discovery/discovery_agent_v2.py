from __future__ import annotations

import asyncio
import gzip
import hashlib
import heapq
import logging
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from itertools import count
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic discovery vocabulary
# ---------------------------------------------------------------------------
# These are broad concepts, not a site-specific URL allow-list. They are used
# as weighted signals across URL, anchor text, title, headings and page text.
PRIMARY_SIGNALS: dict[str, float] = {
    "government scheme": 5.0,
    "scheme": 4.0,
    "schemes": 4.0,
    "financial assistance": 5.0,
    "financial support": 4.5,
    "grant": 4.0,
    "grants": 4.0,
    "funding": 4.0,
    "funding opportunity": 5.0,
    "seed fund": 5.0,
    "seed funding": 5.0,
    "subsidy": 4.5,
    "incentive": 4.0,
    "reimbursement": 4.0,
    "credit guarantee": 5.0,
    "soft loan": 4.5,
    "loan assistance": 4.5,
    "fellowship": 3.5,
    "call for proposal": 4.5,
    "call for proposals": 4.5,
    "request for proposal": 2.5,
    "challenge grant": 4.5,
    "innovation challenge": 3.5,
    "startup challenge": 3.5,
    "incubation programme": 4.0,
    "incubation program": 4.0,
    "accelerator programme": 3.5,
    "accelerator program": 3.5,
    "support programme": 3.5,
    "support program": 3.5,
    "programme support": 3.0,
    "program support": 3.0,
}

EVIDENCE_SIGNALS: dict[str, float] = {
    "eligibility": 2.4,
    "eligible": 1.6,
    "benefits": 2.4,
    "benefit": 1.6,
    "how to apply": 2.8,
    "apply now": 2.0,
    "application process": 2.4,
    "application form": 1.8,
    "guidelines": 1.7,
    "guideline": 1.2,
    "selection criteria": 1.8,
    "funding amount": 2.0,
    "assistance amount": 2.0,
    "last date": 1.5,
    "deadline": 1.4,
    "objectives": 1.0,
    "objective": 0.8,
    "who can apply": 2.4,
    "duration": 0.7,
    "implementing agency": 1.4,
}

AUDIENCE_SIGNALS: dict[str, float] = {
    "startup": 1.8,
    "start-up": 1.8,
    "entrepreneur": 1.7,
    "entrepreneurship": 1.7,
    "innovator": 1.7,
    "innovation": 1.4,
    "msme": 1.8,
    "micro enterprise": 1.4,
    "small enterprise": 1.4,
    "researcher": 1.2,
    "research institution": 1.2,
    "incubator": 1.5,
    "industry": 0.7,
    "technology": 0.7,
    "women entrepreneur": 1.8,
    "student innovator": 1.6,
}

NAVIGATION_SIGNALS: dict[str, float] = {
    "scheme": 4.0,
    "schemes": 4.0,
    "programme": 2.8,
    "programmes": 2.8,
    "program": 2.8,
    "programs": 2.8,
    "initiative": 2.2,
    "initiatives": 2.2,
    "funding": 3.5,
    "grant": 3.5,
    "support": 2.3,
    "opportunity": 2.1,
    "opportunities": 2.1,
    "startup": 2.0,
    "msme": 2.0,
    "innovation": 1.8,
    "entrepreneur": 1.8,
    "incubation": 2.4,
    "accelerator": 2.2,
    "incentive": 2.8,
    "subsidy": 3.0,
    "financial assistance": 3.5,
    "call for proposal": 3.0,
    "apply": 1.3,
    "policy": 1.0,
    "policies": 1.0,
    "services": 0.7,
}

NEGATIVE_SIGNALS: dict[str, float] = {
    "privacy policy": 8.0,
    "terms and conditions": 7.0,
    "terms of use": 7.0,
    "disclaimer": 7.0,
    "cookie policy": 7.0,
    "accessibility": 5.0,
    "contact us": 5.0,
    "about us": 3.5,
    "sitemap": 6.0,
    "login": 7.0,
    "log in": 7.0,
    "sign in": 7.0,
    "sign up": 6.0,
    "my account": 6.0,
    "my dashboard": 6.0,
    "profile": 4.0,
    "search": 3.0,
    "gallery": 5.0,
    "photo gallery": 6.0,
    "video gallery": 6.0,
    "press release": 4.5,
    "news": 2.5,
    "blog": 3.0,
    "event": 2.0,
    "events": 2.0,
    "career": 5.0,
    "careers": 5.0,
    "recruitment": 5.0,
    "vacancy": 5.0,
    "tender": 4.0,
    "procurement notice": 4.0,
    "annual report": 5.0,
    "budget": 5.5,
    "demand for grants": 8.0,
    "detailed demands for grants": 9.0,
    "telephone directory": 6.0,
    "staff directory": 6.0,
    "organization chart": 4.0,
    "organisation chart": 4.0,
    "success story": 2.0,
    "success stories": 2.0,
    "award ceremony": 3.0,
}

HARD_SKIP_PATH_PARTS = {
    "login",
    "logout",
    "signin",
    "signup",
    "register",
    "registration",
    "account",
    "dashboard",
    "profile",
    "search",
    "sitemap",
    "privacy",
    "disclaimer",
    "terms",
    "contact",
    "gallery",
    "careers",
    "career",
    "recruitment",
    "vacancy",
    "newsletter",
    "captcha",
    "wp-admin",
    "wp-login",
    "cart",
    "checkout",
}

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "session",
    "sessionid",
    "phpsessid",
}

HTML_EXTENSIONS = {"", ".html", ".htm", ".php", ".asp", ".aspx", ".jsp"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
ASSET_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".webm",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".xml",
    ".json",
    ".rss",
    ".atom",
}

MULTI_LABEL_SUFFIXES = {
    "gov.in",
    "nic.in",
    "ac.in",
    "edu.in",
    "co.in",
    "org.in",
    "net.in",
    "res.in",
    "com.au",
    "co.uk",
    "org.uk",
    "gov.uk",
    "co.jp",
    "com.sg",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DiscoveryConfig:
    max_depth: int = 3
    max_pages_per_seed: int = 120
    workers_per_seed: int = 4
    max_links_per_page: int = 80
    exploration_links_per_page: int = 12
    max_queue_size: int = 2_500

    candidate_threshold: float = 9.0
    document_threshold: float = 6.5
    crawl_threshold: float = 1.5

    timeout_connect: float = 8.0
    timeout_read: float = 20.0
    timeout_write: float = 10.0
    timeout_pool: float = 10.0
    max_retries: int = 3
    retry_backoff_base: float = 0.7
    request_delay: float = 0.20
    max_response_bytes: int = 4_000_000

    respect_robots: bool = True
    discover_sitemaps: bool = True
    max_sitemap_files: int = 20
    max_sitemap_urls: int = 5_000
    max_sitemap_urls_to_queue: int = 250

    use_browser_fallback: bool = True
    browser_headless: bool = True
    browser_timeout_ms: int = 25_000
    browser_wait_ms: int = 900
    max_browser_pages_per_seed: int = 6
    min_links_before_browser: int = 4

    user_agent: str = (
        "SSIP-Scheme-Discovery/2.0 "
        "(+government-scheme-indexing; respectful bounded crawler)"
    )


@dataclass(slots=True)
class SeedSource:
    name: str
    url: str
    allowed_domains: tuple[str, ...] = ()
    positive_terms: tuple[str, ...] = ()
    negative_terms: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: SeedSource | Mapping[str, Any]) -> SeedSource:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("Each seed source must be a mapping or SeedSource instance.")

        name = str(value.get("name", "")).strip()
        url = str(value.get("url", "")).strip()
        if not name or not url:
            raise ValueError("Each seed source requires non-empty 'name' and 'url'.")

        return cls(
            name=name,
            url=url,
            allowed_domains=tuple(str(x).lower() for x in value.get("allowed_domains", ())),
            positive_terms=tuple(str(x).lower() for x in value.get("positive_terms", ())),
            negative_terms=tuple(str(x).lower() for x in value.get("negative_terms", ())),
        )


@dataclass(slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    content: bytes

    @property
    def text(self) -> str:
        # UTF-8 with replacement is safer for discovery than failing the page.
        return self.content.decode("utf-8", errors="replace")


@dataclass(slots=True)
class LinkInfo:
    url: str
    anchor_text: str = ""
    title_text: str = ""
    rel: str = ""


@dataclass(slots=True)
class PageInfo:
    url: str
    title: str = ""
    description: str = ""
    headings: str = ""
    body_text: str = ""
    canonical_url: str | None = None
    links: list[LinkInfo] = field(default_factory=list)


@dataclass(order=True, slots=True)
class QueueEntry:
    priority: float
    sequence: int
    url: str = field(compare=False)
    depth: int = field(compare=False)
    parent_url: str | None = field(compare=False, default=None)
    anchor_text: str = field(compare=False, default="")
    discovery_method: str = field(compare=False, default="crawl")


class DomainRateLimiter:
    """Small per-host delay to avoid bursts against government websites."""

    def __init__(self) -> None:
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    async def wait(self, host: str, delay: float) -> None:
        if delay <= 0:
            return
        lock = self._locks[host]
        async with lock:
            now = time.monotonic()
            last = self._last_request.get(host, 0.0)
            remaining = delay - (now - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request[host] = time.monotonic()


class BrowserRenderer:
    """Optional Playwright renderer for JavaScript-heavy websites."""

    def __init__(self, config: DiscoveryConfig) -> None:
        self.config = config
        self._playwright = None
        self._browser = None
        self.available = False
        self._semaphore = asyncio.Semaphore(2)

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "Playwright is not installed. JavaScript fallback is disabled. "
                "Install with: pip install playwright && playwright install chromium"
            )
            return

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.browser_headless
            )
            self.available = True
        except Exception as exc:  # pragma: no cover - environment-specific
            logger.warning("Could not start Playwright Chromium: %s", exc)
            await self.close()

    async def render(self, url: str) -> str | None:
        if not self.available or self._browser is None:
            return None

        async with self._semaphore:
            page = None
            try:
                page = await self._browser.new_page(
                    user_agent=self.config.user_agent,
                    java_script_enabled=True,
                )
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.config.browser_timeout_ms,
                )
                await page.wait_for_timeout(self.config.browser_wait_ms)
                return await page.content()
            except Exception as exc:  # pragma: no cover - network/browser-specific
                logger.debug("Browser render failed: %s | %s", url, exc)
                return None
            finally:
                if page is not None:
                    await page.close()

    async def close(self) -> None:
        self.available = False
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


# ---------------------------------------------------------------------------
# Discovery agent
# ---------------------------------------------------------------------------
class DiscoveryAgentV2:
    """
    Bounded multi-source scheme discovery engine.

    It does not depend on a strict URL allow-list. Candidate relevance is
    calculated from multiple independent signals:
      * URL/path
      * anchor text
      * page title and meta description
      * H1/H2/H3 headings
      * cleaned body text
      * scheme evidence such as eligibility, benefits and application process

    It also uses robots.txt, XML sitemaps and an optional Playwright fallback.
    """

    def __init__(
        self,
        seed_sources: Sequence[SeedSource | Mapping[str, Any]],
        max_depth: int | None = None,
        max_pages_per_seed: int | None = None,
        concurrency: int | None = None,
        timeout: float | None = None,
        *,
        config: DiscoveryConfig | None = None,
        use_browser_fallback: bool | None = None,
        respect_robots: bool | None = None,
    ) -> None:
        self.seeds = [SeedSource.from_value(seed) for seed in seed_sources]
        if not self.seeds:
            raise ValueError("At least one seed source is required.")

        self.config = config or DiscoveryConfig()

        # Backward-compatible constructor parameters used by the existing test.
        # Explicit values override config; omitted values preserve config defaults.
        if max_depth is not None:
            self.config.max_depth = max(0, int(max_depth))
        if max_pages_per_seed is not None:
            self.config.max_pages_per_seed = max(1, int(max_pages_per_seed))
        if concurrency is not None:
            self.config.workers_per_seed = max(1, int(concurrency))
        if timeout is not None:
            self.config.timeout_read = max(1.0, float(timeout))
        if use_browser_fallback is not None:
            self.config.use_browser_fallback = bool(use_browser_fallback)
        if respect_robots is not None:
            self.config.respect_robots = bool(respect_robots)

        self._rate_limiter = DomainRateLimiter()
        self._robots_cache: dict[str, tuple[RobotFileParser, list[str], float]] = {}
        self._robots_lock = asyncio.Lock()
        self._results: dict[str, dict[str, Any]] = {}
        self._results_lock = asyncio.Lock()
        self._browser = BrowserRenderer(self.config)

        self.last_run_stats: dict[str, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # URL handling
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_url(url: str, base_url: str | None = None) -> str | None:
        if not url:
            return None
        try:
            absolute = urljoin(base_url, url) if base_url else url
            parsed = urlparse(absolute.strip())
            if parsed.scheme.lower() not in {"http", "https"}:
                return None
            if not parsed.hostname:
                return None

            scheme = parsed.scheme.lower()
            host = parsed.hostname.lower().rstrip(".")
            port = parsed.port
            if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
                netloc = f"{host}:{port}"
            else:
                netloc = host

            path = re.sub(r"/{2,}", "/", parsed.path or "/")
            if path != "/":
                path = path.rstrip("/")

            clean_query: list[tuple[str, str]] = []
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                key_lower = key.lower()
                if key_lower in TRACKING_QUERY_KEYS or key_lower.startswith("utm_"):
                    continue
                clean_query.append((key, value))
            clean_query.sort(key=lambda item: (item[0].lower(), item[1]))

            return urlunparse(
                (scheme, netloc, path, "", urlencode(clean_query, doseq=True), "")
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _root_domain(host: str) -> str:
        host = (host or "").lower().split(":", 1)[0].strip(".")
        if host.startswith("www."):
            host = host[4:]
        parts = host.split(".")
        if len(parts) <= 2:
            return host
        suffix2 = ".".join(parts[-2:])
        if suffix2 in MULTI_LABEL_SUFFIXES and len(parts) >= 3:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])

    def _is_allowed_site(self, url: str, seed: SeedSource) -> bool:
        host = (urlparse(url).hostname or "").lower()
        seed_host = (urlparse(seed.url).hostname or "").lower()
        if not host or not seed_host:
            return False
        if host == seed_host or self._root_domain(host) == self._root_domain(seed_host):
            return True
        return any(
            host == domain or host.endswith(f".{domain}")
            for domain in seed.allowed_domains
        )

    @staticmethod
    def _extension(url: str) -> str:
        path = urlparse(url).path.lower()
        final_segment = path.rsplit("/", 1)[-1]
        if "." not in final_segment:
            return ""
        return "." + final_segment.rsplit(".", 1)[-1]

    def _url_kind(self, url: str) -> str:
        ext = self._extension(url)
        if ext in DOCUMENT_EXTENSIONS:
            return "document"
        if ext in ASSET_EXTENSIONS:
            return "asset"
        if ext in HTML_EXTENSIONS:
            return "html"
        # Unknown extensions are treated conservatively as non-crawlable assets.
        return "asset"

    @staticmethod
    def _has_hard_skip_path(url: str) -> bool:
        path = unescape(urlparse(url).path.lower())
        parts = {part for part in re.split(r"[/_.\-]+", path) if part}
        return bool(parts.intersection(HARD_SKIP_PATH_PARTS))

    # ------------------------------------------------------------------
    # Text and scoring
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_text(text: str) -> str:
        text = unescape(text or "").lower()
        text = re.sub(r"[_/|:;,.()\[\]{}\-]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _dictionary_score(cls, text: str, vocabulary: Mapping[str, float]) -> tuple[float, list[str]]:
        normalised = cls._normalise_text(text)
        if not normalised:
            return 0.0, []
        score = 0.0
        matched: list[str] = []
        for phrase, weight in vocabulary.items():
            if cls._normalise_text(phrase) in normalised:
                score += weight
                matched.append(phrase)
        return score, matched

    def _custom_score(self, text: str, seed: SeedSource) -> tuple[float, list[str]]:
        normalised = self._normalise_text(text)
        score = 0.0
        reasons: list[str] = []
        for term in seed.positive_terms:
            if self._normalise_text(term) in normalised:
                score += 3.0
                reasons.append(f"custom+:{term}")
        for term in seed.negative_terms:
            if self._normalise_text(term) in normalised:
                score -= 4.0
                reasons.append(f"custom-:{term}")
        return score, reasons

    def _navigation_score(self, url: str, anchor_text: str, seed: SeedSource) -> float:
        url_text = unescape(urlparse(url).path + " " + urlparse(url).query)
        url_score, _ = self._dictionary_score(url_text, NAVIGATION_SIGNALS)
        anchor_score, _ = self._dictionary_score(anchor_text, NAVIGATION_SIGNALS)
        negative, _ = self._dictionary_score(f"{url_text} {anchor_text}", NEGATIVE_SIGNALS)
        custom, _ = self._custom_score(f"{url_text} {anchor_text}", seed)

        score = (1.20 * url_score) + (1.45 * anchor_score) - (1.30 * negative) + custom
        if self._has_hard_skip_path(url):
            score -= 12.0
        if self._url_kind(url) == "document":
            score += 0.5
        return round(score, 3)

    def _page_score(
        self,
        page: PageInfo,
        seed: SeedSource,
        anchor_text: str = "",
    ) -> tuple[float, list[str]]:
        fields = {
            "url": (page.url, 1.25),
            "anchor": (anchor_text, 1.20),
            "title": (page.title, 1.85),
            "description": (page.description, 1.10),
            "headings": (page.headings, 1.55),
            # Body weight is intentionally low; title/headings are more reliable.
            "body": (page.body_text[:25_000], 0.32),
        }

        score = 0.0
        reasons: list[str] = []
        primary_fields = 0
        evidence_fields = 0
        audience_fields = 0

        for field_name, (text, field_weight) in fields.items():
            primary_score, primary_matches = self._dictionary_score(text, PRIMARY_SIGNALS)
            evidence_score, evidence_matches = self._dictionary_score(text, EVIDENCE_SIGNALS)
            audience_score, audience_matches = self._dictionary_score(text, AUDIENCE_SIGNALS)
            negative_score, negative_matches = self._dictionary_score(text, NEGATIVE_SIGNALS)
            custom_score, custom_reasons = self._custom_score(text, seed)

            if primary_matches:
                primary_fields += 1
                reasons.extend(f"{field_name}:primary:{x}" for x in primary_matches[:4])
            if evidence_matches:
                evidence_fields += 1
                reasons.extend(f"{field_name}:evidence:{x}" for x in evidence_matches[:4])
            if audience_matches:
                audience_fields += 1
                reasons.extend(f"{field_name}:audience:{x}" for x in audience_matches[:3])
            if negative_matches:
                reasons.extend(f"{field_name}:negative:{x}" for x in negative_matches[:3])
            reasons.extend(f"{field_name}:{x}" for x in custom_reasons[:3])

            score += field_weight * (
                primary_score
                + (0.72 * evidence_score)
                + (0.45 * audience_score)
                - (1.10 * negative_score)
            )
            score += field_weight * custom_score

        # Multi-signal bonuses sharply reduce false positives such as budget pages
        # that contain the isolated word "grant" but no eligibility/application data.
        if primary_fields >= 2:
            score += 3.0
            reasons.append("bonus:primary-in-multiple-fields")
        if primary_fields >= 1 and evidence_fields >= 1:
            score += 4.0
            reasons.append("bonus:scheme-plus-evidence")
        if primary_fields >= 1 and audience_fields >= 1:
            score += 2.0
            reasons.append("bonus:scheme-plus-target-audience")
        if evidence_fields >= 2:
            score += 1.5
            reasons.append("bonus:evidence-in-multiple-fields")

        title_heading = f"{page.title} {page.headings}"
        strong_top_score, strong_top_matches = self._dictionary_score(title_heading, PRIMARY_SIGNALS)
        if strong_top_score >= 4.0:
            score += 3.0
            reasons.extend(f"bonus:title-heading:{x}" for x in strong_top_matches[:3])

        if self._has_hard_skip_path(page.url):
            score -= 18.0
            reasons.append("penalty:hard-skip-path")

        return round(score, 3), list(dict.fromkeys(reasons))[:20]

    def _document_score(
        self,
        url: str,
        anchor_text: str,
        seed: SeedSource,
    ) -> tuple[float, list[str]]:
        pseudo_page = PageInfo(
            url=url,
            title=anchor_text,
            headings=anchor_text,
            body_text="",
        )
        score, reasons = self._page_score(pseudo_page, seed, anchor_text)
        # A relevant PDF guideline/application document is valuable, but an
        # isolated generic PDF should not outrank a full HTML scheme page.
        return round(score * 0.72, 3), reasons

    # ------------------------------------------------------------------
    # Network, robots and sitemaps
    # ------------------------------------------------------------------
    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        delay: float | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult | None:
        host = (urlparse(url).hostname or "").lower()
        max_bytes = max_bytes or self.config.max_response_bytes
        request_delay = self.config.request_delay if delay is None else delay
        retry_statuses = {408, 425, 429, 500, 502, 503, 504}

        for attempt in range(self.config.max_retries + 1):
            await self._rate_limiter.wait(host, request_delay)
            try:
                async with client.stream("GET", url) as response:
                    status = response.status_code
                    if status in retry_statuses and attempt < self.config.max_retries:
                        retry_after = response.headers.get("retry-after", "").strip()
                        try:
                            sleep_for = min(float(retry_after), 20.0)
                        except ValueError:
                            sleep_for = self.config.retry_backoff_base * (2**attempt)
                            sleep_for += random.uniform(0.0, 0.35)
                        await response.aclose()
                        await asyncio.sleep(sleep_for)
                        continue

                    if status >= 400:
                        logger.debug("HTTP %s: %s", status, url)
                        return None

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        remaining = max_bytes - total
                        if remaining <= 0:
                            break
                        chunks.append(chunk[:remaining])
                        total += min(len(chunk), remaining)
                        if total >= max_bytes:
                            break

                    return FetchResult(
                        requested_url=url,
                        final_url=str(response.url),
                        status_code=status,
                        content_type=response.headers.get("content-type", "").lower(),
                        content=b"".join(chunks),
                    )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt >= self.config.max_retries:
                    logger.warning("Fetch failed: %s | %s", url, exc)
                    return None
                sleep_for = self.config.retry_backoff_base * (2**attempt)
                sleep_for += random.uniform(0.0, 0.35)
                await asyncio.sleep(sleep_for)
            except httpx.HTTPError as exc:
                logger.warning("HTTP error: %s | %s", url, exc)
                return None
        return None

    async def _robots_for(
        self,
        client: httpx.AsyncClient,
        seed: SeedSource,
    ) -> tuple[RobotFileParser, list[str], float]:
        parsed = urlparse(seed.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        async with self._robots_lock:
            cached = self._robots_cache.get(origin)
        if cached is not None:
            return cached

        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        sitemap_urls: list[str] = []
        crawl_delay = self.config.request_delay

        result = await self._request(
            client,
            robots_url,
            delay=0,
            max_bytes=750_000,
        )
        if result is not None:
            text = result.text
            try:
                parser.parse(text.splitlines())
                configured_delay = parser.crawl_delay(self.config.user_agent)
                if configured_delay is None:
                    configured_delay = parser.crawl_delay("*")
                if configured_delay is not None:
                    crawl_delay = max(crawl_delay, min(float(configured_delay), 10.0))
            except Exception as exc:
                logger.debug("robots.txt parse issue for %s: %s", origin, exc)

            for line in text.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidate = self.normalize_url(line.split(":", 1)[1].strip())
                    if candidate and self._is_allowed_site(candidate, seed):
                        sitemap_urls.append(candidate)
        else:
            # No readable robots.txt means there are no parsed restrictions.
            parser.parse([])

        cached_value = (parser, list(dict.fromkeys(sitemap_urls)), crawl_delay)
        async with self._robots_lock:
            self._robots_cache[origin] = cached_value
        return cached_value

    async def _can_fetch(
        self,
        client: httpx.AsyncClient,
        seed: SeedSource,
        url: str,
    ) -> tuple[bool, float]:
        parser, _, delay = await self._robots_for(client, seed)
        if not self.config.respect_robots:
            return True, delay
        try:
            return parser.can_fetch(self.config.user_agent, url), delay
        except Exception:
            return True, delay

    @staticmethod
    def _decode_sitemap(result: FetchResult) -> bytes:
        data = result.content
        if data[:2] == b"\x1f\x8b" or result.final_url.lower().endswith(".gz"):
            try:
                return gzip.decompress(data)
            except OSError:
                return data
        return data

    async def _collect_sitemap_urls(
        self,
        client: httpx.AsyncClient,
        seed: SeedSource,
        stats: defaultdict[str, int],
    ) -> list[str]:
        if not self.config.discover_sitemaps:
            return []

        parsed = urlparse(seed.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        _, robots_sitemaps, _ = await self._robots_for(client, seed)
        initial = robots_sitemaps + [
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap-index.xml",
        ]

        pending = list(dict.fromkeys(filter(None, (self.normalize_url(x) for x in initial))))
        visited_sitemaps: set[str] = set()
        page_urls: list[str] = []

        while pending and len(visited_sitemaps) < self.config.max_sitemap_files:
            sitemap_url = pending.pop(0)
            if sitemap_url in visited_sitemaps:
                continue
            visited_sitemaps.add(sitemap_url)

            result = await self._request(
                client,
                sitemap_url,
                max_bytes=8_000_000,
            )
            if result is None:
                continue

            raw = self._decode_sitemap(result)
            try:
                root = ElementTree.fromstring(raw)
            except ElementTree.ParseError:
                # Some sites publish a plain-text sitemap.
                text_urls = re.findall(r"https?://[^\s<>\"']+", raw.decode("utf-8", errors="ignore"))
                for text_url in text_urls:
                    normalised = self.normalize_url(text_url)
                    if normalised and self._is_allowed_site(normalised, seed):
                        page_urls.append(normalised)
                continue

            local_name = root.tag.rsplit("}", 1)[-1].lower()
            locations = [
                (element.text or "").strip()
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1].lower() == "loc" and element.text
            ]

            if local_name == "sitemapindex":
                for location in locations:
                    normalised = self.normalize_url(location)
                    if normalised and self._is_allowed_site(normalised, seed):
                        pending.append(normalised)
            else:
                for location in locations:
                    normalised = self.normalize_url(location)
                    if normalised and self._is_allowed_site(normalised, seed):
                        page_urls.append(normalised)
                        if len(page_urls) >= self.config.max_sitemap_urls:
                            break

            if len(page_urls) >= self.config.max_sitemap_urls:
                break

        stats["sitemaps_read"] += len(visited_sitemaps)
        stats["sitemap_urls"] += len(page_urls)
        return list(dict.fromkeys(page_urls))

    # ------------------------------------------------------------------
    # HTML extraction
    # ------------------------------------------------------------------
    def _parse_page(self, html: str, page_url: str, seed: SeedSource) -> PageInfo:
        soup = BeautifulSoup(html, "html.parser")

        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description = ""
        description_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if description_tag:
            description = str(description_tag.get("content", "")).strip()
        if not description:
            og_description = soup.find("meta", attrs={"property": "og:description"})
            if og_description:
                description = str(og_description.get("content", "")).strip()

        headings = " ".join(
            heading.get_text(" ", strip=True)
            for heading in soup.find_all(["h1", "h2", "h3"], limit=40)
        )

        canonical_url = None
        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        if canonical and canonical.get("href"):
            candidate = self.normalize_url(str(canonical["href"]), page_url)
            if candidate and self._is_allowed_site(candidate, seed):
                canonical_url = candidate

        # Remove repeated navigation and non-content areas before scoring body.
        body_soup = BeautifulSoup(html, "html.parser")
        for element in body_soup.find_all(
            ["script", "style", "noscript", "svg", "canvas", "nav", "footer", "form"]
        ):
            element.decompose()
        body_text = body_soup.get_text(" ", strip=True)
        body_text = re.sub(r"\s+", " ", body_text)[:40_000]

        links: dict[str, LinkInfo] = {}
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            normalised = self.normalize_url(href, page_url)
            if not normalised or not self._is_allowed_site(normalised, seed):
                continue
            if normalised.startswith(("mailto:", "tel:", "javascript:")):
                continue

            anchor_text = anchor.get_text(" ", strip=True)
            title_text = str(anchor.get("title", "")).strip()
            rel_value = anchor.get("rel", [])
            rel = " ".join(rel_value) if isinstance(rel_value, list) else str(rel_value or "")

            existing = links.get(normalised)
            if existing is None or len(anchor_text) > len(existing.anchor_text):
                links[normalised] = LinkInfo(
                    url=normalised,
                    anchor_text=anchor_text[:500],
                    title_text=title_text[:300],
                    rel=rel[:100],
                )

        return PageInfo(
            url=page_url,
            title=title[:1_000],
            description=description[:2_000],
            headings=headings[:8_000],
            body_text=body_text,
            canonical_url=canonical_url,
            links=list(links.values()),
        )

    @staticmethod
    def _looks_javascript_heavy(html: str, page: PageInfo, min_links: int) -> bool:
        if len(page.links) >= min_links:
            return False
        script_count = html.lower().count("<script")
        visible_text_length = len(page.body_text.strip())
        root_markers = any(
            marker in html.lower()
            for marker in ('id="root"', "id='root'", 'id="app"', "id='app'", "__next_data__")
        )
        return script_count >= 5 or visible_text_length < 500 or root_markers

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    @staticmethod
    def url_hash(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    async def _store_candidate(
        self,
        *,
        seed: SeedSource,
        url: str,
        score: float,
        reasons: Iterable[str],
        title: str,
        description: str,
        depth: int,
        parent_url: str | None,
        anchor_text: str,
        discovery_method: str,
        content_kind: str,
    ) -> bool:
        normalised = self.normalize_url(url)
        if not normalised:
            return False

        key = f"{seed.name}|{normalised}"
        record = {
            "url": normalised,
            "source": seed.name,
            "status": "PENDING",
            "content_kind": content_kind,
            "relevance_score": round(score, 3),
            "relevance_reasons": list(dict.fromkeys(reasons))[:20],
            "title": title.strip()[:1_000],
            "description": description.strip()[:2_000],
            "anchor_text": anchor_text.strip()[:500],
            "depth": depth,
            "parent_url": parent_url,
            "discovery_method": discovery_method,
            "hash": self.url_hash(normalised),
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }

        async with self._results_lock:
            old = self._results.get(key)
            if old is None or score > float(old.get("relevance_score", 0.0)):
                self._results[key] = record
                return old is None
        return False

    # ------------------------------------------------------------------
    # Seed crawl
    # ------------------------------------------------------------------
    async def _discover_seed(
        self,
        client: httpx.AsyncClient,
        seed: SeedSource,
    ) -> None:
        seed_url = self.normalize_url(seed.url)
        if not seed_url:
            logger.error("Invalid seed URL: %s | %s", seed.name, seed.url)
            return
        seed.url = seed_url

        stats: defaultdict[str, int] = defaultdict(int)
        queue: asyncio.PriorityQueue[QueueEntry] = asyncio.PriorityQueue()
        sequence = count()
        visited: set[str] = set()
        enqueued: set[str] = set()
        state_lock = asyncio.Lock()
        browser_pages_used = 0

        async def enqueue(
            url: str,
            depth: int,
            priority_score: float,
            *,
            parent_url: str | None,
            anchor_text: str,
            discovery_method: str,
        ) -> bool:
            normalised = self.normalize_url(url)
            if not normalised or not self._is_allowed_site(normalised, seed):
                return False
            if self._url_kind(normalised) != "html":
                return False
            async with state_lock:
                if normalised in visited or normalised in enqueued:
                    return False
                if len(enqueued) >= self.config.max_queue_size:
                    return False
                enqueued.add(normalised)
                queue.put_nowait(
                    QueueEntry(
                        priority=-priority_score,
                        sequence=next(sequence),
                        url=normalised,
                        depth=depth,
                        parent_url=parent_url,
                        anchor_text=anchor_text,
                        discovery_method=discovery_method,
                    )
                )
                stats["queued"] += 1
                return True

        logger.info("Started seed: %s | %s", seed.name, seed_url)
        await enqueue(
            seed_url,
            0,
            100.0,
            parent_url=None,
            anchor_text=seed.name,
            discovery_method="seed",
        )

        # Sitemap URLs are ranked, not blindly fetched. This exposes pages that
        # are not linked from the homepage while keeping the crawl bounded.
        sitemap_urls = await self._collect_sitemap_urls(client, seed, stats)
        ranked_sitemap_urls: list[tuple[float, str]] = []
        for sitemap_page_url in sitemap_urls:
            kind = self._url_kind(sitemap_page_url)
            nav_score = self._navigation_score(sitemap_page_url, "", seed)
            if kind == "document":
                document_score, reasons = self._document_score(sitemap_page_url, "", seed)
                if document_score >= self.config.document_threshold:
                    added = await self._store_candidate(
                        seed=seed,
                        url=sitemap_page_url,
                        score=document_score,
                        reasons=reasons,
                        title="",
                        description="",
                        depth=0,
                        parent_url=None,
                        anchor_text="",
                        discovery_method="sitemap",
                        content_kind="document",
                    )
                    if added:
                        stats["candidates"] += 1
                continue
            if kind == "html":
                ranked_sitemap_urls.append((nav_score, sitemap_page_url))

        ranked_sitemap_urls.sort(key=lambda item: item[0], reverse=True)
        selected_sitemap_urls = ranked_sitemap_urls[: self.config.max_sitemap_urls_to_queue]
        for nav_score, sitemap_page_url in selected_sitemap_urls:
            # A small baseline allows exploration of sitemap pages even when
            # opaque numeric URLs contain no useful words.
            await enqueue(
                sitemap_page_url,
                1,
                max(nav_score, 0.25),
                parent_url=None,
                anchor_text="",
                discovery_method="sitemap",
            )

        async def worker(worker_number: int) -> None:
            nonlocal browser_pages_used
            while True:
                entry = await queue.get()
                try:
                    async with state_lock:
                        enqueued.discard(entry.url)
                        if entry.url in visited:
                            stats["duplicates"] += 1
                            continue
                        if entry.depth > self.config.max_depth:
                            continue
                        if stats["pages_claimed"] >= self.config.max_pages_per_seed:
                            continue
                        visited.add(entry.url)
                        stats["pages_claimed"] += 1

                    allowed, crawl_delay = await self._can_fetch(client, seed, entry.url)
                    if not allowed:
                        stats["robots_blocked"] += 1
                        continue

                    result = await self._request(client, entry.url, delay=crawl_delay)
                    if result is None:
                        stats["fetch_errors"] += 1
                        continue

                    content_type = result.content_type
                    if "html" not in content_type and "xhtml" not in content_type:
                        stats["non_html"] += 1
                        continue

                    final_url = self.normalize_url(result.final_url) or entry.url
                    if not self._is_allowed_site(final_url, seed):
                        stats["external_redirects"] += 1
                        continue

                    html = result.text
                    page = self._parse_page(html, final_url, seed)
                    stats["pages_fetched"] += 1

                    if (
                        self.config.use_browser_fallback
                        and self._browser.available
                        and entry.depth <= 1
                        and self._looks_javascript_heavy(
                            html, page, self.config.min_links_before_browser
                        )
                    ):
                        async with state_lock:
                            can_render = browser_pages_used < self.config.max_browser_pages_per_seed
                            if can_render:
                                browser_pages_used += 1
                        if can_render:
                            rendered_html = await self._browser.render(final_url)
                            if rendered_html:
                                rendered_page = self._parse_page(rendered_html, final_url, seed)
                                if len(rendered_page.links) > len(page.links) or len(
                                    rendered_page.body_text
                                ) > len(page.body_text):
                                    page = rendered_page
                                    stats["browser_renders"] += 1

                    candidate_url = page.canonical_url or final_url
                    page.url = candidate_url
                    score, reasons = self._page_score(page, seed, entry.anchor_text)
                    if score >= self.config.candidate_threshold:
                        added = await self._store_candidate(
                            seed=seed,
                            url=candidate_url,
                            score=score,
                            reasons=reasons,
                            title=page.title,
                            description=page.description,
                            depth=entry.depth,
                            parent_url=entry.parent_url,
                            anchor_text=entry.anchor_text,
                            discovery_method=entry.discovery_method,
                            content_kind="html",
                        )
                        if added:
                            stats["candidates"] += 1

                    if entry.depth >= self.config.max_depth:
                        continue

                    ranked_links: list[tuple[float, LinkInfo]] = []
                    for link in page.links:
                        if link.url == final_url:
                            continue
                        kind = self._url_kind(link.url)
                        combined_anchor = " ".join(
                            part for part in (link.anchor_text, link.title_text) if part
                        )

                        if kind == "asset":
                            continue
                        if kind == "document":
                            document_score, document_reasons = self._document_score(
                                link.url, combined_anchor, seed
                            )
                            if document_score >= self.config.document_threshold:
                                added = await self._store_candidate(
                                    seed=seed,
                                    url=link.url,
                                    score=document_score,
                                    reasons=document_reasons,
                                    title=combined_anchor,
                                    description="",
                                    depth=entry.depth + 1,
                                    parent_url=final_url,
                                    anchor_text=combined_anchor,
                                    discovery_method="link",
                                    content_kind="document",
                                )
                                if added:
                                    stats["candidates"] += 1
                            continue

                        nav_score = self._navigation_score(link.url, combined_anchor, seed)
                        ranked_links.append((nav_score, link))

                    ranked_links.sort(key=lambda item: item[0], reverse=True)
                    selected: list[tuple[float, LinkInfo]] = []
                    exploratory_count = 0
                    for nav_score, link in ranked_links[: self.config.max_links_per_page]:
                        if nav_score >= self.config.crawl_threshold:
                            selected.append((nav_score, link))
                            continue
                        # Controlled exploration prevents missing opaque category
                        # pages while keeping the crawler bounded.
                        if (
                            entry.depth <= 1
                            and exploratory_count < self.config.exploration_links_per_page
                            and nav_score > -3.0
                            and not self._has_hard_skip_path(link.url)
                        ):
                            selected.append((max(nav_score, 0.05), link))
                            exploratory_count += 1

                    for nav_score, link in selected:
                        await enqueue(
                            link.url,
                            entry.depth + 1,
                            nav_score + max(0.0, 1.0 - (entry.depth * 0.25)),
                            parent_url=final_url,
                            anchor_text=" ".join(
                                part for part in (link.anchor_text, link.title_text) if part
                            ),
                            discovery_method="crawl",
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    stats["worker_errors"] += 1
                    logger.exception(
                        "Unexpected discovery error: source=%s worker=%s url=%s",
                        seed.name,
                        worker_number,
                        entry.url,
                    )
                finally:
                    queue.task_done()

        workers = [
            asyncio.create_task(worker(number), name=f"discovery-{seed.name}-{number}")
            for number in range(self.config.workers_per_seed)
        ]
        await queue.join()
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        self.last_run_stats[seed.name] = dict(stats)
        logger.info(
            "Completed seed: %s | Fetched: %d | Candidates: %d | "
            "Queued: %d | Sitemap URLs: %d | Browser renders: %d | Errors: %d",
            seed.name,
            stats["pages_fetched"],
            stats["candidates"],
            stats["queued"],
            stats["sitemap_urls"],
            stats["browser_renders"],
            stats["fetch_errors"] + stats["worker_errors"],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self) -> list[dict[str, Any]]:
        self._results.clear()
        self.last_run_stats.clear()
        self._robots_cache.clear()

        timeout = httpx.Timeout(
            connect=self.config.timeout_connect,
            read=self.config.timeout_read,
            write=self.config.timeout_write,
            pool=self.config.timeout_pool,
        )
        limits = httpx.Limits(
            max_connections=max(20, len(self.seeds) * self.config.workers_per_seed * 2),
            max_keepalive_connections=max(10, len(self.seeds) * 2),
            keepalive_expiry=30.0,
        )

        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-IN,en;q=0.9",
            "Cache-Control": "no-cache",
        }

        if self.config.use_browser_fallback:
            await self._browser.start()

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                headers=headers,
                follow_redirects=True,
                http2=False,
            ) as client:
                await asyncio.gather(
                    *(self._discover_seed(client, seed) for seed in self.seeds),
                    return_exceptions=False,
                )
        finally:
            await self._browser.close()

        return sorted(
            self._results.values(),
            key=lambda item: (
                item["source"].lower(),
                -float(item["relevance_score"]),
                item["url"],
            ),
        )
