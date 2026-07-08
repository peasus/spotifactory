from __future__ import annotations

import re
import subprocess
import time


def scan_devices(timeout: int = 10) -> list[dict]:
    """Scan for nearby Bluetooth devices. Returns [{mac, name}]."""
    result = subprocess.run(
        ["bluetoothctl", "--timeout", str(timeout), "scan", "on"],
        capture_output=True, text=True, timeout=timeout + 5,
    )
    output = result.stdout + result.stderr
    found: dict[str, str] = {}
    for line in output.splitlines():
        m = re.search(r"\[NEW\] Device ([0-9A-F:]{17}) (.+)", line)
        if m:
            mac, name = m.group(1), m.group(2).strip()
            # Skip unnamed or obviously internal entries
            if name and name != mac:
                found[mac] = name
    return [{"mac": mac, "name": name} for mac, name in found.items()]


def pair_and_configure(mac: str) -> None:
    """Pair, trust, and connect to a Bluetooth device."""
    def _bt(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True, text=True, timeout=15,
        )

    _bt("power", "on")
    _bt("agent", "NoInputNoOutput")
    _bt("default-agent")
    _bt("pair", mac)
    time.sleep(2)
    _bt("trust", mac)
    result = _bt("connect", mac)
    if result.returncode != 0 and "Failed" in result.stdout:
        raise RuntimeError(f"bluetoothctl connect failed: {result.stdout.strip()}")


def is_connected(mac: str) -> bool:
    """Return True if the Bluetooth device is currently connected."""
    result = subprocess.run(
        ["bluetoothctl", "info", mac],
        capture_output=True, text=True, timeout=5,
    )
    return "Connected: yes" in result.stdout


def reconnect(mac: str) -> None:
    """Attempt to connect to an already-trusted Bluetooth device. Does not raise."""
    try:
        subprocess.run(
            ["bluetoothctl", "connect", mac],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def write_asoundrc(mac: str) -> None:
    """Write /etc/asound.conf to route ALSA default to the BT speaker via BlueAlsa.

    Written system-wide (not ~/.asoundrc) so Raspotify's system service can read it.
    Requires passwordless sudo for /usr/bin/tee /etc/asound.conf (set up by setup.sh).
    """
    conf = f"""defaults.bluealsa.interface "hci0"
defaults.bluealsa.device "{mac}"
defaults.bluealsa.profile "a2dp"

pcm.!default {{
    type plug
    slave.pcm {{
        type bluealsa
        interface "hci0"
        device "{mac}"
        profile "a2dp"
    }}
}}

ctl.!default {{
    type bluealsa
}}
"""
    subprocess.run(
        ["sudo", "tee", "/etc/asound.conf"],
        input=conf, capture_output=True, text=True, check=True,
    )
