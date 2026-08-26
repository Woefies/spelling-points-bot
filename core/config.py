import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass
class Settings:
    token: str
    prefix: str = "!"
    min_words_for_detect: int = 3
    skip_capitalized: bool = True
    reply_on_mistake: bool = True
    points_per_mistake: int = 1
    # The whole spelling flow, on or off. A server that only wants triggers and
    # reminders should not have to set points to 0 and hope nobody notices.
    spelling_enabled: bool = True
    db_path: str = "data/points.db"
    version: str = "unknown"
    github_repo: str = "Woefies/spelling-points-bot"
    github_branch: str = "master"
    # When set, slash commands sync to this one guild instead of globally.
    # Guild syncs are instant; global syncs can take up to an hour to appear.
    dev_guild_id: int | None = None
    hunspell_dir: str = "/usr/share/hunspell"
    whitelist: set[str] = field(default_factory=lambda: {"lol", "haha", "xd", "omg", "brb"})


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _parse_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a numeric Discord ID, got {raw!r}") from None


def _read_version() -> str:
    """Read the VERSION file baked at repo root; 'unknown' if missing."""
    try:
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip() or "unknown"
    except OSError:
        return "unknown"


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is required")

    defaults = Settings(token=token)

    prefix = os.getenv("PREFIX", defaults.prefix)
    min_words_for_detect = int(os.getenv("MIN_WORDS_FOR_DETECT", defaults.min_words_for_detect))
    skip_capitalized = _parse_bool(os.getenv("SKIP_CAPITALIZED", str(defaults.skip_capitalized)))
    reply_on_mistake = _parse_bool(os.getenv("REPLY_ON_MISTAKE", str(defaults.reply_on_mistake)))
    points_per_mistake = int(os.getenv("POINTS_PER_MISTAKE", defaults.points_per_mistake))
    spelling_enabled = _parse_bool(os.getenv("SPELLING_ENABLED", str(defaults.spelling_enabled)))
    db_path = os.getenv("DB_PATH", defaults.db_path)
    version = _read_version()
    github_repo = os.getenv("GITHUB_REPO", defaults.github_repo)
    github_branch = os.getenv("GITHUB_BRANCH", defaults.github_branch)
    dev_guild_id = _parse_optional_int("DEV_GUILD_ID")
    hunspell_dir = os.getenv("HUNSPELL_DIR", defaults.hunspell_dir)

    return Settings(
        token=token,
        prefix=prefix,
        min_words_for_detect=min_words_for_detect,
        skip_capitalized=skip_capitalized,
        reply_on_mistake=reply_on_mistake,
        points_per_mistake=points_per_mistake,
        spelling_enabled=spelling_enabled,
        db_path=db_path,
        version=version,
        github_repo=github_repo,
        github_branch=github_branch,
        dev_guild_id=dev_guild_id,
        hunspell_dir=hunspell_dir,
    )
