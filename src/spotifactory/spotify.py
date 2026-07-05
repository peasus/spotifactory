from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError, SpotifyPKCE

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
_active_device_id: str | None = None


def _make_auth_manager():
    # Mac dev: client secret in env → standard OAuth with browser flow
    # Pi: no client secret → PKCE flow (no secret needed, relay handles redirect)
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
    if client_secret:
        return SpotifyOAuth(
            client_id=os.environ["SPOTIPY_CLIENT_ID"],
            client_secret=client_secret,
            redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
            scope=" ".join(SCOPES),
        )
    relay_url = os.environ["RELAY_URL"].rstrip("/")
    return SpotifyPKCE(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        redirect_uri=f"{relay_url}/callback",
        scope=" ".join(SCOPES),
        open_browser=False,
    )


def get_client() -> spotipy.Spotify:
    global _client
    if _client is None:
        _client = spotipy.Spotify(auth_manager=_make_auth_manager())
    return _client


def _invalidate_client() -> None:
    global _client
    _client = None


def _set_client(sp: spotipy.Spotify) -> None:
    global _client
    _client = sp


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


def set_active_device(device_id: str) -> None:
    global _active_device_id
    _active_device_id = device_id


def get_active_device() -> str | None:
    return _active_device_id


class DeviceInfo:
    """Snapshot of the best device to target for playback."""
    def __init__(self, device_id: str | None, restricted: bool, name: str = ""):
        self.device_id = device_id
        self.restricted = restricted
        self.name = name

    @property
    def usable(self) -> bool:
        return self.device_id is not None and not self.restricted


@_with_auth_retry
def get_playback_device() -> DeviceInfo:
    """Return info about the best device to target for start_playback.

    Priority:
    1. Device explicitly chosen via Choose Speaker
    2. Currently active Spotify Connect device (from current_playback)
    3. Active device from the devices list (is_active=True)

    Never falls back to an arbitrary non-active device — that would start
    playback on the wrong speaker.
    """
    if _active_device_id is not None:
        return DeviceInfo(_active_device_id, restricted=False)
    sp = get_client()
    playback = sp.current_playback()
    if playback and playback.get("device"):
        dev = playback["device"]
        print(
            f"[spotify] active device: {dev.get('name')!r} "
            f"id={dev.get('id')!r} restricted={dev.get('is_restricted')}",
            flush=True,
        )
        return DeviceInfo(dev.get("id"), restricted=bool(dev.get("is_restricted")), name=dev.get("name", ""))
    # No Spotify Connect session — check devices list
    devices = sp.devices().get("devices", [])
    print(f"[spotify] devices: {[(d.get('name'), d.get('is_active'), d.get('is_restricted')) for d in devices]}", flush=True)
    for d in devices:
        if d.get("is_active"):
            return DeviceInfo(d.get("id"), restricted=bool(d.get("is_restricted")), name=d.get("name", ""))
    return DeviceInfo(None, restricted=False)


def get_playback_device_id() -> str | None:
    return get_playback_device().device_id


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
