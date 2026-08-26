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
            # Verdicts on whether a word dodges a trigger. Cached rather than
            # re-asked: the same dodge comes back every day, a model call costs
            # money and a second of channel latency, and a verdict that changed
            # its mind between two identical messages would be impossible to
            # explain to the person on the receiving end.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evasion_verdicts (
                    guild_id INTEGER NOT NULL,
                    pattern TEXT NOT NULL,
                    word TEXT NOT NULL,
                    verdict INTEGER NOT NULL,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, pattern, word)
                )
                """
            )
            # CREATE TABLE IF NOT EXISTS does nothing to a table that already
            # exists, so a column added later needs an explicit migration —
            # every deployment out there predates punish_minutes.
            columns = {r[1] for r in self._conn.execute("PRAGMA table_info(triggers)")}
            if "punish_minutes" not in columns:
                self._conn.execute("ALTER TABLE triggers ADD COLUMN punish_minutes INTEGER")
            if "watch_evasion" not in columns:
                self._conn.execute(
                    "ALTER TABLE triggers ADD COLUMN watch_evasion INTEGER DEFAULT 0"
                )

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
        "evasion_verdicts": "evasion_verdicts",
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

    # ------------------------------------------------------------ evasion verdicts

    def get_evasion_verdict(self, guild_id: int, pattern: str, word: str) -> bool | None:
        """True/False if this word was judged before, None if it never was."""
        with self._lock:
            row = self._conn.execute(
                "SELECT verdict FROM evasion_verdicts WHERE guild_id = ? AND pattern = ? AND word = ?",
                (guild_id, pattern, word.lower()),
            ).fetchone()
        return None if row is None else bool(row[0])

    def set_evasion_verdict(self, guild_id: int, pattern: str, word: str, verdict: bool) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO evasion_verdicts (guild_id, pattern, word, verdict)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, pattern, word) DO UPDATE SET
                    verdict = excluded.verdict, ts = CURRENT_TIMESTAMP
                """,
                (guild_id, pattern, word.lower(), 1 if verdict else 0),
            )
            self._conn.commit()

    def list_evasion_verdicts(self, guild_id: int) -> list[tuple[str, str, bool]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT pattern, word, verdict FROM evasion_verdicts
                WHERE guild_id = ? ORDER BY verdict DESC, pattern, word
                """,
                (guild_id,),
            ).fetchall()
        return [(r[0], r[1], bool(r[2])) for r in rows]

    def forget_evasion_verdict(self, guild_id: int, word: str | None) -> int:
        """Drop one remembered verdict, or all of them when `word` is None."""
        with self._lock:
            if word is None:
                cur = self._conn.execute(
                    "DELETE FROM evasion_verdicts WHERE guild_id = ?", (guild_id,)
                )
            else:
                cur = self._conn.execute(
                    "DELETE FROM evasion_verdicts WHERE guild_id = ? AND word = ?",
                    (guild_id, word.lower()),
                )
            self._conn.commit()
            return cur.rowcount

    def config_for(self, guild_id: int) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM guild_config WHERE guild_id = ?", (guild_id,)
            ).fetchall()
        return {r[0]: r[1] for r in rows}

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
        watch_evasion: bool = False,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO triggers "
                "(guild_id, pattern, response, reactions, punish_minutes, watch_evasion) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, pattern, response, reactions, punish_minutes, 1 if watch_evasion else 0),
            )
            self._conn.commit()
        return cur.lastrowid

    def list_triggers(self, guild_id: int) -> list[Trigger]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, pattern, response, reactions, punish_minutes, "
                "COALESCE(watch_evasion, 0) FROM triggers WHERE guild_id = ? ORDER BY id",
                (guild_id,),
            )
            rows = cur.fetchall()
        return [_trigger(row) for row in rows]

    def get_trigger(self, guild_id: int, trigger_id: int) -> Trigger | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, guild_id, pattern, response, reactions, punish_minutes, "
                "COALESCE(watch_evasion, 0) FROM triggers WHERE guild_id = ? AND id = ?",
                (guild_id, trigger_id),
            )
            row = cur.fetchone()
        return _trigger(row) if row else None

    _TRIGGER_COLUMNS = ("pattern", "response", "reactions", "punish_minutes", "watch_evasion")

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


def _trigger(row) -> Trigger:
    """Build a Trigger from a row, turning the stored 0/1 back into a bool."""
    return Trigger(*row[:6], watch_evasion=bool(row[6]))
