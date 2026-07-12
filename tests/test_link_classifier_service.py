from services.crawler.crawler_service import CrawlerService
from services.ai.link_classifier_service import LinkClassifierService

url = "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"

crawler = CrawlerService()
classifier = LinkClassifierService()

links = crawler.discover_links(url)

# Test only first 30 links initially to avoid overloading local model
sample_links = links[:30]

result = classifier.classify_links(sample_links)

print("\nUseful Links:")
for link in result["useful_links"]:
    print(link)

print("\nIgnored Links:")
for link in result["ignored_links"][:10]:
    print(link)