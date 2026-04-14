from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Event:
    event_type: str
    details: dict
    created_at: datetime


class Database:
    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS override_today (
                date_local TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def set_override(self, date_local: str, now_iso: str) -> None:
        self._conn.execute(
            """
            INSERT INTO override_today (date_local, enabled, created_at)
            VALUES (?, 1, ?)
            ON CONFLICT(date_local)
            DO UPDATE SET enabled = excluded.enabled, created_at = excluded.created_at
            """,
            (date_local, now_iso),
        )
        self._conn.commit()

    def clear_override(self, date_local: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM override_today WHERE date_local = ?",
            (date_local,),
        )
        self._conn.commit()
        return cur.rowcount

    def clear_all_overrides(self) -> int:
        cur = self._conn.execute("DELETE FROM override_today")
        self._conn.commit()
        return cur.rowcount

    def has_override(self, date_local: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM override_today WHERE date_local = ? AND enabled = 1",
            (date_local,),
        )
        return cur.fetchone() is not None

    def log_event(self, event_type: str, details: dict, created_at_iso: str) -> None:
        self._conn.execute(
            "INSERT INTO events (created_at, event_type, details_json) VALUES (?, ?, ?)",
            (created_at_iso, event_type, json.dumps(details, separators=(",", ":"))),
        )
        self._conn.commit()

    def list_recent_events(self, limit: int = 20) -> list[Event]:
        cur = self._conn.execute(
            "SELECT created_at, event_type, details_json FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        result: list[Event] = []
        for row in rows:
            result.append(
                Event(
                    event_type=row["event_type"],
                    details=json.loads(row["details_json"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return result
