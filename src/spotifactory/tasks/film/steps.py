from __future__ import annotations

from spotifactory.tasks.base import Cancel, Continue, Done, PushMenu, Step, StepOutcome, TaskContext

SHOW_SECS = 4.0


def _film_label(n: int) -> str:
    if n == 0:
        return "No film left"
    return f"{n} shot{'s' if n != 1 else ''} left"


def _battery_label(pct: int | None, charging: bool) -> str:
    if pct is None:
        return "Charging" if charging else ""
    return f"Battery {pct}%{' +' if charging else ''}"


class FilmCountStep(Step):
    """Connects to the printer, shows shots left and battery, then goes back."""

    def __init__(self) -> None:
        super().__init__()
        self.artist: str = ""

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.hardware.printer import get_status
        from spotifactory.tasks.capture.steps import _printer_off_menu
        self.artist = ""
        self.status = "Connecting..."
        status = get_status()
        if not status.printer_found:
            return PushMenu(
                menu=_printer_off_menu(),
                on_confirm=Continue(next_step="check"),  # retry
                on_cancel=Cancel(),
            )
        if status.error:
            self.show_for(f"Error: {status.error[:20]}", 3.0)
            return Done()
        self.artist = _battery_label(status.battery_pct, status.charging)
        self.show_for(_film_label(status.photos_left), SHOW_SECS)
        self.artist = ""
        return Done()
