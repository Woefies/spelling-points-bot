import pathlib
import sqlite3
import threading

from repositories.base import ScoreRepository, Trigger


class SqliteScoreRepository(ScoreRepository):
    def __init__(self, path: str) -> None:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        # timeout is the busy timeout: wait rather than raising "database is
        # locked" the moment the other connection to this file holds a write.
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        # WAL lets readers work while a writer holds the file. Two repositories
        # share this database, and writes land on every message plus a nightly
        # backup and a daily summary — the default rollback journal serialises
        # all of that. The setting is persistent, so setting it twice is a no-op.
        self._conn.execute("PRAGMA journal_mode=WAL")
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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    pattern TEXT NOT NULL,
                    response TEXT,
                    reactions TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (guild_id, key)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trigger_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    trigger_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hits_lookup ON trigger_hits (guild_id, trigger_id, user_id)"
            )
            # CREATE TABLE IF NOT EXISTS does nothing to a table that already
            # exists, so a column added later needs an explicit migration —
            # every deployment out there predates punish_minutes.
            columns = {r[1] for r in self._conn.execute("PRAGMA table_info(triggers)")}
            if "punish_minutes" not in columns:
                self._conn.execute("ALTER TABLE triggers ADD COLUMN punish_minutes INTEGER")

            # The daily leaderboard filters issues_log by guild and date on every
            # run; without this it is a full table scan of an append-only log.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_issues_guild_ts ON issues_log (guild_id, ts)"
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

    def leaderboard_between(
        self, guild_id: int, start_utc: str, end_utc: str, limit: int = 10
    ) -> list[tuple[int, int]]:
        # `scores` only holds running totals, so "today" has to come from the
        # timestamped log. ts is SQLite's CURRENT_TIMESTAMP, i.e. UTC.
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT user_id, COUNT(*) AS n FROM issues_log
                WHERE guild_id = ? AND ts >= ? AND ts < ?
                GROUP BY user_id
                ORDER BY n DESC
                LIMIT ?
                """,
                (guild_id, start_utc, end_utc, limit),
            )
            rows = cur.fetchall()
        return [(row[0], row[1]) for row in rows]

    def count_between(self, guild_id: int, user_id: int, start_utc: str, end_utc: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM issues_log "
                "WHERE guild_id = ? AND user_id = ? AND ts >= ? AND ts < ?",
                (guild_id, user_id, start_utc, end_utc),
            )
            row = cur.fetchone()
        return row[0] if row else 0

    def words_between(
        self, guild_id: int, start_utc: str, end_utc: str
    ) -> list[tuple[int, str, int]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT user_id, word, COUNT(*) AS n FROM issues_log
                WHERE guild_id = ? AND ts >= ? AND ts < ?
                GROUP BY user_id, word
                ORDER BY n DESC, word ASC
                """,
                (guild_id, start_utc, end_utc),
            )
            rows = cur.fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def top_flagged(
        self, guild_id: int, start_utc: str, end_utc: str, kind: str | None, limit: int
    ) -> list[tuple[str, str, int, int]]:
        query = """
            SELECT LOWER(word), kind, COUNT(*) AS hits, COUNT(DISTINCT user_id)
            FROM issues_log
            WHERE guild_id = ? AND ts >= ? AND ts < ?
        """
        params: list = [guild_id, start_utc, end_utc]
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        query += " GROUP BY LOWER(word), kind ORDER BY hits DESC, 1 ASC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def total_issues(self, guild_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM issues_log WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        return row[0] if row else 0

    def log_trigger_hit(self, guild_id: int, trigger_id: int, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO trigger_hits (guild_id, trigger_id, user_id) VALUES (?, ?, ?)",
                (guild_id, trigger_id, user_id),
            )
            self._conn.commit()

    def count_trigger_hits(self, guild_id: int, trigger_id: int, user_id: int) -> int:
        """How often this person has set off this one trigger. Feeds {count}."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM trigger_hits "
                "WHERE guild_id = ? AND trigger_id = ? AND user_id = ?",
                (guild_id, trigger_id, user_id),
            ).fetchone()
        return row[0] if row else 0

    def adjust_points(self, guild_id: int, user_id: int, delta: int) -> int:
        """Add or subtract points, never below zero. Returns the new total."""
        with self._lock:
            self._conn.execute(
                # The delta is bound twice on purpose. excluded.mistakes is the
                # value the INSERT *would* have written — already clamped to 0 for
                # a negative delta — so adding it to the existing score is a no-op.
                # The UPDATE has to see the raw delta.
                """
                INSERT INTO scores (guild_id, user_id, mistakes) VALUES (?, ?, MAX(0, ?))
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET mistakes = MAX(0, mistakes + ?)
                """,
                (guild_id, user_id, delta, delta),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT mistakes FROM scores WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        return row[0] if row else 0

    def set_config(self, guild_id: int, key: str, value: str | None) -> None:
        with self._lock:
            if value is None:
                self._conn.execute(
                    "DELETE FROM guild_config WHERE guild_id = ? AND key = ?", (guild_id, key)
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)
                    ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value
                    """,
                    (guild_id, key, value),
                )
            self._conn.commit()

    def get_config(self, guild_id: int, key: str) -> str | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM guild_config WHERE guild_id = ? AND key = ?", (guild_id, key)
            )
            row = cur.fetchone()
        return row[0] if row else None

    # `reminders` is owned by SqliteReminderRepository, but resetting it from here
    # avoids opening a third connection to the same file just to run one DELETE.
    _CLEARABLE = {
        "reminders": "reminders",
        "triggers": "triggers",
        "trigger_hits": "trigger_hits",
        "whitelist": "whitelist",
        "scores": "scores",
        "guild_config": "guild_config",
    }

    def clear(self, guild_id: int, what: str) -> int:
        # Not user input: a bad key here is a programming error, and the mapping
        # keeps a table name from ever reaching the SQL string unchecked.
        table = self._CLEARABLE[what]
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if not exists:
                return 0
            cur = self._conn.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
            self._conn.commit()
        return cur.rowcount

    def all_config(self, key: str) -> list[tuple[int, str]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT guild_id, value FROM guild_config WHERE key = ?", (key,)
            )
            rows = cur.fetchall()
        return [(row[0], row[1]) for row in rows]

    def add_trigger(
        self,
        guild_id: int,
        pattern: str,
        response: str | None,
        reactions: str | None,
        punish_minutes: int | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO triggers (guild_id, pattern, response, reactions, punish_minutes) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, pattern, response, reactions, punish_minutes),
            )
            self._conn.commit()
        return cur.lastrowid

    def list_triggers(self, guild_id: int) -> list[Trigger]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, pattern, response, reactions, punish_minutes FROM triggers "
                "WHERE guild_id = ? ORDER BY id",
                (guild_id,),
            )
            rows = cur.fetchall()
        return [Trigger(*row) for row in rows]

    def get_trigger(self, guild_id: int, trigger_id: int) -> Trigger | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, pattern, response, reactions, punish_minutes FROM triggers "
                "WHERE guild_id = ? AND id = ?",
                (guild_id, trigger_id),
            )
            row = cur.fetchone()
        return Trigger(*row) if row else None

    _TRIGGER_COLUMNS = ("pattern", "response", "reactions", "punish_minutes")

    def update_trigger(self, guild_id: int, trigger_id: int, changes: dict) -> bool:
        columns = [c for c in self._TRIGGER_COLUMNS if c in changes]
        if not columns:
            return False
        assignments = ", ".join(f"{c} = ?" for c in columns)
        params = [changes[c] for c in columns] + [guild_id, trigger_id]
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE triggers SET {assignments} WHERE guild_id = ? AND id = ?", params
            )
            self._conn.commit()
        return cur.rowcount > 0

    def remove_trigger(self, guild_id: int, trigger_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM triggers WHERE guild_id = ? AND id = ?", (guild_id, trigger_id)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def trigger_exists(self, guild_id: int, pattern: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM triggers WHERE guild_id = ? AND pattern = ? LIMIT 1",
                (guild_id, pattern),
            )
            row = cur.fetchone()
        return row is not None
