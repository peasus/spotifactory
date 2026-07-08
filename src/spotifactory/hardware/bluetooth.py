from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import time

_ANSI = re.compile(r"\x1b\[[0-9;]*[mKABCDHJ]|\r")
_HEX_NAME = re.compile(r"^[0-9A-Fa-f:_\-]+$")


def _is_real_name(name: str, mac: str) -> bool:
    """Return True only for human-readable device names."""
    if not name or len(name) < 3:
        return False
    if name.upper() == mac:
        return False
    if _HEX_NAME.match(name):  # anonymous BLE devices broadcast hex strings as names
        return False
    return True


def _pty_session(commands: list[str], read_duration: float = 0.0) -> str:
    """Run bluetoothctl in a PTY, send commands, collect output.

    Using a PTY makes bluetoothctl flush output line-by-line (as it would on a
    real terminal) instead of block-buffering into the pipe.
    """
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    output_parts: list[str] = []
    deadline = time.monotonic() + read_duration + len(commands) * 0.1

    try:
        for cmd in commands:
            os.write(master_fd, (cmd + "\n").encode())
            time.sleep(0.1)

        if read_duration > 0:
            deadline = time.monotonic() + read_duration
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                try:
                    ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.5))
                except (ValueError, OSError):
                    break
                if not ready:
                    continue
                try:
                    chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                    output_parts.append(_ANSI.sub("", chunk))
                except OSError:
                    break

        os.write(master_fd, b"quit\n")
        time.sleep(0.2)
    except OSError:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        try:
            os.close(master_fd)
        except OSError:
            pass

    return "".join(output_parts)


def scan_devices(timeout: int = 10) -> list[dict]:
    """Scan for nearby Bluetooth devices actively advertising right now."""
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    found: dict[str, str] = {}
    buf = ""
    deadline = time.monotonic() + timeout

    try:
        os.write(master_fd, b"power on\n")
        time.sleep(0.3)
        os.write(master_fd, b"scan on\n")

        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.5))
            except (ValueError, OSError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
            except OSError:
                break
            buf += _ANSI.sub("", chunk)
            *lines, buf = buf.split("\n")
            for line in lines:
                # Initial discovery — name may still be the MAC address
                m = re.search(r"\[NEW\] Device ([0-9A-Fa-f:]{17})(?: (.+))?", line)
                if m:
                    mac = m.group(1).upper()
                    if mac not in found:
                        found[mac] = (m.group(2) or "").strip()
                # Name resolved asynchronously after initial discovery
                m = re.search(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) Name: (.+)", line)
                if m:
                    mac = m.group(1).upper()
                    found[mac] = m.group(2).strip()

        os.write(master_fd, b"scan off\n")
        time.sleep(0.2)
        os.write(master_fd, b"quit\n")
        time.sleep(0.2)
    except OSError:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        try:
            os.close(master_fd)
        except OSError:
            pass

    return [
        {"mac": mac, "name": name}
        for mac, name in found.items()
        if _is_real_name(name, mac)
    ]


def pair_and_configure(mac: str) -> None:
    """Pair, trust, and connect to a Bluetooth device."""
    output = _pty_session(
        ["power on", "agent NoInputNoOutput", "default-agent",
         f"pair {mac}", f"trust {mac}", f"connect {mac}"],
        read_duration=20.0,
    )
    if "Failed to connect" in output or "not available" in output.lower():
        raise RuntimeError(f"Bluetooth pairing failed:\n{output.strip()}")


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
        _pty_session([f"connect {mac}"], read_duration=8.0)
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
