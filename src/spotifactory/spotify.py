from __future__ import annotations

import functools
import os
import re
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError, SpotifyPKCE

from spotifactory.backend.types import ChosenDevice, NowPlayingInfo, TagPlay

load_dotenv()

LABEL = "Spotify"
SHORT_LABEL = "Spotify"
NO_LINK = ("No Spotify link", "on this tag")

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
]


_client: spotipy.Spotify | None = None

# The speaker picked in Choose Speaker. Persisted (see settings.py) because
# Spotify forgets the "active device" after idle and the app restarts on reboot.
_DEVICE_ID_KEY = "SPOTIFACTORY_DEVICE_ID"
_DEVICE_NAME_KEY = "SPOTIFACTORY_DEVICE_NAME"
# Set for a speaker the Web API won't control (Sonos): it's played through
# the Connect route instead (spotifactory/connect.py).
_DEVICE_RESTRICTED_KEY = "SPOTIFACTORY_DEVICE_RESTRICTED"


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


def _connect_target() -> ChosenDevice | None:
    """The chosen speaker, when the Web API won't control it and the Connect
    helper is installed: player commands then go there through the helper."""
    chosen = get_active_device()
    if chosen is None or not chosen.restricted:
        return None
    from spotifactory import connect
    return chosen if connect.available() else None


@_with_auth_retry
def prev_track() -> None:
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.prev_track(target.id)
        return
    get_client().previous_track()


@_with_auth_retry
def next_track() -> None:
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.next_track(target.id)
        return
    get_client().next_track()


@_with_auth_retry
def set_repeat(state: str) -> None:
    """"off", "context" (the album or playlist) or "track"."""
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.repeat(target.id, state)
        return
    get_client().repeat(state)


@_with_auth_retry
def seek(position_ms: int) -> None:
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.seek(target.id, position_ms)
        return
    get_client().seek_track(max(0, int(position_ms)))


@_with_auth_retry
def toggle_shuffle() -> bool | None:
    """Flip shuffle; return the new state, or None if nothing is playing."""
    sp = get_client()
    state = sp.current_playback()
    if not state:
        return None
    new_state = not state["shuffle_state"]
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.shuffle(target.id, new_state)
    else:
        sp.shuffle(new_state)
    return new_state


@_with_auth_retry
def get_volume() -> int | None:
    """The playing device's volume (0-100), or None if there's no device or
    Spotify can't set its volume (some speakers, e.g. Sonos, don't allow it).
    A chosen Sonos is asked directly over the local network."""
    target = _connect_target()
    if target:
        from spotifactory.hardware.sonos import get_volume as sonos_volume
        try:
            return sonos_volume(target.name)
        except Exception as e:
            print(f"[spotify] Sonos volume for {target.name!r}: {e}", flush=True)
            return None
    state = get_client().current_playback()
    dev = (state or {}).get("device") or {}
    if dev.get("is_restricted") or dev.get("supports_volume") is False or dev.get("volume_percent") is None:
        return None
    return int(dev["volume_percent"])


@_with_auth_retry
def set_volume(percent: int) -> None:
    target = _connect_target()
    if target:
        from spotifactory.hardware.sonos import set_volume as sonos_set_volume
        try:
            sonos_set_volume(target.name, percent)
        except Exception as e:
            print(f"[spotify] Sonos volume over UPnP failed ({e}); trying Connect", flush=True)
            from spotifactory import connect
            connect.set_volume(target.id, percent)
        return
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
        pause()
        return False
    start_playback(state["device"]["id"])
    return True


def _routes_to_connect(device_id: str) -> bool:
    target = _connect_target()
    return target is not None and target.id == device_id


@_with_auth_retry
def start_playback(device_id: str, context_uri: str | None = None,
                   restricted: bool | None = None) -> None:
    """Play `context_uri` from the top on `device_id`, or resume there if None.

    A speaker the Web API won't control goes through the Connect helper:
    the chosen one when it's marked restricted, or any one when `restricted`
    says so (and the helper is installed).
    """
    from spotifactory import connect
    if restricted is None:
        restricted = _routes_to_connect(device_id)
    if restricted and connect.available():
        if context_uri:
            connect.play(device_id, context_uri)
        else:
            connect.resume(device_id)
        return
    if context_uri:
        get_client().start_playback(context_uri=context_uri, device_id=device_id)
    else:
        get_client().start_playback(device_id=device_id)


@_with_auth_retry
def pause() -> None:
    target = _connect_target()
    if target:
        from spotifactory import connect
        connect.pause(target.id)
        return
    get_client().pause_playback()


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


