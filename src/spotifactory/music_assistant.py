"""Music Assistant backend: the box as a remote for the owner's own server.

For advanced users who run Music Assistant (MA) on another machine (Home
Assistant, a NAS, a Pi 4/5). The box never talks to Spotify in this mode: MA
holds every streaming login, plays tags on any MA speaker, and the box's own
Bluetooth speaker joins MA as a Squeezelite player (see services.py).

Talks to MA's WebSocket API (``ws://<server>:8095/ws``) with a long-lived
access token. One connection is kept open and shared; calls are serialised.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import uuid
from typing import Any

from spotifactory.backend.types import NowPlayingInfo, TagPlay

LABEL = "Music Assistant"
SHORT_LABEL = "MA"
NO_LINK = ("Tag not playable", "in Music Assistant")

URL_KEY = "MA_URL"
TOKEN_KEY = "MA_TOKEN"
PLAYER_KEY = "MA_PLAYER"            # MA player_id chosen in Choose Speaker
PLAYER_NAME_KEY = "MA_PLAYER_NAME"
SERVER_HOST_KEY = "MA_SERVER_HOST"  # for Squeezelite's -s (services.py)

LOCAL_PLAYER_PREFIX = "spotifactory"   # this box's Squeezelite player
_TIMEOUT_SECS = 10.0
_IMAGE_SIZE = 800
_REPEAT_TO_MA = {"off": "off", "context": "all", "track": "one"}
_REPEAT_FROM_MA = {v: k for k, v in _REPEAT_TO_MA.items()}


class MAError(Exception):
    """Music Assistant refused a command, or couldn't be reached."""


class MAOffline(MAError):
    pass


class MAAuthError(MAError):
    pass


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def ws_url(server_url: str) -> str:
    """http://host:8095 → ws://host:8095/ws (https → wss)."""
    url = server_url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    return url if url.endswith("/ws") else url + "/ws"


def server_host(server_url: str) -> str:
    url = server_url.strip()
    if "://" not in url:
        url = "http://" + url
    return urllib.parse.urlsplit(url).hostname or ""


class Client:
    """A blocking client for MA's WebSocket API."""

    def __init__(self, server_url: str, token: str) -> None:
        self.server_url = server_url.strip().rstrip("/")
        self.token = token.strip()
        self.server_info: dict = {}
        self._ws = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        import websocket   # websocket-client
        try:
            ws = websocket.create_connection(ws_url(self.server_url), timeout=_TIMEOUT_SECS)
            self.server_info = json.loads(ws.recv())
        except Exception as e:
            raise MAOffline(f"can't reach {self.server_url}: {e}") from e
        self._ws = ws
        if int(self.server_info.get("schema_version") or 0) >= 28:
            try:
                ok = self._send("auth", {"token": self.token})
            except MAError as e:
                self.close()
                raise MAAuthError(f"token rejected: {e}") from e
            if not ok:
                self.close()
                raise MAAuthError("token rejected")

    def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _send(self, command: str, args: dict) -> Any:
        message_id = uuid.uuid4().hex
        self._ws.send(json.dumps({"message_id": message_id, "command": command, "args": args}))
        partial: list | None = None
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("message_id") != message_id:
                continue                      # an event, or another reply
            if "error_code" in msg:
                raise MAError(f"{command}: {msg.get('details') or msg['error_code']}")
            if msg.get("partial"):
                partial = (partial or []) + list(msg.get("result") or [])
                continue
            if partial is not None:
                return partial + list(msg.get("result") or [])
            return msg.get("result")

    def call(self, command: str, **args: Any) -> Any:
        """Send a command and return its result. Reconnects once if the
        connection dropped."""
        args = {k: v for k, v in args.items() if v is not None}
        with self._lock:
            for attempt in (1, 2):
                if self._ws is None:
                    self._connect()
                try:
                    return self._send(command, args)
                except MAError:
                    raise
                except Exception as e:
                    self.close()
                    if attempt == 2:
                        raise MAOffline(f"{command}: {e}") from e
        raise MAOffline(command)   # not reached

    @property
    def base_url(self) -> str:
        return (self.server_info.get("base_url") or self.server_info.get("internal_url")
                or self.server_url).rstrip("/")


_client: Client | None = None
_client_lock = threading.Lock()


def configured() -> bool:
    return bool(os.environ.get(URL_KEY, "").strip() and os.environ.get(TOKEN_KEY, "").strip())


