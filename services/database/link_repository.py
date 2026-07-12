import sqlite3
from datetime import datetime

from config import DATABASE_FILE
from utils.logger import logger


class LinkRepository:

    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_FILE)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def save_raw_links(self, links, source_url=""):
        saved_count = 0

        for link in links:
            title = link.get("title", "").strip()
            url = link.get("url", "").strip()
            score = link.get("score", 0)

            if not url or url.startswith("javascript:"):
                continue

            try:
                self.cursor.execute("""
                    INSERT OR IGNORE INTO discovered_links
                    (
                        title,
                        url,
                        source_url,
                        page_type,
                        score,
                        processed,
                        crawl_status,
                        classification_status,
                        updated_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    title,
                    url,
                    source_url,
                    "Unknown",
                    score,
                    0,
                    "DISCOVERED",
                    "PENDING",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

                if self.cursor.rowcount > 0:
                    saved_count += 1

            except Exception as e:
                logger.error(f"Failed to save raw link: {url}")
                logger.error(e)

        self.conn.commit()
        logger.info(f"Saved {saved_count} raw links.")
        return saved_count

    def save_links(self, links, page_type="Unknown"):
        saved_count = 0

        for link in links:
            title = link.get("title", "").strip()
            url = link.get("url", "").strip()
            category = link.get("category", page_type)
            confidence = link.get("confidence", 0)
            reason = link.get("reason", "")

            if not url:
                continue

            try:
                self.cursor.execute("""
                    INSERT OR IGNORE INTO discovered_links
                    (
                        title,
                        url,
                        page_type,
                        processed,
                        crawl_status,
                        classification_status,
                        classification,
                        confidence,
                        reason,
                        updated_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    title,
                    url,
                    category,
                    0,
                    "DISCOVERED",
                    "CLASSIFIED",
                    category,
                    confidence,
                    reason,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

                if self.cursor.rowcount > 0:
                    saved_count += 1

            except Exception as e:
                logger.error(f"Failed to save classified link: {url}")
                logger.error(e)

        self.conn.commit()
        logger.info(f"Saved {saved_count} classified links.")
        return saved_count

    def get_pending_classification_links(self, limit=30, minimum_score=60):
        self.cursor.execute("""
            SELECT id, title, url, source_url, score
            FROM discovered_links
            WHERE classification_status = 'PENDING'
              AND score >= ?
            ORDER BY score DESC, id ASC
            LIMIT ?
        """, (minimum_score, limit))

        rows = self.cursor.fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "source_url": row["source_url"],
                "score": row["score"]
            }
            for row in rows
        ]

    def update_link_classification(self, link_id, classification, confidence, reason):
        self.cursor.execute("""
            UPDATE discovered_links
            SET
                page_type = ?,
                classification = ?,
                confidence = ?,
                reason = ?,
                classification_status = 'CLASSIFIED',
                updated_date = ?
            WHERE id = ?
        """, (
            classification,
            classification,
            confidence,
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            link_id
        ))

        self.conn.commit()

    def mark_link_ignored(self, link_id, reason="Ignored"):
        self.cursor.execute("""
            UPDATE discovered_links
            SET
                classification_status = 'IGNORED',
                reason = ?,
                updated_date = ?
            WHERE id = ?
        """, (
            reason,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            link_id
        ))

        self.conn.commit()

    def get_unprocessed_links(self, limit=20):
        self.cursor.execute("""
            SELECT id, title, url, page_type, classification, confidence, score
            FROM discovered_links
            WHERE processed = 0
            ORDER BY score DESC, id ASC
            LIMIT ?
        """, (limit,))

        rows = self.cursor.fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "page_type": row["page_type"],
                "classification": row["classification"],
                "confidence": row["confidence"],
                "score": row["score"]
            }
            for row in rows
        ]

    def get_classified_links(self, limit=20):
        self.cursor.execute("""
            SELECT id, title, url, classification, confidence, score
            FROM discovered_links
            WHERE classification_status = 'CLASSIFIED'
            ORDER BY score DESC, id ASC
            LIMIT ?
        """, (limit,))

        rows = self.cursor.fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "category": row["classification"],
                "confidence": row["confidence"],
                "score": row["score"]
            }
            for row in rows
        ]

    def mark_processed(self, link_id):
        self.cursor.execute("""
            UPDATE discovered_links
            SET processed = 1,
                updated_date = ?
            WHERE id = ?
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            link_id
        ))

        self.conn.commit()

    def get_total_links(self):
        self.cursor.execute("""
            SELECT COUNT(*)
            FROM discovered_links
        """)

        return self.cursor.fetchone()[0]

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")