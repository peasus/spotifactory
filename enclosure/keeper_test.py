"""Fit test for holding the reader with rails and screw-in keepers.

A full-length section of the panel's inside wall, printed with the same 15°
lean as the body. It has a rail along each long edge of the reader, stops at
the top, and a post beside each rail at the bottom. The reader slides up into
the rails from below until it reaches the stops. Then a small keeper goes under
each bottom corner, held by an M2.5 x 12 screw driven straight up into the post.

The USB plug fills the middle under the board, so there are two keepers, one
per corner, rather than one bar.

Run:  enclosure/.venv/bin/python enclosure/keeper_test.py
Writes out/print/keeper_test.stl (wall section plus both keepers, laid out to
print) and out/keeper_test.png.
"""
from __future__ import annotations

from build123d import Align, Box, Cylinder, Pos, Rot, export_stl, fillet, Axis

import math

import easel
from concepts import OUT, render
from easel import _prism_x

PCB_T = easel.READER_PCB
HALF = easel.READER_W / 2
CLEAR = 0.4                   # channel depth beyond the board (no crush ribs: the keepers hold it)
EDGE_CLEAR = 0.4              # each side of the board's 38.15 mm width
LIP = 1.3                     # lip overlap onto the board's back (1.5 mm is component-free)
LIP_T = 1.2
SIDE_T = 1.8
FLARE = 3.0
TOP_GAP = 0.3                 # stop above the board's top edge
BOARD_UP = 14.0               # board bottom edge above the wall's foot (room for keepers and screws)

POST_X = HALF + EDGE_CLEAR + SIDE_T + 2.75   # post centre, just outside the rail
POST_Z = -4.0                 # behind the wall, clear of the board
POST_R = 2.75
POST_LEN = 14.0
PILOT_D = easel.PILOT_M25
PILOT_DEPTH = 8.0             # M2.5 x 12: ~7 mm of keeper at the screw, ~5 mm into the post
# The post sticks out behind a wall leaning back, so a square underside would
# start printing at its back edge, in mid-air. Instead the underside is level
# (in the printer) for LEDGE mm off the wall, then rises at 45°; the keeper's
# top matches it, and tightening the screw wedges the keeper against the wall.
LEDGE = 2.0

KEEPER_T = 3.0                # along the wall
KEEPER_GAP = 0.2              # keeper below the board's bottom edge
KEEPER_X0 = HALF - 3.0        # reaches 3 mm under the board's corner
KEEPER_Z = (-0.2, POST_Z - POST_R)
SCREW_CLEAR_D = 2.9

WALL_W = 2 * (POST_X + POST_R) + 2.0
WALL_H = BOARD_UP + easel.READER_H + TOP_GAP + 3.0
FOOT_T, FOOT_D = 2.0, 10.0
C = (Align.CENTER, Align.CENTER, Align.MIN)


def _box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))


def underside(z: float, p0: float) -> float:
    """Height (along the wall) of the post's underside at depth z (< 0) behind the wall."""
    d = -z
    flat, rise = math.tan(math.radians(easel.LEAN)), math.tan(math.radians(45 + easel.LEAN))
    return p0 + flat * min(d, LEDGE) + rise * max(d - LEDGE, 0)


def _underside_pts(p0: float, depth: float, below: float):
    """Outline (y, z) of the post's underside from the wall back to `depth`, then
    down to `below` (for the keeper) or up to the post's top."""
    zs = [0.01, -LEDGE, -depth]
    return [(underside(min(z, 0), p0), z) for z in zs]


def local_wall():
    """Wall + rails + stops + posts in the wall's frame: x across, y up the wall,
    z out of its front. The inside face is z = 0; the board lies in z < 0."""
    yb, yt = BOARD_UP, BOARD_UP + easel.READER_H
    back = -(PCB_T + CLEAR)
    part = Pos(0, WALL_H / 2 - 1, easel.WALL / 2) * Box(WALL_W, WALL_H + 2, easel.WALL)
    for s in (-1, 1):
        xs = lambda a, b: (min(s * a, s * b), max(s * a, s * b))
        side_x0 = HALF + EDGE_CLEAR
        y0 = yb - KEEPER_GAP                     # rails start just above the keepers
        r = _prism_x([(y0, 0.01), (yt + TOP_GAP + 2, 0.01), (yt + TOP_GAP + 2, back - LIP_T),
                      (y0, back - LIP_T)], *xs(side_x0, side_x0 + SIDE_T))
        r += _prism_x([(yb, back - FLARE * 0.4), (yb + FLARE, back), (yt + TOP_GAP + 2, back),
                       (yt + TOP_GAP + 2, back - LIP_T), (yb, back - LIP_T)], *xs(HALF - LIP, side_x0 + 0.01))
        # Same sloped underside as the posts, so the rail bottoms build out from the wall.
        far = -12.0
        below = [(underside(0, y0), 0.02), (underside(-LEDGE, y0), -LEDGE),
                 (underside(far, y0), far), (y0 - 50, far), (y0 - 50, 0.02)]
        r -= _prism_x(below, *xs(HALF - LIP - 1, side_x0 + SIDE_T + 1))
        part += r
        part += _box(s * (HALF - 4), s * (side_x0 + 0.01), yt + TOP_GAP, yt + TOP_GAP + 2, 0.01, back)
        # Post: from the wall back past the pilot, with the sloped underside.
        p0 = yb - KEEPER_GAP
        depth = -(POST_Z - POST_R)
        outline = _underside_pts(p0, depth, 0) + [(p0 + POST_LEN, -depth), (p0 + POST_LEN, 0.01)]
        part += _prism_x(outline, *xs(side_x0 + SIDE_T - 0.01, POST_X + POST_R))
        hole_low = underside(POST_Z + PILOT_D / 2, p0)
        part -= Pos(s * POST_X, hole_low - 1, POST_Z) * Rot(-90, 0, 0) * Cylinder(
            PILOT_D / 2, PILOT_DEPTH + 1, align=C)
    return part


