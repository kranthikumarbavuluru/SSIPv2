from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def apply(database_path: Path, migration_path: Path) -> None:
    sql = migration_path.read_text(encoding="utf-8")
    connection = sqlite3.connect(database_path, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(sql)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the approved DST historical archive schema migration.")
    parser.add_argument("--database", type=Path, default=ROOT / "database/ssip_staging_v1.db")
    parser.add_argument(
        "--migration",
        type=Path,
        default=ROOT / "database/migrations/20260712_dst_historical_archive_v1.sql",
    )
    args = parser.parse_args()
    apply(args.database.resolve(), args.migration.resolve())
    print(f"Applied {args.migration.resolve()} to {args.database.resolve()}")


if __name__ == "__main__":
    main()

