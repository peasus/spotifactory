"""Concept B ("easel"), first rough enclosure with real board layout.

Screen + joystick on a sloped face you look down on; the Instax print stands in
a groove behind it, leaning against a hollow panel that holds the PN532 reader
directly behind the tag. Shelled body, open bottom (a base plate closes it).

Run:  enclosure/.venv/bin/python enclosure/easel.py
Writes enclosure/out/easel.png (front, back, cut-away) and easel_body.stl.

Known: SeenGreat OLED HAT layout (maker's drawing), Instax Square print size,
stack height (measured).
PLACEHOLDERS (to measure): screen glass and joystick heights, PN532 thickness,
USB-C panel jack.
"""
from __future__ import annotations

import math

from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildSketch,
    Cylinder,
    Plane,
    Polyline,
    Pos,
    Rot,
    export_stl,
    extrude,
    fillet,
    make_face,
    offset,
)

from concepts import OUT, PRINT_H, PRINT_T, PRINT_W, render

C = (Align.CENTER, Align.CENTER, Align.MIN)
CC = (Align.CENTER, Align.CENTER, Align.CENTER)

# ---------------------------------------------------------------- body
W = 104.0                 # width at the base
TOP_W = 81.0              # width at the top of the panel (print is 72)
WALL = 2.4                # 6 perimeters at 0.4 mm nozzle
FILLET = 6.0              # outside edge radius (panel top is 14 mm deep, so < 7)
SLOPE = 12.0              # control face angle, degrees
LEAN = 15.0               # print leans back this far from vertical
TOP_T = 14.0              # panel thickness at the top; the back drops vertically from here
PANEL_LEN = 82.0          # panel height along its lean
STEP = 5.0                # flat shelf at the top of the slope (groove sits here)
LIP_H, LIP_W, GROOVE = 5.0, 3.0, 2.5

# ---------------------------------------------------------------- boards (known)
HAT_W, HAT_D, HAT_T = 65.0, 30.0, 1.6
HOLE_DX, HOLE_DY = 58.0, 23.5
# Positions in the slope frame: x across, y up-slope, origin at board centre.
# Stack orientation as on the device: joystick on the left, the Pi's USB ports
# along the top (back) edge, where there's room for straight plugs — so the
# screen can sit at the front edge with no chin.
WINDOW = (31.0, 16.0, 0.2, -1.5)          # w, h, cx, cy  (active area 29.4 x 14.7)
GLASS = (35.2, 22.6, 0.3, 0.3)
JOY = (-25.3, 0.2)
BUTTONS = [(24.9, 6.7), (24.9, 0.6), (24.9, -5.4)]  # K1-K3 (unused, covered)
BUTTON_FOOT = (6.2, 3.6)  # tact switch body footprint
GLASS_H = 1.3             # measured: OLED glass top above HAT board top
JOY_HOUSING_H = 2.1       # measured: joystick housing above HAT board top
BUTTON_H = 2.0            # measured: K1-K3 above HAT board top
STACK = 11.5              # measured: HAT board top surface to Pi board bottom surface
READER_W, READER_H = 38.15, 60.0  # measured PN532 board; stands upright, USB end down
READER_HOLES = (33.2, 54.5)       # measured hole spacing (unused: board slides into rails)
ANTENNA_FROM_USB_END = 39.5       # measured: antenna centre to the USB-C end
ANTENNA_H = 31.0                  # measured: loop height along the board (spans full width)
READER_PCB = 1.6
GAP = 0.7                 # print back to panel front face
SOCKET_H = 4.9 - READER_PCB  # measured: PCB bottom to USB-C socket top is 4.9 mm

# ---------------------------------------------------------------- PLACEHOLDERS
JOY_KNOB_H, JOY_KNOB_D = 9.9 - JOY_HOUSING_H, 7.3  # measured: joystick top is 9.9 mm above the board
PI_T, PI_UNDER = 1.4, 1.6  # Pi board thickness; parts on its underside
READER_T = 6.0            # incl. its USB-C socket
TAG = 25.4                # 1" square tag, centred on the 62 mm image
TAG_UP = 49.0             # tag centre above the print's bottom edge

# ---------------------------------------------------------------- power input
# Adafruit 5993 USB-C vertical breakout (5.1k CC pull-downs, so any USB-C cable
# and charger powers it). Dimensions from Adafruit's published STEP model.
PWR_BOARD = (30.48, 15.24, 1.57)    # w, h, thickness
PWR_HOLES = (25.4, 10.16)           # M2.5 hole spacing
PWR_SHELL = (9.35, 4.44)            # USB-C metal shell
PWR_RISE = 9.30                     # shell top above the board's top surface
PWR_X, PWR_Z = W / 2 - 26, 13.0     # board centre on the back wall (lower left, from behind)

