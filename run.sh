#!/usr/bin/env bash
# Launcher for the Discord spelling-tally bot.
# Creates the venv + installs deps on first run, then starts the bot.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "==> Creating virtualenv ($VENV)"
  python3 -m venv "$VENV"
  echo "==> Installing dependencies"
  "$VENV/bin/pip" install -q -r requirements.txt
fi

if [[ ! -f ".env" ]]; then
  echo "ERROR: .env not found. Run: cp .env.example .env  then set DISCORD_TOKEN" >&2
  exit 1
fi

if ! grep -qE '^DISCORD_TOKEN=.+' .env; then
  echo "ERROR: DISCORD_TOKEN is empty in .env" >&2
  exit 1
fi

echo "==> Starting bot"
exec "$PY" bot.py
