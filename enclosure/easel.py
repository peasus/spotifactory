"""Spotifactory enclosure ("easel"): three printable parts.

Screen + joystick on a 12° face you look down on; the Instax print stands in a
groove behind it, leaning against a panel that holds the PN532 reader behind
the tag. USB-C power on the back.

Parts and print orientation:
  body       upright, no supports (inside ledges are propped by 45° wedges)
  faceplate  face down; drops in from inside under a 1.2 mm lip
  baseplate  flat; screws into M3 heat-set inserts in the body, and its posts
             press the Pi up so the whole stack clamps against the faceplate

Run:  enclosure/.venv/bin/python enclosure/easel.py
Writes renders to enclosure/out/ and print files to enclosure/out/print/.
"""
from __future__ import annotations

import math
from pathlib import Path

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
    Vector,
    export_step,
    export_stl,
    extrude,
    fillet,
    make_face,
    offset,
)

from concepts import OUT, PRINT_H, PRINT_T, PRINT_W, render

C = (Align.CENTER, Align.CENTER, Align.MIN)
CC = (Align.CENTER, Align.CENTER, Align.CENTER)
PRINT_DIR = OUT / "print"

# ---------------------------------------------------------------- body
W = 104.0                 # width at the base
TOP_W = 81.0              # width at the top of the panel (print is 72)
WALL = 2.4                # 4 lines at 0.6 mm nozzle (wood-fill PLA)
FILLET = 6.0              # outside edge radius (panel top is 14 mm deep, so < 7)
SLOPE = 12.0              # control face angle, degrees
LEAN = 15.0               # print leans back this far from vertical
TOP_T = 14.0              # panel thickness at the top; the back drops vertically from here
PANEL_LEN = 82.0          # panel height along its lean
STEP = 5.0                # flat shelf at the top of the slope (groove sits here)
LIP_H, LIP_W, GROOVE = 5.0, 3.0, 2.5

# ---------------------------------------------------------------- faceplate
LIP_T = 1.2               # body lip over the faceplate's edge
FP_T = 2.0                # faceplate thickness
FP_OVERLAP = 2.0          # how far the lip overlaps the faceplate
FP_CLEAR = 0.25           # faceplate to pocket clearance, each side
FP_HW = 35.0              # faceplate half-width
FP_CORNER = 3.0

# ---------------------------------------------------------------- base plate
PLATE_T = 2.4
UNDER_CLEAR = 1.5         # lowest point of the Pi above the base plate
BOSS_R, BOSS_H = 4.0, 8.0
INSERT_D, INSERT_DEPTH = 4.0, 5.5   # Adafruit 4255 M3 x 4 mm heat-set insert
SCREW_CLEAR = 3.4                   # M3

# ---------------------------------------------------------------- boards (measured / datasheet)
HAT_W, HAT_D, HAT_T = 65.0, 30.0, 1.6
HOLE_DX, HOLE_DY = 58.0, 23.5       # same pattern on the Pi Zero
# Positions in the slope frame: x across, y up-slope, origin at board centre.
# Stack as on the device: joystick on the left, the Pi's USB ports along the
# top (back) edge where there's room for straight plugs.
WINDOW = (31.0, 16.0, 0.2, -1.5)    # w, h, cx, cy  (active area 29.4 x 14.7)
GLASS = (35.2, 22.6, 0.3, 0.3)
JOY = (-25.3, 0.2)
BUTTONS = [(24.9, 6.7), (24.9, 0.6), (24.9, -5.4)]  # K1-K3 (unused, covered)
BUTTON_FOOT = (6.2, 3.6)
GLASS_H = 1.3             # measured: OLED glass top above HAT board top
JOY_HOUSING_H = 2.1       # measured
JOY_TOP = 9.9             # measured: joystick top above HAT board top
JOY_KNOB_D = 7.3
BUTTON_H = 2.0            # measured
STACK = 11.5              # measured: HAT board top to Pi board bottom
PI_T, PI_UNDER = 1.4, 1.6 # Pi board thickness; parts on its underside (estimate)
PIN_D = 2.3               # locating pins into the HAT's 2.7 mm holes

