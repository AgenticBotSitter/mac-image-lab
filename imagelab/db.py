"""SQLite lifecycle helpers for Mac Image Lab."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def connect_database(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database(path: Path) -> sqlite3.Connection:
    connection = connect_database(path)
    with connection:
        connection.executescript(SCHEMA_PATH.read_text())
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
        )
    return connection


def backup_database(source: Path, destination: Path) -> Path:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect_database(source) as source_connection:
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
            destination_connection.execute("PRAGMA integrity_check")
        finally:
            destination_connection.close()
    return destination
