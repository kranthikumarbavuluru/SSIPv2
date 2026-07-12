from services.crawler.crawler_service import CrawlerService
from services.ai.link_classifier_service import LinkClassifierService
from services.database.link_repository import LinkRepository

url = "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"

crawler = CrawlerService()
classifier = LinkClassifierService()
repo = LinkRepository()

links = crawler.discover_links(url)

sample_links = links[:30]

result = classifier.classify_links(sample_links)

useful_links = result.get("useful_links", [])

repo.save_links(useful_links)

repo.close()

print(f"Saved useful links: {len(useful_links)}")