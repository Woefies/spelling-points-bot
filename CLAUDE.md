# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Discord bot that spell-checks every message (Dutch + English) and tallies "mistake points" per user, per guild. Offline spelling (Hunspell via spylls, pyspellchecker as fallback; no external API), language auto-detected (langdetect), points in SQLite. Also ships a Dutch grammar checker, a repeated-word checker, scheduled channel reminders, and a version drift-check against GitHub.

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

1. **Cogs** (`cogs/`) — auto-loaded in `core/bot.py:setup_hook` via `pkgutil.iter_modules(cogs.__path__)`. Every module in `cogs/` with an `async def setup(bot)` is loaded automatically. Drop a new cog file → it loads. `spelling.py` holds the `on_message` flow; `scores.py`, `admin.py` and `version.py` are `hybrid_command`s (slash + prefix both work); `reminders.py`, `say.py`, `triggers.py`, `daily_summary.py`, `backup.py` and `reset.py` are pure `app_commands` (slash only).
   - `say.py` posts as the bot with no attribution: the interaction reply is `ephemeral=True` (so other members never see the invocation *or* the "used /say" header) and the content goes out via a separate `channel.send()`. Both halves are required — a non-ephemeral reply would expose the invoker. It is gated on `manage_guild` and forces `AllowedMentions.none()`, since anonymous posting plus mass-ping is an abuse vector.
   - Loading is fault-isolated (`_load_cogs`): a cog that raises at import is logged with a traceback and skipped, and the rest still load. Startup logs list which cogs loaded and which failed, so a missing command is traceable to a named cog instead of a silent absence.
   - Command sync (`_sync_commands`) is also non-fatal, and catches broadly on purpose — `sync()` and `copy_global_to()` raise from two unrelated hierarchies (`HTTPException`, plus `AppCommandError` subclasses like `CommandLimitReached` and `TranslationError`), and a failed sync must never stop the bot. **Set `DEV_GUILD_ID` while developing:** it syncs to that one guild and shows up instantly, where the global sync takes up to an hour — new commands look broken when they are merely not propagated yet. Every synced command name is logged.

2. **Checkers** (`services/checkers/`) — pluggable check engines. Each is a `Checker` subclass decorated `@register("name")` (see `base.py`); the decorator **instantiates once** and stores the instance in `REGISTRY`. The `on_message` flow runs every registered checker and sums their `Issue`s into points. **Gotcha:** a new checker module must be imported in `services/checkers/__init__.py` so `@register` actually runs — unlike cogs, checkers are NOT auto-discovered. Currently registered: `spelling`, `repeats`, `dutch_dt`.

3. **Repository** (`repositories/`) — storage interface `ScoreRepository` (`base.py`), default impl `SqliteScoreRepository` (`sqlite_repo.py`). Instantiated directly in `core/bot.py:__init__` (`self.repo`). To swap storage, change that one line. SQLite conn is `check_same_thread=False` guarded by a `threading.Lock` (discord.py runs listeners on the event loop but repo is sync).
   - **Known deviation:** `SqliteReminderRepository` (`repositories/reminders_repo.py`) has no ABC and is instantiated inside `RemindersCog.__init__`, not in `core/bot.py`. It opens a *second* SQLite connection to the same file with its own lock. Neither connection sets `journal_mode=WAL` or a busy `timeout`, so concurrent writes can hit `database is locked`. New storage should follow the `ScoreRepository` pattern instead of copying this one.

### Message flow (`cogs/spelling.py:on_message`)

`clean()` (strip code blocks/URLs/mentions/emoji/digit-words) → skip if empty → `detect()` returns `en`/`nl`/`None`, skips messages under `MIN_WORDS_FOR_DETECT` words → build whitelist (config default set ∪ per-guild DB whitelist ∪ `CHAT_SLANG`, lowercased) → run all REGISTRY checkers → if issues: `add_points`, `log_issue` per issue, ❌ reaction, optional reply.

