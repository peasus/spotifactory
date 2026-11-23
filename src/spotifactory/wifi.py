"""WiFi through NetworkManager (nmcli): the setup hotspot, scanning, joining.

Replaces Balena WiFi Connect, which ran as a separate root process, blocked
the app (so no button worked), and gave up silently: after taking its hotspot
down it rescanned once, and if the chosen network wasn't in that scan it just
brought the hotspot back. Here every step is retried, says what went wrong, and
runs inside the app.

The app runs as a normal user. deploy/upgrade.sh installs a polkit rule that
lets that user drive NetworkManager, and a dnsmasq snippet that points every
DNS name at the hotspot, so phones open the setup page by themselves.
"""
from __future__ import annotations

import re
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass

AP_CONNECTION = "spotifactory-setup"     # our hotspot's NetworkManager profile
AP_SSID = "Spotifactory"
AP_ADDRESS = "10.42.0.1"                 # also in deploy/nm-captive-dns.conf
IFACE = "wlan0"
_OUR_PROFILE_PREFIX = "spotifactory-wifi-"


@dataclass
class Network:
    ssid: str
    security: str      # "none", "wep", "wpa", "wpa3" or "enterprise"
    signal: int


class JoinError(Exception):
    """Joining failed; str() is a short reason for the screen and the page."""


# ---------------------------------------------------------------- connectivity

# Several places, so a network that blocks one (8.8.8.8 DNS is often blocked
# by routers with their own DNS) still counts as online. Name lookups go
# through the router's DNS, which is what the app needs anyway.
_PROBES = [("api.spotify.com", 443), ("1.1.1.1", 443), ("8.8.8.8", 53)]


def has_internet(timeout: float = 3.0) -> bool:
    for host, port in _PROBES:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def wait_for_internet(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if has_internet():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2.0)


# --------------------------------------------------------------------- nmcli

def _nmcli(*args: str, timeout: float = 60.0, check: bool = True) -> str:
    r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.stdout


def _split_terse(line: str) -> list[str]:
    """Split a `nmcli -t` line on unescaped colons, unescaping \\: and \\\\."""
    fields, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields


def _security(flags: str) -> str:
    f = flags.upper()
    if "802.1X" in f:
        return "enterprise"
    if "WPA3" in f and "WPA2" not in f and "WPA1" not in f:
        return "wpa3"
    if "WPA" in f:
        return "wpa"
    if "WEP" in f:
        return "wep"
    return "none"


def parse_scan(output: str) -> list[Network]:
    """`nmcli -t -f SSID,SECURITY,SIGNAL dev wifi list` → one entry per SSID
    (the strongest), strongest first, hidden networks and our own left out."""
    best: dict[str, Network] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        ssid, flags, signal = parts[0], parts[1], parts[2]
        if not ssid or ssid == AP_SSID:
            continue
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        net = Network(ssid, _security(flags), strength)
        if ssid not in best or strength > best[ssid].signal:
            best[ssid] = net
    return sorted(best.values(), key=lambda n: -n.signal)


def scan(rescan: bool = True) -> list[Network]:
    try:
        out = _nmcli("-t", "-f", "SSID,SECURITY,SIGNAL", "dev", "wifi", "list",
                     "ifname", IFACE, "--rescan", "yes" if rescan else "no", timeout=30)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[wifi] scan failed: {e}", flush=True)
        return []
    return parse_scan(out)


def scan_until_found(ssid: str, tries: int = 4) -> Network | None:
    """Right after the hotspot goes down the radio's scan list is often empty
    or partial (WiFi Connect's silent failure): rescan a few times."""
    for attempt in range(tries):
        for net in scan(rescan=True):
            if net.ssid == ssid:
                return net
        print(f"[wifi] {ssid!r} not in scan {attempt + 1}/{tries}", flush=True)
        time.sleep(3.0)
    return None


def _profiles() -> list[tuple[str, str]]:
    """(name, type) of every saved NetworkManager profile."""
    try:
        out = _nmcli("-t", "-f", "NAME,TYPE", "con", "show", timeout=15)
    except (subprocess.SubprocessError, OSError):
        return []
    rows = [_split_terse(l) for l in out.splitlines() if l.strip()]
    return [(r[0], r[1]) for r in rows if len(r) >= 2]


