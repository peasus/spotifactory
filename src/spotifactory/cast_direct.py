"""Google Cast speakers and groups, found and played by the box itself.

Spotify only lists a Cast speaker while one of its own apps is casting to it,
so the box plays the music itself (Raspotify, as for its Bluetooth speaker)
and casts that audio:

    librespot -> PipeWire pipe sink -> OwnTone (owntone.py)
              -> http://<box>:3689/stream.mp3 <- Cast speaker or group
                 (Google's standard media player, started with pychromecast)

Speakers are found with a "legacy unicast" mDNS query: one sent from an
ordinary port, which speakers answer straight back to the sender (RFC 6762
section 6.7). Ordinary mDNS waits for multicast answers, and some networks
never deliver those to the Pi (a friend's Google Wifi: the 2.4 GHz-only Pi
Zero 2 W heard nothing, yet the same speakers answered a direct query).
Nothing is announced on the network.
"""
from __future__ import annotations

import socket
import struct
import time
import uuid as uuidlib

MDNS_ADDR = ("224.0.0.251", 5353)
CAST_SERVICE = "_googlecast._tcp.local"
ID_PREFIX = "cast:"
STREAM_PORT = 3689              # OwnTone's HTTP port (deploy/owntone.conf)
STREAM_PATH = "/stream.mp3"

_PTR, _TXT, _SRV, _A = 12, 16, 33, 1


# --- A small DNS reader (only what mDNS answers need) ------------------------

def _query(name: str) -> bytes:
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"
    return header + qname + struct.pack(">HH", _PTR, 1)


def _read_name(data: bytes, pos: int) -> tuple[str, int]:
    labels, jumped, end = [], False, pos
    for _ in range(64):                      # guard against pointer loops
        length = data[pos]
        if length & 0xC0 == 0xC0:
            if not jumped:
                end = pos + 2
            pos = ((length & 0x3F) << 8) | data[pos + 1]
            jumped = True
            continue
        if length == 0:
            if not jumped:
                end = pos + 1
            break
        labels.append(data[pos + 1:pos + 1 + length].decode("utf-8", "replace"))
        pos += 1 + length
    return ".".join(labels), end


def _records(data: bytes) -> list[tuple[str, int, bytes, int]]:
    """(name, type, rdata, rdata offset) for every record in an mDNS message."""
    _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    pos = 12
    for _ in range(qd):
        _, pos = _read_name(data, pos)
        pos += 4
    out = []
    for _ in range(an + ns + ar):
        name, pos = _read_name(data, pos)
        rtype, _, _, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        out.append((name.lower(), rtype, data[pos:pos + rdlen], pos))
        pos += rdlen
    return out


def _txt(rdata: bytes) -> dict[str, str]:
    out, pos = {}, 0
    while pos < len(rdata):
        length = rdata[pos]
        item = rdata[pos + 1:pos + 1 + length].decode("utf-8", "replace")
        pos += 1 + length
        key, _, value = item.partition("=")
        out[key] = value
    return out


def parse_answer(data: bytes, sender_ip: str) -> list[dict]:
    """Cast speakers described in one mDNS answer."""
    try:
        records = _records(data)
    except (IndexError, struct.error):
        return []
    instances, srv, txt, addrs = [], {}, {}, {}
    for name, rtype, rdata, offset in records:
        if rtype == _PTR and name == CAST_SERVICE:
            instances.append(_read_name(data, offset)[0].lower())
        elif rtype == _SRV and len(rdata) >= 6:
            port = struct.unpack(">H", rdata[4:6])[0]
            srv[name] = (_read_name(data, offset + 6)[0].lower(), port)
        elif rtype == _TXT:
            txt[name] = _txt(rdata)
        elif rtype == _A and len(rdata) == 4:
            addrs[name] = socket.inet_ntoa(rdata)
    found = []
    for inst in instances:
        info = txt.get(inst, {})
        target, port = srv.get(inst, ("", 8009))
        if not info.get("id"):
            continue
        found.append({
            "uuid": info["id"],
            "name": info.get("fn") or inst.split(".")[0],
            "model": info.get("md") or "",
            "host": addrs.get(target) or sender_ip,
            "port": port,
        })
    return found