READER_W, READER_H = 38.15, 60.0  # measured PN532 board; stands upright, USB end down
ANTENNA_FROM_USB_END = 39.5       # measured
ANTENNA_H = 31.0                  # measured: loop height (spans full width)
READER_PCB = 1.6
SOCKET_H = 4.9 - READER_PCB       # measured: PCB bottom to USB-C socket top 4.9 mm
GAP = 0.7                         # print back to panel front face
TAG = 25.4                        # 1" square tag, centred on the 62 mm image
TAG_UP = 49.0                     # tag centre above the print's bottom edge

# Adafruit 5993 USB-C vertical breakout (5.1k CC pull-downs: any USB-C charger
# powers it). From Adafruit's published STEP model.
PWR_BOARD = (30.48, 15.24, 1.57)
PWR_HOLES = (25.4, 10.16)
PWR_SHELL = (9.35, 4.44)
PWR_RISE = 9.30                   # shell top above the board's top surface
PWR_X, PWR_Z = W / 2 - 30, 13.0   # board centre on the back wall (lower left, from behind)

# ---------------------------------------------------------------- derived layout
_A = math.radians(SLOPE)
FP_FACE = -LIP_T                          # faceplate top, below the slope surface
HAT_TOP = FP_FACE - FP_T - GLASS_H        # in the slope frame
STACK_DEPTH = -HAT_TOP + STACK + PI_UNDER # slope surface to the Pi's underside
# Boards start as close to the front as they can: the stack hangs below a
# tilted face, so its lower edge leans forward; keep that 1 mm off the wall.
HAT_S = (WALL + 1.0 + STACK_DEPTH * math.sin(_A)) / math.cos(_A) + HAT_D / 2
FP_Y0, FP_Y1 = -HAT_D / 2 - 2.0, HAT_D / 2 + 4.0   # faceplate extent, slope frame
HF = UNDER_CLEAR + STACK_DEPTH * math.cos(_A) - (HAT_S - HAT_D / 2) * math.sin(_A)
YS = (HAT_S + FP_Y1) * math.cos(_A)       # slope ends where the faceplate does
ZS = HF + YS * math.tan(_A)
_S, _C = math.sin(math.radians(LEAN)), math.cos(math.radians(LEAN))
GY = YS + STEP                            # panel front-bottom
TOP_Y, TOP_Z = GY + PANEL_LEN * _S, ZS + PANEL_LEN * _C
BACK_Y = TOP_Y + TOP_T                    # vertical back wall, outside


def _box(x0, x1, y0, y1, z0, z1):
    """Box from min/max corners, in whatever frame it's placed."""
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=C)


def _rounded(box, radius, axis):
    return fillet(box.edges().filter_by(axis), radius=radius)


def hat_frame():
    """Slope frame at the board centre: x across, y up-slope, z out of the face."""
    s = HAT_S
    return Pos(0, s * math.cos(_A), HF + s * math.sin(_A)) * Rot(SLOPE, 0, 0)


def _print_frame():
    """Origin at the print's bottom edge in the groove; y up the print, z out of its face."""
    return Pos(0, YS + LIP_W + GROOVE / 2, ZS + 0.3) * Rot(90 - LEAN, 0, 0)


def _reader_frame():
    """Reader centre in the print frame: antenna behind the tag, USB end down."""
    centre_up = TAG_UP - (ANTENNA_FROM_USB_END - READER_H / 2)
    return _print_frame() * Pos(0, centre_up, 0)


# Reader mounting depths behind the print plane (negative z in the print frame).
SKIN_IN = -(GAP + WALL)
BOARD_FRONT = SKIN_IN - 0.3
CHANNEL = READER_PCB + 0.6
RAIL_LIP = 1.5
RAIL_BACK = SKIN_IN - CHANNEL - RAIL_LIP


