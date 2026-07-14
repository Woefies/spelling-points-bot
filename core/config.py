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
    db_path: str = "data/points.db"
    version: str = "unknown"
    github_repo: str = "Woefies/spelling-points-bot"
    github_branch: str = "master"
    whitelist: set[str] = field(default_factory=lambda: {"lol", "haha", "xd", "omg", "brb"})


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


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
    db_path = os.getenv("DB_PATH", defaults.db_path)
    version = _read_version()
    github_repo = os.getenv("GITHUB_REPO", defaults.github_repo)
    github_branch = os.getenv("GITHUB_BRANCH", defaults.github_branch)

    return Settings(
        token=token,
        prefix=prefix,
        min_words_for_detect=min_words_for_detect,
        skip_capitalized=skip_capitalized,
        reply_on_mistake=reply_on_mistake,
        points_per_mistake=points_per_mistake,
        db_path=db_path,
        version=version,
        github_repo=github_repo,
        github_branch=github_branch,
    )