def get_client() -> Client:
    global _client
    url, token = os.environ.get(URL_KEY, ""), os.environ.get(TOKEN_KEY, "")
    if not url.strip() or not token.strip():
        raise MAOffline("Music Assistant isn't set up")
    with _client_lock:
        if _client is None or (_client.server_url, _client.token) != (url.strip().rstrip("/"), token.strip()):
            if _client is not None:
                _client.close()
            _client = Client(url, token)
        return _client


def _call(command: str, **args: Any) -> Any:
    return get_client().call(command, **args)


def check(server_url: str, token: str) -> int:
    """Connect with these settings and return how many players MA has.
    Raises MAOffline or MAAuthError."""
    client = Client(server_url, token)
    try:
        return len(client.call("players/all") or [])
    finally:
        client.close()


def has_login() -> bool:
    if not configured():
        return False
    try:
        _call("players/all")
        return True
    except Exception as e:
        print(f"[ma] {e}", flush=True)
        return False


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

_resolved: dict[str, dict | None] = {}


def _resolve(uri: str) -> dict | None:
    """The MA item a link points to (share URL, spotify: URI or MA URI), or
    None if MA can't play it (no such provider set up). Remembered."""
    if uri not in _resolved:
        try:
            _resolved[uri] = _call("music/item_by_uri", uri=uri) or None
        except MAOffline:
            raise
        except MAError as e:
            print(f"[ma] can't resolve {uri}: {e}", flush=True)
            _resolved[uri] = None
    return _resolved[uri]


def pick_uri(uris: list[str]) -> str | None:
    """The first link on a tag that MA can play. If MA can't be reached, the
    first link, so the play attempt can say MA is offline."""
    try:
        for uri in uris:
            if _resolve(uri):
                return uri
    except MAOffline as e:
        print(f"[ma] {e}", flush=True)
        return uris[0] if uris else None
    return None


def _share_links(item: dict, first_provider: str | None = None) -> list[str]:
    """Public links for an item (one per service MA knows it on), the playing
    service's first. These work on other boxes, unlike MA's own URIs."""
    maps = [m for m in item.get("provider_mappings") or [] if m.get("url")]
    maps.sort(key=lambda m: (m.get("provider_instance") != first_provider
                             and m.get("provider_domain") != first_provider))
    links: list[str] = []
    for m in maps:
        if m["url"] not in links:
            links.append(m["url"])
    return links


# ---------------------------------------------------------------------------
# Players and queues
# ---------------------------------------------------------------------------

def _players() -> list[dict]:
    return [p for p in _call("players/all") or []
            if p.get("available", True) and p.get("enabled", True)
            and not p.get("hidden", False) and not p.get("hide_in_ui", False)]


def _player_name(p: dict) -> str:
    return p.get("display_name") or p.get("name") or p.get("player_id", "")


def _player_id() -> str | None:
    """The chosen speaker, else this box's own Squeezelite player."""
    chosen = os.environ.get(PLAYER_KEY, "").strip()
    if chosen:
        return chosen
    for p in _players():
        if _player_name(p).lower().startswith(LOCAL_PLAYER_PREFIX):
            return p["player_id"]
    return None


def _queue(player_id: str | None = None) -> dict | None:
    pid = player_id or _player_id()
    if not pid:
        return None
    return _call("player_queues/get_active_queue", player_id=pid) or None


def _queue_id(player_id: str) -> str:
    q = _queue(player_id)
    return (q or {}).get("queue_id") or player_id


def _playing_queue() -> dict | None:
    """The chosen speaker's queue if it's playing, else any queue that is."""
    q = _queue()
    if q and q.get("state") == "playing":
        return q
    for other in _call("player_queues/all") or []:
        if other.get("state") == "playing" and other.get("current_item"):
            return other
    return q


def _is_local(name: str | None) -> bool:
    return bool(name) and name.lower().startswith(LOCAL_PLAYER_PREFIX)


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def _no_speaker() -> TagPlay:
    return TagPlay(("No speaker:", "Up > Choose Speaker"))


def _same_album(queue: dict, uri: str) -> bool:
    """Whether the queue is already on the album (or playlist) a tag is for."""
    item = (queue.get("current_item") or {})
    media = item.get("media_item") or {}
    album = media.get("album") or {}
    tag = _resolve(uri) or {}
    if not tag or not album:
        return False
    if album.get("uri") and album.get("uri") == tag.get("uri"):
        return True
    ids = {(m.get("item_id"), m.get("provider_instance")) for m in tag.get("provider_mappings") or []}
    ids.add((tag.get("item_id"), tag.get("provider")))
    return (album.get("item_id"), album.get("provider")) in ids


