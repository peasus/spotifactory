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
    playback programmatically is not currently supported — see docs/sonos.md.
    """
    speaker = _get_speaker(speaker_name)
    coordinator = speaker.group.coordinator if speaker.group else speaker
    coordinator.pause()
    print(f"[sonos] paused {speaker_name!r} via SoCo", flush=True)
