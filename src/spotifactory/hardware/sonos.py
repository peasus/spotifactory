from __future__ import annotations

import soco
import soco.discovery

# Cache discovered speakers by name so discovery only runs once per session.
_speaker_cache: dict[str, soco.SoCo] = {}


def _get_speaker(name: str) -> soco.SoCo:
    if name in _speaker_cache:
        return _speaker_cache[name]
    print(f"[sonos] discovering {name!r}…", flush=True)
    speaker = soco.discovery.by_name(name)
    if speaker is None:
        raise RuntimeError(f"Sonos speaker {name!r} not found on network")
    _speaker_cache[name] = speaker
    print(f"[sonos] found {name!r} at {speaker.ip_address}", flush=True)
    return speaker


def pause_speaker(speaker_name: str) -> None:
    """Pause playback on a Sonos speaker via SoCo UPnP.

    Works on active Spotify Connect sessions (Sonos S2 and S1). Starting
    playback goes through spotifactory/connect.py when its helper is
    installed — see docs/sonos.md.
    """
    speaker = _get_speaker(speaker_name)
    coordinator = speaker.group.coordinator if speaker.group else speaker
    coordinator.pause()
    print(f"[sonos] paused {speaker_name!r} via SoCo", flush=True)


# Sonos speakers answer Spotify's ZeroConf "getInfo" on this port and path.
_SPOTIFY_ZC = "http://{ip}:1400/spotifyzc?action=getInfo"


def _spotify_device_id(ip: str) -> str | None:
    """The speaker's Spotify Connect device id, from its ZeroConf endpoint."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(_SPOTIFY_ZC.format(ip=ip), timeout=2) as resp:
            return json.load(resp).get("deviceID") or None
    except Exception as e:
        print(f"[sonos] no Spotify info from {ip}: {e}", flush=True)
        return None


def connect_speakers(timeout: float = 3.0) -> list[dict]:
    """Sonos rooms on the network, as Spotify device rows.

    Spotify leaves idle Sonos speakers out of its device list and won't let
    the Web API control them, so they're found here and played through the
    Connect route instead (see spotifactory/connect.py).
    """
    found = soco.discovery.discover(timeout=timeout) or set()
    rows: dict[str, dict] = {}
    for zone in sorted(found, key=lambda z: z.player_name):
        device_id = _spotify_device_id(zone.ip_address)
        if device_id and device_id not in rows:
            _speaker_cache[zone.player_name] = zone
            rows[device_id] = {"id": device_id, "name": zone.player_name, "type": "Speaker",
                               "is_active": False, "is_restricted": True}
    return list(rows.values())


def get_volume(speaker_name: str) -> int:
    """The room's volume (0-100), read over the local network."""
    speaker = _get_speaker(speaker_name)
    return int(speaker.group.volume if speaker.group else speaker.volume)


def set_volume(speaker_name: str, percent: int) -> None:
    speaker = _get_speaker(speaker_name)
    percent = max(0, min(100, int(percent)))
    if speaker.group:
        speaker.group.volume = percent
    else:
        speaker.volume = percent