def play_tag(uri: str) -> TagPlay:
    try:
        pid = _player_id()
        if not pid:
            return _no_speaker()
        queue = _queue(pid)
        qid = (queue or {}).get("queue_id") or pid
        if queue and queue.get("state") != "playing" and _same_album(queue, uri):
            print(f"[home] resume {uri} on MA player {pid!r}", flush=True)
            _call("player_queues/play", queue_id=qid)
        else:
            print(f"[home] start {uri} on MA player {pid!r}", flush=True)
            _call("player_queues/play_media", queue_id=qid, media=uri, option="replace")
        return TagPlay()
    except MAAuthError as e:
        print(f"[home] {e}", flush=True)
        return TagPlay(("Music Assistant", "token rejected"))
    except MAOffline as e:
        print(f"[home] {e}", flush=True)
        return TagPlay(("Music Assistant", "offline"))
    except MAError as e:
        print(f"[home] play_media error: {e}", flush=True)
        return TagPlay(("Couldn't play", "try again"))


def stop_tag() -> None:
    pause()


def start_tag(uri: str) -> None:
    from spotifactory.backend import NoSpeakerError
    pid = _player_id()
    if not pid:
        raise NoSpeakerError("no Music Assistant speaker chosen")
    _call("player_queues/play_media", queue_id=_queue_id(pid), media=uri, option="replace")


# ---------------------------------------------------------------------------
# Now playing
# ---------------------------------------------------------------------------

def _image_url(image: dict | None, base_url: str) -> str | None:
    if not image or not image.get("path"):
        return None
    if image.get("remotely_accessible"):
        return image["path"]
    if image.get("proxy_id"):
        return f"{base_url}/imageproxy/{image['proxy_id']}?size={_IMAGE_SIZE}"
    path = urllib.parse.quote(urllib.parse.quote(image["path"], safe=""), safe="")
    return f"{base_url}/imageproxy?path={path}&provider={image.get('provider', '')}&size={_IMAGE_SIZE}"


def _first_image(item: dict | None) -> dict | None:
    images = ((item or {}).get("metadata") or {}).get("images") or []
    return next((i for i in images if i.get("type") == "thumb"), images[0] if images else None)


_albums: dict[str, dict] = {}   # album uri → {"links", "length_ms", "tracks"}


def _album_details(album: dict, provider: str | None) -> dict:
    """Public links, running time and track count of an album (remembered)."""
    key = album.get("uri") or f"{album.get('provider')}://album/{album.get('item_id')}"
    if key not in _albums:
        details: dict = {"links": [], "length_ms": None, "tracks": None}
        try:
            full = _resolve(album["uri"]) if album.get("uri") else None
            if full:
                details["links"] = _share_links(full, provider)
            tracks = _call("music/albums/album_tracks", item_id=album.get("item_id"),
                           provider_instance_id_or_domain=album.get("provider")) or []
            if tracks:
                details["tracks"] = len(tracks)
                details["length_ms"] = int(sum((t.get("duration") or 0) for t in tracks) * 1000)
        except MAOffline:
            raise
        except MAError as e:
            print(f"[ma] album details for {key}: {e}", flush=True)
        _albums[key] = details
    return _albums[key]


def _now_playing_from(queue: dict, base_url: str) -> NowPlayingInfo | None:
    item = queue.get("current_item")
    if not item:
        return None
    media = item.get("media_item") or {}
    album = media.get("album") or {}
    playing = queue.get("state") == "playing"
    provider = None
    maps = media.get("provider_mappings") or []
    if maps:
        provider = maps[0].get("provider_instance") or maps[0].get("provider_domain")
    details = _album_details(album, provider) if album else {"links": [], "tracks": None}
    links = details["links"] or ([album["uri"]] if album.get("uri") else [])
    elapsed = float(queue.get("elapsed_time") or 0)
    if playing and queue.get("elapsed_time_last_updated"):
        elapsed += max(0.0, time.time() - float(queue["elapsed_time_last_updated"]))
    duration = int((item.get("duration") or media.get("duration") or 0) * 1000)
    image = item.get("image") or _first_image(album) or _first_image(media)
    return NowPlayingInfo(
        track_name=media.get("name") or item.get("name", ""),
        artist_name=", ".join(a.get("name", "") for a in media.get("artists") or []),
        album_name=album.get("name", ""),
        album_uri=links[0] if links else None,
        artwork_url=_image_url(image, base_url),
        shuffle_active=bool(queue.get("shuffle_enabled")),
        context_uri=links[0] if links else None,
        is_playing=playing,
        device_name=queue.get("display_name"),
        track_uri=media.get("uri"),
        track_number=media.get("track_number") or None,
        progress_ms=min(int(elapsed * 1000), duration) if duration else int(elapsed * 1000),
        duration_ms=duration,
        repeat_state=_REPEAT_FROM_MA.get(queue.get("repeat_mode") or "off", "off"),
        total_tracks=details.get("tracks"),
        links=links,
    )


