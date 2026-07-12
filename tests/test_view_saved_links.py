import sqlite3
from config import DATABASE_FILE

conn = sqlite3.connect(DATABASE_FILE)
cursor = conn.cursor()

cursor.execute("""
SELECT id, title, url, page_type, processed
FROM discovered_links
ORDER BY id DESC
LIMIT 20
""")

rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()