from utils.logger import logger
from services.crawler.crawler_service import CrawlerService
from services.ai.link_classifier_service import LinkClassifierService
from services.database.link_repository import LinkRepository


class DeveloperConsole:

    def __init__(self):
        self.last_links = []
        self.last_classified_result = None

    def show(self):

        while True:

            self.show_menu()

            choice = input("Select Option : ").strip()

            if choice == "1":
                self.discover_links()

            elif choice == "2":
                self.classify_links()

            elif choice == "3":
                self.save_useful_links()

            elif choice == "4":
                self.view_knowledge_base()

            elif choice == "5":
                self.process_unprocessed_links()

            elif choice == "6":
                self.export_excel()

            elif choice == "7":
                self.settings()

            elif choice == "8":
                logger.info("Developer Console Closed")
                break

            else:
                print("\nInvalid option. Please select 1 to 8.\n")

    def show_menu(self):

        print()
        print("=" * 60)
        print(" Startup Scheme Intelligence Platform (SSIP)")
        print("=" * 60)
        print("1. Discover Links")
        print("2. AI Link Classification")
        print("3. Save Useful Links")
        print("4. View Knowledge Base")
        print("5. Process Unprocessed Links")
        print("6. Export Excel")
        print("7. Settings")
        print("8. Exit")
        print("-" * 60)

    def discover_links(self):

        url = input("Enter website URL: ").strip()

        if not url:
            print("\nURL cannot be empty.\n")
            return

        try:
            crawler = CrawlerService()
            links = crawler.discover_links(url)

            self.last_links = links

            print(f"\nDiscovered {len(links)} links:\n")

            for link in links[:20]:
                title = link.get("title", "")
                link_url = link.get("url", "")
                print(f"- {title} | {link_url}")

            if len(links) > 20:
                print(f"\nShowing first 20 links only. Total links: {len(links)}")

        except Exception as e:
            logger.error(f"Discover Links failed : {e}")
            print(f"\nError : {e}\n")

    def classify_links(self):

        if not self.last_links:
            print("\nPlease run 'Discover Links' first.\n")
            return

        try:
            classifier = LinkClassifierService()
            sample_links = self.last_links[:30]

            result = classifier.classify_links(sample_links)
            self.last_classified_result = result

            useful_links = result.get("useful_links", [])

            print("\nUseful Links")
            print("-" * 60)

            for link in useful_links:
                print(
                    f"{link.get('title', '')}\n"
                    f"Category : {link.get('category', '')}\n"
                    f"Confidence : {link.get('confidence', '')}\n"
                    f"URL : {link.get('url', '')}\n"
                )

            print("-" * 60)
            print(f"Useful Links Found : {len(useful_links)}")

        except Exception as e:
            logger.error(f"Classification failed : {e}")
            print(f"\nError : {e}\n")

    def save_useful_links(self):

        if self.last_classified_result is None:
            print("\nPlease classify links first.\n")
            return

        repo = None

        try:
            repo = LinkRepository()
            useful_links = self.last_classified_result.get("useful_links", [])

            saved = repo.save_links(useful_links)

            print(f"\nSaved {saved} useful links into Knowledge Base.\n")

        except Exception as e:
            logger.error(f"Save useful links failed : {e}")
            print(f"\nError : {e}\n")

        finally:
            if repo is not None and hasattr(repo, "close"):
                repo.close()

    def view_knowledge_base(self):

        repo = None

        try:
            repo = LinkRepository()
            links = repo.get_unprocessed_links(limit=20)

            print()
            print("=" * 60)
            print("Knowledge Base")
            print("=" * 60)

            if not links:
                print("No unprocessed links found.")
            else:
                for link in links:
                    print(
                        f"{link.get('id')} | "
                        f"{link.get('title')} | "
                        f"{link.get('page_type')} | "
                        f"{link.get('url')}"
                    )

            print("=" * 60)

        except Exception as e:
            logger.error(f"View Knowledge Base failed : {e}")
            print(f"\nError : {e}\n")

        finally:
            if repo is not None and hasattr(repo, "close"):
                repo.close()

    def process_unprocessed_links(self):
        print("\nFeature will be implemented next.\n")

    def export_excel(self):
        print("\nFeature will be implemented next.\n")

    def settings(self):
        print("\nFeature will be implemented next.\n")