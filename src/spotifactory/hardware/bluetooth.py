from __future__ import annotations

import re
import subprocess
import time


def _bt(args: list[str], input: str | None = None, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bluetoothctl", *args],
        input=input, capture_output=True, text=True, timeout=timeout,
    )


def scan_devices(timeout: int = 10) -> list[dict]:
    """Scan for nearby Bluetooth devices actively advertising right now.

    Captures [NEW] Device lines from the live scan output rather than querying
    `bluetoothctl devices`, which returns all previously-known devices regardless
    of whether they are currently present.
    """
    _bt(["power", "on"])

    scan_proc = subprocess.Popen(
        ["bluetoothctl", "scan", "on"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )

    found: dict[str, str] = {}
    deadline = time.monotonic() + timeout
    try:
        assert scan_proc.stdout is not None
        import select
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([scan_proc.stdout], [], [], min(remaining, 0.5))
            if ready:
                line = scan_proc.stdout.readline()
                if not line:
                    break
                m = re.search(r"\[NEW\] Device ([0-9A-F:]{17}) (.+)", line)
                if m:
                    mac, name = m.group(1), m.group(2).strip()
                    if name and name != mac:
                        found[mac] = name
    finally:
        scan_proc.terminate()
        try:
            scan_proc.wait(timeout=2)
        except Exception:
            scan_proc.kill()

    return [{"mac": mac, "name": name} for mac, name in found.items()]


def pair_and_configure(mac: str) -> None:
    """Pair, trust, and connect to a Bluetooth device."""
    _bt(["power", "on"])

    # Run all pairing commands in a single bluetoothctl session so the
    # agent registration and discovered device state are shared.
    commands = "\n".join([
        "agent NoInputNoOutput",
        "default-agent",
        f"pair {mac}",
        f"trust {mac}",
        f"connect {mac}",
        "quit",
    ]) + "\n"

    result = subprocess.run(
        ["bluetoothctl"],
        input=commands,
        capture_output=True, text=True, timeout=30,
    )

    output = result.stdout + result.stderr
    if "Failed to connect" in output or "not available" in output.lower():
        raise RuntimeError(f"Bluetooth pairing failed:\n{output.strip()}")


def is_connected(mac: str) -> bool:
    """Return True if the Bluetooth device is currently connected."""
    result = _bt(["info", mac])
    return "Connected: yes" in result.stdout


def reconnect(mac: str) -> None:
    """Attempt to connect to an already-trusted Bluetooth device. Does not raise."""
    try:
        _bt(["connect", mac], timeout=10)
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