- It's a `@commands.Cog.listener()`, so it's additive — prefix commands still dispatch normally, no `process_commands` call needed.
- `services/cleaner.py` — `clean()` (pre-check normalization), `tokenize()` (unicode-aware, letters only, keeps case), and `is_noise_word()` (laughter/elongation like `hahaha`, `lmfaooo`). Checkers tokenize the already-cleaned text themselves.
- `services/detector.py` — langdetect wrapper, `DetectorFactory.seed=0` for determinism, only returns supported langs (`en`/`nl`).
- `services/lexicon.py` — `SKIP_WORDS`, the union of `CHAT_SLANG`, `ABBREVIATIONS` and `TECH_TERMS`, merged into the whitelist on every check. Written abbreviations (`enz`, `bijv`, `ipv`) are **not** in any Hunspell dictionary — they are punctuation conventions rather than words — so without this list they read as mistakes. Company-specific words belong in the per-guild whitelist, not here.
- `services/dictionaries.py` — picks a backend per language: Hunspell via `spylls` when `<lang>.dic` exists under `HUNSPELL_DIR`, else pyspellchecker. Loaded lazily on the first check, because `@register` instantiates checkers at import time when no settings exist yet, and reading a dictionary costs a second or two. Lookups are `lru_cache`d; spylls is a readable reference implementation, not a fast one.

### Checker behaviour worth knowing before changing it

