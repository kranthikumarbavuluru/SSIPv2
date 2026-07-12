from services.database.link_repository import LinkRepository

repo = LinkRepository()

links = repo.get_unprocessed_links(limit=10)

for link in links:
    print(link)

repo.close()