#!/usr/bin/env bash
# Spotifactory — one-time Pi setup script
# Run over SSH on a fresh Raspberry Pi OS Lite 64-bit image:
#   ssh spotifactory@spotifactory.local
#   cd ~/spotifactory && bash deploy/setup.sh
set -uo pipefail

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

# ----------------------------------------------------------- PipeWire
echo "==> Configuring PipeWire audio for user $USER..."
USER_ID=$(id -u "$USER")
# Enable linger so user services start at boot without a login session
sudo loginctl enable-linger "$USER"
# Ensure the runtime dir exists so systemctl --user works from this script
sudo mkdir -p "/run/user/$USER_ID"
sudo chown "$USER:$USER" "/run/user/$USER_ID"
sudo chmod 700 "/run/user/$USER_ID"
sudo -u "$USER" \
  XDG_RUNTIME_DIR="/run/user/$USER_ID" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" \
  systemctl --user enable pipewire pipewire-pulse wireplumber || true

# ----------------------------------------------------------- Raspotify
echo "==> Installing Raspotify (Spotify Connect receiver)..."
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
sudo cp "$REPO_DIR/deploy/raspotify.conf" /etc/default/raspotify

# Run Raspotify as the spotifactory user so it shares the PipeWire session
sudo mkdir -p /etc/systemd/system/raspotify.service.d
printf "[Service]\nUser=%s\nGroup=%s\nEnvironment=XDG_RUNTIME_DIR=/run/user/%s\n" \
  "$USER" "$USER" "$USER_ID" \
  | sudo tee /etc/systemd/system/raspotify.service.d/user.conf > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable raspotify
sudo systemctl restart raspotify || true

# Passwordless sudo for "Pair Speaker" menu — restart raspotify
echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl restart raspotify" \
  | sudo tee /etc/sudoers.d/spotifactory-audio > /dev/null

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
echo "  4. Open the Spotify app → Devices → select 'Spotifactory' once to complete"
echo "     Raspotify Zeroconf auth. After that, RFID tags play directly on the Pi."
echo "  5. From the main menu → 'Pair Speaker' to connect a Bluetooth speaker."
echo "     Audio will route through it automatically on the next tag scan."
