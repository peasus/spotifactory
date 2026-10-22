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
for unit in spotifactory.service spotifactory-update.service spotifactory-update.timer; do
  install_unit "$unit"
done
systemctl daemon-reload
systemctl enable --quiet spotifactory
systemctl enable --quiet --now spotifactory-update.timer

SUDO_USER="$APP_USER" bash "$REPO_DIR/deploy/sudoers.sh"

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