def get_now_playing(include_paused: bool = False) -> NowPlayingInfo | None:
    """What MA is playing. With include_paused (the home screen), the chosen
    speaker only; without (Print, Write Tag), the chosen speaker if it's
    playing, else any MA speaker that is."""
    queue = _queue() if include_paused else _playing_queue()
    if not queue:
        return None
    if queue.get("state") != "playing" and not include_paused:
        return None
    return _now_playing_from(queue, get_client().base_url)


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def _qid() -> str | None:
    pid = _player_id()
    return _queue_id(pid) if pid else None


def play_pause() -> bool | None:
    queue = _queue()
    if not queue or not queue.get("current_item"):
        return None
    if queue.get("state") == "playing":
        _call("player_queues/pause", queue_id=queue["queue_id"])
        return False
    _call("player_queues/play", queue_id=queue["queue_id"])
    return True


def pause() -> None:
    qid = _qid()
    if qid:
        _call("player_queues/pause", queue_id=qid)


def pause_if_local() -> bool:
    queue = _queue()
    if queue and queue.get("state") == "playing" and _is_local(queue.get("display_name")):
        _call("player_queues/pause", queue_id=queue["queue_id"])
        return True
    return False


def resume() -> None:
    qid = _qid()
    if qid:
        _call("player_queues/play", queue_id=qid)


def next_track() -> None:
    qid = _qid()
    if qid:
        _call("player_queues/next", queue_id=qid)


def prev_track() -> None:
    qid = _qid()
    if qid:
        _call("player_queues/previous", queue_id=qid)


def seek(position_ms: int) -> None:
    qid = _qid()
    if qid:
        _call("player_queues/seek", queue_id=qid, position=max(0, int(position_ms) // 1000))


def toggle_shuffle() -> bool | None:
    queue = _queue()
    if not queue or not queue.get("current_item"):
        return None
    new_state = not queue.get("shuffle_enabled")
    _call("player_queues/shuffle", queue_id=queue["queue_id"], shuffle_enabled=new_state)
    return new_state


def set_repeat(state: str) -> None:
    qid = _qid()
    if qid:
        _call("player_queues/repeat", queue_id=qid, repeat_mode=_REPEAT_TO_MA.get(state, "off"))


def get_volume() -> int | None:
    pid = _player_id()
    if not pid:
        return None
    for p in _call("players/all") or []:
        if p.get("player_id") == pid:
            level = p.get("volume_level")
            return None if level is None else int(level)
    return None


def set_volume(percent: int) -> None:
    pid = _player_id()
    if pid:
        _call("players/cmd/volume_set", player_id=pid, volume_level=max(0, min(100, int(percent))))


# ---------------------------------------------------------------------------
# Speakers
# ---------------------------------------------------------------------------

def list_speakers() -> list[dict]:
    """MA's players, in Choose Speaker's shape. The box's own appears as
    "Spotifactory" (its Squeezelite player)."""
    return [{"id": p["player_id"], "name": _player_name(p),
             "is_active": p.get("playback_state") == "playing" or p.get("state") == "playing",
             "is_restricted": False}
            for p in _players()]


def choose_speaker(device: dict) -> None:
    from spotifactory.settings import save_setting
    old = os.environ.get(PLAYER_KEY, "").strip() or _player_id()
    save_setting(PLAYER_KEY, device["id"])
    save_setting(PLAYER_NAME_KEY, device.get("name", ""))
    if old and old != device["id"]:
        queue = _queue(old)
        if queue and queue.get("state") == "playing":
            _call("player_queues/transfer", source_queue_id=queue["queue_id"],
                  target_queue_id=device["id"], auto_play=True)


# ---------------------------------------------------------------------------
# Albums
# ---------------------------------------------------------------------------

def album_length_ms(album_uri: str) -> int | None:
    for details in _albums.values():
        if album_uri in details["links"]:
            return details["length_ms"]
    item = _resolve(album_uri)
    if not item or item.get("media_type") not in (None, "album"):
        return None
    return _album_details(item, None)["length_ms"]


def uri_name(uri: str) -> str:
    item = _resolve(uri)
    return (item or {}).get("name") or "something else"


def tag_targets() -> list[dict]:
    """Write Tag: the album that's playing, with its links on every service."""
    info = get_now_playing()
    if not info or not info.album_uri:
        return []
    return [{"uri": info.album_uri, "extra": info.links[1:],
             "label": info.album_name or "This album"}]