def keeper(s: int):
    """Keeper under one bottom corner, in the wall's frame, in place."""
    yb = BOARD_UP
    p0 = yb - KEEPER_GAP
    xs = lambda a, b: (min(s * a, s * b), max(s * a, s * b))
    depth = -KEEPER_Z[1]
    bottom = p0 - KEEPER_T                       # flat: the screw head bears here
    side_x = HALF + EDGE_CLEAR + SIDE_T          # where the post starts
    # Under the board's corner (and the rail): flat top, just below the board.
    k = _prism_x([(bottom, KEEPER_Z[0]), (p0, KEEPER_Z[0]), (p0, -depth), (bottom, -depth)],
                 *xs(KEEPER_X0, side_x))
    # Under the post: top follows the post's sloped underside.
    top = [(y, z) for y, z in _underside_pts(p0, depth, 0) if z <= KEEPER_Z[0] + 0.01]
    top = [(underside(-0.2, p0), KEEPER_Z[0])] + top
    k += _prism_x(top + [(bottom, -depth), (bottom, KEEPER_Z[0])], *xs(side_x - 0.01, POST_X + POST_R))
    k -= Pos(s * POST_X, bottom - 1, POST_Z) * Rot(-90, 0, 0) * Cylinder(
        SCREW_CLEAR_D / 2, 30, align=C)
    return k


def board_and_plug():
    """The reader (antenna side on the wall) and its right-angle plug, for the fit check and render."""
    yb = BOARD_UP
    board = _box(-HALF, HALF, yb, yb + easel.READER_H, 0, -PCB_T)
    socket = _box(-4.5, 4.5, yb, yb + 7, -PCB_T, -PCB_T - easel.SOCKET_H)
    plug = _box(-6.5, 6.5, yb - 9, yb + 2 - 2, -0.3, -0.3 - PCB_T - 16)
    screws = [Pos(s * POST_X, yb - KEEPER_GAP - KEEPER_T - 1.4, POST_Z) * Rot(-90, 0, 0) * (
        Cylinder(2.35, 1.4, align=C) + Pos(0, 0, 1.4) * Cylinder(1.25, 12, align=C)) for s in (-1, 1)]
    return board, socket, plug, screws


LEAN = Pos(0, 0, FOOT_T) * Rot(90 - easel.LEAN, 0, 0)


def wall_section():
    part = (LEAN * local_wall()) & Box(400, 400, 400, align=C)
    # Foot in front only, so the board and the screwdriver come in from below behind it.
    return part + Pos(0, -FOOT_D / 2 + 1, 0) * Box(WALL_W, FOOT_D, FOOT_T, align=C)


def keepers_flat():
    """Both keepers lying flat (their screw holes vertical), beside the wall section."""
    out = []
    for i, s in enumerate((-1, 1)):
        k = keeper(s)
        k = Rot(90, 0, 0) * k                     # wall's y (along the screw) becomes z
        bb = k.bounding_box()
        k = Pos(-bb.center().X + (i - 0.5) * 20, -bb.center().Y - 30, -bb.min.Z) * k
        out.append(k)
    return out


if __name__ == "__main__":
    wall = local_wall()
    ks = [keeper(-1), keeper(1)]
    board, socket, plug, screws = board_and_plug()
    print("valid:", wall.is_valid, all(k.is_valid for k in ks))
    print(f"board vs rails/stops/posts: {(wall & board).volume:.3f} mm³")
    print(f"plug vs keepers: {sum((plug & k).volume for k in ks):.3f} mm³; "
          f"board vs keepers: {sum((board & k).volume for k in ks):.3f} mm³; "
          f"keepers vs wall: {sum((wall & k).volume for k in ks):.3f} mm³")
    # Board can't slide out: dropped 1 mm, it lands on the keepers.
    print(f"board dropped 1 mm hits keepers: {sum((Pos(0, -1, 0) * board & k).volume for k in ks):.2f} mm³")

    printed = [wall_section(), *keepers_flat()]
    out = printed[0] + printed[1] + printed[2]
    (OUT / "print").mkdir(parents=True, exist_ok=True)
    export_stl(out, str(OUT / "print" / "keeper_test.stl"))
    assembled = {"body": LEAN * wall, "cover": [LEAN * k for k in ks], "reader": LEAN * board,
                 "port": LEAN * socket, "plugs": LEAN * plug, "spacers": [LEAN * s for s in screws]}
    render({"Assembled, from behind": assembled,
            "Bottom corner: keeper + screw": assembled,
            "As printed": {"body": out}},
           OUT / "keeper_test.png", views=[(15, 70), (-30, 60), (35, -60)], columns=3)
    bb = out.bounding_box()
    print(f"print {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; wrote", OUT / "print" / "keeper_test.stl")
