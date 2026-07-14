#!/usr/bin/env bash
# Check whether the running bot matches the latest VERSION on GitHub.
# Prefers the RUNNING container's baked VERSION (docker exec) so it stays honest
# even after `git pull` without a rebuild; falls back to the local checkout file.
set -euo pipefail

REPO="${GITHUB_REPO:-Woefies/spelling-points-bot}"
BRANCH="${GITHUB_BRANCH:-master}"
CONTAINER="${SPELLBOT_CONTAINER:-spellbot}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_VERSION_FILE="${SCRIPT_DIR}/../VERSION"

# Running version: try the live container first, else the checkout file.
running=""
if command -v docker >/dev/null 2>&1 && docker exec "$CONTAINER" cat /app/VERSION >/dev/null 2>&1; then
    running="$(docker exec "$CONTAINER" cat /app/VERSION | tr -d '[:space:]')"
    source_label="running container ($CONTAINER)"
elif [ -f "$LOCAL_VERSION_FILE" ]; then
    running="$(tr -d '[:space:]' < "$LOCAL_VERSION_FILE")"
    source_label="local checkout"
else
    echo "error: could not determine running version (no container, no local VERSION file)" >&2
    exit 1
fi

# Latest version on GitHub.
latest="$(curl -fsSL "https://raw.githubusercontent.com/${REPO}/${BRANCH}/VERSION" 2>/dev/null | tr -d '[:space:]' || true)"
if [ -z "$latest" ]; then
    echo "error: could not fetch latest VERSION from GitHub" >&2
    exit 1
fi

echo "running: v${running} (${source_label})"
echo "latest:  v${latest} (GitHub ${REPO}@${BRANCH})"
if [ "$running" = "$latest" ]; then
    echo "✅ up to date"
    exit 0
else
    echo "⚠️  update available — pull and rebuild"
    exit 1
fi
