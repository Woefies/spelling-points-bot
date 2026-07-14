# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Discord bot that spell-checks every message (Dutch + English) and tallies "mistake points" per user, per guild. Offline spelling (pyspellchecker, no external API), language auto-detected (langdetect), points in SQLite.

## Run / dev

```bash
./run.sh                 # creates .venv + installs deps on first run, then starts bot
# or manually:
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then set DISCORD_TOKEN
python bot.py
```

- `.env` required with non-empty `DISCORD_TOKEN` (`run.sh` hard-fails otherwise). Other config is optional env overrides — see `.env.example` and `core/config.py`.
- No test suite, no linter config, no CI. Not a git repo.
- Requires **MESSAGE CONTENT INTENT** enabled in Discord Developer Portal (bot reads message text).

## Architecture

Three swap points, each backed by an interface/registry. Adding a feature = drop a file at the right point, no wiring elsewhere.

1. **Cogs** (`cogs/`) — auto-loaded in `core/bot.py:setup_hook` via `pkgutil.iter_modules(cogs.__path__)`. Every module in `cogs/` with an `async def setup(bot)` is loaded automatically. Drop a new cog file → it loads. `spelling.py` holds the `on_message` flow; `scores.py` and `admin.py` are `hybrid_command`s (slash + prefix both work).

2. **Checkers** (`services/checkers/`) — pluggable check engines. Each is a `Checker` subclass decorated `@register("name")` (see `base.py`); the decorator **instantiates once** and stores the instance in `REGISTRY`. The `on_message` flow runs every registered checker and sums their `Issue`s into points. **Gotcha:** a new checker module must be imported in `services/checkers/__init__.py` so `@register` actually runs (`spelling` is imported there for this reason) — unlike cogs, checkers are NOT auto-discovered.

3. **Repository** (`repositories/`) — storage interface `ScoreRepository` (`base.py`), default impl `SqliteScoreRepository` (`sqlite_repo.py`). Instantiated directly in `core/bot.py:__init__` (`self.repo`). To swap storage, change that one line. SQLite conn is `check_same_thread=False` guarded by a `threading.Lock` (discord.py runs listeners on the event loop but repo is sync).

### Message flow (`cogs/spelling.py:on_message`)

`clean()` (strip code blocks/URLs/mentions/emoji/digit-words) → skip if empty → `detect()` returns `en`/`nl`/`None`, skips messages under `MIN_WORDS_FOR_DETECT` words → build whitelist (config default set ∪ per-guild DB whitelist, lowercased) → run all REGISTRY checkers → if issues: `add_points`, `log_issue` per issue, ❌ reaction, optional reply.

- `services/cleaner.py` — `clean()` (pre-check normalization) and `tokenize()` (unicode-aware, letters only, keeps case). Checkers tokenize the already-cleaned text themselves.
- `services/detector.py` — langdetect wrapper, `DetectorFactory.seed=0` for determinism, only returns supported langs (`en`/`nl`).
- `SpellingChecker` skips: whitelisted words, len≤1, and (when `skip_capitalized`) capitalized non-first tokens (proper-noun heuristic).

## Data model (SQLite, `data/points.db`)

`scores` (guild_id, user_id, mistakes — upserted), `whitelist` (guild_id, word — per-guild ignored words), `issues_log` (append-only audit of every flagged word with lang/kind/timestamp). Tables auto-created on repo init.

## Conventions

- Config flows one way: `.env` → `load_settings()` → `Settings` dataclass → `bot.settings`. Read config off `bot.settings`, never `os.getenv` outside `core/config.py`.
- `Settings.whitelist` is a hardcoded default set merged with the DB whitelist at check time — global-ish defaults live in config, per-guild additions in DB.
- Cogs reach shared state via `self.bot.settings` and `self.bot.repo`.
