"""Pixel icons for the 128x64 OLED, drawn pixel for pixel so they stay crisp
(lines and fonts at this size come out jagged). '#' is a lit pixel."""
from __future__ import annotations

PREV = (
    "##.....#....#",
    "##....##...##",
    "##...###..###",
    "##..####.####",
    "##.##########",
    "##..####.####",
    "##...###..###",
    "##....##...##",
    "##.....#....#",
)

NEXT = tuple(row[::-1] for row in PREV)

SHUFFLE = (
    "............#..",
    ".............#.",
    "#####.....#####",
    ".....#...#...#.",
    "......#.#...#..",
    ".......#.......",
    "......#.#...#..",
    ".....#...#...#.",
    "#####.....#####",
    ".............#.",
    "............#..",
)

REPEAT = (
    "..........#....",
    "..........##...",
    "..###########..",
    "..#.......##...",
    "..#.......#....",
    "..#.........#..",
    "....#.......#..",
    "...##.......#..",
    "..###########..",
    "...##..........",
    "....#..........",
)

REPEAT_ONE = (
    "..........#....",
    "..........##...",
    "..###########..",
    "..#...##..##...",
    "..#....#..#....",
    "..#....#....#..",
    "....#.###...#..",
    "...##.......#..",
    "..###########..",
    "...##..........",
    "....#..........",
)


def size(icon) -> tuple[int, int]:
    return len(icon[0]), len(icon)


def draw(display, x: int, y: int, icon, on: bool = True) -> None:
    """Draw `icon` with its top-left at (x, y), a run of pixels at a time;
    on=False draws it in black (cut out of a lit background)."""
    for row, line in enumerate(icon):
        col = 0
        while col < len(line):
            if line[col] == "#":
                end = col
                while end + 1 < len(line) and line[end + 1] == "#":
                    end += 1
                display.draw_rect(x + col, y + row, x + end, y + row, on=on)
                col = end + 1
            else:
                col += 1


def draw_badge(display, x: int, y: int, icon, pad: int = 2) -> None:
    """`icon` cut out of a lit, corner-rounded box: how a toggle shows it's on."""
    w, h = size(icon)
    x0, y0, x1, y1 = x - pad, y - pad, x + w - 1 + pad, y + h - 1 + pad
    display.draw_rect(x0 + 1, y0, x1 - 1, y1)
    display.draw_rect(x0, y0 + 1, x1, y1 - 1)
    draw(display, x, y, icon, on=False)