# ---------------------------------------------------------------- base sized to the stack
# The lowest corner of the stack (Pi underside at the board's front edge) clears
# the base plate by 1 mm, so the base is only as tall as the boards need.
STACK_DEPTH = WALL + GLASS_H + STACK + PI_UNDER  # slope surface to Pi underside
_A = math.radians(SLOPE)
# No chin: boards start as close to the front as they can. The stack hangs
# below a tilted face, so its lower edge leans forward; keep that 1 mm clear
# of the front wall.
HAT_S = (WALL + 1.0 + STACK_DEPTH * math.sin(_A)) / math.cos(_A) + HAT_D / 2
HF = WALL + 1.0 + STACK_DEPTH * math.cos(_A) - (HAT_S - HAT_D / 2) * math.sin(_A)
YS = (HAT_S + HAT_D / 2 + 4.0) * math.cos(_A)   # slope ends 4 mm past the board
ZS = HF + YS * math.tan(_A)


def _slope_frame(s: float):
    """Location `s` mm up the slope face from the front edge (z = outward normal)."""
    a = math.radians(SLOPE)
    return Pos(0, s * math.cos(a), HF + s * math.sin(a)) * Rot(SLOPE, 0, 0)


def _back_y() -> float:
    """y of the outside of the vertical back wall."""
    return YS + STEP + PANEL_LEN * math.sin(math.radians(LEAN)) + TOP_T


def _power_board_top() -> float:
    """y of the breakout's top (connector) side: its shell ends flush with the back wall."""
    return _back_y() - PWR_RISE


def _print_frame():
    """Origin at the print's bottom edge in the groove; y up the print, z out of its face."""
    return Pos(0, YS + LIP_W + GROOVE / 2, ZS + 0.3) * Rot(90 - LEAN, 0, 0)


def _reader_frame():
    """Reader centre in the print frame: antenna behind the tag, USB end down."""
    centre_up = TAG_UP - (ANTENNA_FROM_USB_END - READER_H / 2)
    return _print_frame() * Pos(0, centre_up, 0)


# Depths behind the print plane (negative z in the print/reader frame).
SKIN_IN = -(GAP + WALL)                    # inside of the panel's front skin
BOARD_FRONT = SKIN_IN - 0.3                # antenna side of the reader
CHANNEL = READER_PCB + 0.6                 # rail slot the board slides in
RAIL_LIP = 1.5                             # lip behind the board edge
RAIL_BACK = SKIN_IN - CHANNEL - RAIL_LIP


def _box(x0, x1, y0, y1, z0, z1):
    """Axis-aligned box from min/max corners, in whatever frame it's placed."""
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=C)


def rails():
    """Card-guide rails on the inside of the panel's front skin, plus bottom stops.

    The reader drops in from a slot in the panel top, antenna side forward, and
    rests on the two stops; the gap between them clears its USB-C plug.
    """
    rf = _reader_frame()
    half, lo, hi = READER_W / 2, -READER_H / 2, READER_H / 2
    parts = []
    for side in (-1, 1):
        def m(a, b):
            return (min(side * a, side * b), max(side * a, side * b))
        parts.append(_box(*m(half + 0.4, half + 2.4), lo - 2, hi, RAIL_BACK, SKIN_IN))       # wall
        parts.append(_box(*m(half - RAIL_LIP, half + 2.4), lo - 2, hi, RAIL_BACK,
                          SKIN_IN - CHANNEL))                                                  # lip
        parts.append(_box(*m(half - 6, half + 2.4), lo - 2, lo - 0.3, RAIL_BACK, SKIN_IN))   # stop
    out = parts[0]
    for q in parts[1:]:
        out = out + q
    return rf * out


def _slot():
    """Opening in the panel top the reader is lowered through (clears its socket)."""
    depth = READER_PCB + SOCKET_H + 1.0
    return _reader_frame() * _box(-READER_W / 2 - 0.5, READER_W / 2 + 0.5,
                                  READER_H / 2 - 5, READER_H / 2 + 80, SKIN_IN - depth, SKIN_IN)