def set_active_device(device_id: str, name: str = "", restricted: bool = False) -> None:
    """Remember the speaker chosen in Choose Speaker, across idle and restarts."""
    from spotifactory.settings import save_setting
    save_setting(_DEVICE_ID_KEY, device_id)
    save_setting(_DEVICE_NAME_KEY, name)
    save_setting(_DEVICE_RESTRICTED_KEY, "1" if restricted else "")


def get_active_device() -> ChosenDevice | None:
    device_id = os.environ.get(_DEVICE_ID_KEY, "").strip()
    if not device_id:
        return None
    return ChosenDevice(device_id, os.environ.get(_DEVICE_NAME_KEY, "").strip(),
                        restricted=os.environ.get(_DEVICE_RESTRICTED_KEY, "").strip() == "1")


@_with_auth_retry
def resolve_chosen_device(chosen: ChosenDevice) -> str | None:
    """Return the chosen speaker's current device id, or None if Spotify doesn't list it.

    Matches by id first, then by name, since some speakers get a new id when
    they reconnect. A restricted speaker (Sonos) is taken as it is: Spotify
    leaves it out of the list while it's idle.
    """
    if chosen.restricted:
        from spotifactory import connect
        if connect.available():
            return chosen.id
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
def transfer_playback(device_id: str, restricted: bool = False) -> None:
    from spotifactory import connect
    if restricted and connect.available():
        connect.transfer(device_id)
        return
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
def album_length_ms(album_uri: str) -> int | None:
    """Total running time of an album (remembered: albums don't change).
    None for anything that isn't an album, such as a podcast show."""
    if not album_uri.startswith("spotify:album:"):
        return None
    if album_uri not in _album_lengths:
        sp = get_client()
        page = sp.album_tracks(album_uri, limit=50)
        total = 0
        while page:
            total += sum(t.get("duration_ms") or 0 for t in page["items"])
            page = sp.next(page) if page.get("next") else None
        _album_lengths[album_uri] = total
    return _album_lengths[album_uri]


# ---------------------------------------------------------------------------
# The rest of the backend interface (see spotifactory/backend)
# ---------------------------------------------------------------------------

def has_login() -> bool:
    """A saved login that Spotify accepts right now."""
    try:
        get_now_playing()
        return True
    except Exception:
        return False


_SHARE_LINK = re.compile(r"^https?://open\.spotify\.com/(?:intl-[\w-]+/)?(album|playlist|artist|show|track)/([A-Za-z0-9]+)")


def pick_uri(uris: list[str]) -> str | None:
    """The first Spotify link on a tag, as a spotify: URI. Tags can carry other
    services' links too (an Apple Music one, or one printed in another mode),
    and they may come first."""
    for uri in uris:
        if uri.startswith("spotify:"):
            return uri
        m = _SHARE_LINK.match(uri)
        if m:
            return f"spotify:{m.group(1)}:{m.group(2)}"
    return None


# A Sonos S2 the tag couldn't start (no Connect helper): lifting the tag
# pauses it over the local network instead (see docs/sonos.md).
_soco_speaker: str | None = None


