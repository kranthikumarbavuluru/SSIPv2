from services.crawler.crawler_service import CrawlerService

url = "https://www.startupindia.gov.in/content/sih/en/government-schemes.html"

crawler = CrawlerService()

text = crawler.read_website(url)
links = crawler.discover_links(url)

print("Text Preview:")
print(text[:1000])

print("\nTotal Links Found:", len(links))

for link in links[:10]:
    print(link)