import json
import os
import sqlite3
from datetime import UTC, datetime

from app.models import Ticket

_DEFAULT_URL = "sqlite:///triagebot.db"


def _db_path() -> str:
    url = os.environ.get("DATABASE_URL", _DEFAULT_URL)
    return url.removeprefix("sqlite:///")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    _create_table(conn)
    return conn


def _create_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            tags TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def insert_ticket(
    title: str,
    description: str,
    category: str,
    priority: str,
    tags: list[str],
) -> Ticket:
    now = datetime.now(UTC).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO tickets
                (title, description, category, priority, tags, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (title, description, category, priority, json.dumps(tags), now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_ticket(row)


def _row_to_ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        category=row["category"],
        priority=row["priority"],
        tags=json.loads(row["tags"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
