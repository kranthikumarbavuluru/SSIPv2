from utils.logger import logger

from services.crawler.crawler_service import CrawlerService
from services.database.seed_url_repository import SeedUrlRepository
from services.database.link_repository import LinkRepository
from services.scoring.link_scoring_service import LinkScoringService


class DiscoveryAgent:

    def __init__(self):
        self.seed_repo = SeedUrlRepository()
        self.crawler = CrawlerService()
        self.link_repo = LinkRepository()
        self.scorer = LinkScoringService()

    def run(self):
        logger.info("=" * 60)
        logger.info("Discovery Agent Started")
        logger.info("=" * 60)

        sources = self.seed_repo.get_active_sources()

        total_sources = len(sources)
        total_discovered = 0
        total_saved = 0

        logger.info(f"Found {total_sources} active seed sources.")

        for source in sources:
            name = source["source_name"]
            url = source["url"]

            logger.info(f"Crawling: {name} | {url}")

            try:
                links = self.crawler.discover_links(url)

                total_discovered += len(links)

                scored_links = self.scorer.score_links(links)

                saved = self.link_repo.save_raw_links(
                    scored_links,
                    source_url=url
                )

                total_saved += saved

                logger.info(
                    f"{name}: {len(links)} discovered, "
                    f"{len(scored_links)} scored, "
                    f"{saved} new saved."
                )

            except Exception as e:
                logger.error(f"{name} failed.")
                logger.error(e)

        logger.info("=" * 60)
        logger.info("Discovery Agent Completed")
        logger.info(f"Total Sources: {total_sources}")
        logger.info(f"Total Links Discovered: {total_discovered}")
        logger.info(f"Total New Links Saved: {total_saved}")
        logger.info("=" * 60)

    def close(self):
        self.seed_repo.close()
        self.link_repo.close()