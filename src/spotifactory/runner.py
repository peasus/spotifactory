from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Type

from spotifactory.display import icons, lcd
from spotifactory.menu.definitions import MenuDef
from spotifactory.menu.navigation import NavStack
from spotifactory.tasks.base import (
    Cancel,
    Continue,
    Done,
    PushMenu,
    StepOutcome,
    Task,
    TaskContext,
)

# Tags only work on the home screen, so a menu left open would make the
# device look broken — return home after this long without input.
_MENU_IDLE_SECS = 60.0
_SCROLL_X = 125           # scrollbar occupies x 125-127 on the 128 px display

# Menu action -> (systemctl verb, what the screen says meanwhile). Needs the
# passwordless sudo rule for these from deploy/setup.sh.
_POWER = {"reboot": ("reboot", "Rebooting..."), "shutdown": ("poweroff", "Shutting down...")}

# The auto-updater (deploy/update.sh) and the app talk through files here: the
# app's heartbeat (is it up, and is someone using it), a request for an
# update now, and the result of the last update.
_VOLUME_STEP = 5                    # percent per press of a volume button
_VOLUME_SHOW_SECS = 1.5             # how long the volume bar stays up
_VOLUME_FRESH_SECS = 3.0            # trust our own idea of the volume this long after setting it

# Holding left/right on the home screen scrubs through the track, like a CD
# player's search: each hold tick moves the target, faster the longer it's held.
_SEEK_STEP_MS = 5_000
_SEEK_FAST_STEP_MS = 15_000
_SEEK_FAST_AFTER = 2.0              # seconds held before the bigger steps
_SEEK_SEND_EVERY = 0.8              # seconds between seeks sent while held (plus one on release)
_SEEK_SHOW_SECS = 1.5               # how long the position stays up after letting go

_REPEAT_NEXT = {"off": "context", "context": "track", "track": "off"}

# Pressing the joystick on the home screen cycles these, like a CD player's DISP.
_DISPLAY_MODES = ("now", "time", "album")

_HEARTBEAT_SECS = 10.0
_BUSY_AFTER_INPUT_SECS = 120.0      # menus touched this recently: someone's using it
_UPDATED_NOTE_SECS = 15 * 60        # show "Updated" if the app restarted this soon after


def state_dir() -> Path:
    return Path(os.environ.get("SPOTIFACTORY_STATE", "~/.cache/spotifactory")).expanduser()


