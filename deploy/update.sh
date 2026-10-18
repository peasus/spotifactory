#!/usr/bin/env bash
# Spotifactory auto-update. Runs as root from spotifactory-update.service:
# nightly from its timer, or now from the app's "Check for Updates".
#   update.sh APP_USER
#
# Follows the `stable` branch (SPOTIFACTORY_UPDATE_BRANCH in .env to change;
# SPOTIFACTORY_AUTO_UPDATE=0 to skip the nightly run). Waits if the box is in
# use, unless asked from the menu. After updating it restarts the app and
# checks it comes back; if not, it rolls back and won't retry that release.
set -uo pipefail

APP_USER="${1:-spotifactory}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
STATE="$USER_HOME/.cache/spotifactory"        # shared with the app (runner.state_dir)
HEARTBEAT="$STATE/heartbeat"
REQUEST="$STATE/update-requested"
STATUS="$STATE/update-status"
BAD="$STATE/update-bad-commit"

as_user() { runuser -u "$APP_USER" -- "$@"; }
log() { echo "[update] $*"; }
record() { as_user mkdir -p "$STATE"; echo "$*" | as_user tee "$STATUS" > /dev/null; }
setting() { grep -E "^$1=" "$REPO_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2-; }

exec 9> /run/spotifactory-update.lock
flock -n 9 || { log "already running"; exit 0; }

BRANCH="$(setting SPOTIFACTORY_UPDATE_BRANCH)"
BRANCH="${BRANCH:-stable}"
ASKED=0
if [ -f "$REQUEST" ]; then
  ASKED=1
  rm -f "$REQUEST"
fi
if [ "$ASKED" = 0 ] && [ "$(setting SPOTIFACTORY_AUTO_UPDATE)" = "0" ]; then
  log "nightly updates are off (SPOTIFACTORY_AUTO_UPDATE=0)"
  exit 0
fi
# Don't interrupt someone listening, printing or in the menus.
if [ "$ASKED" = 0 ] && [ -f "$HEARTBEAT" ] \
   && [ $(( $(date +%s) - $(stat -c %Y "$HEARTBEAT") )) -lt 120 ] && grep -q busy "$HEARTBEAT"; then
  log "in use; trying again next time"
  exit 0
fi

cd "$REPO_DIR" || exit 1
if ! as_user git fetch --quiet origin "$BRANCH"; then
  log "couldn't fetch $BRANCH"
  record "error fetch"
  exit 1
fi
PREV="$(as_user git rev-parse HEAD)"
NEW="$(as_user git rev-parse FETCH_HEAD)"
if [ "$PREV" = "$NEW" ]; then
  log "up to date (${PREV:0:7})"
  record "current ${PREV:0:7}"
  exit 0
fi
if [ "$NEW" = "$(cat "$BAD" 2>/dev/null)" ]; then
  log "skipping ${NEW:0:7}: it failed before"
  record "current ${PREV:0:7}"
  exit 0
fi

# Check out a revision and bring the box in line with it: Python packages if
# they changed, then the system-level steps (service files, sudo rule).
install_rev() {   # install_rev TO FROM
  as_user git -c advice.detachedHead=false checkout --quiet --force --detach "$1" || return 1
  if ! as_user git diff --quiet "$2" "$1" -- pyproject.toml; then
    local platform
    platform="$(setting SPOTIFACTORY_PLATFORM)"
    as_user "$REPO_DIR/.venv/bin/pip" install --quiet -e ".[${platform:-seengreat}]" || return 1
  fi
  bash "$REPO_DIR/deploy/upgrade.sh" "$APP_USER" || return 1
}

# The app writes its heartbeat every few seconds once it's up and drawing.
came_back() {   # came_back SINCE_EPOCH
  for _ in $(seq 1 30); do
    sleep 4
    if [ -f "$HEARTBEAT" ] && [ "$(stat -c %Y "$HEARTBEAT")" -ge "$1" ] \
       && systemctl is-active --quiet spotifactory; then
      return 0
    fi
  done
  return 1
}

log "updating ${PREV:0:7} -> ${NEW:0:7} ($BRANCH)"
START="$(date +%s)"
if install_rev "$NEW" "$PREV" && systemctl restart spotifactory && came_back "$START"; then
  log "updated to ${NEW:0:7}"
  record "updated ${NEW:0:7}"
  rm -f "$BAD"
  exit 0
fi

log "update to ${NEW:0:7} failed; rolling back to ${PREV:0:7}"
echo "$NEW" | as_user tee "$BAD" > /dev/null
install_rev "$PREV" "$NEW"
systemctl restart spotifactory
record "rolled back ${PREV:0:7}"
exit 1
