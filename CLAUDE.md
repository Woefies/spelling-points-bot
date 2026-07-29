# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Discord bot that spell-checks every message (Dutch + English) and tallies "mistake points" per user, per guild. Offline spelling (pyspellchecker, no external API), language auto-detected (langdetect), points in SQLite. Also ships a Dutch grammar checker, a repeated-word checker, scheduled channel reminders, and a version drift-check against GitHub.

## Run / dev

```bash
./run.sh                 # creates .venv + installs deps on first run, then starts bot
# or manually:
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then set DISCORD_TOKEN
python bot.py
```

- **Python 3.10+ required.** The code uses PEP 604 unions (`int | None`) in evaluated annotation positions (dataclass fields, function signatures) with no `from __future__ import annotations` anywhere. On 3.9 the import fails outright. `run.sh` builds the venv from whatever `python3` is on PATH and does not check this — verify the interpreter before blaming the code. Docker uses `python:3.12-slim`, so container runs are fine.
- `.env` required with non-empty `DISCORD_TOKEN` (`run.sh` hard-fails otherwise). Other config is optional env overrides — see `.env.example` and `core/config.py`.
- No test suite, no linter config, no CI. It *is* a git repo (remote `Woefies/spelling-points-bot`, default branch `master`).
- Two **privileged intents** are needed in the Discord Developer Portal: **MESSAGE CONTENT INTENT** (bot reads message text) and **SERVER MEMBERS INTENT** (`core/bot.py` sets `intents.members = True` to populate the member cache for the leaderboard). Missing either → `PrivilegedIntentsRequired` at login. The README only documents the first one.
- Reminders that ping need the **Mention @everyone** bot permission; the README's OAuth scope list omits it.

## Architecture

Three swap points, each backed by an interface/registry. Adding a feature = drop a file at the right point, no wiring elsewhere.

1. **Cogs** (`cogs/`) — auto-loaded in `core/bot.py:setup_hook` via `pkgutil.iter_modules(cogs.__path__)`. Every module in `cogs/` with an `async def setup(bot)` is loaded automatically. Drop a new cog file → it loads. `spelling.py` holds the `on_message` flow; `scores.py`, `admin.py` and `version.py` are `hybrid_command`s (slash + prefix both work); `reminders.py` is pure `app_commands` (slash only).
   - **No error isolation:** `load_extension` is not wrapped in try/except, so *any* import-time error in *any* cog takes the whole bot down at startup. Cheap to introduce accidentally — see the `zoneinfo` note under Reminders.

2. **Checkers** (`services/checkers/`) — pluggable check engines. Each is a `Checker` subclass decorated `@register("name")` (see `base.py`); the decorator **instantiates once** and stores the instance in `REGISTRY`. The `on_message` flow runs every registered checker and sums their `Issue`s into points. **Gotcha:** a new checker module must be imported in `services/checkers/__init__.py` so `@register` actually runs — unlike cogs, checkers are NOT auto-discovered. Currently registered: `spelling`, `repeats`, `dutch_dt`.

3. **Repository** (`repositories/`) — storage interface `ScoreRepository` (`base.py`), default impl `SqliteScoreRepository` (`sqlite_repo.py`). Instantiated directly in `core/bot.py:__init__` (`self.repo`). To swap storage, change that one line. SQLite conn is `check_same_thread=False` guarded by a `threading.Lock` (discord.py runs listeners on the event loop but repo is sync).
   - **Known deviation:** `SqliteReminderRepository` (`repositories/reminders_repo.py`) has no ABC and is instantiated inside `RemindersCog.__init__`, not in `core/bot.py`. It opens a *second* SQLite connection to the same file with its own lock. Neither connection sets `journal_mode=WAL` or a busy `timeout`, so concurrent writes can hit `database is locked`. New storage should follow the `ScoreRepository` pattern instead of copying this one.

### Message flow (`cogs/spelling.py:on_message`)

`clean()` (strip code blocks/URLs/mentions/emoji/digit-words) → skip if empty → `detect()` returns `en`/`nl`/`None`, skips messages under `MIN_WORDS_FOR_DETECT` words → build whitelist (config default set ∪ per-guild DB whitelist ∪ `CHAT_SLANG`, lowercased) → run all REGISTRY checkers → if issues: `add_points`, `log_issue` per issue, ❌ reaction, optional reply.

- It's a `@commands.Cog.listener()`, so it's additive — prefix commands still dispatch normally, no `process_commands` call needed.
- `services/cleaner.py` — `clean()` (pre-check normalization), `tokenize()` (unicode-aware, letters only, keeps case), and `is_noise_word()` (laughter/elongation like `hahaha`, `lmfaooo`). Checkers tokenize the already-cleaned text themselves.
- `services/detector.py` — langdetect wrapper, `DetectorFactory.seed=0` for determinism, only returns supported langs (`en`/`nl`).
- `services/lexicon.py` — `CHAT_SLANG`, a frozenset of nl+en internet abbreviations merged into the whitelist on every check.

### Checker behaviour worth knowing before changing it