def body():
    s, c = math.sin(math.radians(LEAN)), math.cos(math.radians(LEAN))
    gy = YS + STEP                                 # panel front-bottom
    top_y, top_z = gy + PANEL_LEN * s, ZS + PANEL_LEN * c
    bx = top_y + TOP_T                             # back face: vertical, full height
    profile = [
        (0, 0), (0, HF), (YS, ZS), (gy, ZS),
        (top_y, top_z), (bx, top_z), (bx, 0),
    ]
    with BuildSketch(Plane.YZ) as sk:
        with BuildLine():
            Polyline(*profile, close=True)
        make_face()
    solid = extrude(sk.sketch, amount=W / 2, both=True)

    # Lean the left and right faces inwards so the body looks planted.
    t = (W - TOP_W) / 2 / top_z            # side lean, from the two widths
    h = top_z + 1.0
    with BuildSketch(Plane.XZ) as tk:
        with BuildLine():
            Polyline((-W / 2, 0), (W / 2, 0), (W / 2 - h * t, h), (-W / 2 + h * t, h), close=True)
        make_face()
    solid = solid & extrude(tk.sketch, amount=200, both=True)

    # Round the outside edges. Bottom edges stay sharp (sits flat; prints flat on
    # the bed), and so does the inside corner where the print stands against the
    # panel, so the print's bottom edge seats fully.
    def rounded(e) -> bool:
        c = e.center()
        if c.Z < 0.01:
            return False
        return not (abs(c.Y - gy) < 0.01 and abs(c.Z - ZS) < 0.01)
    solid = fillet([e for e in solid.edges() if rounded(e)], radius=FILLET)
    shell = offset(solid, amount=-WALL, openings=solid.faces().sort_by(Axis.Z)[0])
    shell = shell + (rails() & solid) - _slot()

    # Lip at the front of the groove, so the print can't slide off the shelf.
    lip = Pos(0, YS + LIP_W / 2, ZS) * Box(PRINT_W + 8, LIP_W, LIP_H, align=C)
    lip = fillet(lip.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1], radius=1.0)
    shell = shell + lip

    # Screen window, joystick hole, posts for the HAT under the slope.
    f = _slope_frame(HAT_S)
    ww, wh, wx, wy = WINDOW
    shell -= f * Pos(wx, wy, 0) * Box(ww, wh, WALL * 3, align=CC)
    # The joystick's 10 mm square housing rises through the face, so the opening
    # is square with 0.5 mm clearance rather than a round hole for the knob.
    shell -= f * Pos(*JOY, 0) * Box(11, 11, WALL * 3, align=CC)
    # The unused K1-K3 stand taller than the glass, so they get a shallow pocket
    # under the face (0.4 mm clearance) instead of holes.
    pocket = BUTTON_H - GLASS_H + 0.4
    ys = [by for _, by in BUTTONS]
    shell -= f * Pos(BUTTONS[0][0], (max(ys) + min(ys)) / 2, -WALL) * Box(
        BUTTON_FOOT[0] + 1.5, max(ys) - min(ys) + BUTTON_FOOT[1] + 1.5, pocket, align=C)
    for hx in (-HOLE_DX / 2, HOLE_DX / 2):
        for hy in (-HOLE_DY / 2, HOLE_DY / 2):
            post_len = GLASS_H
            post = f * Pos(hx, hy, -WALL - post_len) * Cylinder(2.6, post_len, align=C)
            hole = f * Pos(hx, hy, -WALL - post_len) * Cylinder(1.1, post_len, align=C)
            shell = shell + post - hole

    # USB-C power: the breakout sits on four posts inside the back wall with its
    # socket flush with the outside, showing through a rounded slot.
    post_len = PWR_RISE - WALL
    for dx in (-PWR_HOLES[0] / 2, PWR_HOLES[0] / 2):
        for dz in (-PWR_HOLES[1] / 2, PWR_HOLES[1] / 2):
            at = Pos(PWR_X + dx, bx - WALL, PWR_Z + dz) * Rot(90, 0, 0)
            shell = shell + at * Cylinder(2.75, post_len, align=C) - at * Cylinder(1.1, post_len, align=C)
    slot = Box(PWR_SHELL[0] + 0.5, WALL * 3, PWR_SHELL[1] + 0.5, align=CC)
    slot = fillet(slot.edges().filter_by(Axis.Y), radius=(PWR_SHELL[1] + 0.5) / 2 - 0.05)
    shell -= Pos(PWR_X, bx, PWR_Z) * slot
    return shell


