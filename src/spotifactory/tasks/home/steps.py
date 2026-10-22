from __future__ import annotations

import sys
import threading
import time

from spotifactory.tasks.base import (
    Cancel,
    Step,
    StepOutcome,
    TaskContext,
)

_POLL_INTERVAL_SECS = 5.0   # how often to refresh now-playing display from Spotify (only while playing)
_SCREEN_OFF_SECS = 600.0    # blank display after this many idle seconds
_CARRY_SECS = 2.0           # after the menu: trust the remembered screen this long for the tag to be seen again
_SHUFFLE_SETTLE_SECS = 3.0  # Spotify can report the old shuffle/repeat state briefly after a change
_POLL_ERROR_LOG_SECS = 60.0  # log failed polls at most this often


class PlaybackLog:
    """Journal lines for what Spotify does while a tag is down: each track,
    speaker or play/pause change, and tracks that aren't from the tag's album
    (e.g. an Echo dropping into Autoplay mid-album)."""

    def __init__(self) -> None:
        self.reset(None)
        self._error_logged_at = 0.0

    def reset(self, tag_uri: str | None) -> None:
        self._tag_uri = tag_uri
        self._last = None
        self._last_pos = ""

    def update(self, info) -> None:
        key = (info.track_uri, info.is_playing, info.device_name)
        if key != self._last:
            # Autoplay keeps reporting the album as the context, so check the
            # track's own album; for a playlist tag, the context is all there is.
            if not self._tag_uri:
                off = False
            elif self._tag_uri.startswith("spotify:album:"):
                off = info.album_uri != self._tag_uri
            else:
                off = info.context_uri != self._tag_uri
            print(f"[play] {'off-album: ' if off else ''}"
                  f"{'playing' if info.is_playing else 'paused'} #{info.track_number} "
                  f"{info.track_name} - {info.artist_name} ({info.album_name}) "
                  f"| ctx {info.context_uri} | {info.device_name} "
                  f"| at {_secs(info.progress_ms)}/{_secs(info.duration_ms)} "
                  f"| prev last seen {self._last_pos or '-'}", flush=True)
            self._last = key
        self._last_pos = f"{_secs(info.progress_ms)}/{_secs(info.duration_ms)}"

    def nothing(self) -> None:
        if self._last is not None:
            print(f"[play] nothing playing | prev last seen {self._last_pos or '-'}", flush=True)
            self._last = None

    def error(self, e: Exception) -> None:
        now = time.monotonic()
        if now - self._error_logged_at >= _POLL_ERROR_LOG_SECS:
            print(f"[play] poll failed: {type(e).__name__}: {e}", flush=True)
            self._error_logged_at = now