# ================================================================ body
def outer():
    """The solid outside shape: side profile, leaning sides, rounded edges."""
    profile = [(0, 0), (0, HF), (YS, ZS), (GY, ZS), (TOP_Y, TOP_Z), (BACK_Y, TOP_Z), (BACK_Y, 0)]
    with BuildSketch(Plane.YZ) as sk:
        with BuildLine():
            Polyline(*profile, close=True)
        make_face()
    solid = extrude(sk.sketch, amount=W / 2, both=True)

    # Lean the left and right faces inwards so it looks planted.
    t, h = (W - TOP_W) / 2 / TOP_Z, TOP_Z + 1.0
    with BuildSketch(Plane.XZ) as tk:
        with BuildLine():
            Polyline((-W / 2, 0), (W / 2, 0), (W / 2 - h * t, h), (-W / 2 + h * t, h), close=True)
        make_face()
    solid = solid & extrude(tk.sketch, amount=200, both=True)

    # Round the outside edges. Bottom edges stay sharp (sits flat, prints flat),
    # and so does the corner the print stands in, so it seats fully.
    def rounded(e) -> bool:
        c = e.center()
        return c.Z > 0.01 and not (abs(c.Y - GY) < 0.01 and abs(c.Z - ZS) < 0.01)
    return fillet([e for e in solid.edges() if rounded(e)], radius=FILLET)


def rails():
    """Card-guide rails inside the panel's front skin, plus bottom stops.

    The reader drops in from the slot in the panel top, antenna side forward,
    and rests on the stops; the gap between them clears its USB-C plug.
    """
    half, lo, hi = READER_W / 2, -READER_H / 2, READER_H / 2
    out = None
    for side in (-1, 1):
        def m(a, b):
            return (min(side * a, side * b), max(side * a, side * b))
        for piece in (
            _box(*m(half + 0.4, half + 2.4), lo - 2, hi, RAIL_BACK, SKIN_IN),                  # wall
            _box(*m(half - RAIL_LIP, half + 2.4), lo - 2, hi, RAIL_BACK, SKIN_IN - CHANNEL),   # lip
            _box(*m(half - 6, half + 2.4), lo - 2, lo - 0.3, RAIL_BACK, SKIN_IN),              # stop
        ):
            out = piece if out is None else out + piece
    return _reader_frame() * out


def _reader_slot():
    """Opening in the panel top the reader is lowered through. Also the warm-air outlet."""
    depth = READER_PCB + SOCKET_H + 1.0
    return _reader_frame() * _box(-READER_W / 2 - 0.5, READER_W / 2 + 0.5,
                                  READER_H / 2 - 5, READER_H / 2 + 80, SKIN_IN - depth, SKIN_IN)


def _faceplate_outline(grow: float, z0: float, z1: float):
    """Faceplate-shaped block in the slope frame, grown by `grow` on every side."""
    b = _box(-FP_HW - grow, FP_HW + grow, FP_Y0 - grow, FP_Y1 + grow, z0, z1)
    return _rounded(b, max(FP_CORNER + grow, 0.5), Axis.Z)


def boss_positions():
    inner = W / 2 - WALL - BOSS_R - 0.5
    return [(sx * inner, y) for sx in (-1, 1)
            for y in (WALL + BOSS_R + 0.5, BACK_Y - WALL - BOSS_R - 0.5)]


