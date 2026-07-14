import pathlib
import sqlite3
import threading

from repositories.base import ScoreRepository


class SqliteScoreRepository(ScoreRepository):
    def __init__(self, path: str) -> None:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scores (
                    guild_id INTEGER,
                    user_id INTEGER,
                    mistakes INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS whitelist (
                    guild_id INTEGER,
                    word TEXT,
                    PRIMARY KEY (guild_id, word)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS issues_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    word TEXT,
                    lang TEXT,
                    kind TEXT,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.commit()

    def add_points(self, guild_id: int, user_id: int, n: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scores (guild_id, user_id, mistakes)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET mistakes = mistakes + excluded.mistakes
                """,
                (guild_id, user_id, n),
            )
            self._conn.commit()

    def get_score(self, guild_id: int, user_id: int) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT mistakes FROM scores WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = cur.fetchone()
        return row[0] if row else 0

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT user_id, mistakes FROM scores
                WHERE guild_id = ?
                ORDER BY mistakes DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
            rows = cur.fetchall()
        return [(row[0], row[1]) for row in rows]

    def add_whitelist(self, guild_id: int, word: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO whitelist (guild_id, word) VALUES (?, ?)",
                (guild_id, word.lower()),
            )
            self._conn.commit()

    def remove_whitelist(self, guild_id: int, word: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM whitelist WHERE guild_id = ? AND word = ?",
                (guild_id, word.lower()),
            )
            self._conn.commit()

    def get_whitelist(self, guild_id: int) -> set[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT word FROM whitelist WHERE guild_id = ?",
                (guild_id,),
            )
            rows = cur.fetchall()
        return {row[0] for row in rows}

    def log_issue(self, guild_id: int, user_id: int, word: str, lang: str, kind: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO issues_log (guild_id, user_id, word, lang, kind)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, word, lang, kind),
            )
            self._conn.commit()