- `SpellingChecker` skips: whitelisted words, len≤1, noise words, and (when `skip_capitalized`) capitalized non-first tokens (proper-noun heuristic). Side effect: an ALL-CAPS message is effectively unchecked past the first token.
- Hunspell is what makes Dutch checkable: it applies affix and compounding rules, so `zonnebrandcrème` and `voetbalwedstrijdverslag` pass without being in any list. A flat word list can never hold them — Dutch glues words together without limit — which is why pyspellchecker produced so many false positives. Debian's `hunspell-nl` (built from OpenTaal) is installed in the Dockerfile.
- A word is only a mistake if unknown in **both** the nl and en dictionaries (deliberate, so code-switched messages don't false-positive). This is why many real misspellings slip through — a Dutch typo that happens to be a valid English word is never flagged.
- Scoring is inconsistent between checkers by construction: `SpellingChecker` dedups via a `set` (same typo 3× = 1 point), while `repeats` and `dutch_dt` emit one `Issue` per match (3 points).
- `repeats` honours `ctx["whitelist"]` on top of its own `_ALLOWLIST` (`had`, `dat`, `die` — all of which double legitimately in Dutch). A word an admin has whitelisted must be fine for *every* checker, or whitelisting looks broken to the person who did it.
- `dutch_dt` is the exception and cannot honour the whitelist: it reports a rule name (`als→dan`), not a word, so there is nothing to match against. Its `als→dan` rule still fires on the perfectly correct "beter/leuker/sneller **als** je …" (conditional *if*), and the only fix is dropping the rule.
- The reply on mistake (`cogs/spelling.py`) is **not** wrapped in try/except, unlike the ❌ reaction right above it — missing send permission or a deleted message raises inside `on_message`.

## Reminders (`cogs/reminders.py` + `repositories/reminders_repo.py`)

Slash-only group `/reminder add|edit|list|remove`, gated behind `default_permissions=manage_guild` (users without *Manage Server* don't see the command at all). A `tasks.loop(seconds=30)` compares `datetime.now(ZoneInfo("Europe/Amsterdam"))` formatted as `HH:MM` against each stored reminder. Frequencies: `daily` / `weekdays` (Mon-Fri) / `weekly` (weekday 0-6) / `monthly` (day clamped to month length) / `once` (deleted after firing).

**One reminder can hold several times of day**, stored comma-separated in the existing `time` column (`"09:00,11:00,13:00"`) and parsed by `_parse_times`, which normalises, sorts and dedupes. This is why `last_fired` stores `"YYYY-MM-DD HH:MM"` rather than a bare date: the guard has to allow a second firing later the same day while still blocking the 30s loop from double-sending inside one minute. Rows written before this change hold a bare date, which simply never matches — costing exactly one extra send on the day of the upgrade, deemed cheaper than a migration.

`/reminder edit` and `/reminder remove` (and `/trigger remove`) autocomplete the `id` parameter with the guild's own rows, so nobody has to look up a number first. discord.py passes `self` to an autocomplete callback defined inside a class automatically (`pass_command_binding`), so these are plain cog methods. Both Discord limits are handled: choice names are truncated at 100 characters and the list at 25.

`/reminder edit` patches only `message`, `time`, `channel_id` and `mention`. Frequency, day and date are intentionally not editable: validating those combinations lives in `add_cmd`, and duplicating it in an edit path invites the two drifting apart.

**No reminder or trigger text lives in the code.** There is no preset or seed command: every reminder and trigger is created at runtime and stored in SQLite, so changing wording never needs a code change, a rebuild, or a deploy by whoever runs the host. Restoring a lost set comes from a backup snapshot (see below), which holds the real current text rather than a stale template.

## Command help text

`description=` on a command and each `app_commands.describe` string are what Discord shows while someone is typing, and **Discord caps both at 100 characters** — the API rejects the whole sync if any is longer, which takes down every command, not just the offending one. **Command, subcommand and parameter names are English; every description, choice label and reply is Dutch.** That split is the convention here — `add`/`list`/`remove`/`edit` are what Discord users expect to type, while everything read on screen is in the team's language. Do not add a Dutch command name.

Write descriptions as a hint with a concrete example (`"Tijd als HH:MM. Meerdere momenten per dag met kommas: 09:00, 13:00, 17:00"`), and keep them in Dutch: the entire user-facing surface is Dutch, while the code and these notes are English.

- **`TZ = ZoneInfo("Europe/Amsterdam")` runs at module import.** `tzdata` is not in `requirements.txt`, so this depends entirely on the OS tz database being present in the image. If it isn't, the cog fails to import — since fault isolation landed this only costs you the reminders cog rather than the whole bot, and the startup log names it. Add `tzdata` to requirements if that shows up.
- Because the cog pins the timezone explicitly, the container's `TZ` env is irrelevant. Don't "fix" reminders by setting `TZ` in `docker-compose.yml`.
- Send failures are swallowed (`except discord.HTTPException: pass`), so a missing *Mention @everyone* permission looks like silence, not an error.
- `exists_similar()` matches on message+time+frequency only, ignoring channel — re-running `/reminder setup` with a different channel reports "already exist" instead of moving them. There is no edit command.

## Triggers and the daily summary

`cogs/triggers.py` reacts to keywords with a reply, emoji, or both — a social nudge, not a mistake, so it awards no points. Rows live in the `triggers` table and are editable at runtime via `/trigger add|edit|list|remove`; nothing is hardcoded. `/trigger add` refuses a pattern that already exists.

`/trigger edit` differs from `/reminder edit` on purpose: it takes a `changes` dict rather than keyword arguments, because a trigger legitimately needs a field *cleared*. A lone `-` empties `response` or `reactions`, which the reminder version has no equivalent of — "not given" and "make empty" have to be distinguishable. It refuses an edit that would leave a trigger with neither a reply nor reactions, since that is a row that does nothing. Patterns are matched with `services/variants.compile_phrases`, which wraps `\b…\b` word boundaries around each phrase — that is what keeps the profanity trigger off `kankeren` and `borstkanker`. It cannot keep it off a genuine medical mention, which is a known and accepted limitation. At most one reply fires per message however many triggers match.

Overviews print display names; only messages aimed at one person (a warning, a mute) mention them. A list of mentions reads as if everyone in it is being addressed, and it stays noisy even though a mention inside an embed does not notify.

`cogs/daily_summary.py` posts the day's leaderboard on weekdays at a configurable time (`/summary enable|uit|list`), reading `issues_log` because `scores` only holds running totals. **Timezone trap:** `issues_log.ts` is SQLite's `CURRENT_TIMESTAMP` (UTC) while the reporting day is Amsterdam local, so it queries a UTC *range* built by `_utc_window_for_local_day`, never `DATE(ts)`. A plain date match silently files everything logged between local midnight and 01:00/02:00 into the previous day.

`services/variants.py` is shared by both: `pick_variant` picks one of several `|`-separated phrasings per firing (so recurring output does not go stale), and `compile_phrases` builds the matching regex. Reminders and triggers both store variants in a single text column.

## Resetting

`/reset` wipes one category (`reminders`, `triggers`, `whitelist`, `scores`, `guild_config`, or all of them) for the calling guild. It **always writes a backup snapshot first and aborts if that fails** — the snapshot is the only way back, so taking it afterwards would be pointless. It also requires an explicit `bevestig: True`; a destructive command that fires on a single click is a footgun.

`SqliteScoreRepository.clear()` maps a caller-supplied key through `_CLEARABLE` before it reaches the SQL string, so a table name is never interpolated unchecked, and it returns 0 for a table that does not exist yet rather than raising. It clears `reminders` too, even though `SqliteReminderRepository` owns that table — running one DELETE is not worth a third connection to the same file.

## Punishment (`cogs/punishment.py` + `services/punishment.py`)

Times a member out once their mistakes *for the local day* cross a multiple of a configurable threshold (default 20). Threshold, ladder and both announcement texts are per-guild settings, not constants — tuning this must not need a redeploy by whoever runs the host. The ladder defaults to 1/2/5/10/20/30 minutes and its last rung repeats rather than escalating, so a bad day cannot end in an hour of silence. Custom texts take `{user}`, `{count}` and `{minutes}`; `render()` falls back to the built-in text when a template is malformed, because admins write these by hand and a stray brace must not swallow the announcement.

**Three modes, off by default.** `warn` announces who *would* have been muted without touching anyone, and exists because this is the only feature that can stop a colleague from talking — the bot still has false positives on names and jargon. Run `warn` before `mute`.

`services/punishment.py` holds the arithmetic and imports no discord.py, so the escalation is testable on its own. `crossed()` compares tiers rather than testing for an exact multiple: one message can carry several mistakes and jump 18 → 21 straight past a boundary.

The spelling cog stays unaware of any of this — it fires `bot.dispatch("mistakes_recorded", message, points)` and the punishment cog listens. Timeouts need **Moderate Members** and the bot's role above the target's; Discord refuses to time out admins and the owner at all, which is reported in-channel rather than swallowed.

## Rate limiting

`RateLimitedTree` in `core/bot.py` puts one shared cooldown (5 uses / 15 s / user) in front of every slash command via `interaction_check`, rather than a decorator per command that a new cog could forget. It lets non-application-command interactions through untouched — autocomplete fires on every keystroke and must never be throttled.

## Backups

`data/` is a mounted volume, so configuration already survives a rebuild — the gap backups close is the database file itself being lost or corrupted. `cogs/backup.py` writes a JSON snapshot of `reminders`, `triggers`, `whitelist`, `guild_config` and `scores` at 04:00 daily into `data/backups/` (gitignored), keeping the newest 14. `issues_log` is excluded on purpose: append-only audit data, unbounded, pointless to restore.

`services/backup.py` holds the logic and talks to SQLite directly rather than through a repository, so `scripts/export_config.py` and `scripts/import_config.py` can reuse it without importing discord.py. Writes go to a `.tmp` file and are then `replace()`d into position, so a crash mid-write cannot leave a truncated file that looks valid. Missing tables are skipped rather than raising — `reminders` only exists once that cog has run.

Restore is destructive by design (wipe the table, reinsert): a merge would leave old and restored rows indistinguishable. `import_config.py` is therefore a dry run unless `--replace` is passed.

The backup cog pins a fixed UTC+1 offset instead of `ZoneInfo`, so it does not inherit the tzdata dependency that can stop the reminders cog from loading. It drifts to 05:00 local in summer, which is fine for a nightly job.

## Data model (SQLite, `data/points.db`)

`scores` (guild_id, user_id, mistakes — upserted), `whitelist` (guild_id, word — per-guild ignored words), `issues_log` (append-only audit of every flagged word with lang/kind/timestamp, indexed on `(guild_id, ts)` for the daily summary), `triggers` (keyword → response/reactions), `guild_config` (per-guild key/value, currently the daily-summary channel and time), `reminders` (schedule rows, see above). Tables auto-created on repo init by whichever repo owns them.

Triggers and config live on `SqliteScoreRepository` rather than in a repo of their own, deliberately: a separate repo would mean a third SQLite connection to the same file, which is the problem flagged above. The class name is now narrower than what it stores.

`issues_log` grows unbounded and has no index beyond the implicit rowid; there is no pruning job.

`scripts/report_flagged.py` reads `issues_log` offline to surface the most-frequently flagged words as default-whitelist candidates (stdlib only, no bot import). It groups by `kind` and can filter on it (`--kind spelling|repeat|grammar_nl`) — without that, "this word is whitelisted but still gets flagged" is unanswerable, because the whitelist only ever applied to the spelling checker. Note the table is a historical log: a word whitelisted today still appears for every time it was flagged before that. Its `DEFAULT_WHITELIST` constant is a hand-maintained copy of `Settings.whitelist` and does **not** include `CHAT_SLANG`, so its "already default" column under-reports — keep it in sync manually or it drifts.

## Conventions

- Config flows one way: `.env` → `load_settings()` → `Settings` dataclass → `bot.settings`. Read config off `bot.settings`, never `os.getenv` outside `core/config.py` (`scripts/` are standalone and exempt).
- `/whitelist add|remove` take a comma-separated list, not a single word: the flagged-words report produces batches, and one command per word does not scale. `/whitelist remove` autocompletes from the guild's own entries — on a hybrid command that has to go through `@cmd.autocomplete("param")` rather than the `@app_commands.autocomplete` decorator. Its filter reads the text after the last comma, so suggestions keep working while typing a list.

`Settings.whitelist` is a hardcoded default set merged with the DB whitelist at check time — global-ish defaults live in config, per-guild additions in DB. Genuinely-global slang belongs in `services/lexicon.py` instead.
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
