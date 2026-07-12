from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.request import Request, urlopen

from .common import hostname, trusted_hostname


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: str
    content: str = ""
    reason: str = ""


class SourceFetchAgent:
    """Official-domain fetcher. Network access is disabled for preview by default."""

    def __init__(
        self,
        allowed_domains: list[str],
        enabled: bool = False,
        respect_robots_txt: bool = True,
        minimum_delay_seconds: float = 2.0,
        timeout_seconds: int = 20,
    ) -> None:
        self.allowed_domains = allowed_domains
        self.enabled = enabled
        self.respect_robots_txt = respect_robots_txt
        self.minimum_delay_seconds = minimum_delay_seconds
        self.timeout_seconds = timeout_seconds
        self._last_fetch = 0.0

    @staticmethod
    def snapshot(active_catalogue: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(active_catalogue, destination)

    def fetch(self, url: str) -> FetchResult:
        if not self.enabled:
            return FetchResult(url, "NETWORK_DISABLED", reason="Preview network access is disabled.")
        host = hostname(url)
        if not trusted_hostname(host, self.allowed_domains):
            return FetchResult(url, "DOMAIN_REJECTED", reason=f"Untrusted domain: {host}")
        if self.respect_robots_txt:
            parser = robotparser.RobotFileParser()
            parser.set_url(f"https://{host}/robots.txt")
            try:
                parser.read()
                if not parser.can_fetch("SSIPGovernedCatalogueBot/1.0", url):
                    return FetchResult(url, "ROBOTS_REJECTED", reason="robots.txt disallows access.")
            except OSError as exc:
                return FetchResult(url, "ROBOTS_UNAVAILABLE", reason=str(exc))
        wait = self.minimum_delay_seconds - (time.monotonic() - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        request = Request(url, headers={"User-Agent": "SSIPGovernedCatalogueBot/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            self._last_fetch = time.monotonic()
            return FetchResult(url, "FETCHED", content=body)
        except OSError as exc:
            return FetchResult(url, "FETCH_FAILED", reason=str(exc))
