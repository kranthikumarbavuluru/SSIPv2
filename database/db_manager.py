import sqlite3
from pathlib import Path
from utils.logger import logger
from config import DATABASE_FILE

# Database location
DB_PATH = DATABASE_FILE


class DatabaseManager:

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()

    def create_tables(self):

        # ============================
        # Seed URLs
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS seed_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT,
            url TEXT UNIQUE,
            category TEXT,
            active INTEGER DEFAULT 1
        )
        """)

        # ============================
        # Discovered Links
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seed_id INTEGER,
            title TEXT,
            url TEXT UNIQUE,
            page_type TEXT,
            processed INTEGER DEFAULT 0,
            discovered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ============================
        # Documents (PDFs)
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER,
            document_name TEXT,
            pdf_url TEXT,
            local_path TEXT,
            downloaded INTEGER DEFAULT 0
        )
        """)

        # ============================
        # Schemes
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS schemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_name TEXT,
            ministry TEXT,
            department TEXT,
            official_url TEXT,
            pdf_url TEXT,
            status TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ============================
        # AI Extracted JSON
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS extracted_json (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_id INTEGER,
            json_data TEXT,
            extracted_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ============================
        # Crawl History
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            status TEXT,
            crawled_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ============================
        # Errors
        # ============================
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT,
            error_message TEXT,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        self.conn.commit()

        logger.info("Knowledge Base tables verified successfully.")

    def close(self):
        self.conn.close()


if __name__ == "__main__":

    db = DatabaseManager()

    db.create_tables()

    db.close()