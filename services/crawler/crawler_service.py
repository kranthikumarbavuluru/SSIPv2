import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from config import USER_AGENT, REQUEST_TIMEOUT
from utils.logger import logger


class CrawlerService:

    def __init__(self):
        self.headers = {
            "User-Agent": USER_AGENT
        }

    def read_website(self, url):
        logger.info(f"Reading website: {url}")

        response = requests.get(
            url,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        logger.info(f"Website read successfully: {url}")

        return "\n".join(lines)

    def discover_links(self, url):
        logger.info(f"Discovering links from: {url}")

        response = requests.get(
            url,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        links = []
        seen = set()

        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            href = a["href"]
            full_url = urljoin(url, href)

            if full_url not in seen:
                seen.add(full_url)
                links.append({
                    "title": title,
                    "url": full_url
                })

        logger.info(f"Discovered {len(links)} links from: {url}")

        return links