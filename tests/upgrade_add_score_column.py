import sqlite3
from config import DATABASE_FILE

conn = sqlite3.connect(DATABASE_FILE)
cursor = conn.cursor()

try:
    cursor.execute("""
        ALTER TABLE discovered_links
        ADD COLUMN score INTEGER DEFAULT 0
    """)
    print("Score column added successfully.")

except sqlite3.OperationalError as e:

    if "duplicate column name" in str(e):
        print("Score column already exists.")
    else:
        raise

conn.commit()
conn.close()