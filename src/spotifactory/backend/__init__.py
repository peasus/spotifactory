"""The music service the box plays through.

Everything outside the service modules talks to music through here, never to
spotify.py directly, so a box can be switched to another service (Music
Assistant, next) in one place. Spotify is the only backend today and the
default.

Each call looks the backend up when it runs, so tests that patch
``spotifactory.spotify.<name>`` still take effect.
"""
from __future__ import annotations

import os
from types import ModuleType

from spotifactory.backend.types import ChosenDevice, NowPlayingInfo, TagPlay

__all__ = [
    "ChosenDevice", "NowPlayingInfo", "TagPlay",
    "name", "current", "label", "has_login", "pick_uri",
    "play_tag", "stop_tag", "start_tag",
    "get_now_playing", "play_pause", "pause", "pause_if_local", "resume",
    "next_track", "prev_track", "seek", "toggle_shuffle", "set_repeat",
    "get_volume", "set_volume",
    "list_speakers", "choose_speaker",
    "album_length_ms", "uri_name",
]

BACKEND_KEY = "MUSIC_BACKEND"
_DEFAULT = "spotify"


def name() -> str:
    """The backend chosen for this box ("spotify" unless set otherwise)."""
    return os.environ.get(BACKEND_KEY, "").strip().lower() or _DEFAULT


def current() -> ModuleType:
    chosen = name()
    if chosen != "spotify":
        print(f"[backend] unknown {BACKEND_KEY}={chosen!r}, using Spotify", flush=True)
    from spotifactory import spotify
    return spotify


def label() -> str:
    """The service's name for screens, e.g. "Checking Spotify..."."""
    return current().LABEL


def has_login() -> bool:
    """Whether the backend can be used now (Spotify: a saved login that works)."""
    return current().has_login()


def pick_uri(uris: list[str]) -> str | None:
    """The link on a tag this backend should play, or None if none suits it."""
    return current().pick_uri(uris)


# --- Tags -------------------------------------------------------------------

def play_tag(uri: str) -> TagPlay:
    """Play a tag that was just placed (resume if it's what's already loaded)."""
    return current().play_tag(uri)


def stop_tag() -> None:
    """The tag was lifted: pause wherever play_tag started it."""
    current().stop_tag()


def start_tag(uri: str) -> None:
    """Menu > Scan Tag: start `uri` on the usual speaker. Raises NoSpeakerError."""
    current().start_tag(uri)


# --- Playback ---------------------------------------------------------------

def get_now_playing(include_paused: bool = False) -> NowPlayingInfo | None:
    return current().get_now_playing(include_paused=include_paused)


def play_pause() -> bool | None:
    return current().play_pause()


def pause() -> None:
    current().pause()


def pause_if_local() -> bool:
    """Pause if it's playing on this box's own speaker; return whether it did."""
    return current().pause_if_local()


def resume() -> None:
    current().resume()


def next_track() -> None:
    current().next_track()


def prev_track() -> None:
    current().prev_track()


def seek(position_ms: int) -> None:
    current().seek(position_ms)


def toggle_shuffle() -> bool | None:
    return current().toggle_shuffle()


def set_repeat(state: str) -> None:
    current().set_repeat(state)


def get_volume() -> int | None:
    return current().get_volume()


def set_volume(percent: int) -> None:
    current().set_volume(percent)


# --- Speakers ---------------------------------------------------------------

def list_speakers() -> list[dict]:
    """Speakers for Choose Speaker: dicts with id, name, is_active, is_restricted."""
    return current().list_speakers()


def choose_speaker(device: dict) -> None:
    """Remember `device` as the speaker and move playback there. The choice is
    saved even when the move fails (the exception is raised after saving)."""
    current().choose_speaker(device)


# --- Albums -----------------------------------------------------------------

def album_length_ms(album_uri: str) -> int | None:
    """Total running time of an album, or None if this backend can't tell."""
    return current().album_length_ms(album_uri)


def uri_name(uri: str) -> str:
    """The name of an album or playlist from its link."""
    return current().uri_name(uri)


class NoSpeakerError(Exception):
    """There's no speaker to play on (choose one in Choose Speaker)."""