def play_tag(uri: str) -> TagPlay:
    """Start (or resume) `uri` for a tag just placed, picking the speaker:
    1. the one chosen in Choose Speaker, with no silent fallback;
    2. this box's own Raspotify;
    3. whatever Spotify is already playing on."""
    global _soco_speaker
    _soco_speaker = None
    try:
        from spotifactory.connect import ConnectError
        from spotifactory.connect import available as connect_available

        # Already in this album or playlist (even paused)? Resume rather than
        # restart from track 1.
        ctx_uri, alb_uri = get_current_context()
        in_context = (ctx_uri == uri or alb_uri == uri)

        def _play(device_id: str, restricted: bool | None = None) -> None:
            start_playback(device_id, None if in_context else uri, restricted=restricted)

        verb = "resume" if in_context else "start"

        chosen = get_active_device()
        if chosen is not None:
            label = chosen.name or "Chosen speaker"
            dev_id = resolve_chosen_device(chosen)
            if dev_id is None:
                print(f"[home] chosen device {label!r} not listed by Spotify", flush=True)
                return TagPlay((label, "not available"))
            print(f"[home] {verb} {uri} on chosen device {label!r} ({dev_id})", flush=True)
            try:
                _play(dev_id)
            except (spotipy.SpotifyException, ConnectError) as e:
                # Idle Echos stay listed but 404 until woken; a Sonos can
                # refuse the Connect route the same way.
                print(f"[home] chosen device {label!r} didn't respond: {e}", flush=True)
                return TagPlay((label, "not responding"))
            return TagPlay()

        raspotify = find_device_by_name("Spotifactory")
        if raspotify:
            dev_id = raspotify["id"]
            print(f"[home] {verb} {uri} on Raspotify {dev_id!r}", flush=True)
            try:
                get_client().transfer_playback(dev_id, force_play=False)
            except Exception:
                pass
            _play(dev_id)
            return TagPlay()

        # Raspotify not logged in yet: whatever Spotify is playing on.
        dev = get_playback_device()
        if dev.restricted and dev.device_id and connect_available():
            # Sonos S2 playing already: start the tag there through the
            # Connect route (spotifactory/connect.py).
            print(f"[home] {verb} {uri} on restricted {dev.name!r} via Connect", flush=True)
            _play(dev.device_id, restricted=True)
            return TagPlay()
        if dev.restricted:
            print(f"[home] device {dev.name!r} is restricted — pause only via SoCo", flush=True)
            _soco_speaker = dev.name
            return TagPlay(("Start in Spotify,", "tag removes pauses"))
        if dev.device_id is None:
            return TagPlay(("No speaker:", "Up > Choose Speaker"))
        print(f"[home] {verb} {uri} on device {dev.device_id!r}", flush=True)
        _play(dev.device_id)
        return TagPlay()
    except Exception as e:
        _soco_speaker = None
        reason = getattr(e, "reason", None)
        if reason == "NO_ACTIVE_DEVICE" or "restricted device" in str(e).lower():
            return TagPlay(("No speaker:", "Up > Choose Speaker"))
        print(f"[home] start_playback error: {e}", flush=True)
        return TagPlay(("Couldn't play", "try again"))


def stop_tag() -> None:
    global _soco_speaker
    speaker, _soco_speaker = _soco_speaker, None
    if speaker:
        from spotifactory.hardware.sonos import pause_speaker
        pause_speaker(speaker)
        return
    pause()


def start_tag(uri: str) -> None:
    from spotifactory.backend import NoSpeakerError
    try:
        start_playback(get_playback_device_id(), uri)
    except spotipy.SpotifyException as e:
        if "device" in str(e).lower() or "restricted" in str(e).lower():
            raise NoSpeakerError(str(e)) from e
        raise


def pause_if_local() -> bool:
    """Pause if it's playing on this box's Raspotify (the Pi Zero 2 W has one
    radio for Wi-Fi and Bluetooth, so printing over Bluetooth while streaming
    to the BT speaker stutters). Other speakers are left alone."""
    sp = get_client()
    playback = sp.current_playback()
    device_name = ((playback or {}).get("device") or {}).get("name", "")
    if playback and playback.get("is_playing") and device_name.lower().startswith("spotifactory"):
        sp.pause_playback()
        return True
    return False


def resume() -> None:
    get_client().start_playback()


def _sonos_speakers(listed: list[dict]) -> list[dict]:
    """Sonos rooms Spotify didn't list (it hides them while idle), when the
    Connect helper is installed to play them (spotifactory/connect.py)."""
    from spotifactory import connect
    if not connect.available():
        return []
    try:
        from spotifactory.hardware.sonos import connect_speakers
        found = connect_speakers()
    except Exception as e:
        print(f"[speaker] Sonos discovery failed: {e}", flush=True)
        return []
    ids = {d.get("id") for d in listed}
    return [d for d in found if d["id"] not in ids]


def list_speakers() -> list[dict]:
    devices = get_devices()
    return devices + _sonos_speakers(devices)


def choose_speaker(device: dict) -> None:
    # Save first: the choice stands even if the speaker is asleep right now
    # (idle Echos are listed but return 404 until something wakes them).
    restricted = bool(device.get("is_restricted"))
    set_active_device(device["id"], device.get("name", ""), restricted=restricted)
    transfer_playback(device["id"], restricted=restricted)


def tag_targets() -> list[dict]:
    """Write Tag: what's playing's album, and its playlist if it's playing from one."""
    playback = get_client().current_playback()
    item = (playback or {}).get("item") or {}
    album = item.get("album") or {}
    targets = []
    if album.get("uri"):
        targets.append({"uri": album["uri"], "label": album.get("name") or "This album"})
    context = (playback or {}).get("context") or {}
    if context.get("type") == "playlist":
        try:
            name = uri_name(context["uri"])
        except Exception:
            name = "This playlist"
        targets.append({"uri": context["uri"], "label": f"Playlist: {name}"})
    return targets
