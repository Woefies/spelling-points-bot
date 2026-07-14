from abc import ABC, abstractmethod


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
