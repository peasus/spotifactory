#!/usr/bin/env bash
# Bring the system in line with this checkout: the systemd units and the sudo
# rule. Idempotent; setup.sh runs it, and so does every auto-update, so a
# change here reaches boxes that are already out in the world.
#   sudo bash deploy/upgrade.sh APP_USER
set -euo pipefail

APP_USER="${1:-${SUDO_USER:-spotifactory}}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_UID="$(id -u "$APP_USER")"

# The unit files are written for user spotifactory, uid 1000, the repo in its
# home: patch them to this box's.
install_unit() {
  local tmp
  tmp="$(mktemp)"
  sed -e "s|User=spotifactory|User=$APP_USER|g" \
      -e "s|/home/spotifactory/spotifactory|$REPO_DIR|g" \
      -e "s|/run/user/1000|/run/user/$APP_UID|g" \
      -e "s|update.sh spotifactory|update.sh $APP_USER|g" \
      "$REPO_DIR/deploy/$1" > "$tmp"
  install -m 644 "$tmp" "/etc/systemd/system/$1"
  rm -f "$tmp"
}
for unit in spotifactory.service spotifactory-update.service spotifactory-update.timer; do
  install_unit "$unit"
done
systemctl daemon-reload
systemctl enable --quiet spotifactory
systemctl enable --quiet --now spotifactory-update.timer

SUDO_USER="$APP_USER" bash "$REPO_DIR/deploy/sudoers.sh"