def body():
    solid = outer()
    shell = offset(solid, amount=-WALL, openings=solid.faces().sort_by(Axis.Z)[0])
    cavity = solid - shell
    f = hat_frame()

    # Faceplate pocket (from inside) and the window in the lip above it.
    shell -= f * _faceplate_outline(FP_CLEAR, FP_FACE - FP_T - 6, FP_FACE)
    shell -= f * _faceplate_outline(-FP_OVERLAP, -6, 6)

    # 45° wedges under the remaining ledges, so the body prints without supports.
    for side in (-1, 1):
        x0 = side * (FP_HW + FP_CLEAR)
        with BuildSketch(Plane.XZ) as wk:
            with BuildLine():
                Polyline((x0, -WALL), (x0 + side * 80, -WALL), (x0 + side * 80, -WALL - 80), close=True)
            make_face()
        # Plane.XZ extrudes along -Y; place it so it spans the slope from the front wall back.
        wedge = Pos(0, FP_Y1, 0) * extrude(wk.sketch, amount=FP_Y1 - FP_Y0 + 40)
        shell += (f * wedge) & cavity
    # Under the shelf behind the faceplate (clear of the reader's cable in the middle).
    # The faceplate's back edge is square to the tilted face, so its lower corner
    # sits further back than the slope's end: start behind that.
    fp_back = (f * Pos(0, FP_Y1 + FP_CLEAR, FP_FACE - FP_T)).position.Y
    with BuildSketch(Plane.YZ) as sk:
        y0, top = fp_back + 0.3, ZS - WALL
        with BuildLine():
            Polyline((y0, top), (GY + 6, top), (GY + 6, top - (GY + 6 - y0)), close=True)
        make_face()
    for side in (-1, 1):
        shelf = Pos(side * 36, 0, 0) * extrude(sk.sketch, amount=24, both=True)
        shell += shelf & cavity

    # Reader rails and its top slot; lip at the front of the print's groove.
    shell = shell + (rails() & solid) - _reader_slot()
    # Sunk 1 mm into the shelf so it bonds to it rather than sitting on the fillet.
    lip = Pos(0, YS + LIP_W / 2, ZS - 1) * Box(PRINT_W + 8, LIP_W, LIP_H + 1, align=C)
    shell += fillet(lip.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1], radius=1.0)

    # USB-C power: breakout on four posts inside the back wall, socket flush with
    # the outside through a rounded slot.
    post_len = PWR_RISE - WALL
    for dx in (-PWR_HOLES[0] / 2, PWR_HOLES[0] / 2):
        for dz in (-PWR_HOLES[1] / 2, PWR_HOLES[1] / 2):
            at = Pos(PWR_X + dx, BACK_Y - WALL, PWR_Z + dz) * Rot(90, 0, 0)
            shell = shell + at * Cylinder(2.75, post_len, align=C) - at * Cylinder(1.1, post_len, align=C)
    slot = _rounded(Box(PWR_SHELL[0] + 0.5, WALL * 3, PWR_SHELL[1] + 0.5, align=CC),
                    (PWR_SHELL[1] + 0.5) / 2 - 0.05, Axis.Y)
    shell -= Pos(PWR_X, BACK_Y, PWR_Z) * slot

    # Vents low on the back (warm air leaves through the reader slot up top).
    for i in range(5):
        vx = -(14 + 5 * i)
        shell -= Pos(vx, BACK_Y, 6) * _rounded(Box(2.4, WALL * 3, 14, align=C), 1.15, Axis.Y)

    # Bosses for the base plate's heat-set inserts.
    for bx, by in boss_positions():
        boss = Pos(bx, by, 0) * Cylinder(BOSS_R, BOSS_H, align=C)
        shell = shell + (boss & solid) - Pos(bx, by, 0) * Cylinder(INSERT_D / 2, INSERT_DEPTH, align=C)
    return shell


# ================================================================ faceplate
def faceplate():
    """Flat plate with the screen window and joystick opening; pins locate the HAT."""
    plate = _faceplate_outline(0, FP_FACE - FP_T, FP_FACE)
    ww, wh, wx, wy = WINDOW
    plate -= Pos(wx, wy, FP_FACE - FP_T - 1) * _rounded(Box(ww, wh, FP_T + 2, align=C), 1.0, Axis.Z)
    plate -= Pos(*JOY, FP_FACE - FP_T - 1) * _rounded(Box(11, 11, FP_T + 2, align=C), 1.5, Axis.Z)
    # The unused K1-K3 stand taller than the glass: shallow pocket underneath.
    ys = [by for _, by in BUTTONS]
    pocket = BUTTON_H - GLASS_H + 0.4
    plate -= Pos(BUTTONS[0][0], (max(ys) + min(ys)) / 2, FP_FACE - FP_T) * Box(
        BUTTON_FOOT[0] + 1.5, max(ys) - min(ys) + BUTTON_FOOT[1] + 1.5, pocket, align=C)
    # Shoulders the HAT rests on (so the glass just touches the plate) and pins
    # into its mounting holes.
    for hx in (-HOLE_DX / 2, HOLE_DX / 2):
        for hy in (-HOLE_DY / 2, HOLE_DY / 2):
            plate += Pos(hx, hy, HAT_TOP) * Cylinder(2.5, GLASS_H, align=C)
            plate += Pos(hx, hy, HAT_TOP - HAT_T - 1.0) * Cylinder(PIN_D / 2, HAT_T + 1.0, align=C)
    return hat_frame() * plate


