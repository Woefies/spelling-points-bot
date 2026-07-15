"""SQLite repository for scheduled reminders."""

import pathlib
import sqlite3
import threading
from dataclasses import dataclass


@dataclass
class Reminder:
    id: int
    guild_id: int
    channel_id: int
    message: str
    time: str  # "HH:MM" (Europe/Amsterdam)
    frequency: str  # daily | weekly | monthly | once
    day: int | None  # weekday 0-6 (weekly) or day-of-month 1-31 (monthly)
    date: str | None  # "YYYY-MM-DD" (once)
    mention: str  # everyone | here | none
    last_fired: str | None  # "YYYY-MM-DD" guard against double sends


class SqliteReminderRepository:
    def __init__(self, path: str) -> None:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    time TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    day INTEGER,
                    date TEXT,
                    mention TEXT NOT NULL DEFAULT 'none',
                    last_fired TEXT
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _row_to_reminder(row: tuple) -> Reminder:
        return Reminder(*row)

    def add(
        self,
        guild_id: int,
        channel_id: int,
        message: str,
        time: str,
        frequency: str,
        day: int | None = None,
        date: str | None = None,
        mention: str = "none",
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO reminders (guild_id, channel_id, message, time, frequency, day, date, mention)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, message, time, frequency, day, date, mention),
            )
            self._conn.commit()
        return cur.lastrowid

    def remove(self, guild_id: int, reminder_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM reminders WHERE guild_id = ? AND id = ?",
                (guild_id, reminder_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def list_for_guild(self, guild_id: int) -> list[Reminder]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, channel_id, message, time, frequency, day, date, mention, last_fired "
                "FROM reminders WHERE guild_id = ? ORDER BY id",
                (guild_id,),
            )
            rows = cur.fetchall()
        return [self._row_to_reminder(r) for r in rows]

    def all(self) -> list[Reminder]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, channel_id, message, time, frequency, day, date, mention, last_fired "
                "FROM reminders"
            )
            rows = cur.fetchall()
        return [self._row_to_reminder(r) for r in rows]

    def mark_fired(self, reminder_id: int, date: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET last_fired = ? WHERE id = ?",
                (date, reminder_id),
            )
            self._conn.commit()

    def exists_similar(self, guild_id: int, message: str, time: str, frequency: str) -> bool:
        """Used to avoid seeding duplicate built-in reminders on repeated /reminder setup."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM reminders WHERE guild_id = ? AND message = ? AND time = ? AND frequency = ? LIMIT 1",
                (guild_id, message, time, frequency),
            )
            row = cur.fetchone()
        return row is not None
