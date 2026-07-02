from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

load_dotenv()

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
]


@dataclass
class NowPlayingInfo:
    track_name: str
    artist_name: str
    album_name: str
    album_uri: str
    artwork_url: str
    shuffle_active: bool = False


_client: spotipy.Spotify | None = None


def get_client() -> spotipy.Spotify:
    global _client
    if _client is None:
        _client = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIPY_CLIENT_ID"],
            client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
            redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
            scope=" ".join(SCOPES),
        ))
    return _client


def _invalidate_client() -> None:
    global _client
    _client = None


def _with_auth_retry(fn):
    """Reset the cached client and retry once if the OAuth token is rejected."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SpotifyOauthError:
            _invalidate_client()
            return fn(*args, **kwargs)
    return wrapper


@_with_auth_retry
def prev_track() -> None:
    get_client().previous_track()


@_with_auth_retry
def next_track() -> None:
    get_client().next_track()


@_with_auth_retry
def toggle_shuffle() -> None:
    sp = get_client()
    state = sp.current_playback()
    if state:
        sp.shuffle(not state["shuffle_state"])


@_with_auth_retry
def get_devices() -> list[dict]:
    result = get_client().devices()
    return result.get("devices", [])


@_with_auth_retry
def transfer_playback(device_id: str) -> None:
    get_client().transfer_playback(device_id, force_play=False)


@_with_auth_retry
def get_now_playing() -> NowPlayingInfo | None:
    sp = get_client()
    playback = sp.current_playback()
    if not playback or not playback.get("is_playing") or playback.get("item") is None:
        return None
    item = playback["item"]
    album = item["album"]
    return NowPlayingInfo(
        track_name=item["name"],
        artist_name=", ".join(a["name"] for a in item["artists"]),
        album_name=album["name"],
        album_uri=album["uri"],
        artwork_url=album["images"][0]["url"],
        shuffle_active=bool(playback.get("shuffle_state", False)),
    )