# ================================================================ base plate
def baseplate():
    """Flat plate under the body: screws, vents, foot recesses, and posts that
    press the Pi up so the stack clamps against the faceplate."""
    foot = outer().faces().sort_by(Axis.Z)[0]
    plate = extrude(foot, amount=PLATE_T, dir=(0, 0, -1))
    for bx, by in boss_positions():
        plate -= Pos(bx, by, -PLATE_T - 1) * Cylinder(SCREW_CLEAR / 2, PLATE_T + 2, align=C)

    f = hat_frame()
    pi_bottom = HAT_TOP - STACK
    below_pi = f * _box(-60, 60, -60, 60, pi_bottom - 60, pi_bottom)
    for hx in (-HOLE_DX / 2, HOLE_DX / 2):
        for hy in (-HOLE_DY / 2, HOLE_DY / 2):
            p = f * Pos(hx, hy, pi_bottom)
            at = p.position
            post = Pos(at.X, at.Y, 0) * Cylinder(2.5, at.Z + 2, align=C)
            plate += post & below_pi

    # Vent slots under the Pi.
    centre_y = (f * Pos(0, 0, 0)).position.Y
    for i in range(-4, 5):
        plate -= Pos(i * 6.0, centre_y, -PLATE_T - 1) * _rounded(
            Box(2.4, 18, PLATE_T + 2, align=C), 1.15, Axis.Z)
    return plate


# ================================================================ boards etc. (for checks + renders)
def internals():
    f = hat_frame()
    gw, gh, gx, gy = GLASS
    holes = [Pos(hx, hy, 0) * Cylinder(1.35, 50, align=CC)
             for hx in (-HOLE_DX / 2, HOLE_DX / 2) for hy in (-HOLE_DY / 2, HOLE_DY / 2)]
    hat = Box(HAT_W, HAT_D, HAT_T, align=C)
    pi_pcb = Box(HAT_W, HAT_D, PI_T, align=C)
    for h in holes:
        hat, pi_pcb = hat - h, pi_pcb - h
    hat = f * Pos(0, 0, HAT_TOP - HAT_T) * hat
    glass = f * Pos(gx, gy, HAT_TOP) * Box(gw, gh, GLASS_H, align=C)
    joy = f * Pos(*JOY, HAT_TOP) * Box(10, 10, JOY_HOUSING_H, align=C)
    knob = f * Pos(*JOY, HAT_TOP + JOY_HOUSING_H) * Cylinder(
        JOY_KNOB_D / 2, JOY_TOP - JOY_HOUSING_H, align=C)
    buttons = [f * Pos(bx, by, HAT_TOP) * Box(*BUTTON_FOOT, BUTTON_H, align=C) for bx, by in BUTTONS]
    pi_bottom = HAT_TOP - STACK
    pi = f * Pos(0, 0, pi_bottom) * pi_pcb
    # Parts on the Pi's underside stay clear of its mounting holes (keep-out).
    pi_under = f * Pos(0, 0, pi_bottom - PI_UNDER) * Box(HOLE_DX - 8, HAT_D - 4, PI_UNDER, align=C)

    pf = _print_frame()
    card = pf * Pos(0, PRINT_H / 2, 0) * Box(PRINT_W, PRINT_H, PRINT_T, align=C)
    image = pf * Pos(0, PRINT_H - 6 - 31, PRINT_T + 0.2) * Box(62, 62, 0.2, align=C)
    tag = pf * Pos(0, TAG_UP, -0.3) * Box(TAG, TAG, 0.3, align=C)

    rf = _reader_frame()
    reader = rf * Pos(0, 0, BOARD_FRONT - READER_PCB) * Box(READER_W, READER_H, READER_PCB, align=C)
    socket = rf * Pos(0, -READER_H / 2 + 3, BOARD_FRONT - READER_PCB - SOCKET_H) * Box(
        9, 7, SOCKET_H, align=C)
    antenna = rf * Pos(0, ANTENNA_FROM_USB_END - READER_H / 2, BOARD_FRONT - 0.2) * Box(
        READER_W - 1, ANTENNA_H, 0.2, align=C)

    top = BACK_Y - PWR_RISE
    pwr_board = Pos(PWR_X, top - PWR_BOARD[2], PWR_Z) * Box(
        PWR_BOARD[0], PWR_BOARD[2], PWR_BOARD[1], align=(Align.CENTER, Align.MIN, Align.CENTER))
    pwr_shell = Pos(PWR_X, top, PWR_Z) * _rounded(
        Box(PWR_SHELL[0], PWR_RISE, PWR_SHELL[1], align=(Align.CENTER, Align.MIN, Align.CENTER)),
        PWR_SHELL[1] / 2 - 0.05, Axis.Y)
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
        "pi": [pi, pi_under, pwr_board],
    }


