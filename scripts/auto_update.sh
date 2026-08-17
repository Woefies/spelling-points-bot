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
# /update now inside Discord drops a request file in the data volume, which this
# picks up on its next run. The bot cannot rebuild itself — that would mean
# mounting the Docker socket into a container that reacts to user input.
#
# Exit codes: 0 nothing to do or update succeeded, 1 update failed (rolled back),
# 2 could not determine what is running or what is available.
set -uo pipefail

# Schedulers hand you a minimal environment. Synology's Task Scheduler in
# particular runs without /usr/local/bin, which is exactly where Container
# Manager installs docker — so a script that works over SSH fails silently at
# 03:00. Put the usual locations back before looking for anything.
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$(dirname "$0")/.." || exit 2

for tool in git curl; do
    command -v "$tool" >/dev/null 2>&1 || {
        printf 'ERROR: %s not found on PATH (%s)\n' "$tool" "$PATH" >&2
        exit 2
    }
done

# Git refuses to operate on a repo owned by a different user unless that user
# has explicitly trusted it (CVE-2022-24765 mitigation). Task Scheduler often
# runs this as root, while the repo was cloned as another user over SSH —
# without this, every git command below fails with "dubious ownership".
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$(pwd)"; then
    git config --global --add safe.directory "$(pwd)"
fi

REPO="${GITHUB_REPO:-Woefies/spelling-points-bot}"
BRANCH="${GITHUB_BRANCH:-master}"
# docker-compose.yml sets `container_name: spellbot` explicitly, so compose
# does NOT use the usual <project>-<service>-<index> naming here — the real
# container is just "spellbot".
CONTAINER="${SPELLBOT_CONTAINER:-spellbot}"
COMPOSE="${DOCKER_COMPOSE:-docker compose}"
SETTLE_SECONDS="${SETTLE_SECONDS:-25}"
REQUEST_FILE="${REQUEST_FILE:-data/.update-requested}"
# The bot reads this on its next start and reports the outcome in Discord — it
# cannot see whether the rebuild that replaced it succeeded any other way.
RESULT_FILE="${RESULT_FILE:-data/.update-result}"

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

requested=""
if [ -f "$REQUEST_FILE" ]; then
    requested="yes"
    log "update requested from Discord: $(cat "$REQUEST_FILE" 2>/dev/null | head -1)"
fi

case "${1:-}" in
    --check)
        [ "$current" = "$latest" ] && log "up to date" || log "update available"
        [ -n "$requested" ] && log "a manual update is pending"
        exit 0 ;;
    --force) log "forcing a rebuild" ;;
    *)
        if [ "$current" = "$latest" ] && [ -z "$requested" ]; then
            log "already up to date, nothing to do"
            exit 0
        fi ;;
esac

# Clear the request before doing the work, not after: a request that survives a
# failed rebuild would retry forever on every scheduled run.
[ -n "$requested" ] && rm -f "$REQUEST_FILE"

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
    printf 'failed\n%s\n%s\nDe build ging mis.\n' "${current:-onbekend}" "$latest" > "$RESULT_FILE"
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
    printf 'ok\n%s\n%s\n' "${current:-onbekend}" "$latest" > "$RESULT_FILE"
    exit 0
fi

log "ERROR: container is not healthy after the rebuild"
printf 'failed\n%s\n%s\nDe nieuwe versie bleef niet draaien.\n' "${current:-onbekend}" "$latest" > "$RESULT_FILE"
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
