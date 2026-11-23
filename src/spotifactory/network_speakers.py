"""Speakers on the network that Spotify can't play to: Google Cast speakers
and groups (cast_direct.py) and AirPlay speakers (owntone.py).

Spotify only lists a Cast speaker while one of its own apps is casting to it,
and has no AirPlay at all. For these speakers the box plays the music itself
(Raspotify, as for its Bluetooth speaker) and streams that audio on. Spotify
sees the box's own "Spotifactory" device playing, so tags, buttons and volume
work as they do for the Bluetooth speaker.

The chosen one is kept in .env (settings.py) by its full row id, e.g.
"cast:192.168.86.31:8009:<uuid>" or "owntone:<output id>".
"""
from __future__ import annotations

import os

from spotifactory import audio_route, cast_direct, owntone

ID_KEY = "SPOTIFACTORY_NETWORK_SPEAKER_ID"
NAME_KEY = "SPOTIFACTORY_NETWORK_SPEAKER_NAME"


class NetworkSpeakerError(Exception):
    pass


def is_network_id(device_id: str | None) -> bool:
    return bool(device_id) and str(device_id).startswith((cast_direct.ID_PREFIX, owntone.ID_PREFIX))


def chosen() -> tuple[str, str] | None:
    """(row id, name) of the network speaker in use, or None."""
    device_id = os.environ.get(ID_KEY, "").strip()
    if not is_network_id(device_id):
        return None
    return device_id, os.environ.get(NAME_KEY, "").strip()


def speakers() -> list[dict]:
    """Cast speakers the box finds itself, then OwnTone's AirPlay speakers.
    Cast always goes the box's own way: it works on networks that hide
    speakers from OwnTone, and with Cast groups."""
    current = chosen()
    current_id = current[0] if current else None
    rows: list[dict] = []
    use_direct = cast_direct.available()
    if use_direct:
        try:
            rows += cast_direct.speakers(current_id)
        except Exception as e:
            print(f"[speakers] Cast discovery failed: {e}", flush=True)
    for row in owntone.speakers(current_id):
        if use_direct and row["type"] == "Cast":
            continue
        rows.append(row)
    return rows


def _play(device_id: str, name: str) -> None:
    if device_id.startswith(cast_direct.ID_PREFIX):
        try:
            cast_direct.play(device_id, name)
        except Exception as e:
            raise NetworkSpeakerError(f"Cast: {e}") from e
    else:
        try:
            owntone.select(device_id)
        except owntone.OwnToneError as e:
            raise NetworkSpeakerError(str(e)) from e


def _stop(device_id: str) -> None:
    if device_id.startswith(cast_direct.ID_PREFIX):
        cast_direct.stop(device_id)
    else:
        owntone.stop()


def select(device: dict) -> None:
    """Use the network speaker `device` (a row from speakers()). The choice is
    saved first, so it stands if the speaker doesn't answer right now; raises
    NetworkSpeakerError then."""
    from spotifactory.settings import save_setting
    if device.get("needs_pairing"):
        raise NetworkSpeakerError("needs pairing (PIN), not supported yet")
    previous = chosen()
    save_setting(ID_KEY, device["id"])
    save_setting(NAME_KEY, device.get("name", ""))
    if previous and previous[0] != device["id"]:
        _stop(previous[0])
    _play(device["id"], device.get("name", ""))


def route_audio() -> bool:
    """Before a tag plays: point the box's audio at OwnTone if a network
    speaker is chosen. Does nothing without one."""
    if chosen() is None:
        return False
    return owntone.route_audio()


def after_play(delay: float = 1.5) -> None:
    """After a tag started playing: make sure the chosen speaker is playing
    the box's audio (a Cast speaker goes idle when the stream stops, e.g.
    after a pause), in the background so the screen doesn't wait."""
    current = chosen()
    if current is None:
        return
    import threading
    import time

    def run() -> None:
        time.sleep(delay)            # let audio reach OwnTone's pipe first
        try:
            _play(*current)
            owntone.play()
        except NetworkSpeakerError as e:
            print(f"[speakers] {current[1]!r} didn't answer: {e}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def reselect() -> None:
    """At startup: re-apply the saved choice (PipeWire forgets the sink)."""
    if route_audio():
        after_play(delay=0)


def release() -> None:
    """Stop using a network speaker (another speaker was chosen, or Music
    Assistant mode): audio back to the box's own speaker."""
    from spotifactory.settings import save_setting
    current = chosen()
    if current is None:
        return
    save_setting(ID_KEY, "")
    save_setting(NAME_KEY, "")
    local = audio_route.local_sink(exclude=(owntone.SINK,))
    if local:
        audio_route.route_to(local)
    _stop(current[0])