def cut(parts: dict, keep_x_max: float):
    """Keep only geometry at x <= keep_x_max, for a cut-away view from +x."""
    half = Pos(keep_x_max, -50, -50) * Box(200, 400, 400, align=(Align.MAX, Align.MIN, Align.MIN))
    out = {}
    for key, value in parts.items():
        kept = [s & half for s in (value if isinstance(value, list) else [value])]
        kept = [k for k in kept if k.volume > 1e-3]
        if kept:
            out[key] = kept
    return out


def print_orientation():
    """Each part moved to sit on the bed (z = 0) the way it should be printed."""
    b, fp, bp = body(), faceplate(), baseplate()
    # Faceplate: undo the slope frame, flip face-down.
    fp_flat = Rot(180, 0, 0) * (hat_frame().inverse() * fp)
    fp_flat = Pos(0, 0, -fp_flat.bounding_box().min.Z) * fp_flat
    bp_flat = Pos(0, 0, PLATE_T) * bp
    return {"body": b, "faceplate": fp_flat, "baseplate": bp_flat}


def export_parts() -> dict[str, Path]:
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, part in print_orientation().items():
        stl = PRINT_DIR / f"spotifactory_{name}.stl"
        export_stl(part, str(stl))
        out[name] = stl
    # STEP files in assembled position, for tweaking in Fusion / Onshape.
    for name, part in (("body", body()), ("faceplate", faceplate()), ("baseplate", baseplate())):
        export_step(part, str(PRINT_DIR / f"spotifactory_{name}.step"))
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    b, fp, bp = body(), faceplate(), baseplate()
    inside = internals()
    whole = {"body": b, "cover": fp, "port": bp, **{k: v for k, v in inside.items() if k != "port"}}
    whole["port"] = [bp, *inside["port"]]
    section = cut({"body": b, "cover": fp, **inside, "pi": [*inside["pi"], bp]}, keep_x_max=-0.5)
    render(
        {
            "Front": {k: v for k, v in whole.items() if k not in ("pi", "reader", "tag")},
            "Back (USB-C power + vents)": {"body": b, "print": inside["print"], "port": bp},
            "Cut-away side view": section,
        },
        OUT / "easel.png",
        views=[(22, -55), (20, 130), (0, 0)],
    )
    files = export_parts()
    flat = print_orientation()
    render(
        {
            "Body (upright)": {"body": flat["body"]},
            "Faceplate (face down)": {"cover": flat["faceplate"]},
            "Base plate (flat)": {"port": flat["baseplate"]},
        },
        OUT / "parts.png",
        views=[(25, -55), (35, -55), (35, -55)],
    )
    print("wrote", OUT / "easel.png", OUT / "parts.png", "and", ", ".join(p.name for p in files.values()))
