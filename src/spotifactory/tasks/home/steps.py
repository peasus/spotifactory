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


class HomeScanStep(Step):
    """Event-driven RFID home screen.

    Uses nfcpy supervision mode so the PN532 fires on_place/on_remove natively —
    no application-level polling for tag presence. The step runs until the user
    navigates away (cancel).

    Behaviour:
      tag placed (new)  → start_playback for that album
      tag still present → no-op (PN532 supervises; on_place is not re-fired)
      tag removed       → pause if Spotify is still on the album we started
    """

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._sim_tag: str | None = None
        self.artist: str = ""
        self.shuffle_active: bool = False
        self.screen_off: bool = False
        self._idle_since: float = time.monotonic()

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
        self._idle_since = time.monotonic()

        _active_uri: str | None = None
        _soco_speaker: str | None = None  # set when active device is Sonos (restricted)
        last_poll = 0.0

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
                info = get_now_playing()
                if info:
                    self.status = info.track_name
                    self.artist = info.artist_name
                    self.shuffle_active = info.shuffle_active
                else:
                    self.status = "Place tag..."
                    self.artist = ""
                    self.shuffle_active = False
            except Exception:
                pass

        def on_place(card: dict) -> None:
            nonlocal _active_uri, _soco_speaker, last_poll
            uri = card.get("uri")
            if not uri:
                return
            print(f"[home] tag placed {card['uid']} → {uri}", flush=True)
            _active_uri = uri  # set regardless so on_remove can pause if needed
            self.screen_off = False
            self.status = "Loading..."
            self.artist = ""
            # Schedule a poll ~1.5 s from now — gives Spotify time to start before we query.
            last_poll = time.monotonic() - _POLL_INTERVAL_SECS + 1.5
            if ctx.dry_run:
                print(f"[home] dry_run: would start_playback {uri}", flush=True)
                return
            try:
                from spotifactory.spotify import (
                    get_active_device, find_device_by_name, get_current_context,
                    get_playback_device, get_client,
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

                # Tier 1: User explicitly chose a device via Choose Speaker
                if get_active_device() is not None:
                    dev = get_playback_device()
                    print(f"[home] {'resume' if _in_context else 'start'} {uri} on chosen device {dev.device_id!r}", flush=True)
                    _play(dev.device_id)
                    _soco_speaker = None
                    return

                # Tier 2: Default to local Raspotify instance
                raspotify = find_device_by_name("Spotifactory")
                if raspotify:
                    dev_id = raspotify["id"]
                    print(f"[home] {'resume' if _in_context else 'start'} {uri} on Raspotify {dev_id!r}", flush=True)
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
                    self.status = "Open Spotify:"
                    self.artist = "select Spotifactory"
                    return
                print(f"[home] {'resume' if _in_context else 'start'} {uri} on device {dev.device_id!r}", flush=True)
                _play(dev.device_id)
                _soco_speaker = None
            except Exception as e:
                reason = getattr(e, "reason", None)
                if reason == "NO_ACTIVE_DEVICE" or "restricted device" in str(e).lower():
                    self.status = "Select speaker in"
                    self.artist = "Spotify app first"
                else:
                    print(f"[home] start_playback error: {e}", flush=True)
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
                        from spotifactory.spotify import get_now_playing, get_client
                        info = get_now_playing()
                        if info and info.album_uri == _active_uri:
                            get_client().pause_playback()
                    except Exception as e:
                        print(f"[home] pause_playback error: {e}", flush=True)
            _active_uri = None
            _soco_speaker = None
            self.status = "Place tag..."
            self.artist = ""
            self.shuffle_active = False
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

        def terminate() -> bool:
            check_sim()
            on_poll()
            check_idle()
            return self._cancel.is_set()

        # --- attempt real RFID ---
        # watch_tags blocks until terminate() returns True, then nfcpy spends
        # ~1-2s tearing down the ContactlessFrontend. Run it in a daemon thread
        # so we can return Cancel() the instant cancel is set without waiting
        # for hardware teardown to complete.
        try:
            from spotifactory.hardware.rfid import PORT, watch_tags
            print(f"[home] opening RFID reader on {PORT!r}…", flush=True)

            _rfid_exc: list[Exception] = []
            _rfid_done = threading.Event()

            def _run_rfid() -> None:
                try:
                    watch_tags(on_place=on_place, on_remove=on_remove, terminate=terminate, port=PORT)
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
                f"[home]   entering soft-wait (press t to simulate a tag)",
                flush=True,
            )
            sys.stderr.flush()

            while not self._cancel.is_set():
                terminate()
                self._cancel.wait(timeout=0.05)

        return Cancel()
