#!/usr/bin/env bash
# Spotifactory — one-time Pi setup script
# Run over SSH on a fresh Raspberry Pi OS Lite 64-bit image:
#   ssh spotifactory@spotifactory.local
#   cd ~/spotifactory && bash deploy/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER="${SUDO_USER:-$(whoami)}"

echo "==> Spotifactory setup (repo: $REPO_DIR, user: $USER)"

# ------------------------------------------------------------------ Packages
echo "==> Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
  python3 python3-pip python3-venv python3-dev build-essential \
  python3-dbus \
  libjpeg-dev libopenjp2-7 \
  libusb-1.0-0-dev \
  i2c-tools \
  bluetooth bluez \
  avahi-daemon \
  curl

# ------------------------------------------------------------ Hardware config
echo "==> Enabling I2C..."
sudo raspi-config nonint do_i2c 0

echo "==> Setting hostname to 'spotifactory'..."
sudo hostnamectl set-hostname spotifactory
# Ensure avahi advertises the new hostname so spotifactory.local resolves
sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon

echo "==> Adding $USER to hardware groups..."
sudo usermod -a -G spi,gpio,i2c,bluetooth "$USER"

# --------------------------------------------------------- Balena WiFi Connect
echo "==> Installing Balena WiFi Connect..."
# This script replaces dhcpcd with NetworkManager and installs wifi-connect binary
bash <(curl -sL https://github.com/balena-os/wifi-connect/raw/master/scripts/raspbian-install.sh)

# ---------------------------------------------------- Python virtual environment
echo "==> Setting up Python environment..."
cd "$REPO_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[rpi]" -q

# ----------------------------------------------------------------- .env check
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/deploy/env.example" "$REPO_DIR/.env"
  echo ""
  echo "  *** ACTION REQUIRED ***"
  echo "  Edit $REPO_DIR/.env and fill in your Spotify credentials:"
  echo "    nano $REPO_DIR/.env"
  echo ""
fi

# --------------------------------------------------------------- systemd service
echo "==> Installing systemd service..."
sudo cp "$REPO_DIR/deploy/spotifactory.service" /etc/systemd/system/spotifactory.service
# Patch the user and working directory to match the actual setup
sudo sed -i "s|User=spotifactory|User=$USER|g" /etc/systemd/system/spotifactory.service
sudo sed -i "s|/home/spotifactory/spotifactory|$REPO_DIR|g" /etc/systemd/system/spotifactory.service
sudo systemctl daemon-reload
sudo systemctl enable spotifactory

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with Spotify credentials: nano $REPO_DIR/.env"
echo "  2. Make sure http://spotifactory.local:8080/callback is in your Spotify"
echo "     Developer Dashboard as an allowed Redirect URI."
echo "  3. Reboot: sudo reboot"
echo "     On boot the device will guide the recipient through WiFi + Spotify setup."