def _clock(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class Runner:
    """Platform-agnostic loop driver.

    The platform runner (simulated or Pi) calls handle_*/tick/render on each
    iteration — it never needs to know what task is running or what state it's in.
    """

    def __init__(
        self,
        display: Any,
        menus: dict[str, MenuDef],
        dry_run: bool = True,
        printer_dry_run: bool = False,
        home_task_class: Optional[Type[Task]] = None,
    ) -> None:
        self.display = display
        self.menus = menus
        self.dry_run = dry_run
        self.printer_dry_run = printer_dry_run
        self.nav = NavStack(menus["main"])
        self._task: Task | None = None
        self._pushed_menu: PushMenu | None = None
        self._home_task_class = home_task_class
        self._home_blanked: bool = False
        self._last_input: float = time.monotonic()
        self._shuffle_busy: bool = False
        self._message: tuple[str, str, float | None] | None = None   # (line 1, line 2, until)
        self._last_beat: float = 0.0
        self._volume: int | None = None              # last volume we set or read
        self._volume_at: float = 0.0
        self._volume_shown_until: float = 0.0
        self._volume_pending = 0                     # presses not yet sent to Spotify
        self._volume_lock = threading.Lock()
        self._volume_sending = False
        self._repeat_busy: bool = False
        self._display_mode = _DISPLAY_MODES[0]
        self._skip_on_release = 0                    # -1/+1: a left/right tap waiting to be let go
        self._swallow_release = False                # that press woke the screen; ignore its hold
        self._seek_target: int | None = None         # ms; set while scrubbing
        self._seek_started = 0.0
        self._seek_released = False
        self._seek_shown_until = 0.0
        self._seek_lock = threading.Lock()
        self._seek_sending = False
        self._note_recent_update()

        if home_task_class is not None:
            print(f"[runner] starting home task: {home_task_class.__name__}", flush=True)
            self._start_task(home_task_class)
            print(f"[runner] home task started, task={self._task}", flush=True)

    # ------------------------------------------------------------------
    # Input handlers — called by the platform runner
    # ------------------------------------------------------------------

    def handle_up(self) -> None:
        self._last_input = time.monotonic()
        if self._in_home_scan():
            if self._wake_if_sleeping():
                return
            self._cycle_repeat()
            return
        if self._accepting_nav_input:
            self.nav.current.move_up()

    def _open_menu_from_home(self) -> None:
        if self._wake_if_sleeping():
            return
        from spotifactory.tasks.home.steps import HomeScanStep
        step = self._task.current_step
        if isinstance(step, HomeScanStep):
            HomeScanStep.remember(step)      # so it comes back as it was
        step.cancel()                        # the home task ends; the menu shows

    def handle_down(self) -> None:
        self._last_input = time.monotonic()
        if self._in_qr_auth():
            self._task.current_step.toggle_url()
            return
        if self._in_home_scan():
            if self._wake_if_sleeping():
                return
            self._toggle_shuffle()
            return
        if self._accepting_nav_input:
            self.nav.current.move_down()

    def handle_left(self) -> None:
        self._last_input = time.monotonic()
        if self._in_home_mode():
            self._home_skip_pressed(-1)
            return
        # In a menu or a running task: treat left as Back
        self.handle_back()

    def handle_right(self) -> None:
        self._last_input = time.monotonic()
        if self._in_qr_auth():
            self._task.current_step.toggle_url()
            return
        if self._in_home_mode():
            self._home_skip_pressed(+1)
        else:
            self.handle_select()

    # Left/right on the home screen: a tap skips when it's let go, a hold
    # scrubs through the track. Platforms without hold/release events call
    # handle_release right after handle_left/right, so a press just skips.

    def _home_skip_pressed(self, direction: int) -> None:
        if self._wake_if_sleeping():
            self._swallow_release = True
            return
        self._skip_on_release = direction

    def handle_release(self, direction: int) -> None:
        """Left (-1) or right (+1) let go."""
        self._last_input = time.monotonic()
        skip, self._skip_on_release = self._skip_on_release, 0
        if self._swallow_release:
            self._swallow_release = False
            return
        with self._seek_lock:
            seeking = self._seek_target is not None
            if seeking:
                self._seek_released = True
                start = not self._seek_sending
                self._seek_sending = True
        if seeking:
            if start:
                threading.Thread(target=self._send_seek, daemon=True).start()
            return
        if skip == direction and self._in_home_scan():
            self._next_track() if direction > 0 else self._prev_track()

    def handle_seek_hold(self, direction: int) -> None:
        """Left (-1) or right (+1) still held: move the scrub target on."""
        self._last_input = time.monotonic()
        if self._swallow_release or not self._in_home_scan():
            return
        step = self._task.current_step
        now = time.monotonic()
        with self._seek_lock:
            if self._seek_target is None:
                if not step.tag_active or not step.duration_ms:
                    return                      # nothing to scrub through
                self._seek_target = step.position_ms()
                self._seek_started = now
            self._skip_on_release = 0
            self._seek_released = False
            fast = now - self._seek_started >= _SEEK_FAST_AFTER
            jump = _SEEK_FAST_STEP_MS if fast else _SEEK_STEP_MS
            self._seek_target = max(0, min(step.duration_ms - 1000, self._seek_target + direction * jump))
            self._seek_shown_until = now + _SEEK_SHOW_SECS
            start = not self._seek_sending
            self._seek_sending = True
        if start:
            threading.Thread(target=self._send_seek, daemon=True).start()

    def _send_seek(self) -> None:
        """Send the scrub target to Spotify about once a second while held, and
        once more when let go; then stop scrubbing."""
        step = self._task.current_step if self._in_home_scan() else None
        sent, sent_at = None, 0.0
        try:
            from spotifactory.spotify import seek
            while True:
                with self._seek_lock:
                    target, released = self._seek_target, self._seek_released
                    if target is None:
                        return
                    if released and target == sent:
                        self._seek_target = None
                        return
                if target != sent and (released or time.monotonic() - sent_at >= _SEEK_SEND_EVERY):
                    seek(target)
                    sent, sent_at = target, time.monotonic()
                    if step is not None:
                        step.set_position(target)
                else:
                    time.sleep(0.05)
        except Exception as e:
            print(f"[runner] seek: {e}", flush=True)
            with self._seek_lock:
                self._seek_target = None
            self._message = ("Couldn't skip", "through the track", time.monotonic() + 2.0)
        finally:
            with self._seek_lock:
                again = self._seek_target is not None     # held again as we finished
                self._seek_sending = again
            if again:
                threading.Thread(target=self._send_seek, daemon=True).start()

    def handle_select(self) -> None:
        self._last_input = time.monotonic()
        if self._in_home_scan():
            if not self._wake_if_sleeping():
                i = _DISPLAY_MODES.index(self._display_mode)
                self._display_mode = _DISPLAY_MODES[(i + 1) % len(_DISPLAY_MODES)]
            return
        item = self.nav.current.selected_item

        if self._pushed_menu is not None:
            if item.action == "confirm":
                if item.data is not None and self._task is not None:
                    self._task.ctx.data["selected"] = item.data
                self._resolve(self._pushed_menu.on_confirm)
            elif item.action == "cancel":
                self._resolve(self._pushed_menu.on_cancel)
            return

        if self._task is not None:
            return  # background work running — ignore

        if item.task is not None:
            self._start_task(item.task)
        elif item.submenu and item.submenu in self.menus:
            self.nav.push(self.menus[item.submenu])
        elif item.action == "back":
            self.nav.pop()
        elif item.action == "home":
            self._return_home()
        elif item.action in _POWER:
            self._power(item.action)
        elif item.action == "update":
            self._check_for_updates()

    def handle_volume(self, direction: int) -> None:
        """Volume up (+1) or down (-1) by _VOLUME_STEP on the playing device.
        Presses that come in while Spotify is still answering are added up and
        sent together, so holding the button doesn't queue a backlog."""
        self._last_input = time.monotonic()
        if self._wake_if_sleeping():
            return
        with self._volume_lock:
            self._volume_pending += direction
            if self._volume_sending:
                return
            self._volume_sending = True
        threading.Thread(target=self._send_volume, daemon=True).start()

    def _send_volume(self) -> None:
        try:
            from spotifactory.spotify import get_volume, set_volume
            volume = self._volume
            if volume is None or time.monotonic() - self._volume_at > _VOLUME_FRESH_SECS:
                volume = get_volume()
            if volume is None:
                with self._volume_lock:
                    self._volume_pending = 0
                self._message = ("Volume:", "use the speaker", time.monotonic() + 2.0)
                return
            while True:
                with self._volume_lock:
                    presses, self._volume_pending = self._volume_pending, 0
                if not presses:
                    return
                volume = max(0, min(100, volume + presses * _VOLUME_STEP))
                self._volume, self._volume_at = volume, time.monotonic()
                self._volume_shown_until = time.monotonic() + _VOLUME_SHOW_SECS
                set_volume(volume)
        except Exception as e:
            print(f"[runner] volume: {e}", flush=True)
            with self._volume_lock:
                self._volume_pending = 0
            self._message = ("Couldn't change", "the volume", time.monotonic() + 2.0)
        finally:
            with self._volume_lock:
                self._volume_sending = False
            if self._volume_pending:          # a press came in as we finished
                self.handle_volume(0)

    def handle_menu(self) -> None:
        """The menu button (the bottom one): opens the menu from home and closes it again,
        straight back to home from any depth. Over a prompt or a running step
        it's Back."""
        self._last_input = time.monotonic()
        if self._in_home_mode():
            if self._in_home_scan():
                self._open_menu_from_home()
            return
        if self._pushed_menu is not None or self._task is not None:
            self.handle_back()
            return
        if self._wake_if_sleeping():
            return
        while self.nav.pop():
            pass
        if self._home_task_class is not None:
            self._start_task(self._home_task_class)

    def handle_play_pause(self) -> None:
        """Not on a button (lifting the album pauses); the sim keeps it on space."""
        self._last_input = time.monotonic()
        if self._wake_if_sleeping():
            return

        def work() -> None:
            try:
                from spotifactory.spotify import play_pause
                playing = play_pause()
            except Exception as e:
                print(f"[runner] play/pause: {e}", flush=True)
                playing = "error"
            note = {True: "Playing", False: "Paused", None: "Nothing to play"}.get(playing, "Couldn't do that")
            self._message = (note, "", time.monotonic() + 1.2)

        threading.Thread(target=work, daemon=True).start()

    def handle_tag_scan_sim(self, uri: str = "spotify:album:5Z9iiGl2FcIfa3BMiv6OIw") -> None:
        """Simulate an RFID tag scan (sim / dry_run mode). Press T in the sim."""
        from spotifactory.tasks.home.steps import HomeScanStep
        if (
            self._in_home_scan()
            and isinstance(self._task.current_step, HomeScanStep)
        ):
            self._task.current_step.simulate_scan(uri)

    def handle_back(self) -> None:
        self._last_input = time.monotonic()
        if self._wake_if_sleeping():
            return
        if self._pushed_menu is not None:
            self._resolve(self._pushed_menu.on_cancel)
        elif self._in_home_scan():
            self._open_menu_from_home()     # boards without a menu button, and the sim
        elif self._task is None:
            if not self.nav.pop() and self._home_task_class is not None:
                self._start_task(self._home_task_class)
        elif not self._in_home_mode():
            self._cancel_running_step()

    # ------------------------------------------------------------------
    # Tick — advance task state; call on every loop iteration
    # ------------------------------------------------------------------

    def tick(self) -> None:
        self._beat()
        self._return_home_if_idle()
        if self._task is None:
            return
        if self._pushed_menu is not None:
            return
        step = self._task.current_step
        if step is None or not step.is_done:
            return
        self._resolve(step.outcome)

    # ------------------------------------------------------------------
    # Render — draw current state to the display
    # ------------------------------------------------------------------

    def render(self) -> None:
        if self._volume is not None and time.monotonic() < self._volume_shown_until:
            self._render_volume(self._volume)
            return
        if self._message is not None:
            line1, line2, until = self._message
            if until is None or time.monotonic() < until:
                self.display.clear()
                self.display.draw_text(2, 18, line1)
                self.display.draw_text(2, 34, line2)
                self.display.update()
                return
            self._message = None

        if self._in_qr_auth():
            self._render_qr_auth()
            return

        if self._in_home_scan():
            self._render_home()
            return

        if (
            self._task
            and self._task.current_step
            and not self._task.current_step.is_done
        ):
            self._render_status(self._task.current_step)
            return

        self._render_menu()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _in_home_mode(self) -> bool:
        """True whenever the HomeTask is active (any step, no pushed menu)."""
        return (
            self._home_task_class is not None
            and isinstance(self._task, self._home_task_class)
            and self._pushed_menu is None
        )

    def _in_qr_auth(self) -> bool:
        """True while QRAuthStep is showing its QR code (qr_image is set)."""
        from spotifactory.tasks.reauth.steps import QRAuthStep
        return (
            self._task is not None
            and self._task.current_step is not None
            and isinstance(self._task.current_step, QRAuthStep)
            and not self._task.current_step.is_done
            and getattr(self._task.current_step, "qr_image", None) is not None
        )

    def _in_home_scan(self) -> bool:
        """True only during the HomeScanStep (home-screen rendering)."""
        from spotifactory.tasks.home.steps import HomeScanStep
        return (
            self._in_home_mode()
            and self._task.current_step is not None
            and isinstance(self._task.current_step, HomeScanStep)
            and not self._task.current_step.is_done
        )

    @property
    def _accepting_nav_input(self) -> bool:
        return self._pushed_menu is not None or self._task is None

    def _start_task(self, task_class: type) -> None:
        ctx = TaskContext(display=self.display, dry_run=self.dry_run, printer_dry_run=self.printer_dry_run)
        self._task = task_class(ctx)
        self._task.start_current_step()

    def _cancel_running_step(self) -> None:
        """Ask the current step to stop, if it supports it (QR auth, tag write, prompts)."""
        step = self._task.current_step if self._task else None
        if step is not None and not step.is_done and hasattr(step, "cancel"):
            step.cancel()

    def _return_home_if_idle(self) -> None:
        if self._home_task_class is None:
            return
        if time.monotonic() - self._last_input < _MENU_IDLE_SECS:
            return
        if self._pushed_menu is not None:
            self._resolve(self._pushed_menu.on_cancel)  # Cancel → home
        elif self._task is None:
            while self.nav.pop():
                pass
            self._start_task(self._home_task_class)

    def _show(self, line1: str, line2: str = "", seconds: float | None = None) -> None:
        """A full-screen message; stays up until `seconds` pass (or for good if None)."""
        self._message = (line1, line2, None if seconds is None else time.monotonic() + seconds)
        self.render()

    def _power(self, action: str) -> None:
        """Reboot or power off the Pi. Off the Pi (the simulator), just say so."""
        verb, label = _POWER[action]
        if not sys.platform.startswith("linux"):
            print(f"[runner] {action}: not on the Pi, ignoring", flush=True)
            self._show(label, "(simulator: no)", 2.0)
            return
        self._show(label, "")
        try:
            # -n: fail at once rather than wait for a password nobody can type
            result = subprocess.run(["sudo", "-n", "systemctl", verb],
                                    capture_output=True, text=True, timeout=15)
            error = "" if result.returncode == 0 else (result.stderr.strip() or f"exit {result.returncode}")
        except Exception as e:
            error = str(e)
        if error:
            print(f"[runner] {action} failed: {error}", flush=True)
            self._show(f"Couldn't {'reboot' if action == 'reboot' else 'shut down'}", "Run setup.sh again", 5.0)

    def _busy(self) -> bool:
        """Is someone using the box? Then the nightly update waits."""
        if time.monotonic() - self._last_input < _BUSY_AFTER_INPUT_SECS:
            return True
        if self._in_home_scan():
            return bool(getattr(self._task.current_step, "tag_active", False))
        return self._task is not None and not self._in_home_mode()   # printing, pairing...

    def _beat(self) -> None:
        """Tell the updater the app is up (and whether it's in use). Only under
        systemd, which sets INVOCATION_ID: not in tests or the simulator."""
        if not os.environ.get("INVOCATION_ID"):
            return
        now = time.monotonic()
        if now - self._last_beat < _HEARTBEAT_SECS:
            return
        self._last_beat = now
        try:
            state_dir().mkdir(parents=True, exist_ok=True)
            (state_dir() / "heartbeat").write_text("busy\n" if self._busy() else "idle\n")
        except OSError as e:
            print(f"[runner] heartbeat: {e}", flush=True)

    def _note_recent_update(self) -> None:
        """Just restarted by an update? Say so for a moment."""
        try:
            path = state_dir() / "update-status"
            words = path.read_text().split()
            fresh = time.time() - path.stat().st_mtime < _UPDATED_NOTE_SECS
        except OSError:
            return
        if fresh and words[:1] == ["updated"]:
            self._message = ("Updated", words[1] if len(words) > 1 else "", time.monotonic() + 4.0)

    def _check_for_updates(self) -> None:
        """Run the updater now (even though someone's using the box). If there's
        an update, it restarts the app; otherwise say what happened."""
        if not sys.platform.startswith("linux"):
            self._show("Check for updates", "(simulator: no)", 2.0)
            return
        self._show("Checking for", "updates...")

        def work() -> None:
            try:
                state_dir().mkdir(parents=True, exist_ok=True)
                (state_dir() / "update-requested").touch()
                result = subprocess.run(["sudo", "-n", "systemctl", "start", "spotifactory-update"],
                                        capture_output=True, text=True, timeout=900)
                error = result.stderr.strip() if result.returncode else ""
            except Exception as e:
                error = str(e)
            try:
                words = (state_dir() / "update-status").read_text().split()
            except OSError:
                words = []
            if words[:1] == ["current"]:
                note = ("Up to date", words[1] if len(words) > 1 else "")
            elif words[:2] == ["rolled", "back"]:
                note = ("Update failed", "kept the old one")
            elif words[:1] == ["error"]:
                note = ("Couldn't update", "no internet?")
            else:
                print(f"[runner] update: {error or words}", flush=True)
                note = ("Couldn't update", "Run setup.sh again")
            self._message = (*note, time.monotonic() + 5.0)    # the main loop draws it

        threading.Thread(target=work, daemon=True).start()

    def _prev_track(self) -> None:
        try:
            from spotifactory.spotify import prev_track
            prev_track()
        except Exception:
            pass

    def _next_track(self) -> None:
        try:
            from spotifactory.spotify import next_track
            next_track()
        except Exception:
            pass

    def _toggle_shuffle(self) -> None:
        """Flip the shuffle icon now, then confirm (or revert) from Spotify off the UI thread."""
        if self._shuffle_busy:
            return  # one change at a time — Spotify's state is stale mid-change
        step = self._task.current_step
        previous = step.shuffle_active
        step.set_shuffle(not previous)
        self._shuffle_busy = True

        def work() -> None:
            try:
                from spotifactory.spotify import toggle_shuffle
                confirmed = toggle_shuffle()
            except Exception as e:
                print(f"[runner] toggle_shuffle failed: {e}", flush=True)
                confirmed = None
            step.set_shuffle(previous if confirmed is None else confirmed)
            self._shuffle_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _cycle_repeat(self) -> None:
        """Repeat off → album/playlist → track → off, like a CD player's REPEAT.
        The icon changes now; Spotify confirms (or it reverts) off the UI thread."""
        if self._repeat_busy:
            return
        step = self._task.current_step
        previous = step.repeat_state
        state = _REPEAT_NEXT.get(previous, "off")
        step.set_repeat(state)
        self._repeat_busy = True

        def work() -> None:
            try:
                from spotifactory.spotify import set_repeat
                set_repeat(state)
            except Exception as e:
                print(f"[runner] repeat: {e}", flush=True)
                step.set_repeat(previous)
                self._message = ("Couldn't change", "repeat", time.monotonic() + 2.0)
            finally:
                self._repeat_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _wake_if_sleeping(self) -> bool:
        """Blank the display and eat the button press if the home screen is sleeping."""
        if not self._in_home_scan():
            return False
        step = self._task.current_step
        if not step.screen_off:
            return False
        step.wake()
        self._home_blanked = False
        return True

    def _return_home(self) -> None:
        """After a task ends, go back to the home screen — unless we're already
        in HomeTask (Up-key cancel path), in which case surface the menu."""
        if self._home_task_class is not None and not isinstance(self._task, self._home_task_class):
            self._start_task(self._home_task_class)
        else:
            self._task = None

    def _resolve(self, outcome: StepOutcome) -> None:
        if isinstance(outcome, Continue):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._task.advance(outcome.next_step)
            if self._task.is_complete:
                self._return_home()
            else:
                self._task.start_current_step()

        elif isinstance(outcome, PushMenu):
            self._last_input = time.monotonic()  # idle timeout starts when the menu appears
            self._pushed_menu = outcome
            self.nav.push(outcome.menu)

        elif isinstance(outcome, Done):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._return_home()

        elif isinstance(outcome, Cancel):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._return_home()

    def _render_qr_auth(self) -> None:
        step = self._task.current_step
        self.display.clear()

        if getattr(step, "_show_url", False):
            # URL text view — full URL split across lines
            url = step.session_url.replace("https://", "").replace("http://", "")
            self.display.draw_text(2, 0, "Visit:")
            col = 21
            for i, chunk in enumerate([url[j:j + col] for j in range(0, len(url), col)]):
                self.display.draw_text(2, 14 + i * 12, chunk)
            self.display.draw_text(2, 52, "< Cancel  > QR Code")
        else:
            # QR view — QR on left, labels on right
            qr = step.qr_image
            self.display.draw_image(0, 3, qr)
            x = qr.width + 4
            self.display.draw_text(x, 8, "Scan Code")
            self.display.draw_text(x, 36, "> View URL")
            self.display.draw_text(x, 50, "< Cancel")

        self.display.update()

    def _render_home(self) -> None:
        step = self._task.current_step
        if step.screen_off:
            if not self._home_blanked:
                self.display.clear()
                self.display.update()
                self._home_blanked = True
            return
        self._home_blanked = False

        song = step.status
        artist = getattr(step, "artist", "")
        shuffle = getattr(step, "shuffle_active", False)
        repeat = getattr(step, "repeat_state", "off")

        d = self.display
        d.clear()
        scrub = self._seek_target is not None or time.monotonic() < self._seek_shown_until
        # Scrubbing from the album screen shows the time.
        mode = self._display_mode
        if mode == "album" and scrub:
            mode = "time"
        if mode == "time":
            self._render_time(step, shuffle, repeat)
            d.update()
            return
        if mode == "album":
            self._render_album(step, artist)
            d.update()
            return

        d.draw_text(2, 0, song)
        if scrub:
            self._draw_scrub(step)
        elif artist:
            d.draw_text(2, 14, artist)

        # A cross laid out like the joystick: repeat (up) over shuffle (down),
        # skips (left/right) halfway between. A setting that's on is inverted.
        # It sits on the left, the side of the box the joystick is on, clear
        # of the progress bar along the bottom edge.
        sw, sh = icons.size(icons.SHUFFLE)
        rw, rh = icons.size(icons.REPEAT)
        pw, ph = icons.size(icons.PREV)
        shuf_top = 58 - sh
        rep_top = shuf_top - 6 - rh
        skip_top = (rep_top + shuf_top + sh) // 2 - ph // 2
        sx = 2 + pw + 8
        rep_icon = icons.REPEAT_ONE if repeat == "track" else icons.REPEAT
        (icons.draw_badge if repeat != "off" else icons.draw)(d, sx + sw // 2 - rw // 2, rep_top, rep_icon)
        (icons.draw_badge if shuffle else icons.draw)(d, sx, shuf_top, icons.SHUFFLE)
        icons.draw(d, sx - 8 - pw, skip_top, icons.PREV)
        icons.draw(d, sx + sw + 8, skip_top, icons.NEXT)
        if getattr(step, "tag_active", False):
            self._draw_track_count(step, skip_top - 1)
            if not scrub:                       # the scrub line shows it then
                self._draw_progress(step)
        d.update()

    def _draw_track_count(self, step, y: int) -> None:
        """Which track of how many ("3/12"), against the right edge."""
        track, total = step.track_number, step.total_tracks
        if not track:
            return
        text = f"{track}/{total}" if total else str(track)
        self.display.draw_text(126 - self.display.text_width(text), y, text)

    def _draw_progress(self, step) -> None:
        """A thin bar along the bottom edge: dotted for the whole track, solid
        (two pixels tall) for the part played."""
        dur = step.duration_ms
        if not dur:
            return
        d = self.display
        for x in range(0, 128, 2):
            d.draw_rect(x, 63, x, 63)
        played = round(127 * min(step.position_ms(), dur) / dur)
        if played:
            d.draw_rect(0, 62, played, 63)

    def _render_time(self, step, shuffle: bool, repeat: str) -> None:
        """CD-player time display: track number, the repeat and shuffle flags,
        big elapsed time (where we'll land, while scrubbing) and a bar."""
        d = self.display
        playing = getattr(step, "tag_active", False)
        pos = self._seek_target if self._seek_target is not None else step.position_ms()
        dur = step.duration_ms if playing else 0
        track = step.track_number if playing else None
        lcd.tiny_text(d, 2, 19, "TRACK")
        lcd.seg_text(d, 2, 27, f"{track:02d}" if track else "--", w=9, h=17, gap=3)
        flags = ("RPT 1" if repeat == "track" else "RPT", "RND")
        x = 127 - lcd.flags_width(flags)
        x = lcd.flag(d, x, 0, flags[0], repeat != "off") + 3
        lcd.flag(d, x, 0, flags[1], shuffle)
        t = _clock(pos) if playing else "-:--"
        lcd.seg_text(d, 127 - lcd.seg_width(t, 13, 4), 19, t)
        d.draw_rect(0, 62, 127, 62)                                   # progress
        if dur:
            d.draw_rect(0, 61, round(127 * min(pos, dur) / dur), 63)

    def _render_album(self, step, artist: str) -> None:
        """Album, artist, which track of how many, and the album's length."""
        d = self.display
        if not getattr(step, "tag_active", False):
            d.draw_text(2, 0, step.status)            # "Place tag..."
            lcd.tiny_text(d, 2, 33, "TRACK")
            lcd.seg_text(d, 2, 41, "--", w=8, h=17, gap=3)
            return
        d.draw_text(2, 0, step.album_name or step.status)
        d.draw_text(2, 14, artist)
        track, total = step.track_number, step.total_tracks
        lcd.tiny_text(d, 2, 33, "TRACK")
        x = lcd.seg_text(d, 2, 41, f"{track:02d}" if track else "--", w=8, h=17, gap=3)
        if total:
            lcd.tiny_text(d, x + 3, 53, f"/{total}")
        if step.album_length_ms:
            t = _clock(step.album_length_ms)
            tx = 127 - lcd.seg_width(t, 8, 3)
            lcd.tiny_text(d, 127 - lcd.tiny_width("TOTAL"), 33, "TOTAL")
            lcd.seg_text(d, tx, 41, t, w=8, h=17, gap=3)

    def _draw_scrub(self, step) -> None:
        """While scrubbing: where we'll land, in place of the artist line."""
        pos = self._seek_target if self._seek_target is not None else step.position_ms()
        dur = step.duration_ms
        self.display.draw_text(2, 14, f"{_clock(pos)} / {_clock(dur)}")
        left, right, y = 2, 125, 27
        self.display.draw_rect(left, y + 1, right, y + 1)                  # track line
        if dur:
            x = left + round((right - left) * min(pos, dur) / dur)
            self.display.draw_rect(max(left, x - 1), y, min(right, x + 1), y + 2)   # where

    def _render_status(self, step) -> None:
        text = step.status
        artist = getattr(step, "artist", "")
        detail = getattr(step, "detail", "")
        self.display.clear()
        if artist and detail:
            self.display.draw_text(2, 4, text)
            self.display.draw_text(2, 20, artist)
            self.display.draw_text(2, 36, detail)
        elif artist:
            self.display.draw_text(2, 14, text)
            self.display.draw_text(2, 28, artist)
        else:
            self.display.draw_text(2, 20, text)
        self.display.update()

    def _render_menu(self) -> None:
        state = self.nav.current
        self.display.clear()
        self.display.draw_text(2, 0, state.menu.title)
        if state.menu.subtitle:
            self.display.draw_text(2, 11, state.menu.subtitle)
            y = 24
        else:
            y = 14
        list_top = y
        for idx, item in state.visible_items:
            self.display.draw_text(
                2, y, item.label, selected=(idx == state.selected_index)
            )
            y += 12
        self._draw_scrollbar(state, list_top, y - 2)
        self.display.update()

    def _render_volume(self, volume: int) -> None:
        """A volume bar, shown for a moment after each volume press."""
        d = self.display
        d.clear()
        d.draw_text(2, 6, f"Volume {volume}%")
        left, right, top, bottom = 4, 123, 30, 44
        d.draw_rect(left, top, right, bottom)                            # frame...
        d.draw_rect(left + 1, top + 1, right - 1, bottom - 1, on=False)  # ...hollow
        fill = round((right - left - 3) * volume / 100)
        if fill:
            d.draw_rect(left + 2, top + 2, left + 1 + fill, bottom - 2)
        d.update()

    def _draw_scrollbar(self, state, top: int, bottom: int) -> None:
        """Slim bar on the right edge when the menu has more items than fit."""
        total, rows = len(state.menu.items), state.menu.visible_rows
        if total <= rows:
            return
        # Clear a strip so the bar stays visible beside a highlighted row.
        self.display.draw_rect(_SCROLL_X - 2, top, 127, bottom, on=False)
        for dot_y in range(top, bottom + 1, 3):          # dotted track
            self.display.draw_rect(_SCROLL_X + 1, dot_y, _SCROLL_X + 1, dot_y)
        track = bottom - top + 1
        thumb = max(6, round(track * rows / total))
        thumb_top = top + round((track - thumb) * state.scroll_offset / (total - rows))
        self.display.draw_rect(_SCROLL_X, thumb_top, _SCROLL_X + 2, thumb_top + thumb - 1)
