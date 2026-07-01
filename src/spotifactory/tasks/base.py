from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Thread
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from spotifactory.menu.definitions import MenuDef


# ---------------------------------------------------------------------------
# Outcome types — a Step returns exactly one of these
# ---------------------------------------------------------------------------

@dataclass
class Continue:
    next_step: str | None = None  # None = advance to next in sequence


@dataclass
class PushMenu:
    menu: MenuDef
    on_confirm: StepOutcome
    on_cancel: StepOutcome


@dataclass
class Done:
    pass


@dataclass
class Cancel:
    pass


StepOutcome = Union[Continue, PushMenu, Done, Cancel]


# ---------------------------------------------------------------------------
# Shared context passed between steps
# ---------------------------------------------------------------------------

@dataclass
class TaskContext:
    display: Any = None
    dry_run: bool = True
    printer_dry_run: bool = False
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step base class
# ---------------------------------------------------------------------------

class Step(ABC):
    def __init__(self) -> None:
        self._status: str = ""
        self._outcome: StepOutcome | None = None
        self._thread: Thread | None = None

    # -- Status string read by the runner while the step is working ----------

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        self._status = value

    # -- Convenience: set status and block for a display duration ------------

    def show_for(self, message: str, seconds: float) -> None:
        self._status = message
        time.sleep(seconds)

    # -- Threading -----------------------------------------------------------

    def start(self, ctx: TaskContext) -> None:
        self._outcome = None
        self._thread = Thread(target=self._execute, args=(ctx,), daemon=True)
        self._thread.start()

    def _execute(self, ctx: TaskContext) -> None:
        import traceback
        print(f"[step] START {type(self).__name__}", flush=True)
        try:
            self._outcome = self.run(ctx)
            print(f"[step] DONE  {type(self).__name__} → {type(self._outcome).__name__}", flush=True)
        except Exception as exc:
            print(f"[step] CRASH {type(self).__name__}: {exc}", flush=True)
            traceback.print_exc()
            self._status = f"Error: {type(exc).__name__}"
            self._outcome = Done()

    @property
    def is_done(self) -> bool:
        return self._outcome is not None

    @property
    def outcome(self) -> StepOutcome | None:
        return self._outcome

    # -- Subclasses implement this -------------------------------------------

    @abstractmethod
    def run(self, ctx: TaskContext) -> StepOutcome: ...


# ---------------------------------------------------------------------------
# Task base class
# ---------------------------------------------------------------------------

class Task(ABC):
    steps: list[tuple[str, type[Step]]] = []

    def __init__(self, ctx: TaskContext) -> None:
        self.ctx = ctx
        self._instances: dict[str, Step] = {
            name: cls() for name, cls in self.__class__.steps
        }
        self._order: list[str] = [name for name, _ in self.__class__.steps]
        self._idx: int = 0

    @property
    def current_step_name(self) -> str | None:
        return self._order[self._idx] if not self.is_complete else None

    @property
    def current_step(self) -> Step | None:
        name = self.current_step_name
        return self._instances[name] if name else None

    @property
    def is_complete(self) -> bool:
        return self._idx >= len(self._order)

    def start_current_step(self) -> None:
        step = self.current_step
        if step:
            step.start(self.ctx)

    def advance(self, next_step: str | None = None) -> None:
        if next_step is not None:
            self._idx = self._order.index(next_step)
        else:
            self._idx += 1
