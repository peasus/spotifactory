#!/usr/bin/env bash
# Spotifactory — one-time Pi setup script
# Run over SSH on a fresh Raspberry Pi OS Lite 64-bit image:
#   ssh spotifactory@spotifactory.local
#   cd ~/spotifactory && bash deploy/setup.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER="${SUDO_USER:-$(whoami)}"
USER_ID="$(id -u "$USER")"

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
  pipewire wireplumber libspa-0.2-bluetooth pipewire-alsa pipewire-pulse \
  avahi-daemon \
  curl

# ------------------------------------------------------------ Hardware config
echo "==> Enabling I2C and SPI..."
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0

echo "==> Setting hostname to 'spotifactory'..."
sudo hostnamectl set-hostname spotifactory
# Ensure avahi advertises the new hostname so spotifactory.local resolves
sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon

echo "==> Adding $USER to hardware groups..."
sudo usermod -a -G spi,gpio,i2c,bluetooth,dialout "$USER"

# ----------------------------------------------------------- Bluetooth config
echo "==> Configuring Bluetooth..."
sudo systemctl enable bluetooth
sudo rfkill unblock bluetooth
# Ensure the controller auto-powers on after every boot
if grep -q "AutoEnable" /etc/bluetooth/main.conf 2>/dev/null; then
  sudo sed -i 's/.*AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
else
  echo "AutoEnable=true" | sudo tee -a /etc/bluetooth/main.conf
fi
sudo systemctl restart bluetooth

# --------------------------------------------------------- Balena WiFi Connect
echo "==> Installing Balena WiFi Connect..."
# The Balena installer script only ships a 32-bit ARM binary; on 64-bit Pi OS
# we download the aarch64 release directly instead.
ARCH="$(uname -m)"
WC_VERSION="v4.4.6"
if [ "$ARCH" = "aarch64" ]; then
  WC_URL="https://github.com/balena-os/wifi-connect/releases/download/${WC_VERSION}/wifi-connect-${WC_VERSION}-linux-aarch64.tar.gz"
  echo "  Detected aarch64 — downloading 64-bit binary..."
  curl -sL "$WC_URL" | sudo tar -xz -C /usr/local/sbin/
  sudo chmod +x /usr/local/sbin/wifi-connect
  # Still need NetworkManager (the installer script normally sets this up)
  sudo apt-get install -y network-manager
  sudo systemctl enable NetworkManager
  # dhcpcd conflicts with NetworkManager (present on Bullseye; not installed on Bookworm)
  sudo systemctl disable dhcpcd 2>/dev/null || true
  sudo systemctl stop dhcpcd 2>/dev/null || true
else
  bash <(curl -sL https://github.com/balena-os/wifi-connect/raw/master/scripts/raspbian-install.sh)
fi

if wifi-connect --version &>/dev/null; then
  echo "  WiFi Connect installed: $(wifi-connect --version)"
else
  echo "  WARNING: WiFi Connect install failed — captive portal will not work."
  echo "  The app will still run if WiFi is already configured."
fi

# ----------------------------------------------------------- PipeWire + autologin
echo "==> Configuring PipeWire audio for user $USER..."
# PipeWire/WirePlumber need a real login session to register A2DP with BlueZ.
# loginctl enable-linger is not sufficient — autologin to tty1 creates the
# full session (D-Bus, seat) that PipeWire requires on Pi OS Lite.
sudo raspi-config nonint do_boot_behaviour B2

# ----------------------------------------------------------- Raspotify
echo "==> Installing Raspotify (Spotify Connect receiver)..."
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh

# Disable the system service — we run Raspotify as a user service instead so it
# lives in the same PipeWire session without user-namespace auth complications.
sudo systemctl disable raspotify
sudo systemctl stop raspotify || true

# Install as a user service so librespot and PipeWire share the same session.
mkdir -p "$HOME/.config/systemd/user/"
cat > "$HOME/.config/systemd/user/raspotify.service" << 'UNIT'
[Unit]
Description=Raspotify (Spotify Connect Client)
After=pipewire.service pipewire-pulse.service wireplumber.service
Wants=pipewire.service pipewire-pulse.service

[Service]
# --system-cache keeps the Zeroconf login across restarts, so "Spotifactory" only
# has to be picked in the Spotify app once. Audio caching is off to spare the SD card.
ExecStart=/usr/bin/librespot --backend pulseaudio --name Spotifactory --bitrate 160 --system-cache %h/.cache/librespot --disable-audio-cache
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable raspotify
systemctl --user start raspotify || true

# ------------------------------------------------------------------------ .env
# Start from the example, then fill in this owner's values from a provisioning
# file kept out of git, so nothing needs typing by hand. Done before the Python
# install, which reads the platform from .env.
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/deploy/env.example" "$REPO_DIR/.env"
fi
USER_HOME="$(getent passwd "$USER" | cut -d: -f6)"
for PROVISION in "$REPO_DIR/deploy/provision.env" "$USER_HOME/spotifactory-provision.env"; do
  if [ -f "$PROVISION" ]; then
    echo "==> Filling .env from $PROVISION"
    python3 "$REPO_DIR/deploy/apply_env.py" "$PROVISION" "$REPO_DIR/.env"
  fi
done
chmod 600 "$REPO_DIR/.env"

# ---------------------------------------------------- Python virtual environment
echo "==> Setting up Python environment..."
cd "$REPO_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
# Load .env to check SPOTIFACTORY_PLATFORM if already present
PLATFORM="seengreat"
if [ -f "$REPO_DIR/.env" ]; then
  PLATFORM=$(grep -oP '(?<=SPOTIFACTORY_PLATFORM=)\S+' "$REPO_DIR/.env" || echo "seengreat")
fi
echo "  Platform: $PLATFORM"
.venv/bin/pip install -e ".[$PLATFORM]" -q

# ----------------------------------------------------------------- .env check
if grep -qE '^SPOTIPY_CLIENT_ID=(your_client_id_here)?$' "$REPO_DIR/.env"; then
  echo ""
  echo "  *** ACTION REQUIRED ***"
  echo "  No Spotify client ID. Put it in deploy/provision.env (see"
  echo "  deploy/provision.env.example) and rerun, or edit .env by hand:"
  echo "    nano $REPO_DIR/.env"
  echo ""
fi

# ------------------------------------------------- services and the sudo rule
# The app's service, the nightly updater and its timer, and passwordless sudo
# for what the app and deploys need. The same script runs after every
# auto-update, so boxes in the field pick up changes to these too.
echo "==> Installing services and the sudo rule..."
sudo bash "$REPO_DIR/deploy/upgrade.sh" "$USER"

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Set SPOTIPY_CLIENT_ID in .env: nano $REPO_DIR/.env"
echo "     (Leave SPOTIPY_CLIENT_SECRET unset — the Pi logs in via the relay with PKCE.)"
echo "  2. Reboot: sudo reboot"
echo "     On boot the device will guide the recipient through WiFi + Spotify setup."
echo "  3. Open the Spotify app → Devices → select 'Spotifactory' once to complete"
echo "     Raspotify Zeroconf auth. After that, RFID tags play directly on the Pi."
echo "  4. From the main menu → 'Pair Device' to connect a Bluetooth speaker"
echo "     (put it in pairing mode first), then the Instax printer."
echo ""
echo "To run by hand over SSH, stop the service first so they don't fight over"
echo "the RFID reader and buttons: sudo systemctl stop spotifactory"
echo "Updates install themselves each night from the stable branch (or from"
echo "the menu: Check for Updates). To update now over SSH:"
echo "  sudo systemctl start spotifactory-update && journalctl -u spotifactory-update -n 20"
