from __future__ import annotations

import sys
import threading
import time

import spotipy

from spotifactory.tasks.base import (
    Cancel,
    Continue,
    Step,
    StepOutcome,
    TaskContext,
)

_POLL_INTERVAL_SECS = 5.0  # how often to refresh now-playing from Spotify


class HomeScanStep(Step):
    """Waits for an RFID tag while showing now-playing info.

    Always attempts the real hardware first.  If the RFID reader is not
    accessible (OSError, ImportError, etc.) it falls back to a soft-wait loop
    that can be unblocked with simulate_scan() — useful for Mac dev when the
    reader is temporarily unavailable.

    Loops back to itself via Continue(next_step="scan") so the home screen
    remains active until the user navigates to the main menu (Up → Cancel).
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

    def run(self, ctx: TaskContext) -> StepOutcome:
        self._cancel.clear()
        self._sim_tag = None
        self.status = "Place tag..."
        self.artist = ""
        self.shuffle_active = False
        last_poll = 0.0

        def on_poll() -> None:
            nonlocal last_poll
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

        def sim_tag_set() -> bool:
            return self._sim_tag is not None

        # --- attempt real hardware ---
        card = None
        try:
            from spotifactory.rfid import PORT, read_card_cancellable
            print(f"[home] opening RFID reader on {PORT!r}…", flush=True)
            card = read_card_cancellable(
                self._cancel,
                on_poll=on_poll,
                also_stop=sim_tag_set,
            )
            print(f"[home] RFID returned card={card}", flush=True)
        except Exception as exc:
            import glob
            available = (
                glob.glob("/dev/cu.usbserial*")
                + glob.glob("/dev/tty.usbserial*")
                + glob.glob("/dev/ttyUSB*")
                + glob.glob("/dev/ttyAMA*")
            )
            print(
                f"[home] RFID unavailable ({type(exc).__name__}: {exc})\n"
                f"[home]   tried port: {PORT!r}\n"
                f"[home]   available:  {available or ['(none found)']}\n"
                f"[home]   set NFC_PORT env var to override",
                flush=True,
            )
            sys.stderr.flush()
            # Fall back to soft-wait; t-key / simulate_scan() still works
            print("[home] entering soft-wait (press t to simulate a tag)", flush=True)
            while not self._cancel.is_set() and self._sim_tag is None:
                on_poll()
                time.sleep(0.1)
            print("[home] soft-wait exited", flush=True)

        # --- resolve outcome ---
        if self._cancel.is_set():
            return Cancel()

        if self._sim_tag is not None:
            ctx.data["uri"] = self._sim_tag
            return Continue()

        if not card or "uri" not in card:
            self.show_for("No URI on tag", 2.0)
            if self._cancel.is_set():
                return Cancel()
            return Continue(next_step="scan")

        ctx.data["uri"] = card["uri"]
        return Continue()


class HomePlayStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Starting playback..."
        if ctx.dry_run:
            time.sleep(0.5)
            return Continue()
        try:
            from spotifactory.spotify import get_client
            get_client().start_playback(context_uri=ctx.data["uri"])
        except spotipy.SpotifyException as e:
            msg = "No active device" if "device" in str(e).lower() else "Spotify error"
            self.show_for(msg, 3.0)
            return Continue(next_step="scan")
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Continue(next_step="scan")
        return Continue()


class HomeDoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.show_for("Playing!", 2.0)
        return Continue(next_step="scan")
