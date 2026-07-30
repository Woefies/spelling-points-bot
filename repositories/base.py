from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Trigger:
    """A keyword the bot reacts to.

    `pattern` and `response` both hold '|'-separated alternatives, but they mean
    different things: every pattern phrase is matched, one response variant is
    picked at random.
    """

    id: int
    guild_id: int
    pattern: str
    response: str | None  # None = react only, don't reply
    reactions: str | None  # comma-separated emoji, None = reply only


class ScoreRepository(ABC):
    @abstractmethod
    def add_points(self, guild_id: int, user_id: int, n: int) -> None:
        ...

    @abstractmethod
    def get_score(self, guild_id: int, user_id: int) -> int:
        ...

    @abstractmethod
    def leaderboard(self, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        ...

    @abstractmethod
    def add_whitelist(self, guild_id: int, word: str) -> None:
        ...

    @abstractmethod
    def remove_whitelist(self, guild_id: int, word: str) -> None:
        ...

    @abstractmethod
    def get_whitelist(self, guild_id: int) -> set[str]:
        ...

    @abstractmethod
    def log_issue(self, guild_id: int, user_id: int, word: str, lang: str, kind: str) -> None:
        ...

    @abstractmethod
    def leaderboard_between(
        self, guild_id: int, start_utc: str, end_utc: str, limit: int = 10
    ) -> list[tuple[int, int]]:
        """(user_id, issue count) within a UTC window, highest first.

        Takes a range rather than a date because `issues_log.ts` is UTC while the
        reporting day is Amsterdam local — a plain DATE(ts) match would put the
        first hours of a Dutch day in the previous bucket. Bounds are
        'YYYY-MM-DD HH:MM:SS', matching SQLite's CURRENT_TIMESTAMP format.
        """
        ...

    @abstractmethod
    def add_trigger(
        self, guild_id: int, pattern: str, response: str | None, reactions: str | None
    ) -> int:
        ...

    @abstractmethod
    def list_triggers(self, guild_id: int) -> list[Trigger]:
        ...

    @abstractmethod
    def get_trigger(self, guild_id: int, trigger_id: int) -> Trigger | None:
        ...

    @abstractmethod
    def update_trigger(self, guild_id: int, trigger_id: int, changes: dict) -> bool:
        """Patch the given columns. A value of None clears that column, so the
        caller decides what 'not given' versus 'make empty' means — unlike the
        reminder equivalent, a trigger legitimately needs its reply or its
        reactions removed."""
        ...

    @abstractmethod
    def remove_trigger(self, guild_id: int, trigger_id: int) -> bool:
        ...

    @abstractmethod
    def trigger_exists(self, guild_id: int, pattern: str) -> bool:
        ...

    @abstractmethod
    def count_between(self, guild_id: int, user_id: int, start_utc: str, end_utc: str) -> int:
        """How many issues this one user collected in a UTC window."""
        ...

    @abstractmethod
    def words_between(
        self, guild_id: int, start_utc: str, end_utc: str
    ) -> list[tuple[int, str, int]]:
        """(user_id, word, times) within a UTC window, most-flagged first."""
        ...

    @abstractmethod
    def set_config(self, guild_id: int, key: str, value: str | None) -> None:
        """Store a per-guild setting; None deletes it."""
        ...

    @abstractmethod
    def get_config(self, guild_id: int, key: str) -> str | None:
        ...

    @abstractmethod
    def clear(self, guild_id: int, what: str) -> int:
        """Delete every row for this guild from one resettable table. Returns the count."""
        ...

    @abstractmethod
    def all_config(self, key: str) -> list[tuple[int, str]]:
        """(guild_id, value) for every guild that has this key set."""
        ...
