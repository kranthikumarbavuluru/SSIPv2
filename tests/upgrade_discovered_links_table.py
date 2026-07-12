import sqlite3
from config import DATABASE_FILE

conn = sqlite3.connect(DATABASE_FILE)
cursor = conn.cursor()

columns = [
    ("source_url", "TEXT"),
    ("crawl_status", "TEXT DEFAULT 'DISCOVERED'"),
    ("classification_status", "TEXT DEFAULT 'PENDING'"),
    ("classification", "TEXT"),
    ("confidence", "REAL DEFAULT 0"),
    ("reason", "TEXT"),
    ("updated_date", "TIMESTAMP")
]

for column_name, column_type in columns:
    try:
        cursor.execute(f"ALTER TABLE discovered_links ADD COLUMN {column_name} {column_type}")
        print(f"Added column: {column_name}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print(f"Column already exists: {column_name}")
        else:
            raise

conn.commit()
conn.close()

print("discovered_links table upgraded successfully.")