#!/usr/bin/env bash
# Pull and rebuild the bot when GitHub has a newer VERSION, and roll back if the
# rebuild produces a container that will not stay up.
#
# Scheduler-agnostic: Synology Task Scheduler, cron and systemd timers all just
# run this file. Once a day is deliberate — it leaves a window to revert a bad
# merge before it reaches the host.
#
#   ./scripts/auto_update.sh            # update if a newer version exists
#   ./scripts/auto_update.sh --check    # report only, change nothing
#   ./scripts/auto_update.sh --force    # rebuild even when versions match
#
# Exit codes: 0 nothing to do or update succeeded, 1 update failed (rolled back),
# 2 could not determine what is running or what is available.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

REPO="${GITHUB_REPO:-Woefies/spelling-points-bot}"
BRANCH="${GITHUB_BRANCH:-master}"
CONTAINER="${SPELLBOT_CONTAINER:-discord_bot-spellbot-1}"
COMPOSE="${DOCKER_COMPOSE:-docker compose}"
SETTLE_SECONDS="${SETTLE_SECONDS:-25}"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

running_version() {
    $DOCKER exec "$CONTAINER" cat /app/VERSION 2>/dev/null | tr -d '[:space:]'
}

container_up() {
    [ "$($DOCKER inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]
}

# Docker on a NAS usually needs root. Detect rather than hardcode sudo, so this
# also works when run as a user that is in the docker group.
if docker info >/dev/null 2>&1; then
    DOCKER="docker"
elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
    COMPOSE="sudo $COMPOSE"
else
    log "ERROR: cannot talk to Docker (needs root, or passwordless sudo for the scheduler)"
    exit 2
fi

latest="$(curl -fsSL --max-time 20 "https://raw.githubusercontent.com/${REPO}/${BRANCH}/VERSION" 2>/dev/null | tr -d '[:space:]')"
[ -z "$latest" ] && { log "ERROR: could not read VERSION from GitHub"; exit 2; }

current="$(running_version)"
[ -z "$current" ] && log "WARN: container '$CONTAINER' is not running or has no VERSION"

log "running: ${current:-unknown} | available: $latest"

case "${1:-}" in
    --check) [ "$current" = "$latest" ] && log "up to date" || log "update available"; exit 0 ;;
    --force) log "forcing a rebuild" ;;
    *) [ "$current" = "$latest" ] && { log "already up to date, nothing to do"; exit 0; } ;;
esac

# Remember where we are so a failed update can be undone. The image is what
# actually runs, so tagging it is what makes the rollback real — resetting git
# alone would leave the broken image in place.
previous_commit="$(git rev-parse HEAD)"
rollback_tag="spellbot:rollback-$(date +%Y%m%d-%H%M%S)"
image="$($DOCKER inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null)"
if [ -n "$image" ] && $DOCKER tag "$image" "$rollback_tag" 2>/dev/null; then
    log "tagged current image as $rollback_tag"
else
    rollback_tag=""
    log "WARN: could not tag the current image — a failed update cannot be rolled back automatically"
fi

log "pulling $BRANCH"
if ! git pull --ff-only origin "$BRANCH"; then
    log "ERROR: git pull failed (local changes on the host?). Nothing was rebuilt."
    exit 2
fi

log "rebuilding"
if ! $COMPOSE up -d --build; then
    log "ERROR: build failed"
    git reset --hard "$previous_commit" >/dev/null 2>&1
    [ -n "$rollback_tag" ] && $COMPOSE up -d >/dev/null 2>&1
    log "rolled back to $previous_commit"
    exit 1
fi

# A container that starts and then dies looks identical to a healthy one for the
# first few seconds, so wait before believing it.
log "waiting ${SETTLE_SECONDS}s to see whether it stays up"
sleep "$SETTLE_SECONDS"

if container_up && [ "$(running_version)" = "$latest" ]; then
    log "OK: now running $latest"
    exit 0
fi

log "ERROR: container is not healthy after the rebuild"
$DOCKER logs --tail 30 "$CONTAINER" 2>&1 | sed 's/^/    /'
git reset --hard "$previous_commit" >/dev/null 2>&1
log "rolling back to $previous_commit"
$COMPOSE up -d --build >/dev/null 2>&1
if container_up; then
    log "rollback OK: running $(running_version) again"
else
    log "ROLLBACK FAILED — the bot is down and needs a human"
fi
exit 1