def discover(timeout: float = 3.0) -> list[dict]:
    """Cast speakers and groups that answer a direct query, each once."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.settimeout(0.5)
        sock.sendto(_query(CAST_SERVICE), MDNS_ADDR)
        found: dict[str, dict] = {}
        resent = False
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not resent and time.monotonic() > end - timeout / 2:
                sock.sendto(_query(CAST_SERVICE), MDNS_ADDR)   # UDP: ask twice
                resent = True
            try:
                data, (ip, _) = sock.recvfrom(9000)
            except socket.timeout:
                continue
            for dev in parse_answer(data, ip):
                found.setdefault(dev["uuid"], dev)
        return sorted(found.values(), key=lambda d: d["name"].lower())
    except OSError as e:
        print(f"[cast] direct discovery failed: {e}", flush=True)
        return []
    finally:
        sock.close()


def available() -> bool:
    """pychromecast is installed (pyproject) and OwnTone is answering."""
    import importlib.util

    from spotifactory import owntone
    return importlib.util.find_spec("pychromecast") is not None and owntone.available()


def speakers(chosen_id: str | None = None) -> list[dict]:
    """Choose Speaker rows (Spotify's device shape) for the Cast speakers found."""
    chosen_uuid = parse_id(chosen_id)[2] if chosen_id and chosen_id.startswith(ID_PREFIX) else None
    rows = []
    for dev in discover():
        rows.append({
            "id": f"{ID_PREFIX}{dev['host']}:{dev['port']}:{dev['uuid']}",
            "name": dev["name"],
            "type": "Cast",
            "is_active": dev["uuid"] == chosen_uuid,
            "is_restricted": False,
        })
    return rows


def parse_id(device_id: str) -> tuple[str, int, str]:
    host, port, uuid = device_id[len(ID_PREFIX):].split(":", 2)
    return host, int(port), uuid


# --- The stream ----------------------------------------------------------------
# OwnTone serves whatever it's playing as MP3 at /stream.mp3, with no speaker
# of its own selected; the box's audio reaches it through its pipe.

def _box_ip(towards: str) -> str:
    """This box's address on the speaker's network."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((towards, 9))          # no packet is sent for UDP connect
        return probe.getsockname()[0]
    finally:
        probe.close()


def stream_url(host: str) -> str:
    return f"http://{_box_ip(host)}:{STREAM_PORT}{STREAM_PATH}"


# --- Casting -------------------------------------------------------------------

def _connect(host: str, port: int, uuid: str, name: str = ""):
    import pychromecast
    cc = pychromecast.get_chromecast_from_host(
        (host, port, uuidlib.UUID(uuid), None, name or None), tries=2, timeout=10)
    cc.wait(timeout=10)
    return cc


def _resolve(device_id: str, name: str) -> tuple[str, int, str]:
    """The speaker's address now: a group's leader, and so its address and
    port, can move, so it's looked up again by its id when it can be."""
    host, port, uuid = parse_id(device_id)
    for dev in discover(timeout=2.0):
        if dev["uuid"] == uuid:
            return dev["host"], dev["port"], uuid
    return host, port, uuid


def play(device_id: str, name: str = "") -> None:
    """Have the Cast speaker or group play the box's stream (if it isn't
    already), then start OwnTone's player, which waits for a listener."""
    from spotifactory import owntone
    if not owntone.route_audio():
        raise RuntimeError("couldn't route audio to OwnTone")
    owntone.deselect_all()                 # OwnTone's own speakers stay quiet
    host, port, uuid = _resolve(device_id, name)
    cc = _connect(host, port, uuid, name)
    try:
        url = stream_url(host)
        mc = cc.media_controller
        status = mc.status
        if not (status and status.content_id == url
                and status.player_state in ("PLAYING", "BUFFERING")):
            print(f"[cast] {name or host}: playing {url}", flush=True)
            mc.play_media(url, "audio/mpeg", stream_type="LIVE", title="Spotifactory")
            mc.block_until_active(timeout=10)
    finally:
        cc.disconnect(timeout=5)
    owntone.play()


def stop(device_id: str) -> None:
    """Close the media player on the speaker."""
    try:
        host, port, uuid = parse_id(device_id)
        cc = _connect(host, port, uuid)
    except Exception as e:
        print(f"[cast] stop: {e}", flush=True)
        return
    try:
        cc.quit_app()
    except Exception as e:
        print(f"[cast] stop: {e}", flush=True)
    finally:
        cc.disconnect(timeout=5)
