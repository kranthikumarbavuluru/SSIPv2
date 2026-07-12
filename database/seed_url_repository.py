import sqlite3
from config import DATABASE_FILE
from utils.logger import logger


class SeedUrlRepository:

    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_FILE)
        self.cursor = self.conn.cursor()

    def add_default_sources(self):
        sources = [
            ("Startup India", "https://www.startupindia.gov.in/content/sih/en/government-schemes.html", "Startup Portal"),
            ("NIDHI DST", "https://nidhi.dst.gov.in/", "DST Startup Schemes"),
            ("BIRAC", "https://birac.nic.in/", "Biotech Startup Schemes"),
            ("MeitY Startup Hub", "https://msh.meity.gov.in/", "MeitY Startup Schemes"),
            ("Atal Innovation Mission", "https://aim.gov.in/", "Innovation Mission")
        ]

        for source_name, url, category in sources:
            self.cursor.execute("""
                INSERT OR IGNORE INTO seed_urls
                (source_name, url, category, active)
                VALUES (?, ?, ?, 1)
            """, (source_name, url, category))

        self.conn.commit()
        logger.info("Default seed URLs added successfully.")

    def get_active_sources(self):
        self.cursor.execute("""
            SELECT id, source_name, url, category
            FROM seed_urls
            WHERE active = 1
        """)

        rows = self.cursor.fetchall()

        return [
            {
                "id": row[0],
                "source_name": row[1],
                "url": row[2],
                "category": row[3]
            }
            for row in rows
        ]

    def close(self):
        self.conn.close()