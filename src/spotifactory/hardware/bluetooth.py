from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import time

_ANSI = re.compile(r"\x1b\[[0-9;]*[mKABCDHJ]|\r")
_HEX_NAME = re.compile(r"^[0-9A-Fa-f:_\-]+$")

# Instax Square Link BLE address prefix (IOS personality)
_INSTAX_IOS_PREFIX = "FA:AB:BC:"
# Corresponding Classic BT address prefix (Android/RFCOMM personality)
_INSTAX_ANDROID_PREFIX = "88:B4:36:"


def is_instax(device: dict) -> bool:
    """Return True if device is an Instax printer (name starts with INSTAX-)."""
    return device.get("name", "").upper().startswith("INSTAX-")


def instax_classic_addr(ios_mac: str) -> str:
    """Derive the Classic BT (RFCOMM) address from the BLE IOS address.

    Fujifilm firmware convention: FA:AB:BC:xx:xx:xx → 88:B4:36:xx:xx:xx.
    The last three octets are the same across both personalities.
    """
    suffix = ios_mac.upper()[len(_INSTAX_IOS_PREFIX):]
    return _INSTAX_ANDROID_PREFIX + suffix


def _is_real_name(name: str, mac: str) -> bool:
    """Return True only for human-readable device names."""
    if not name or len(name) < 3:
        return False
    if name.upper() == mac:
        return False
    if name.startswith("(") and name.endswith(")"):  # BlueZ placeholders: (unknown), (random), etc.
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
    non_connectable: set[str] = set()  # beacons: Connectable: no
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
                # [NEW] = first time seen; [CHG] = already known, actively advertising
                m = re.search(r"\[(?:NEW|CHG)\] Device ([0-9A-Fa-f:]{17})", line)
                if m:
                    mac = m.group(1).upper()
                    if mac not in found:
                        found[mac] = ""
                # [NEW] carries the name inline; [CHG] must say "Name:" or "Alias:" explicitly.
                # Accepting any [CHG] payload captures RSSI/TxPower/etc as fake names.
                m = re.search(r"\[NEW\] Device ([0-9A-Fa-f:]{17}) (.+)", line)
                if not m:
                    m = re.search(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) (?:Name|Alias): (.+)", line)
                if m:
                    mac = m.group(1).upper()
                    name = m.group(2).strip()
                    if name:
                        found[mac] = name
                # Beacons advertise Connectable: no — exclude them regardless of name.
                # Classic BT devices (speakers etc.) don't emit this property at all,
                # so we only exclude on an explicit no rather than requiring yes.
                m = re.search(r"\[CHG\] Device ([0-9A-Fa-f:]{17}) Connectable: no", line)
                if m:
                    non_connectable.add(m.group(1).upper())

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

    # For MACs with no resolved name yet, query bluetoothctl info
    for mac in list(found):
        if not _is_real_name(found[mac], mac):
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                m = re.search(r"Name: (.+)", line)
                if m:
                    candidate = m.group(1).strip()
                    if _is_real_name(candidate, mac):
                        found[mac] = candidate
                    break

    return [
        {"mac": mac, "name": name}
        for mac, name in found.items()
        if _is_real_name(name, mac) and mac not in non_connectable
    ]


def pair_and_configure(mac: str) -> None:
    """Pair, trust, and connect to a Bluetooth device.

    Scan must remain active during pairing so BlueZ can reach the device.
    Auto-confirms passkey prompts (numeric comparison pairing).
    """
    pair_out = _pair_interactive(mac)
    print(f"[bluetooth] pair output:\n{pair_out}", flush=True)
    if "Failed to pair" in pair_out or "not available" in pair_out.lower():
        raise RuntimeError("Keep speaker in pairing mode and try again")

    conn_out = _pty_session([f"trust {mac}", f"connect {mac}"], read_duration=10.0)
    print(f"[bluetooth] connect output:\n{conn_out}", flush=True)
    if "Failed to connect" in conn_out:
        raise RuntimeError("Paired but could not connect — try again")


def _pair_interactive(mac: str, timeout: float = 25.0) -> str:
    """Run pairing in a PTY session, auto-responding yes to passkey prompts."""
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    output_parts: list[str] = []
    buf = ""
    deadline = time.monotonic() + timeout

    try:
        for cmd in ["power on", "agent NoInputNoOutput", "default-agent",
                    "scan on", f"pair {mac}"]:
            os.write(master_fd, (cmd + "\n").encode())
            time.sleep(0.1)

        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([master_fd], [], [], min(remaining, 0.3))
            except (ValueError, OSError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
            except OSError:
                break
            cleaned = _ANSI.sub("", chunk)
            output_parts.append(cleaned)
            buf += cleaned

            # Auto-confirm numeric comparison passkey
            if "(yes/no):" in buf:
                os.write(master_fd, b"yes\n")
                buf = ""

            # Pairing finished (success or failure)
            if "Pairing successful" in buf or "Failed to pair" in buf:
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


def set_bt_audio_output(mac: str) -> None:
    """Set the paired BT speaker as the default PipeWire audio output.

    PipeWire names BT sinks as bluez_output.AA_BB_CC_DD_EE_FF.1.
    Uses pactl (PulseAudio compat layer) to set the default sink so
    Raspotify's ALSA output routes to the speaker automatically.
    """
    sink = "bluez_output." + mac.replace(":", "_") + ".1"
    result = subprocess.run(
        ["pactl", "set-default-sink", sink],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        print(f"[bluetooth] pactl set-default-sink: {result.stderr.strip()}", flush=True)
