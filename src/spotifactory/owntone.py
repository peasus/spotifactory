"""AirPlay speakers (and Cast ones it finds), through OwnTone on the box.

The box plays the music itself (Raspotify) and OwnTone, an audio server on
the box, streams that audio on to the speaker:

    librespot -> PipeWire sink "spotifactory_network" -> named pipe
              -> OwnTone (pipe input, autostart) -> AirPlay speaker

OwnTone finds speakers with ordinary mDNS and lists them on its JSON API
(http://localhost:3689/api/outputs). Some networks never deliver mDNS
multicast to the Pi; Cast speakers are found and played without OwnTone
then (cast_direct.py). See network_speakers.py for choosing one.

Nothing changes on a box without OwnTone (deploy/upgrade.sh installs it).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from spotifactory import audio_route

_API_ENV = "SPOTIFACTORY_OWNTONE_URL"
_DEFAULT_API = "http://localhost:3689"
PIPE_ENV = "SPOTIFACTORY_OWNTONE_PIPE"
DEFAULT_PIPE = "/srv/music/spotifactory"     # in OwnTone's library (deploy/owntone.conf)
SINK = "spotifactory_network"

ID_PREFIX = "owntone:"
# OwnTone also lists its own local outputs (ALSA, PulseAudio, fifo); only
# speakers on the network belong in Choose Speaker. Types are matched by
# prefix: OwnTone says "AirPlay 2" for AirPlay 2 speakers.
_NETWORK_TYPES = (("airplay", "AirPlay"), ("chromecast", "Cast"))


def _kind(output_type) -> str | None:
    t = str(output_type or "").lower()
    return next((kind for prefix, kind in _NETWORK_TYPES if t.startswith(prefix)), None)
_TIMEOUT = 3.0


class OwnToneError(Exception):
    pass


def _api() -> str:
    return (os.environ.get(_API_ENV) or _DEFAULT_API).rstrip("/")


def _pipe() -> str:
    return os.environ.get(PIPE_ENV) or DEFAULT_PIPE


def _request(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_api() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise OwnToneError(f"{method} {path}: {e}") from e
    return json.loads(raw) if raw else None


def _outputs() -> list[dict]:
    return (_request("GET", "/api/outputs") or {}).get("outputs", [])


def speakers(chosen_id: str | None = None) -> list[dict]:
    """Network speakers OwnTone has found, as Choose Speaker rows (the same
    shape as Spotify's device list). [] without OwnTone."""
    try:
        outputs = _outputs()
    except OwnToneError as e:
        print(f"[owntone] no speaker list: {e}", flush=True)
        return []
    rows = []
    for out in outputs:
        kind = _kind(out.get("type"))
        if not kind:
            continue
        row_id = ID_PREFIX + str(out.get("id"))
        rows.append({
            "id": row_id,
            "name": out.get("name") or "Speaker",
            "type": kind,
            "is_active": row_id == chosen_id,
            "is_restricted": False,
            # AirPlay speakers that want a PIN or password (Apple TV,
            # HomePods with access limits): pairing isn't on the box yet.
            "needs_pairing": bool(out.get("needs_auth_key") or out.get("requires_auth")),
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def route_audio() -> bool:
    """Point the box's audio at OwnTone's pipe."""
    ok = audio_route.ensure_sink(SINK, "module-pipe-sink", f"file={_pipe()}",
                                 "format=s16le", "rate=44100", "channels=2",
                                 "sink_properties=device.description=Network_speaker")
    return ok and audio_route.route_to(SINK)


def select(device_id: str, wait_secs: float = 10.0) -> None:
    """Make the speaker OwnTone's only output. A speaker that has just woken
    up can take a few seconds to be listed again, so this retries."""
    output_id = device_id[len(ID_PREFIX):]
    if not route_audio():
        raise OwnToneError("couldn't route audio to OwnTone")
    deadline = time.monotonic() + wait_secs
    while True:
        try:
            if any(str(o.get("id")) == output_id for o in _outputs()):
                _request("PUT", "/api/outputs/set", {"outputs": [output_id]})
                return
            err: Exception = OwnToneError(f"speaker {output_id} not found")
        except OwnToneError as e:
            err = e
        if time.monotonic() >= deadline:
            raise err
        time.sleep(1.0)


def available() -> bool:
    try:
        _request("GET", "/api/config")
        return True
    except OwnToneError:
        return False


def deselect_all() -> None:
    _request("PUT", "/api/outputs/set", {"outputs": []})


def play() -> None:
    """Start the player. With no speaker of its own selected (a Cast speaker
    pulling /stream.mp3), OwnTone leaves the pipe paused until asked."""
    try:
        _request("PUT", "/api/player/play")
    except OwnToneError as e:
        print(f"[owntone] play: {e}", flush=True)


def stop() -> None:
    """Stop OwnTone and deselect its speakers."""
    for method, path, body in (("PUT", "/api/player/stop", None),
                               ("PUT", "/api/outputs/set", {"outputs": []})):
        try:
            _request(method, path, body)
        except OwnToneError as e:
            print(f"[owntone] {path}: {e}", flush=True)
