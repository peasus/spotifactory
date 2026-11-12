#!/usr/bin/env bash
# Bring the system in line with this checkout: the systemd units, the sudo
# rule and the boot config. Idempotent; setup.sh runs it, and so does every auto-update, so a
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
for unit in spotifactory.service spotifactory-splash.service spotifactory-update.service spotifactory-update.timer; do
  install_unit "$unit"
done
systemctl daemon-reload
systemctl enable --quiet spotifactory spotifactory-splash
systemctl enable --quiet --now spotifactory-update.timer

SUDO_USER="$APP_USER" bash "$REPO_DIR/deploy/sudoers.sh"

# Squeezelite: the box's player in Music Assistant mode (advanced; Menu >
# Music Source). Installed everywhere but off: the app turns it on and
# Raspotify off when that mode is chosen. A failure here (no network for apt)
# mustn't fail the update; it's tried again next time.
if ! command -v squeezelite > /dev/null; then
  echo "==> Installing Squeezelite (for Music Assistant mode)..."
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends squeezelite; then
    { apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends squeezelite; } \
      || echo "  WARNING: couldn't install squeezelite; Music Assistant mode can't play on this box yet"
  fi
  # The package's own system service plays to ALSA as its own user; ours
  # runs in the PipeWire session instead.
  systemctl disable --now squeezelite > /dev/null 2>&1 || true
fi
USER_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
USER_UNITS="$USER_HOME/.config/systemd/user"
install -d -o "$APP_USER" -g "$APP_USER" "$USER_HOME/.config" "$USER_HOME/.config/systemd" "$USER_UNITS"
SQ_TMP="$(mktemp)"
sed -e "s|/home/spotifactory/spotifactory|$REPO_DIR|g" "$REPO_DIR/deploy/squeezelite.service" > "$SQ_TMP"
install -m 644 -o "$APP_USER" -g "$APP_USER" "$SQ_TMP" "$USER_UNITS/squeezelite.service"
rm -f "$SQ_TMP"

# The OLED's I2C bus at 400 kHz (the Pi's default is 100): a full screen
# update takes 38 ms instead of 159, and the app reads the buttons in the
# same loop. The screen is the only thing on this bus. Takes effect at the
# next boot.
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
if [ -f "$BOOT_CONFIG" ] && ! grep -q "^dtparam=i2c_arm_baudrate=" "$BOOT_CONFIG"; then
  echo "dtparam=i2c_arm_baudrate=400000" >> "$BOOT_CONFIG"
  echo "==> I2C at 400 kHz from the next reboot"
fi
