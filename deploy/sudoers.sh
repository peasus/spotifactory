#!/usr/bin/env bash
# Spotifactory — passwordless sudo for the few commands the app and deploys need.
# setup.sh runs this; on a Pi set up before a rule was added, run it on its own:
#   cd ~/spotifactory && bash deploy/sudoers.sh
# (asks for your password once, then the app and SSH deploys don't need it).
set -uo pipefail

USER="${SUDO_USER:-$(whoami)}"
SUDOERS_FILE=/etc/sudoers.d/spotifactory-service

# Without a password, this user may: start/stop/restart only this service, so
# updates can be deployed over SSH (git pull + restart); and reboot or power
# off, for the Reboot and Shutdown menu items; and run the updater, for
# "Check for Updates".
COMMANDS=(
  "/usr/bin/systemctl start spotifactory"
  "/usr/bin/systemctl stop spotifactory"
  "/usr/bin/systemctl restart spotifactory"
  "/usr/bin/systemctl reboot"
  "/usr/bin/systemctl poweroff"
  "/usr/bin/systemctl start spotifactory-update"
)
RULE="$USER ALL=(root) NOPASSWD: $(IFS=,; echo "${COMMANDS[*]}" | sed 's/,/, /g')"

# Check the rule before installing it: a broken file in sudoers.d can lock out sudo.
TMP="$(mktemp)"
echo "$RULE" > "$TMP"
if ! sudo visudo -cf "$TMP" > /dev/null; then
  echo "  WARNING: sudoers rule failed validation — not installed."
  rm -f "$TMP"
  exit 1
fi
sudo install -m 440 -o root -g root "$TMP" "$SUDOERS_FILE"
rm -f "$TMP"
echo "==> Passwordless sudo for: ${COMMANDS[*]}"
