from __future__ import annotations

import soco
import soco.discovery
from soco.plugins.sharelink import ShareLinkPlugin, SpotifyShare

# Cache discovered speakers by name so discovery only runs once per session.
_speaker_cache: dict[str, soco.SoCo] = {}
_spotify_sn_patched = False


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


def _ensure_spotify_service_number() -> None:
    """Patch SpotifyShare.service_number() to match this Sonos system.

    SoCo hardcodes 2311 but the actual Spotify service_type reported by Sonos
    is 3079. Using the wrong value results in UPnP error 804.
    """
    global _spotify_sn_patched
    if _spotify_sn_patched:
        return
    try:
        from soco.music_services import MusicService
        ms = MusicService("Spotify")
        sn = int(ms.service_type)
        SpotifyShare.service_number = lambda self: sn
        print(f"[sonos] Spotify service_type={sn} (patched from {sn})", flush=True)
    except Exception as e:
        print(f"[sonos] could not read Spotify service_type, using default: {e}", flush=True)
    _spotify_sn_patched = True


def play_spotify_uri(speaker_name: str, uri: str) -> None:
    """Clear the queue and start playing a Spotify URI on a Sonos speaker."""
    _ensure_spotify_service_number()
    speaker = _get_speaker(speaker_name)
    plugin = ShareLinkPlugin(speaker)
    speaker.clear_queue()
    try:
        position = plugin.add_share_link_to_queue(uri)
    except Exception as e:
        if "804" in str(e):
            raise RuntimeError(
                f"Sonos UPnP 804 — Spotify is not linked in the Sonos app. "
                f"Open the Sonos app → Browse → Add Music Services → Spotify."
            ) from e
        raise
    speaker.play_from_queue(position - 1)
    print(f"[sonos] playing {uri} on {speaker_name!r}", flush=True)


def pause_speaker(speaker_name: str) -> None:
    """Pause playback on a Sonos speaker."""
    try:
        speaker = _get_speaker(speaker_name)
        speaker.pause()
        print(f"[sonos] paused {speaker_name!r}", flush=True)
    except Exception as e:
        print(f"[sonos] pause error: {e}", flush=True)
