"""Google Cast and AirPlay speakers, through OwnTone running on the box.

Spotify only lists a Cast speaker while one of its own apps is casting to it,
and it has no AirPlay at all, so the box can't hand these speakers a Spotify
stream. Instead the box plays the music itself (Raspotify, as for the
Bluetooth speaker) and OwnTone, an audio server on the box, streams that audio
on to the speaker:

    librespot -> PipeWire sink "spotifactory_network" -> named pipe
              -> OwnTone (pipe input, autostart) -> Cast / AirPlay speaker

OwnTone finds the speakers itself (mDNS, Cast groups included) and lists
them on its JSON API (http://localhost:3689/api/outputs). Choosing one in
Choose Speaker selects it in OwnTone and points the box's audio at the pipe;
choosing any other speaker points it back. Spotify sees the box's own
"Spotifactory" device playing, so tags, buttons and volume work as they do
for the Bluetooth speaker.

Nothing changes on a box without OwnTone (deploy/upgrade.sh installs it).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

_API_ENV = "SPOTIFACTORY_OWNTONE_URL"
_DEFAULT_API = "http://localhost:3689"
PIPE_ENV = "SPOTIFACTORY_OWNTONE_PIPE"
DEFAULT_PIPE = "/srv/music/spotifactory"     # in OwnTone's library (deploy/owntone.conf)
SINK = "spotifactory_network"

# The network speaker chosen in Choose Speaker (settings.py keeps it in .env).
OUTPUT_ID_KEY = "SPOTIFACTORY_NETWORK_SPEAKER_ID"
OUTPUT_NAME_KEY = "SPOTIFACTORY_NETWORK_SPEAKER_NAME"

ID_PREFIX = "owntone:"
# OwnTone also lists its own local outputs (ALSA, PulseAudio, fifo); only
# speakers on the network belong in Choose Speaker.
_NETWORK_TYPES = {"airplay": "AirPlay", "chromecast": "Cast"}
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


def available() -> bool:
    """OwnTone is installed and answering on this box."""
    try:
        _request("GET", "/api/config")
        return True
    except OwnToneError:
        return False


def is_network_id(device_id: str | None) -> bool:
    return bool(device_id) and str(device_id).startswith(ID_PREFIX)


def chosen() -> tuple[str, str] | None:
    """(OwnTone output id, name) of the network speaker in use, or None."""
    output_id = os.environ.get(OUTPUT_ID_KEY, "").strip()
    if not output_id:
        return None
    return output_id, os.environ.get(OUTPUT_NAME_KEY, "").strip()


def _outputs() -> list[dict]:
    return (_request("GET", "/api/outputs") or {}).get("outputs", [])


def speakers() -> list[dict]:
    """Cast and AirPlay speakers OwnTone has found, as Choose Speaker rows
    (the same shape as Spotify's device list). [] without OwnTone."""
    try:
        outputs = _outputs()
    except OwnToneError as e:
        print(f"[owntone] no speaker list: {e}", flush=True)
        return []
    current = chosen()
    rows = []
    for out in outputs:
        kind = _NETWORK_TYPES.get(str(out.get("type", "")).lower())
        if not kind:
            continue
        rows.append({
            "id": ID_PREFIX + str(out.get("id")),
            "name": out.get("name") or "Speaker",
            "type": kind,
            "is_active": bool(current and current[0] == str(out.get("id"))),
            "is_restricted": False,
            # AirPlay speakers that want a PIN or password (Apple TV,
            # HomePods with access limits): pairing isn't on the box yet.
            "needs_pairing": bool(out.get("needs_auth_key") or out.get("requires_auth")),
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


# --- Audio routing (PipeWire, through its PulseAudio commands) --------------

def _pactl(*args: str) -> subprocess.CompletedProcess | None:
    if not sys.platform.startswith("linux"):
        print(f"[owntone] not on the Pi, skipping pactl {' '.join(args)}", flush=True)
        return None
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[owntone] pactl {' '.join(args)}: {e}", flush=True)
        return None


def _sinks() -> list[str]:
    result = _pactl("list", "short", "sinks")
    if result is None or result.returncode != 0:
        return []
    return [line.split()[1] for line in result.stdout.splitlines() if len(line.split()) > 1]


def _ensure_sink() -> bool:
    """The PipeWire sink that writes into OwnTone's pipe. PipeWire forgets
    loaded modules when it restarts, so this is checked before each use."""
    if SINK in _sinks():
        return True
    result = _pactl("load-module", "module-pipe-sink", f"file={_pipe()}", f"sink_name={SINK}",
                    "format=s16le", "rate=44100", "channels=2",
                    "sink_properties=device.description=Network_speaker")
    if result is None or result.returncode != 0:
        print(f"[owntone] couldn't add the pipe sink: "
              f"{(result.stderr if result else '').strip()}", flush=True)
        return False
    return True


def _route_to(sink: str) -> bool:
    """Make `sink` the default and move streams already playing onto it."""
    result = _pactl("set-default-sink", sink)
    if result is None or result.returncode != 0:
        return False
    inputs = _pactl("list", "short", "sink-inputs")
    for line in (inputs.stdout.splitlines() if inputs and inputs.returncode == 0 else []):
        parts = line.split()
        if parts:
            _pactl("move-sink-input", parts[0], sink)
    return True


def _local_sink() -> str | None:
    """Where the box's audio goes without a network speaker: the paired
    Bluetooth speaker if there is one, else the first other sink."""
    mac = os.environ.get("SPOTIFACTORY_SPEAKER_MAC", "").strip()
    sinks = [s for s in _sinks() if s != SINK]
    if mac:
        bt = "bluez_output." + mac.replace(":", "_") + ".1"
        if bt in sinks:
            return bt
    return sinks[0] if sinks else None


def route_audio() -> bool:
    """Point the box's audio at OwnTone's pipe if a network speaker is chosen.
    Safe to call often (before each tag): it only acts when something's off."""
    if chosen() is None:
        return False
    return _ensure_sink() and _route_to(SINK)


# --- Choosing ----------------------------------------------------------------

def select(device: dict, wait_secs: float = 10.0) -> None:
    """Use the network speaker `device` (a row from speakers()). Raises
    OwnToneError if OwnTone can't take it; the choice is saved either way."""
    from spotifactory.settings import save_setting
    output_id = str(device["id"])[len(ID_PREFIX):]
    save_setting(OUTPUT_ID_KEY, output_id)
    save_setting(OUTPUT_NAME_KEY, device.get("name", ""))
    if not _ensure_sink() or not _route_to(SINK):
        raise OwnToneError("couldn't route audio to the network speaker")
    _select_output(output_id, wait_secs)


def _select_output(output_id: str, wait_secs: float) -> None:
    """Make `output_id` OwnTone's only speaker. A speaker that has just woken
    up can take a few seconds to be listed again, so this retries."""
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


def reselect() -> None:
    """At startup: OwnTone may have dropped the selection while the speaker
    was off. Quietly re-apply it (and the audio route)."""
    current = chosen()
    if current is None:
        return
    route_audio()
    try:
        _select_output(current[0], wait_secs=0)
    except OwnToneError as e:
        print(f"[owntone] chosen speaker {current[1]!r} not there yet: {e}", flush=True)


def release() -> None:
    """Stop using a network speaker (another speaker was chosen): audio back
    to the box's own speaker, OwnTone stopped and its speakers deselected."""
    from spotifactory.settings import save_setting
    if chosen() is None:
        return
    save_setting(OUTPUT_ID_KEY, "")
    save_setting(OUTPUT_NAME_KEY, "")
    local = _local_sink()
    if local:
        _route_to(local)
    for method, path, body in (("PUT", "/api/player/stop", None),
                               ("PUT", "/api/outputs/set", {"outputs": []})):
        try:
            _request(method, path, body)
        except OwnToneError as e:
            print(f"[owntone] {path}: {e}", flush=True)