- `SpellingChecker` skips: whitelisted words, len≤1, noise words, and (when `skip_capitalized`) capitalized non-first tokens (proper-noun heuristic). Side effect: an ALL-CAPS message is effectively unchecked past the first token.
- A word is only a mistake if unknown in **both** the nl and en dictionaries (deliberate, so code-switched messages don't false-positive). This is why many real misspellings slip through — a Dutch typo that happens to be a valid English word is never flagged.
- Scoring is inconsistent between checkers by construction: `SpellingChecker` dedups via a `set` (same typo 3× = 1 point), while `repeats` and `dutch_dt` emit one `Issue` per match (3 points).
- Known false positives, do not "fix" the symptom without checking these: `dutch_dt`'s `als→dan` rule fires on the perfectly correct "beter/leuker/sneller **als** je …" (conditional *if*), and `repeats` flags the ordinary Dutch "ik denk **dat dat** goed is" (only `had` is allowlisted).
- The reply on mistake (`cogs/spelling.py`) is **not** wrapped in try/except, unlike the ❌ reaction right above it — missing send permission or a deleted message raises inside `on_message`.

## Reminders (`cogs/reminders.py` + `repositories/reminders_repo.py`)

Slash-only group `/reminder setup|add|list|remove`, gated behind `default_permissions=manage_guild` (users without *Manage Server* don't see the command at all). A `tasks.loop(seconds=30)` compares `datetime.now(ZoneInfo("Europe/Amsterdam"))` formatted as `HH:MM` against each stored reminder; a `last_fired` date column guards against double sends. Frequencies: `daily` / `weekly` (weekday 0-6) / `monthly` (day clamped to month length) / `once` (deleted after firing).

- **`TZ = ZoneInfo("Europe/Amsterdam")` runs at module import.** `tzdata` is not in `requirements.txt`, so this depends entirely on the OS tz database being present in the image. If it isn't, the cog fails to import and — per the no-error-isolation note above — the **entire bot fails to start**. Add `tzdata` to requirements if this ever surfaces.
- Because the cog pins the timezone explicitly, the container's `TZ` env is irrelevant. Don't "fix" reminders by setting `TZ` in `docker-compose.yml`.
- Send failures are swallowed (`except discord.HTTPException: pass`), so a missing *Mention @everyone* permission looks like silence, not an error.
- `exists_similar()` matches on message+time+frequency only, ignoring channel — re-running `/reminder setup` with a different channel reports "already exist" instead of moving them. There is no edit command.

## Data model (SQLite, `data/points.db`)

`scores` (guild_id, user_id, mistakes — upserted), `whitelist` (guild_id, word — per-guild ignored words), `issues_log` (append-only audit of every flagged word with lang/kind/timestamp), `reminders` (schedule rows, see above). Tables auto-created on repo init by whichever repo owns them.

`issues_log` grows unbounded and has no index beyond the implicit rowid; there is no pruning job.

`scripts/report_flagged.py` reads `issues_log` offline to surface the most-frequently flagged words as default-whitelist candidates (stdlib only, no bot import). Its `DEFAULT_WHITELIST` constant is a hand-maintained copy of `Settings.whitelist` and does **not** include `CHAT_SLANG`, so its "already default" column under-reports — keep it in sync manually or it drifts.

## Conventions

- Config flows one way: `.env` → `load_settings()` → `Settings` dataclass → `bot.settings`. Read config off `bot.settings`, never `os.getenv` outside `core/config.py` (`scripts/` are standalone and exempt).
- `Settings.whitelist` is a hardcoded default set merged with the DB whitelist at check time — global-ish defaults live in config, per-guild additions in DB. Genuinely-global slang belongs in `services/lexicon.py` instead.
- Cogs reach shared state via `self.bot.settings` and `self.bot.repo`.

## Versioning

- Root `VERSION` file is the single source of truth, baked into the Docker image via `COPY . .` and read at startup by `core/config.py:_read_version()` into `Settings.version`.
- `/version` cog (`cogs/version.py`) and `scripts/check_version.sh` compare it against `https://raw.githubusercontent.com/<repo>/<branch>/VERSION` (repo/branch overridable via `GITHUB_REPO` / `GITHUB_BRANCH`). Comparison is string equality only.
- **Bump `VERSION` before every push** — the drift check is only meaningful if the file changes when the code does.
- A `pre-commit` hook at `scripts/hooks/pre-commit` auto-bumps the `VERSION` patch on every commit (enable with `git config core.hooksPath scripts/hooks`); a manually staged `VERSION` change is respected instead.
- `core.hooksPath` is **per-clone local config, never committed**. Enabling it here does nothing for anyone else's checkout — every clone must run `git config core.hooksPath scripts/hooks` once, or its commits land unbumped.
- Historical caveat: `VERSION` sat at `0.1.0` across every commit up to and including the reminders merge, because the hook was not enabled at the time. Any version comparison against a build from that era is meaningless — `0.1.0` covers both the pre- and post-reminders code.

## Deployment

Docker Compose on a NAS/server: `docker compose up -d --build`, `data/` bind-mounted for DB persistence, `restart: unless-stopped`. The image has no healthcheck and runs as root.

**When a feature "doesn't work" in production, check the running image first** — `docker exec spellbot ls /app/cogs/` and `docker compose logs spellbot`. Pulling code without `--build` leaves the old image running, and the version check (see above) will not tell you.

## Docs drift

`README.md` predates several features and currently omits `/reminder`, `/version`, the `dutch_dt` and `repeats` checkers, and `services/lexicon.py`; its "Notes & limitations" still claims *"Spelling only, not grammar — by design"* even though `dutch_dt` is a grammar checker. Update it alongside this file when touching those areas.
