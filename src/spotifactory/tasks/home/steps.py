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

_POLL_INTERVAL_SECS = 1.0   # how often to refresh now-playing display from Spotify


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

    def cancel(self) -> None:
        self._cancel.set()

    def simulate_scan(self, uri: str) -> None:
        """Inject a virtual tag scan; works in both hardware and fallback modes."""
        self._sim_tag = uri

    # ------------------------------------------------------------------

    def run(self, ctx: TaskContext) -> StepOutcome:
        self._cancel.clear()
        self._sim_tag = None
        self.status = "Place tag..."
        self.artist = ""
        self.shuffle_active = False

        _active_uri: str | None = None
        _device_error: bool = False
        last_poll = 0.0

        def on_poll() -> None:
            nonlocal last_poll
            if _device_error:
                return  # keep error visible until next successful scan
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
            nonlocal _active_uri, _device_error
            uri = card.get("uri")
            if not uri:
                return
            print(f"[home] tag placed {card['uid']} → {uri}", flush=True)
            _active_uri = uri  # set regardless so on_remove can pause if needed
            if ctx.dry_run:
                print(f"[home] dry_run: would start_playback {uri}", flush=True)
                return
            try:
                from spotifactory.spotify import get_now_playing, get_client
                info = get_now_playing()
                if info and info.album_uri == uri:
                    print(f"[home] already playing {uri}, skipping start_playback", flush=True)
                    return
                get_client().start_playback(context_uri=uri)
                _device_error = False
            except Exception as e:
                if getattr(e, "reason", None) == "NO_ACTIVE_DEVICE":
                    _device_error = True
                    self.status = "No active device"
                    self.artist = "Go to Choose Speaker"
                else:
                    print(f"[home] start_playback error: {e}", flush=True)

        def on_remove(card: dict) -> None:
            nonlocal _active_uri
            if not _active_uri:
                return
            if self._cancel.is_set():
                # user navigated away — nfcpy fires on_release as it exits, ignore it
                _active_uri = None
                return
            print(f"[home] tag removed {card['uid']}", flush=True)
            if not ctx.dry_run:
                try:
                    from spotifactory.spotify import get_now_playing, get_client
                    info = get_now_playing()
                    if info and info.album_uri == _active_uri:
                        get_client().pause_playback()
                except Exception as e:
                    print(f"[home] pause_playback error: {e}", flush=True)
            _active_uri = None

        def check_sim() -> None:
            sim = self._sim_tag
            if sim is not None:
                self._sim_tag = None
                on_place({"uid": f"sim:{sim}", "uri": sim})

        def terminate() -> bool:
            check_sim()
            on_poll()
            return self._cancel.is_set()

        # --- attempt real RFID ---
        try:
            from spotifactory.hardware.rfid import PORT, watch_tags
            print(f"[home] opening RFID reader on {PORT!r}…", flush=True)
            watch_tags(on_place=on_place, on_remove=on_remove, terminate=terminate, port=PORT)

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
                time.sleep(0.1)

        return Cancel()