def _secs(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


# What the home screen showed, kept across a trip to the menu so it comes back
# as it was instead of blank until the reader sees the tag again.
_CARRY_FIELDS = ("status", "artist", "shuffle_active", "repeat_state", "is_playing",
                 "progress_ms", "duration_ms", "progress_at", "track_number",
                 "total_tracks", "album_name", "album_uri", "album_length_ms",
                 "tag_active", "tag_uri")


class HomeScanStep(Step):
    _carried: dict | None = None
    """Event-driven RFID home screen.

    Uses nfcpy supervision mode so the PN532 fires on_place/on_remove natively —
    no application-level polling for tag presence. The step runs until the user
    navigates away (cancel).

    Behaviour:
      tag placed (new)  → start_playback for that album
      tag still present → no-op (PN532 supervises; on_place is not re-fired)
      tag removed       → pause, whatever is playing (Autoplay after the album too)
    """

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._sim_tag: str | None = None
        self.artist: str = ""
        self.shuffle_active: bool = False
        self.screen_off: bool = False
        self.tag_active: bool = False        # a tag is on the reader (the box is in use)
        self.tag_uri: str | None = None
        self._idle_since: float = time.monotonic()
        self._shuffle_set_at: float = 0.0
        self.repeat_state: str = "off"       # "off", "context" or "track"
        self._repeat_set_at: float = 0.0
        # Where the track was at the last poll (seeking starts from here).
        self.is_playing: bool = False
        self.progress_ms: int = 0
        self.duration_ms: int = 0
        self.progress_at: float = 0.0
        # For the time and album displays.
        self.track_number: int | None = None
        self.total_tracks: int | None = None
        self.album_name: str = ""
        self.album_uri: str | None = None
        self.album_length_ms: int | None = None

    @classmethod
    def remember(cls, step: "HomeScanStep") -> None:
        """Keep `step`'s screen for the next home screen (leaving for the menu)."""
        cls._carried = {k: getattr(step, k) for k in _CARRY_FIELDS} if step.tag_active else None

    def set_shuffle(self, active: bool) -> None:
        """Show a shuffle state we just set; polls won't override it while Spotify settles."""
        self.shuffle_active = active
        self._shuffle_set_at = time.monotonic()

    def set_repeat(self, state: str) -> None:
        """Show a repeat state we just set; polls won't override it while Spotify settles."""
        self.repeat_state = state
        self._repeat_set_at = time.monotonic()

    def set_position(self, progress_ms: int) -> None:
        """Where we just sought to, until the next poll says otherwise."""
        self.progress_ms = progress_ms
        self.progress_at = time.monotonic()

    def position_ms(self) -> int:
        """The track position now, counting on from the last poll while playing."""
        pos = self.progress_ms
        if self.is_playing:
            pos += int((time.monotonic() - self.progress_at) * 1000)
        return min(pos, self.duration_ms) if self.duration_ms else pos

    def cancel(self) -> None:
        self._cancel.set()

    def simulate_scan(self, uri: str) -> None:
        """Inject a virtual tag scan; works in both hardware and fallback modes."""
        self._sim_tag = uri

    def wake(self) -> None:
        """Called by the runner on any button press when screen is blanked."""
        self.screen_off = False
        self._idle_since = time.monotonic()

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> StepOutcome:
        self._cancel.clear()
        self._sim_tag = None
        self.status = "Place tag..."
        self.artist = ""
        self.shuffle_active = False
        self.screen_off = False
        self.tag_active = False
        self.tag_uri = None
        self._idle_since = time.monotonic()
        carried, HomeScanStep._carried = HomeScanStep._carried, None
        carry_until = 0.0
        if carried:
            for k, v in carried.items():
                setattr(self, k, v)
            carry_until = float("inf")         # the wait starts once the reader is watching

        _active_uri: str | None = None
        _soco_speaker: str | None = None  # set when active device is Sonos (restricted)
        last_poll = 0.0
        playlog = PlaybackLog()

        def on_poll() -> None:
            nonlocal last_poll
            # Only poll Spotify while a tag is active — idle screen needs no API calls.
            if _active_uri is None:
                return
            now = time.monotonic()
            if now - last_poll < _POLL_INTERVAL_SECS:
                return
            last_poll = now
            try:
                from spotifactory.spotify import get_now_playing
                info = get_now_playing(include_paused=True)
                if info:
                    playlog.update(info)
                    self.is_playing = info.is_playing
                    self.duration_ms = info.duration_ms
                    self.set_position(info.progress_ms)
                    if time.monotonic() - self._repeat_set_at >= _SHUFFLE_SETTLE_SECS:
                        self.repeat_state = info.repeat_state
                    self.track_number, self.total_tracks = info.track_number, info.total_tracks
                    self.album_name = info.album_name
                    if info.album_uri != self.album_uri:
                        self.album_uri, self.album_length_ms = info.album_uri, None
                        if info.album_uri and info.album_uri.startswith("spotify:album:"):
                            try:
                                from spotifactory.spotify import album_length_ms
                                self.album_length_ms = album_length_ms(info.album_uri)
                            except Exception as e:
                                print(f"[home] album length: {e}", flush=True)
                else:
                    playlog.nothing()
                    self.is_playing = False
                if info and not info.is_playing:
                    info = None
                if info:
                    self.status = info.track_name
                    self.artist = info.artist_name
                    if time.monotonic() - self._shuffle_set_at >= _SHUFFLE_SETTLE_SECS:
                        self.shuffle_active = info.shuffle_active
                elif _active_uri is None:
                    # Tag was removed between poll scheduling and this call.
                    self.status = "Place tag..."
                    self.artist = ""
                    self.shuffle_active = False
                # else: tag still present but Spotify not reflecting playback yet — keep "Loading..."
            except Exception as e:
                playlog.error(e)

        def on_place(card: dict) -> None:
            nonlocal _active_uri, _soco_speaker, last_poll, carry_until
            uri = card.get("uri")
            if not uri:
                return
            print(f"[home] tag placed {card['uid']} → {uri}", flush=True)
            _active_uri = uri  # set regardless so on_remove can pause if needed
            playlog.reset(uri)
            same = carry_until and uri == self.tag_uri    # back from the menu, same album
            carry_until = 0.0
            self.tag_active = True
            self.tag_uri = uri
            self.screen_off = False
            if not same:
                self.status = "Loading..."
                self.artist = ""
            # Poll as soon as possible — on_poll now guards against resetting "Loading..."
            # to "Place tag..." if Spotify hasn't reflected the new state yet.
            last_poll = time.monotonic() - _POLL_INTERVAL_SECS
            if ctx.dry_run:
                print(f"[home] dry_run: would start_playback {uri}", flush=True)
                return
            try:
                import spotipy

                from spotifactory.spotify import (
                    find_device_by_name,
                    get_active_device,
                    get_client,
                    get_current_context,
                    get_playback_device,
                    resolve_chosen_device,
                )

                # Check if we're already in this album context (even if paused).
                # If so, resume rather than restart from track 1.
                _ctx_uri, _alb_uri = get_current_context()
                _in_context = (_ctx_uri == uri or _alb_uri == uri)

                def _play(device_id: str) -> None:
                    if _in_context:
                        get_client().start_playback(device_id=device_id)
                    else:
                        get_client().start_playback(context_uri=uri, device_id=device_id)

                verb = "resume" if _in_context else "start"

                # Tier 1: the speaker last picked in Choose Speaker (persisted).
                # No silent fallback — playing in a different room would be worse
                # than saying the chosen speaker isn't reachable.
                chosen = get_active_device()
                if chosen is not None:
                    label = chosen.name or "Chosen speaker"
                    dev_id = resolve_chosen_device(chosen)
                    if dev_id is None:
                        print(f"[home] chosen device {label!r} not listed by Spotify", flush=True)
                        self.status = label
                        self.artist = "not available"
                        return
                    print(f"[home] {verb} {uri} on chosen device {label!r} ({dev_id})", flush=True)
                    try:
                        _play(dev_id)
                    except spotipy.SpotifyException as e:
                        # Idle Echos stay listed but 404 until woken.
                        print(f"[home] chosen device {label!r} didn't respond: {e}", flush=True)
                        self.status = label
                        self.artist = "not responding"
                    _soco_speaker = None
                    return

                # Tier 2: Default to local Raspotify instance
                raspotify = find_device_by_name("Spotifactory")
                if raspotify:
                    dev_id = raspotify["id"]
                    print(f"[home] {verb} {uri} on Raspotify {dev_id!r}", flush=True)
                    try:
                        get_client().transfer_playback(dev_id, force_play=False)
                    except Exception:
                        pass
                    _play(dev_id)
                    _soco_speaker = None
                    return

                # Tier 3: Fall back to active Spotify device (Raspotify not yet auth'd)
                dev = get_playback_device()
                if dev.restricted:
                    # Sonos S2: programmatic play not supported (see docs/sonos.md).
                    print(f"[home] device {dev.name!r} is restricted — pause only via SoCo", flush=True)
                    _soco_speaker = dev.name
                    self.status = "Start in Spotify,"
                    self.artist = "tag removes pauses"
                    return
                if dev.device_id is None:
                    self.status = "No speaker:"
                    self.artist = "Up > Choose Speaker"
                    return
                print(f"[home] {verb} {uri} on device {dev.device_id!r}", flush=True)
                _play(dev.device_id)
                _soco_speaker = None
            except Exception as e:
                reason = getattr(e, "reason", None)
                if reason == "NO_ACTIVE_DEVICE" or "restricted device" in str(e).lower():
                    self.status = "No speaker:"
                    self.artist = "Up > Choose Speaker"
                else:
                    print(f"[home] start_playback error: {e}", flush=True)
                    self.status = "Couldn't play"
                    self.artist = "try again"
                _soco_speaker = None

        def on_remove(card: dict) -> None:
            nonlocal _active_uri, _soco_speaker
            if not _active_uri:
                return
            if self._cancel.is_set():
                # user navigated away — nfcpy fires on_release as it exits, ignore it
                _active_uri = None
                _soco_speaker = None
                return
            print(f"[home] tag removed {card['uid']}", flush=True)
            if not ctx.dry_run:
                if _soco_speaker:
                    from spotifactory.hardware.sonos import pause_speaker
                    pause_speaker(_soco_speaker)
                else:
                    try:
                        from spotifactory.spotify import get_client
                        get_client().pause_playback()
                    except Exception as e:
                        print(f"[home] pause_playback error: {e}", flush=True)
            _active_uri = None
            _soco_speaker = None
            self.tag_active = False
            self.tag_uri = None
            self.status = "Place tag..."
            self.artist = ""
            self.shuffle_active = False
            self.repeat_state = "off"
            self.is_playing = False
            self._idle_since = time.monotonic()

        def check_idle() -> None:
            if _active_uri is None and not self.screen_off:
                if time.monotonic() - self._idle_since >= _SCREEN_OFF_SECS:
                    self.screen_off = True

        def check_sim() -> None:
            sim = self._sim_tag
            if sim is not None:
                self._sim_tag = None
                on_place({"uid": f"sim:{sim}", "uri": sim})

        def check_carry() -> None:
            nonlocal carry_until
            # The remembered screen, but its tag hasn't turned up: it was lifted
            # while in the menu.
            if carry_until == float("inf"):
                carry_until = time.monotonic() + _CARRY_SECS
            if carry_until and _active_uri is None and time.monotonic() >= carry_until:
                carry_until = 0.0
                self.tag_active, self.tag_uri, self.is_playing = False, None, False
                self.status, self.artist = "Place tag...", ""
                self.shuffle_active, self.repeat_state = False, "off"

        def terminate() -> bool:
            check_sim()
            check_carry()
            on_poll()
            check_idle()
            return self._cancel.is_set()

        # --- attempt real RFID ---
        # watch_tags blocks until terminate() returns True, then nfcpy spends
        # ~1-2s tearing down the ContactlessFrontend. Run it in a daemon thread
        # so we can return Cancel() the instant cancel is set without waiting
        # for hardware teardown to complete.
        try:
            from spotifactory.hardware.rfid import current_port, watch_tags
            print(f"[home] opening RFID reader on {current_port()!r}…", flush=True)

            _rfid_exc: list[Exception] = []
            _rfid_done = threading.Event()

            def _run_rfid() -> None:
                try:
                    while not self._cancel.is_set():
                        watch_tags(on_place=on_place, on_remove=on_remove, terminate=terminate)
                        if not self._cancel.is_set():
                            # nfcpy exited without cancel — PN532 supervision dropped.
                            # Reopen the reader so the home screen keeps working, with
                            # a pause so a reader that keeps failing instantly doesn't
                            # spin reopening the serial port.
                            print("[home] RFID: restarting after unexpected exit", flush=True)
                            self._cancel.wait(1.0)
                except Exception as exc:
                    _rfid_exc.append(exc)
                finally:
                    _rfid_done.set()

            threading.Thread(target=_run_rfid, daemon=True).start()

            while not self._cancel.is_set() and not _rfid_done.is_set():
                self._cancel.wait(timeout=0.05)

            if _rfid_exc:
                raise _rfid_exc[0]  # trigger soft-wait fallback below

        except Exception as exc:
            available = []
            try:
                import glob
                available = (
                    glob.glob("/dev/cu.usbserial*")
                    + glob.glob("/dev/tty.usbserial*")
                    + glob.glob("/dev/ttyUSB*")
                    + glob.glob("/dev/ttyAMA*")
                )
            except Exception:
                pass
            print(
                f"[home] RFID unavailable ({type(exc).__name__}: {exc})\n"
                f"[home]   available: {available or ['(none found)']}\n"
                f"[home]   replug the USB reader — will retry every 30 s",
                flush=True,
            )
            sys.stderr.flush()
            self.status = "Replug RFID reader"
            self.artist = ""

            _next_rfid_retry = time.monotonic() + 30.0

            while not self._cancel.is_set():
                terminate()
                self._cancel.wait(timeout=0.05)

                if time.monotonic() >= _next_rfid_retry and not self._cancel.is_set():
                    _next_rfid_retry = time.monotonic() + 30.0
                    print("[home] retrying RFID connection…", flush=True)
                    try:
                        watch_tags(
                            on_place=on_place, on_remove=on_remove,
                            terminate=terminate,
                        )
                        # watch_tags exited cleanly — terminate() returned True
                        break
                    except Exception:
                        pass  # still not available; keep waiting

        return Cancel()
