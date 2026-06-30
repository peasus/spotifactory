from __future__ import annotations

import os
from typing import Any

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
    ) -> None:
        self.display = display
        self.menus = menus
        self.dry_run = dry_run
        self.nav = NavStack(menus["main"])
        self._task: Task | None = None
        self._pushed_menu: PushMenu | None = None  # active PushMenu context

    # ------------------------------------------------------------------
    # Input handlers — called by the platform runner
    # ------------------------------------------------------------------

    def handle_up(self) -> None:
        if self._accepting_nav_input:
            self.nav.current.move_up()

    def handle_down(self) -> None:
        if self._accepting_nav_input:
            self.nav.current.move_down()

    def handle_select(self) -> None:
        item = self.nav.current.selected_item

        if self._pushed_menu is not None:
            # Inside a task-pushed menu: route to confirm or cancel outcome
            if item.action == "confirm":
                self._resolve(self._pushed_menu.on_confirm)
            elif item.action == "cancel":
                self._resolve(self._pushed_menu.on_cancel)
            return

        if self._task is not None:
            return  # background work running — ignore

        # Normal menu navigation
        if item.task is not None:
            self._start_task(item.task)
        elif item.submenu and item.submenu in self.menus:
            self.nav.push(self.menus[item.submenu])
        elif item.action == "back":
            self.nav.pop()
        elif item.action == "reboot":
            os.system("sudo reboot")
        elif item.action == "shutdown":
            os.system("sudo shutdown -h now")

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
            return  # waiting for user input; outcome already processed
        step = self._task.current_step
        if step is None or not step.is_done:
            return
        self._resolve(step.outcome)

    # ------------------------------------------------------------------
    # Render — draw current state to the display
    # ------------------------------------------------------------------

    def render(self) -> None:
        # Background step is working — show its status
        if (
            self._task
            and self._task.current_step
            and not self._task.current_step.is_done
        ):
            self._render_status(self._task.current_step.status)
            return

        # Menu (regular nav or task-pushed confirm/retry menu)
        self._render_menu()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _accepting_nav_input(self) -> bool:
        return self._pushed_menu is not None or self._task is None

    def _start_task(self, task_class: type) -> None:
        ctx = TaskContext(display=self.display, dry_run=self.dry_run)
        self._task = task_class(ctx)
        self._task.start_current_step()

    def _resolve(self, outcome: StepOutcome) -> None:
        if isinstance(outcome, Continue):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._task.advance(outcome.next_step)
            if self._task.is_complete:
                self._task = None
            else:
                self._task.start_current_step()

        elif isinstance(outcome, PushMenu):
            self._pushed_menu = outcome
            self.nav.push(outcome.menu)

        elif isinstance(outcome, Done):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._task = None

        elif isinstance(outcome, Cancel):
            if self._pushed_menu is not None:
                self.nav.pop()
                self._pushed_menu = None
            self._task = None

    def _render_status(self, text: str) -> None:
        self.display.clear()
        self.display.draw_text(2, 20, text)
        self.display.update()

    def _render_menu(self) -> None:
        state = self.nav.current
        self.display.clear()
        self.display.draw_text(2, 0, state.menu.title)
        y = 14
        for idx, item in state.visible_items:
            self.display.draw_text(
                2, y, item.label, selected=(idx == state.selected_index)
            )
            y += 12
        self.display.update()
