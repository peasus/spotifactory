"""Shapes shared by every music backend (Spotify today, Music Assistant next).

Kept apart from the backends so the UI can use them without importing one.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NowPlayingInfo:
    track_name: str
    artist_name: str
    album_name: str               # for a podcast episode: the show
    album_uri: str | None         # the album's link in the backend; None for local files
    artwork_url: str | None
    shuffle_active: bool = False
    context_uri: str | None = None  # playlist/album/artist the track is playing from
    is_playing: bool = True
    device_name: str | None = None
    track_uri: str | None = None
    track_number: int | None = None
    progress_ms: int = 0
    duration_ms: int = 0
    repeat_state: str = "off"     # "off", "context" (album/playlist) or "track"
    total_tracks: int | None = None   # on the track's album
    # Every link to the album a tag can carry, album_uri first (Music
    # Assistant: one per service it knows the album on). Empty for Spotify.
    links: list[str] = field(default_factory=list)


@dataclass
class ChosenDevice:
    id: str
    name: str
    restricted: bool = False


@dataclass
class TagPlay:
    """What placing a tag did, for the home screen. `message` is two lines to
    show instead of the track (an error, or what to do next); None if it
    started or resumed."""
    message: tuple[str, str] | None = None