def _profile_ssid(name: str) -> str:
    try:
        return _nmcli("-g", "802-11-wireless.ssid", "con", "show", name, timeout=15).strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def saved_wifi() -> list[str]:
    """Names of saved WiFi profiles, other than our hotspot."""
    return [n for n, t in _profiles()
            if t in ("802-11-wireless", "wifi") and n != AP_CONNECTION]


def _delete(name: str) -> None:
    _nmcli("con", "delete", name, check=False, timeout=20)


# ------------------------------------------------------------------- hotspot

def start_hotspot() -> None:
    """An open network called Spotifactory, with DHCP and DNS from NetworkManager."""
    _delete(AP_CONNECTION)
    _nmcli("con", "add", "type", "wifi", "ifname", IFACE, "con-name", AP_CONNECTION,
           "autoconnect", "no", "ssid", AP_SSID,
           "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
           "ipv4.method", "shared", "ipv4.addresses", f"{AP_ADDRESS}/24",
           "ipv6.method", "disabled", timeout=20)
    _nmcli("--wait", "30", "con", "up", AP_CONNECTION, timeout=40)
    print(f"[wifi] hotspot {AP_SSID!r} up on {AP_ADDRESS}", flush=True)


def stop_hotspot() -> None:
    _nmcli("--wait", "15", "con", "down", AP_CONNECTION, check=False, timeout=25)
    _delete(AP_CONNECTION)


# ---------------------------------------------------------------------- join

def _reason(stderr: str) -> str:
    s = stderr.lower()
    if "secrets were required" in s or "802-1x supplicant" in s:
        return "Wrong password?"
    if "no network with ssid" in s or "not found" in s:
        return "Network not found"
    if "timeout" in s or "timed out" in s:
        return "Timed out"
    return "Couldn't connect"


def join(ssid: str, passphrase: str = "", identity: str = "",
         security: str | None = None) -> None:
    """Join `ssid` and wait for the internet. Raises JoinError with a reason.

    Makes a new profile and only removes older ones for the same network once
    the new one works, so a mistyped password never loses one that worked.
    """
    if security is None:
        found = scan_until_found(ssid)
        if found is None:
            raise JoinError("Network not found")
        security = found.security

    name = _OUR_PROFILE_PREFIX + uuid.uuid4().hex[:6]
    args = ["con", "add", "type", "wifi", "ifname", IFACE, "con-name", name, "ssid", ssid]
    if security == "enterprise":
        args += ["wifi-sec.key-mgmt", "wpa-eap", "802-1x.eap", "peap",
                 "802-1x.phase2-auth", "mschapv2",
                 "802-1x.identity", identity, "802-1x.password", passphrase]
    elif security == "wpa3":
        args += ["wifi-sec.key-mgmt", "sae", "wifi-sec.psk", passphrase]
    elif security == "wpa":
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", passphrase]
    elif security == "wep":
        args += ["wifi-sec.key-mgmt", "none", "wifi-sec.wep-key0", passphrase]
    try:
        _nmcli(*args, timeout=20)
    except subprocess.CalledProcessError as e:
        print(f"[wifi] couldn't save {ssid!r}: {e.stderr.strip()}", flush=True)
        raise JoinError("Bad password format" if "psk" in (e.stderr or "").lower()
                        else "Couldn't connect") from e

    r = subprocess.run(["nmcli", "--wait", "45", "con", "up", name],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"[wifi] joining {ssid!r} failed: {r.stderr.strip()}", flush=True)
        _delete(name)
        raise JoinError(_reason(r.stderr))

    if not wait_for_internet(30):
        print(f"[wifi] joined {ssid!r} but no internet", flush=True)
        _nmcli("con", "down", name, check=False, timeout=20)
        _delete(name)
        raise JoinError("No internet")

    for other in saved_wifi():
        if other != name and _profile_ssid(other) == ssid:
            _delete(other)
    print(f"[wifi] joined {ssid!r}", flush=True)


def try_saved_networks(seconds: float = 30.0) -> bool:
    """With the hotspot down, give NetworkManager a chance to rejoin a saved
    network (the router may just have been slow to come back)."""
    if not saved_wifi():
        return False
    _nmcli("dev", "wifi", "rescan", "ifname", IFACE, check=False, timeout=20)
    _nmcli("dev", "connect", IFACE, check=False, timeout=40)
    return wait_for_internet(seconds)


def wifi_qr_payload() -> str:
    """What a phone camera reads to join the open setup network."""
    escaped = re.sub(r'([\\;,:"])', r"\\\1", AP_SSID)
    return f"WIFI:T:nopass;S:{escaped};;"
