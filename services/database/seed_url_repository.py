import sqlite3

from config import DATABASE_FILE
from utils.logger import logger


class SeedUrlRepository:

    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_FILE)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def add_default_sources(self):
        sources = [
            ("Startup India", "https://www.startupindia.gov.in/content/sih/en/government-schemes.html", "Startup Portal"),
            ("NIDHI DST", "https://nidhi.dst.gov.in/", "DST Startup Schemes"),
            ("BIRAC", "https://birac.nic.in/", "Biotech Startup Schemes"),
            ("MeitY Startup Hub", "https://msh.meity.gov.in/", "MeitY Startup Schemes"),
            ("Atal Innovation Mission", "https://aim.gov.in/", "Innovation Mission")
        ]

        saved_count = 0

        for source_name, url, category in sources:
            self.cursor.execute("""
                INSERT OR IGNORE INTO seed_urls
                (source_name, url, category, active)
                VALUES (?, ?, ?, 1)
            """, (source_name, url, category))

            if self.cursor.rowcount > 0:
                saved_count += 1

        self.conn.commit()

        logger.info(f"Default seed URLs added: {saved_count}")

        return saved_count

    def get_active_sources(self):
        self.cursor.execute("""
            SELECT id, source_name, url, category
            FROM seed_urls
            WHERE active = 1
            ORDER BY id
        """)

        rows = self.cursor.fetchall()

        return [
            {
                "id": row["id"],
                "source_name": row["source_name"],
                "url": row["url"],
                "category": row["category"]
            }
            for row in rows
        ]

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("Seed URL database connection closed.")