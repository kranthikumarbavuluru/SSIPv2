from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .html_parser import parse_html_document
from .models import FetchFailure, SourceDocument
from .pdf_parser import parse_pdf_document
from .utils import atomic_write_json, load_json, sha256_text, utc_now_iso


logger = logging.getLogger(__name__)


class SourceFetcher:
    def __init__(
        self,
        *,
        cache_dir: Path,
        timeout_seconds: float = 30.0,
        max_connections: int = 10,
        cache_ttl_hours: int = 24,
        max_download_mb: int = 20,
        max_pdf_pages: int = 80,
        use_browser_fallback: bool = True,
        browser_text_threshold: int = 450,
        browser_ignore_https_errors: bool = False,
        browser_force_hosts: list[str] | None = None,
        insecure_ssl_hosts: list[str] | None = None,
        user_agent: str = "SSIP-Scheme-Extraction-Agent/1.0",
        retries: int = 2,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.timeout_seconds = timeout_seconds
        self.cache_ttl_hours = cache_ttl_hours
        self.max_download_bytes = max_download_mb * 1024 * 1024
        self.max_pdf_pages = max_pdf_pages
        self.use_browser_fallback = use_browser_fallback
        self.browser_text_threshold = browser_text_threshold
        self.browser_ignore_https_errors = browser_ignore_https_errors
        self.browser_force_hosts = {
            host.casefold() for host in (browser_force_hosts or []) if host
        }
        self.insecure_ssl_hosts = {host.casefold() for host in (insecure_ssl_hosts or [])}
        self.retries = max(0, retries)

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max(2, max_connections // 2),
        )
        timeout = httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.7",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        self.client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True,
            headers=headers,
            verify=True,
        )
        self.insecure_client: httpx.AsyncClient | None = None
        if self.insecure_ssl_hosts:
            self.insecure_client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
                headers=headers,
                verify=False,
            )

        self.failures: list[FetchFailure] = []
        self.stats: dict[str, int] = {
            "cache_hits": 0,
            "network_fetches": 0,
            "browser_renders": 0,
            "pdf_documents": 0,
            "html_documents": 0,
            "fetch_failures": 0,
        }

        self._playwright: Any = None
        self._browser: Any = None
        self._browser_lock = asyncio.Lock()
        self._browser_semaphore = asyncio.Semaphore(2)
        self._browser_unavailable_logged = False

    async def __aenter__(self) -> "SourceFetcher":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                logger.debug("Browser close failed", exc_info=True)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("Playwright stop failed", exc_info=True)

        await self.client.aclose()
        if self.insecure_client is not None:
            await self.insecure_client.aclose()

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{sha256_text(url)}.json"

    def _cache_is_fresh(self, payload: dict[str, Any]) -> bool:
        cached_at = payload.get("cached_at")
        if not cached_at:
            return False
        try:
            timestamp = datetime.fromisoformat(str(cached_at))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - timestamp <= timedelta(hours=self.cache_ttl_hours)
        except (TypeError, ValueError):
            return False

    def _load_cache(self, url: str) -> SourceDocument | None:
        payload = load_json(self._cache_path(url), default=None)
        if not isinstance(payload, dict) or not self._cache_is_fresh(payload):
            return None

        document_payload = payload.get("document")
        if not isinstance(document_payload, dict):
            return None

        self.stats["cache_hits"] += 1
        return SourceDocument.from_dict(document_payload)

    def _save_cache(self, requested_url: str, document: SourceDocument) -> None:
        atomic_write_json(
            self._cache_path(requested_url),
            {
                "requested_url": requested_url,
                "cached_at": utc_now_iso(),
                "document": document.to_dict(),
            },
        )

    def _record_failure(
        self,
        *,
        url: str,
        exc: Exception,
        master_id: str | None,
        source: str | None,
    ) -> None:
        self.stats["fetch_failures"] += 1
        failure = FetchFailure(
            url=url,
            error_type=type(exc).__name__,
            error_message=str(exc)[:1000],
            attempted_at=utc_now_iso(),
            master_id=master_id,
            source=source,
        )
        self.failures.append(failure)
        logger.warning("Source fetch failed: %s | %s", url, exc)

    async def _request(self, url: str) -> httpx.Response:
        parsed = urlparse(url)
        client = self.client
        if parsed.hostname and parsed.hostname.casefold() in self.insecure_ssl_hosts:
            if self.insecure_client is None:
                raise RuntimeError("Insecure client is not configured")
            client = self.insecure_client

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_download_bytes:
                    raise ValueError(
                        f"Content too large: {int(content_length)} bytes "
                        f"(limit {self.max_download_bytes})"
                    )

                if len(response.content) > self.max_download_bytes:
                    raise ValueError(
                        f"Downloaded content too large: {len(response.content)} bytes "
                        f"(limit {self.max_download_bytes})"
                    )
                return response
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                await asyncio.sleep(min(4.0, 0.6 * (2 ** attempt)))

        assert last_error is not None
        raise last_error

    @staticmethod
    def _looks_like_pdf(url: str, content_type: str, content: bytes) -> bool:
        return (
            urlparse(url).path.casefold().endswith(".pdf")
            or "application/pdf" in content_type.casefold()
            or content.startswith(b"%PDF")
        )

    async def _ensure_browser(self) -> bool:
        if self._browser is not None:
            return True

        async with self._browser_lock:
            if self._browser is not None:
                return True

            try:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                return True
            except Exception as exc:
                if not self._browser_unavailable_logged:
                    logger.info(
                        "Playwright browser fallback unavailable: %s. "
                        "Normal HTML/PDF extraction will continue.",
                        exc,
                    )
                    self._browser_unavailable_logged = True
                self._browser = None
                return False

    async def _render_with_browser(self, url: str) -> str | None:
        if not await self._ensure_browser():
            return None

        async with self._browser_semaphore:
            context = await self._browser.new_context(
                ignore_https_errors=self.browser_ignore_https_errors,
                locale="en-IN",
            )
            page = await context.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.timeout_seconds * 1000),
                )
                try:
                    await page.wait_for_load_state(
                        "networkidle",
                        timeout=min(int(self.timeout_seconds * 1000), 15000),
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(800)
                self.stats["browser_renders"] += 1
                return await page.content()
            finally:
                await context.close()

    async def fetch(
        self,
        *,
        url: str,
        title_hint: str = "",
        master_id: str | None = None,
        source: str | None = None,
        force_refresh: bool = False,
    ) -> SourceDocument | None:
        if not force_refresh:
            cached = self._load_cache(url)
            if cached is not None:
                return cached

        try:
            response = await self._request(url)
            self.stats["network_fetches"] += 1

            content_type = response.headers.get("content-type", "")
            final_url = str(response.url)

            if self._looks_like_pdf(final_url, content_type, response.content):
                document = await asyncio.to_thread(
                    parse_pdf_document,
                    url=final_url,
                    content=response.content,
                    title_hint=title_hint,
                    max_pages=self.max_pdf_pages,
                    http_status=response.status_code,
                    content_type=content_type,
                )
                self.stats["pdf_documents"] += 1
            else:
                html = response.text
                document = parse_html_document(
                    url=final_url,
                    html=html,
                    http_status=response.status_code,
                    content_type=content_type,
                )

                rendered_host = (urlparse(final_url).hostname or "").casefold()
                force_browser = (
                    rendered_host in self.browser_force_hosts
                    or any(
                        rendered_host.endswith(f".{host}")
                        for host in self.browser_force_hosts
                    )
                )
                if (
                    self.use_browser_fallback
                    and (
                        force_browser
                        or len(document.text) < self.browser_text_threshold
                    )
                ):
                    rendered_html = await self._render_with_browser(final_url)
                    if rendered_html:
                        rendered_document = parse_html_document(
                            url=final_url,
                            html=rendered_html,
                            http_status=response.status_code,
                            content_type="text/html; rendered=playwright",
                            rendered_with_browser=True,
                        )
                        if len(rendered_document.text) > len(document.text):
                            document = rendered_document

                self.stats["html_documents"] += 1

            self._save_cache(url, document)
            return document

        except Exception as exc:
            self._record_failure(
                url=url,
                exc=exc,
                master_id=master_id,
                source=source,
            )
            return None
