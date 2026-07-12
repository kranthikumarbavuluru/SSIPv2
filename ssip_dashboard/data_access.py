from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd


class ReadOnlyDatabaseError(RuntimeError):
    """Raised when the dashboard cannot open the SQLite database read-only."""


@contextmanager
def readonly_connection(
    database_path: Path,
    *,
    timeout_seconds: float = 30.0,
) -> Iterator[sqlite3.Connection]:
    if not database_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    uri = database_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as exc:
        raise ReadOnlyDatabaseError(
            f"Could not open database in read-only mode: {database_path}"
        ) from exc

    try:
        yield connection
    finally:
        connection.close()


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def read_table(connection: sqlite3.Connection, table_name: str) -> pd.DataFrame:
    if not table_exists(connection, table_name):
        return pd.DataFrame()
    return pd.read_sql_query(f'SELECT * FROM "{table_name}"', connection)


def read_normalization_plan(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return pd.DataFrame(rows)


def read_dashboard_tables(
    database_path: Path,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, pd.DataFrame]:
    table_names = (
        "scheme_staging",
        "public_schemes",
        "admin_review_queue",
        "rejected_scheme_records",
        "scheme_attributes",
        "scheme_contacts",
        "scheme_sources",
        "publication_audit_log",
    )
    if not database_path.exists():
        return {name: pd.DataFrame() for name in table_names}
    with readonly_connection(
        database_path,
        timeout_seconds=timeout_seconds,
    ) as connection:
        return {name: read_table(connection, name) for name in table_names}
