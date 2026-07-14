# Spelling Points Bot

A Discord bot that spell-checks every message in **Dutch & English** and tallies "mistake points" per user.

- Offline spelling via [pyspellchecker](https://github.com/barrust/pyspellchecker) (no external API calls).
- Automatic language detection via [langdetect](https://github.com/Mimino666/langdetect) so Dutch and English messages are checked against the right dictionary.
- Points are stored in SQLite, per user, per guild.

## Architecture

The bot is **cog-based**: every feature (spelling checks, score commands, admin/whitelist commands) lives in its own cog under `cogs/`, auto-loaded on startup.

Spelling itself runs through a **pluggable checker registry** in `services/checkers/`. Each check engine is a `Checker` subclass registered with `@register("name")`; the registry runs every registered checker against a message and sums up the points it contributes. To add a new check engine (e.g. a grammar checker, a profanity checker, etc.), drop a new `Checker` subclass in `services/checkers/` and register it — no other code changes needed, it's picked up automatically.

Storage is **swappable**: `repositories/base.py` defines the storage interface, `repositories/sqlite_repo.py` is the default SQLite-backed implementation. Swap in a different repository implementation without touching cogs or services.

To add a new feature entirely, drop a new cog in `cogs/`.

## Project layout

```
bot.py                              # entrypoint — loads config, builds bot, loads cogs, runs
core/
  config.py                         # env/config loading (.env via python-dotenv)
  bot.py                            # Bot subclass, cog auto-loading, intents setup
cogs/
  spelling.py                       # on_message spell-check flow, awards points
  scores.py                         # /score, /leaderboard commands
  admin.py                          # /whitelist add|remove and other mod commands
services/
  cleaner.py                        # message text normalization/cleaning before checking
  detector.py                       # language detection (langdetect wrapper)
  checkers/
    base.py                         # Checker base class + @register registry
    spelling.py                     # pyspellchecker-based Checker implementation
repositories/
  base.py                           # storage interface (points, whitelist, etc.)
  sqlite_repo.py                    # SQLite implementation
scripts/
  report_flagged.py                 # offline report: most-flagged words, whitelist candidates
data/                               # SQLite DB lives here (gitignored, dir tracked via .gitkeep)
requirements.txt
.env.example
.gitignore
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then paste your bot token into DISCORD_TOKEN
python bot.py
```

## Run with Docker (recommended for servers/NAS)

Easiest way to run this 24/7 on a NAS (Synology, QNAP, TrueNAS) or any Linux box with Docker.

```bash
cp .env.example .env    # then paste your bot token into DISCORD_TOKEN
docker compose up -d --build
```

- `docker compose logs -f` — follow the logs.
- `docker compose down` — stop it.
- `docker compose up -d --build` — rebuild after pulling code changes.

The `data/` folder is mounted as a volume, so the SQLite points database survives restarts and rebuilds. `restart: unless-stopped` in `docker-compose.yml` means the bot auto-starts when the NAS reboots.

**Synology specifics:** either SSH in and run the `docker compose` command above from the project folder, or use **Container Manager → Project → Create** and point it at the folder containing `docker-compose.yml`.

## Discord Developer Portal setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Open the **Bot** tab, add a bot, and copy its token into `.env` as `DISCORD_TOKEN`.
3. On the **Bot** tab, enable **MESSAGE CONTENT INTENT** (privileged intent) — required, since the bot reads message content to spell-check it.
4. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: Read Messages/View Channels, Send Messages, Add Reactions, Read Message History
5. Copy the generated URL, open it, and invite the bot to your server.

## Commands

| Command | Description |
|---|---|
| `/score [user]` | Show a user's mistake tally (defaults to yourself). |
| `/leaderboard` | Show the top offenders in the server. |
| `/whitelist add <word>` | Ignore `<word>` in spell-checking (requires Manage Server). |
| `/whitelist remove <word>` | Remove `<word>` from the whitelist (requires Manage Server). |

Both slash commands and their prefix equivalents (default prefix `!`, e.g. `!score`) work.

## Configuration

Set these in `.env` (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_TOKEN` | *(required)* | Your bot's token from the Developer Portal. |
| `PREFIX` | `!` | Prefix for text commands (in addition to slash commands). |
| `MIN_WORDS_FOR_DETECT` | `3` | Minimum word count before a message is language-detected and checked; shorter messages are skipped. |
| `SKIP_CAPITALIZED` | `true` | Skip words that are capitalized (heuristic for proper nouns/names). |
| `REPLY_ON_MISTAKE` | `true` | Whether the bot replies in-channel when it finds a mistake, vs. silently tallying. |
| `POINTS_PER_MISTAKE` | `1` | Points awarded per detected mistake. |
| `DB_PATH` | `data/points.db` | Path to the SQLite database file. |

## Reviewing flagged words (whitelist candidates)

Every flagged word is logged to the `issues_log` table in SQLite. To see which words get flagged most often — good candidates for the default whitelist — run the offline report:

```bash
python scripts/report_flagged.py                          # top 30 flagged words, all servers
python scripts/report_flagged.py --min-hits 3 --lang nl   # Dutch words flagged 3+ times
python scripts/report_flagged.py --csv data/flagged.csv   # dump the full list to CSV
```

Flags: `--limit N` (rows shown, default 30), `--min-hits N` (minimum flag count), `--lang en|nl` (filter by language), `--csv PATH` (write full result to CSV). The report reads `DB_PATH` (default `data/points.db`).

The `NOTE` column marks words already in the default whitelist so you can skip them. When you spot a legitimate word (slang, a name, a loanword) that keeps getting flagged, either whitelist it per-server with `/whitelist add <word>`, or — to cover every server — add it to the default set in `core/config.py` (`Settings.whitelist`).

## Notes & limitations

- **Spelling only, not grammar** — by design. The bot catches misspelled words, not grammatical errors.
- **Dutch dictionary is weaker than English** — expect more false negatives/positives on Dutch text.
- **Proper nouns and slang can false-positive.** Use `/whitelist add <word>` to permanently ignore specific words per server.
- **Short or foreign-language messages are skipped** — anything under `MIN_WORDS_FOR_DETECT` words isn't checked, since language detection is unreliable on very short strings.
