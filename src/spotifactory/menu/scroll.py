import time

PAUSE_START_SECS: float = 3.0   # hold before starting scroll
SCROLL_PX_PER_SEC: float = 30.0  # display pixels per second
PAUSE_END_SECS: float = 1.0      # hold at end before looping


class _Entry:
    def __init__(self, text: str, overflow: float, now: float) -> None:
        self.text = text
        self.overflow = overflow
        self._t = now
        self._phase = 0  # 0 = wait, 1 = scroll, 2 = end-pause

    def get(self, now: float) -> float:
        elapsed = now - self._t
        if self._phase == 0:
            if elapsed >= PAUSE_START_SECS:
                self._phase = 1
                self._t = now
            return 0.0
        elif self._phase == 1:
            px = elapsed * SCROLL_PX_PER_SEC
            if px >= self.overflow:
                self._phase = 2
                self._t = now
                return self.overflow
            return px
        else:
            if elapsed >= PAUSE_END_SECS:
                self._phase = 0
                self._t = now
                return 0.0
            return self.overflow


class ScrollTracker:
    """Tracks per-position horizontal scroll state for overflowing text."""

    def __init__(self) -> None:
        self._entries: dict[tuple, _Entry] = {}

    def offset(self, key: tuple, text: str, overflow: float) -> float:
        """Return current scroll offset in display pixels.

        key: unique (x, y) position identifier
        overflow: how many display pixels the text exceeds the available width
        """
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is None or entry.text != text:
            self._entries[key] = _Entry(text, overflow, now)
            return 0.0
        return entry.get(now)

    def clear(self, key: tuple) -> None:
        self._entries.pop(key, None)
