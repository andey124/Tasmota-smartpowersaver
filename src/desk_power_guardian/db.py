from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock


@dataclass(frozen=True)
class Event:
    event_type: str
    details: dict
    created_at: datetime


@dataclass(frozen=True)
class PowerSample:
    created_at: datetime
    topic: str
    power_watts: float
    payload: dict


class Database:
    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def init_schema(self) -> None:
        with self._lock:
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

                CREATE TABLE IF NOT EXISTS power_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    power_watts REAL NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def set_override(self, date_local: str, now_iso: str) -> None:
        with self._lock:
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
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM override_today WHERE date_local = ?",
                (date_local,),
            )
            self._conn.commit()
            return cur.rowcount

    def clear_all_overrides(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM override_today")
            self._conn.commit()
            return cur.rowcount

    def has_override(self, date_local: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM override_today WHERE date_local = ? AND enabled = 1",
                (date_local,),
            )
            return cur.fetchone() is not None

    def log_event(self, event_type: str, details: dict, created_at_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (created_at, event_type, details_json) VALUES (?, ?, ?)",
                (created_at_iso, event_type, json.dumps(details, separators=(",", ":"))),
            )
            self._conn.commit()

    def log_power_sample(
        self,
        created_at_iso: str,
        topic: str,
        power_watts: float,
        payload: dict,
        retention_limit: int,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO power_samples (created_at, topic, power_watts, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (created_at_iso, topic, power_watts, json.dumps(payload, separators=(",", ":"))),
            )
            if retention_limit > 0:
                self._conn.execute(
                    """
                    DELETE FROM power_samples
                    WHERE id NOT IN (
                        SELECT id FROM power_samples ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (retention_limit,),
                )
            self._conn.commit()

    def list_recent_events(self, limit: int = 20) -> list[Event]:
        with self._lock:
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

    def list_recent_power_samples(self, limit: int = 20) -> list[PowerSample]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT created_at, topic, power_watts, payload_json
                FROM power_samples
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()

        result: list[PowerSample] = []
        for row in rows:
            result.append(
                PowerSample(
                    created_at=datetime.fromisoformat(row["created_at"]),
                    topic=row["topic"],
                    power_watts=row["power_watts"],
                    payload=json.loads(row["payload_json"]),
                )
            )
        return result