def internals():
    f = _slope_frame(HAT_S)
    hat_top = -WALL - GLASS_H
    gw, gh, gx, gy = GLASS
    hat = f * Pos(0, 0, hat_top - HAT_T) * Box(HAT_W, HAT_D, HAT_T, align=C)
    glass = f * Pos(gx, gy, hat_top) * Box(gw, gh, GLASS_H, align=C)
    joy = f * Pos(*JOY, hat_top) * Box(10, 10, JOY_HOUSING_H, align=C)
    knob = f * Pos(*JOY, hat_top + JOY_HOUSING_H) * Cylinder(JOY_KNOB_D / 2, JOY_KNOB_H, align=C)
    buttons = [f * Pos(bx, by, hat_top) * Box(*BUTTON_FOOT, BUTTON_H, align=C) for bx, by in BUTTONS]
    pi_bottom = hat_top - STACK
    pi = f * Pos(0, 0, pi_bottom - PI_UNDER) * Box(HAT_W, HAT_D, PI_T + PI_UNDER, align=C)

    # The print standing in the groove, image facing out, tag on its back.
    pf = _print_frame()
    card = pf * Pos(0, PRINT_H / 2, 0) * Box(PRINT_W, PRINT_H, PRINT_T, align=C)
    image = pf * Pos(0, PRINT_H - 6 - 31, PRINT_T + 0.2) * Box(62, 62, 0.2, align=C)
    tag = pf * Pos(0, TAG_UP, -0.3) * Box(TAG, TAG, 0.3, align=C)

    # Reader in the rails, antenna side facing the print; its USB-C socket sits
    # on the back at the bottom short edge.
    rf = _reader_frame()
    reader = rf * Pos(0, 0, BOARD_FRONT - READER_PCB) * Box(READER_W, READER_H, READER_PCB, align=C)
    socket = rf * Pos(0, -READER_H / 2 + 3, BOARD_FRONT - READER_PCB - SOCKET_H) * Box(
        9, 7, SOCKET_H, align=C)
    antenna_up = ANTENNA_FROM_USB_END - READER_H / 2
    antenna = rf * Pos(0, antenna_up, BOARD_FRONT - 0.2) * Box(READER_W - 1, ANTENNA_H, 0.2, align=C)

    top = _power_board_top()
    pwr_board = Pos(PWR_X, top - PWR_BOARD[2], PWR_Z) * Box(
        PWR_BOARD[0], PWR_BOARD[2], PWR_BOARD[1], align=(Align.CENTER, Align.MIN, Align.CENTER))
    pwr_shell = Box(PWR_SHELL[0], PWR_RISE, PWR_SHELL[1], align=(Align.CENTER, Align.MIN, Align.CENTER))
    pwr_shell = Pos(PWR_X, top, PWR_Z) * fillet(  # USB-C shells have rounded ends
        pwr_shell.edges().filter_by(Axis.Y), radius=PWR_SHELL[1] / 2 - 0.05)
    return {
        "hat": [hat, joy, *buttons],
        "screen": glass,
        "buttons": knob,
        "reader": reader,
        "antenna": antenna,
        "print": card,
        "image": image,
        "tag": tag,
        "port": [pwr_shell, socket],
        "pi": [pi, pwr_board],
    }


def cut(parts: dict, keep_x_max: float):
    """Keep only geometry at x <= keep_x_max, for a cut-away view from +x."""
    half = Pos(keep_x_max, -50, -50) * Box(200, 400, 400, align=(Align.MAX, Align.MIN, Align.MIN))
    out = {}
    for key, value in parts.items():
        shapes = value if isinstance(value, list) else [value]
        kept = [s & half for s in shapes]
        kept = [k for k in kept if k.volume > 1e-3]
        if kept:
            out[key] = kept
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    b = body()
    export_stl(b, str(OUT / "easel_body.stl"))
    inside = internals()
    whole = {"body": b, **inside}
    # Cut just off-centre so the section passes through the screen and reader.
    section = cut({"body": b, **inside}, keep_x_max=-0.5)
    bb = b.bounding_box()
    dims = f"{bb.size.X:.0f} W × {bb.size.Y:.0f} D × {bb.size.Z:.0f} H mm (body)"
    render(
        {
            "Front": {k: v for k, v in whole.items() if k not in ("pi", "reader", "tag")},
            "Back (USB-C power)": {k: v for k, v in whole.items() if k in ("body", "print")},
            "Cut-away side view": section,
        },
        OUT / "easel.png",
        views=[(22, -55), (20, 130), (0, 0)],
    )
    print(f"wrote {OUT / 'easel.png'}  {dims}")
