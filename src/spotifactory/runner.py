from __future__ import annotations

import os
from typing import Any, Optional, Type

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

        if home_task_class is not None:
            print(f"[runner] starting home task: {home_task_class.__name__}", flush=True)
            self._start_task(home_task_class)
            print(f"[runner] home task started, task={self._task}", flush=True)

    # ------------------------------------------------------------------
    # Input handlers — called by the platform runner
    # ------------------------------------------------------------------

    def handle_up(self) -> None:
        if self._in_home_scan():
            self._task.current_step.cancel()
            return
        if self._accepting_nav_input:
            self.nav.current.move_up()

    def handle_down(self) -> None:
        if self._in_qr_auth():
            self._task.current_step.toggle_url()
            return
        if self._in_home_scan():
            self._toggle_shuffle()
            return
        if self._accepting_nav_input:
            self.nav.current.move_down()

    def handle_left(self) -> None:
        if self._in_qr_auth():
            self._task.current_step.cancel()
            return
        if self._in_home_mode():
            self._prev_track()
            return
        # In a menu: treat left as Back
        if self._accepting_nav_input:
            self._do_back()

    def handle_right(self) -> None:
        if self._in_qr_auth():
            self._task.current_step.toggle_url()
            return
        if self._in_home_mode():
            self._next_track()
        else:
            self.handle_select()

    def handle_select(self) -> None:
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
        elif item.action == "reboot":
            os.system("sudo reboot")
        elif item.action == "shutdown":
            os.system("sudo shutdown -h now")

    def handle_tag_scan_sim(self, uri: str = "spotify:album:5Z9iiGl2FcIfa3BMiv6OIw") -> None:
        """Simulate an RFID tag scan (sim / dry_run mode). Press T in the sim."""
        from spotifactory.tasks.home.steps import HomeScanStep
        if (
            self._in_home_scan()
            and isinstance(self._task.current_step, HomeScanStep)
        ):
            self._task.current_step.simulate_scan(uri)

    def handle_back(self) -> None:
        if self._pushed_menu is not None:
            self._resolve(self._pushed_menu.on_cancel)
        elif self._task is None:
            self.nav.pop()

    # ------------------------------------------------------------------
    # Tick — advance task state; call on every loop iteration
    # ------------------------------------------------------------------

    def tick(self) -> None:
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
            self._render_status(self._task.current_step.status)
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

    def _do_back(self) -> None:
        if self._pushed_menu is not None:
            self._resolve(self._pushed_menu.on_cancel)
        elif self._task is None:
            self.nav.pop()

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
        try:
            from spotifactory.spotify import toggle_shuffle
            toggle_shuffle()
        except Exception:
            pass

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
            self.display.draw_text(2, 52, "< Cancel  v Toggle")
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
        song = step.status
        artist = getattr(step, "artist", "")
        shuffle = getattr(step, "shuffle_active", False)

        self.display.clear()
        self.display.draw_text(2, 0, song)
        if artist:
            self.display.draw_text(2, 14, artist)

        # Bottom legend:  <<  [shuffle]  >>
        # cy=52 keeps the icon and its dot (at cy+hh+5=61) within the 64px display.
        self.display.draw_text(2, 50, "<<")
        self._draw_shuffle_icon(64, 52, active=shuffle)
        self.display.draw_text(114, 50, ">>")
        self.display.update()

    def _draw_shuffle_icon(self, cx: int, cy: int, active: bool = False) -> None:
        """Spotify-style shuffle icon: two crossing arrows with an active dot.

        A small filled dot is drawn below the icon when shuffle is on.
        """
        hw, hh = 8, 4   # half-width / half-height of the X cross

        # Incoming horizontal stubs (left side)
        self.display.draw_line(cx - hw - 4, cy - hh, cx - hw, cy - hh, width=1.05)
        self.display.draw_line(cx - hw - 4, cy + hh, cx - hw, cy + hh, width=1.05)

        # Crossing diagonals
        self.display.draw_line(cx - hw, cy - hh, cx + hw, cy + hh, width=1.05)
        self.display.draw_line(cx - hw, cy + hh, cx + hw, cy - hh, width=1.05)

        # Outgoing horizontal stubs (right side)
        self.display.draw_line(cx + hw, cy - hh, cx + hw + 4, cy - hh, width=1.05)
        self.display.draw_line(cx + hw, cy + hh, cx + hw + 4, cy + hh, width=1.05)

        # Arrowheads at right exits (> shape on each)
        self.display.draw_line(cx + hw + 2, cy - hh - 2, cx + hw + 4, cy - hh, width=1.05)
        self.display.draw_line(cx + hw + 2, cy - hh + 2, cx + hw + 4, cy - hh, width=1.05)
        self.display.draw_line(cx + hw + 2, cy + hh - 2, cx + hw + 4, cy + hh, width=1.05)
        self.display.draw_line(cx + hw + 2, cy + hh + 2, cx + hw + 4, cy + hh, width=1.05)

        # Active indicator: filled dot centred below the icon
        if active:
            self.display.draw_circle(cx, cy + hh + 5, 2)

    def _render_status(self, text: str) -> None:
        self.display.clear()
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
        for idx, item in state.visible_items:
            self.display.draw_text(
                2, y, item.label, selected=(idx == state.selected_index)
            )
            y += 12
        self.display.update()
