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
    "playlist-read-private",
]


@dataclass
class NowPlayingInfo:
    track_name: str
    artist_name: str
    album_name: str               # for a podcast episode: the show
    album_uri: str | None         # None for local files
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


_client: spotipy.Spotify | None = None

# The speaker picked in Choose Speaker. Persisted (see settings.py) because
# Spotify forgets the "active device" after idle and the app restarts on reboot.
_DEVICE_ID_KEY = "SPOTIFACTORY_DEVICE_ID"
_DEVICE_NAME_KEY = "SPOTIFACTORY_DEVICE_NAME"


@dataclass
class ChosenDevice:
    id: str
    name: str


class _DevicePKCE(SpotifyPKCE):
    """PKCE auth that never asks for input on the terminal.

    With no saved login and no code, spotipy falls back to printing a URL and
    waiting on input() for the redirect — which hangs a hand-run app (and gets
    an EOF under systemd). On the device, login is the QR/relay flow, so raise
    instead; callers treat it as "not logged in".
    """

    def _get_auth_response_interactive(self, open_browser=False):
        raise SpotifyOauthError("No saved Spotify login — use Connect Spotify (QR code)")


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
    return _DevicePKCE(
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
def set_repeat(state: str) -> None:
    """"off", "context" (the album or playlist) or "track"."""
    get_client().repeat(state)


@_with_auth_retry
def seek(position_ms: int) -> None:
    get_client().seek_track(max(0, int(position_ms)))


@_with_auth_retry
def toggle_shuffle() -> bool | None:
    """Flip shuffle; return the new state, or None if nothing is playing."""
    sp = get_client()
    state = sp.current_playback()
    if not state:
        return None
    new_state = not state["shuffle_state"]
    sp.shuffle(new_state)
    return new_state


@_with_auth_retry
def get_volume() -> int | None:
    """The playing device's volume (0-100), or None if there's no device or
    Spotify can't set its volume (some speakers, e.g. Sonos, don't allow it)."""
    state = get_client().current_playback()
    dev = (state or {}).get("device") or {}
    if dev.get("is_restricted") or dev.get("supports_volume") is False or dev.get("volume_percent") is None:
        return None
    return int(dev["volume_percent"])


@_with_auth_retry
def set_volume(percent: int) -> None:
    get_client().volume(max(0, min(100, int(percent))))


@_with_auth_retry
def play_pause() -> bool | None:
    """Pause if playing, else resume on the same device. Returns whether it's
    now playing, or None if there's nothing to resume."""
    sp = get_client()
    state = sp.current_playback()
    if not state or not state.get("device"):
        return None
    if state.get("is_playing"):
        sp.pause_playback()
        return False
    sp.start_playback(device_id=state["device"]["id"])
    return True


@_with_auth_retry
def get_devices() -> list[dict]:
    result = get_client().devices()
    return result.get("devices", [])


@_with_auth_retry
def find_device_by_name(name: str) -> dict | None:
    """Return first Spotify Connect device whose name starts with `name` (case-insensitive)."""
    devices = get_client().devices().get("devices", [])
    name_lower = name.lower()
    for d in devices:
        if d.get("name", "").lower().startswith(name_lower):
            return d
    return None


def set_active_device(device_id: str, name: str = "") -> None:
    """Remember the speaker chosen in Choose Speaker, across idle and restarts."""
    from spotifactory.settings import save_setting
    save_setting(_DEVICE_ID_KEY, device_id)
    save_setting(_DEVICE_NAME_KEY, name)


def get_active_device() -> ChosenDevice | None:
    device_id = os.environ.get(_DEVICE_ID_KEY, "").strip()
    if not device_id:
        return None
    return ChosenDevice(device_id, os.environ.get(_DEVICE_NAME_KEY, "").strip())


@_with_auth_retry
def resolve_chosen_device(chosen: ChosenDevice) -> str | None:
    """Return the chosen speaker's current device id, or None if Spotify doesn't list it.

    Matches by id first, then by name, since some speakers get a new id when
    they reconnect.
    """
    devices = get_client().devices().get("devices", [])
    for d in devices:
        if d.get("id") == chosen.id:
            return d["id"]
    for d in devices:
        if chosen.name and d.get("name") == chosen.name:
            return d.get("id")
    return None


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
    chosen = get_active_device()
    if chosen is not None:
        return DeviceInfo(chosen.id, restricted=False, name=chosen.name)
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
def get_current_context() -> tuple[str | None, str | None]:
    """Return (context_uri, album_uri) from current playback, including when paused."""
    playback = get_client().current_playback()
    if not playback or not playback.get("item"):
        return None, None
    context = playback.get("context")
    context_uri = context.get("uri") if context else None
    album_uri = (playback["item"].get("album") or {}).get("uri")
    return context_uri, album_uri


@_with_auth_retry
def get_now_playing(include_paused: bool = False) -> NowPlayingInfo | None:
    """What's playing, or None. Handles podcast episodes (the show stands in for
    the album) and items with no artwork or URI, such as local files.
    include_paused also returns a paused track (is_playing False)."""
    sp = get_client()
    playback = sp.current_playback(additional_types="episode")
    if not playback or playback.get("item") is None:
        return None
    if not playback.get("is_playing") and not include_paused:
        return None
    item = playback["item"]
    context = playback.get("context")
    if item.get("type") == "episode":
        show = item.get("show") or {}
        collection, images = show, item.get("images") or show.get("images") or []
        artist = show.get("publisher") or show.get("name", "")
    else:
        collection = item.get("album") or {}
        images = collection.get("images") or []
        artist = ", ".join(a["name"] for a in item.get("artists", []))
    return NowPlayingInfo(
        track_name=item.get("name", ""),
        artist_name=artist,
        album_name=collection.get("name", ""),
        album_uri=collection.get("uri"),
        artwork_url=images[0]["url"] if images else None,
        shuffle_active=bool(playback.get("shuffle_state", False)),
        context_uri=context.get("uri") if context else None,
        is_playing=bool(playback.get("is_playing")),
        device_name=(playback.get("device") or {}).get("name"),
        track_uri=item.get("uri"),
        track_number=item.get("track_number"),
        progress_ms=playback.get("progress_ms") or 0,
        duration_ms=item.get("duration_ms") or 0,
        repeat_state=playback.get("repeat_state") or "off",
        total_tracks=collection.get("total_tracks"),
    )


@_with_auth_retry
def uri_name(uri: str) -> str:
    """The name of an album or playlist from its URI."""
    _, kind, ident = uri.split(":", 2)
    sp = get_client()
    if kind == "album":
        return sp.album(ident)["name"]
    if kind == "playlist":
        return sp._get(f"playlists/{ident}", fields="name")["name"]   # see FetchPlaylistInfoStep
    return kind


_album_lengths: dict[str, int] = {}


@_with_auth_retry
def album_length_ms(album_uri: str) -> int:
    """Total running time of an album (remembered: albums don't change)."""
    if album_uri not in _album_lengths:
        sp = get_client()
        page = sp.album_tracks(album_uri, limit=50)
        total = 0
        while page:
            total += sum(t.get("duration_ms") or 0 for t in page["items"])
            page = sp.next(page) if page.get("next") else None
        _album_lengths[album_uri] = total
    return _album_lengths[album_uri]
