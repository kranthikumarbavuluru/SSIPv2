from services.database.seed_url_repository import SeedUrlRepository

repo = SeedUrlRepository()

repo.add_default_sources()

sources = repo.get_active_sources()

print("\nActive Seed URLs:\n")

for source in sources:
    print(source)

repo.close()