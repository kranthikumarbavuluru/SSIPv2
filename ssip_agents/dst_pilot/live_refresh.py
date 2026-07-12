from __future__ import annotations

import csv
import gzip
import hashlib
import logging
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from .call_extractor import trusted_url
from .common import clean, utc_now
from .profile import DepartmentProfile


LOGGER = logging.getLogger(__name__)


class OfficialLiveCallRefresher:
    """Bounded, respectful refresh of the current DST call index and its official evidence links."""

    INDEX_URL = "https://dst.gov.in/call-for-proposals"

    def __init__(self, profile: DepartmentProfile, output_dir: Path, delay_seconds: float = 0.6) -> None:
        self.profile = profile
        self.output_dir = output_dir
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SSIP-DST-Evidence-Pilot/1.0 (+official-source-curation)"
        adapter = HTTPAdapter(max_retries=0)
        self.session.mount("https://", adapter)
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request = 0.0

    @staticmethod
    def _normalize(url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", parsed.query, ""))

    def _allowed(self, url: str) -> bool:
        if not trusted_url(url, self.profile.official_domains):
            return False
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots_url = urljoin(origin, "/robots.txt")
            robots = urllib.robotparser.RobotFileParser(robots_url)
            try:
                response = self.session.get(robots_url, timeout=(3, 5))
                if response.ok:
                    robots.parse(response.text.splitlines())
                else:
                    robots.parse(["User-agent: *", "Disallow:"])
            except Exception:
                robots.parse(["User-agent: *", "Disallow:"])
            self._robots[origin] = robots
        return self._robots[origin].can_fetch(self.session.headers["User-Agent"], url)

    def _fetch(self, url: str) -> tuple[str, str]:
        if not self._allowed(url):
            return "", ""
        wait = self.delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=(6, 15))
        self._last_request = time.monotonic()
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", "").casefold():
            return "", ""
        return self._normalize(response.url), response.text

    def _save(self, url: str, content: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        path = self.output_dir / "snapshots" / f"{digest}.html.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(content)
        return str(path.relative_to(self.output_dir))

    @staticmethod
    def _main_links(url: str, content: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        main = soup.find("main") or soup.find("article") or soup.body or soup
        output: list[str] = []
        for anchor in main.find_all("a", href=True):
            target = urljoin(url, anchor["href"]).split("#", 1)[0]
            if target not in output:
                output.append(target)
        return output

    def run(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        queue: list[tuple[str, int]] = [(self.INDEX_URL, 0)]
        queue.extend((str(item["page_url"]), 1) for item in self.profile.payload.get("monitored_call_pages", []))
        visited: set[str] = set()
        rows: list[dict[str, str]] = []
        successful_pages = 0
        while queue and len(visited) < 12:
            requested, depth = queue.pop(0)
            normalized = self._normalize(requested)
            if normalized in visited:
                continue
            visited.add(normalized)
            try:
                final_url, content = self._fetch(normalized)
            except requests.RequestException as exc:
                LOGGER.warning("DST live refresh failed for %s: %s", normalized, exc)
                rows.append({
                    "requested_url": normalized,
                    "final_url": "",
                    "snapshot_path": "",
                    "fetched_at": utc_now(),
                    "fetch_status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            if not content:
                rows.append({
                    "requested_url": normalized,
                    "final_url": final_url,
                    "snapshot_path": "",
                    "fetched_at": utc_now(),
                    "fetch_status": "SKIPPED_NON_HTML_OR_DISALLOWED",
                    "error": "",
                })
                continue
            successful_pages += 1
            rows.append({
                "requested_url": normalized,
                "final_url": final_url,
                "snapshot_path": self._save(final_url, content),
                "fetched_at": utc_now(),
                "fetch_status": "OK",
                "error": "",
            })
            links = self._main_links(final_url, content)
            if depth == 0:
                queue.extend((link, 1) for link in links if "/callforproposals" in urlparse(link).path and trusted_url(link, {"dst.gov.in"}))
            elif depth == 1:
                external = [link for link in links if trusted_url(link, self.profile.official_domains) and urlparse(link).hostname != "dst.gov.in"]
                queue.extend((link, 2) for link in external[:2])
        inventory = self.output_dir / "live_crawled_pages.csv"
        with inventory.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "requested_url", "final_url", "snapshot_path", "fetched_at", "fetch_status", "error",
            ])
            writer.writeheader()
            writer.writerows(rows)
        if not successful_pages:
            raise RuntimeError(f"DST live refresh did not retrieve any official HTML pages; inspect {inventory}.")
        return inventory
