"""CD-player display pieces for the 128x64 OLED, drawn with rectangles so
they look the same on every display: seven-segment digits, a 3x5 pixel font
for labels, and annunciator flags (lit when on, dimmed when off)."""
from __future__ import annotations

_SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
             "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g"}

_TINY = {
    "A": (".#.", "#.#", "###", "#.#", "#.#"),
    "C": (".##", "#..", "#..", "#..", ".##"),
    "D": ("##.", "#.#", "#.#", "#.#", "##."),
    "K": ("#.#", "#.#", "##.", "#.#", "#.#"),
    "L": ("#..", "#..", "#..", "#..", "###"),
    "N": ("##.", "#.#", "#.#", "#.#", "#.#"),
    "O": ("###", "#.#", "#.#", "#.#", "###"),
    "P": ("##.", "#.#", "##.", "#..", "#.."),
    "R": ("##.", "#.#", "##.", "#.#", "#.#"),
    "T": ("###", ".#.", ".#.", ".#.", ".#."),
    "0": ("###", "#.#", "#.#", "#.#", "###"),
    "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"),
    "3": ("###", "..#", ".##", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"),
    "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"),
    "7": ("###", "..#", "..#", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"),
    "9": ("###", "#.#", "###", "..#", "###"),
    "/": ("..#", "..#", ".#.", "#..", "#.."),
    " ": ("...",) * 5,
}
TINY_H = 5


def _digit(d, x: int, y: int, ch: str, w: int, h: int, t: int) -> None:
    m = h // 2
    boxes = {
        "a": (x + 1, y, x + w - 2, y + t - 1),
        "b": (x + w - t, y + 1, x + w - 1, y + m - 1),
        "c": (x + w - t, y + m + 1, x + w - 1, y + h - 2),
        "d": (x + 1, y + h - t, x + w - 2, y + h - 1),
        "e": (x, y + m + 1, x + t - 1, y + h - 2),
        "f": (x, y + 1, x + t - 1, y + m - 1),
        "g": (x + 1, y + m - t // 2, x + w - 2, y + m - t // 2 + t - 1),
    }
    for s in _SEGMENTS.get(ch, ""):
        d.draw_rect(*boxes[s])


def seg_width(text: str, w: int, gap: int) -> int:
    return sum(2 + gap if c == ":" else w + gap for c in text) - gap


def seg_text(d, x: int, y: int, text: str, w: int = 13, h: int = 25, gap: int = 4) -> int:
    """Seven-segment `text` (digits, '-' and ':') with its top-left at (x, y);
    returns the x after it."""
    t = 3 if h >= 21 else 2
    for ch in text:
        if ch == ":":
            dot = h // 4
            d.draw_rect(x, y + dot, x + 1, y + dot + 1)
            d.draw_rect(x, y + h - dot - 2, x + 1, y + h - dot - 1)
            x += 2 + gap
        else:
            _digit(d, x, y, ch, w, h, t)
            x += w + gap
    return x - gap


def tiny_width(text: str) -> int:
    return 4 * len(text) - 1


def tiny_text(d, x: int, y: int, text: str, on: bool = True) -> int:
    """`text` in the 3x5 font (capitals, digits, '/'); returns the x after it."""
    for ch in text.upper():
        for row, line in enumerate(_TINY.get(ch, _TINY[" "])):
            for col, px in enumerate(line):
                if px == "#":
                    d.draw_rect(x + col, y + row, x + col, y + row, on=on)
        x += 4
    return x - 1


def flag(d, x: int, y: int, text: str, on: bool) -> int:
    """An annunciator, 9 px tall: `text` cut out of a lit box when on, a faint
    outline of the box when off. Returns the x after it."""
    w = tiny_width(text) + 4
    if on:
        d.draw_rect(x, y, x + w - 1, y + 8)
        tiny_text(d, x + 2, y + 2, text, on=False)
    else:
        for xx in range(x, x + w, 2):                  # dotted outline
            d.draw_rect(xx, y, xx, y)
            d.draw_rect(xx, y + 8, xx, y + 8)
        tiny_text(d, x + 2, y + 2, text)
    return x + w


def flags_width(texts) -> int:
    return sum(tiny_width(t) + 4 for t in texts) + 3 * (len(texts) - 1)
