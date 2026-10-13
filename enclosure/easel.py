"""Spotifactory enclosure ("easel"): printable parts.

Screen + joystick on a 12° face you look down on; the Instax print stands in a
groove behind it, leaning against a panel that holds the PN532 reader behind
the tag. USB-C power on the back.

Parts and print orientation:
  body       upright, no supports
  faceplate  face down; the Pi + HAT stack screws to it (through spacers) and
             the assembly goes in from below, under a 1.2 mm lip
  spacers    4 tubes between the HAT and the Pi
  baseplate  flat, under the body; screws into M3 heat-set inserts in the
             body's corners, carries the USB-C power board on a bracket, and
             its posts press the stack up against the lip

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
    Cone,
    Cylinder,
    Plane,
    Polyline,
    Pos,
    Rot,
    chamfer,
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
BOTTOM_CHAMFER = 1.0      # bottom outside edge: with the inset base plate, a clean shadow line
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
PILOT_M25 = 2.1           # pilot hole for M2.5 screws threading into PLA

# ---------------------------------------------------------------- base plate
PLATE_T = 2.4
PLATE_INSET = 0.6         # plate edge inside the body's (chamfered) bottom edge
UNDER_CLEAR = 1.5         # lowest point of the Pi above the base plate
BOSS_R, BOSS_H = 4.0, 8.0
INSERT_D, INSERT_DEPTH = 4.0, 5.5   # Adafruit 4255 M3 x 4 mm heat-set insert
SCREW_CLEAR = 3.4                   # M3
HEAD_D, HEAD_H = 5.2, 2.0           # M2.5 pan head under the Pi (posts clear it)

# ---------------------------------------------------------------- boards (measured / datasheet)
HAT_W, HAT_D, HAT_T = 65.0, 30.0, 1.6
HOLE_DX, HOLE_DY = 58.0, 23.5       # same pattern on the Pi Zero
# Positions in the slope frame: x across, y up-slope, origin at board centre.
# Stack as on the device: joystick on the left, the Pi's USB ports along the
# back edge where there's room for straight plugs.
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
BOARD_GAP = STACK - HAT_T - PI_T    # ASSUMED 8.5: HAT underside to Pi top = spacer length
PI_PORTS_X = (-21.5, -8.9)          # PWR, USB micro-USB ports on the back edge (Pi Zero layout)
MICRO_USB_PLUG = (11.0, 7.0, 28.0)  # overmold w, h, length incl. cable bend

READER_W, READER_H = 38.15, 60.0  # measured PN532 board; stands upright, USB end down
READER_HOLES = (33.2, 54.5)       # measured hole spacing
READER_HOLE_D = 3.0               # ASSUMED: check against the board
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
PWR_COLLAR = (12.0, 5.0)            # plastic around the shell, 8.8 mm tall
PWR_RISE = 9.30                     # shell top above the board's top surface
PWR_X, PWR_Z = W / 2 - 30, 13.0     # board centre (lower left, seen from behind)
PLUG_OPENING = (13.5, 8.0)          # wall opening: fits most USB-C plug overmolds

# ---------------------------------------------------------------- derived layout
_A = math.radians(SLOPE)
FP_FACE = -LIP_T                          # faceplate top, below the slope surface
HAT_TOP = FP_FACE - FP_T - GLASS_H        # in the slope frame
PI_BOTTOM = HAT_TOP - STACK
STACK_DEPTH = -PI_BOTTOM + PI_UNDER       # slope surface to the Pi's underside
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
# The back leans in at the same angle as the sides; the top keeps TOP_T of
# depth, so the base reaches further back.
BACK_LEAN = math.atan((W - TOP_W) / 2 / TOP_Z)
_BT = math.tan(BACK_LEAN)
BACK_Y = TOP_Y + TOP_T + TOP_Z * _BT      # outside of the back wall, at the bed


def back_out_y(z: float) -> float:
    """y of the outside of the (leaning) back wall at height z."""
    return BACK_Y - z * _BT


def back_in_y(z: float) -> float:
    """y of the inside of the back wall at height z."""
    return back_out_y(z) - WALL / math.cos(BACK_LEAN)


WALL_IN_Y = back_in_y(0)
# Socket ends just inside the wall, measured at its top (the wall leans in).
PWR_BOARD_TOP_Y = back_in_y(PWR_Z + PWR_SHELL[1] / 2) - 0.2 - PWR_RISE


def _box(x0, x1, y0, y1, z0, z1):
    """Box from min/max corners, in whatever frame it's placed."""
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=C)


def _rounded(box, radius, axis):
    return fillet(box.edges().filter_by(axis), radius=radius)


def _yz_prism(points, half_width=200.0):
    """Polygon in the side (YZ) plane, extruded across the full width."""
    with BuildSketch(Plane.YZ) as sk:
        with BuildLine():
            Polyline(*points, close=True)
        make_face()
    return extrude(sk.sketch, amount=half_width, both=True)


def inner_front_y(z: float) -> float:
    """y of the inside of the panel's front wall at height z (extended below the shelf)."""
    return GY + WALL / _C + (z - ZS) * _S / _C


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


# Depths behind the print plane (negative z in the print/reader frame).
SKIN_IN = -(GAP + WALL)                    # inside of the panel's front wall
BOARD_FRONT = SKIN_IN - 0.3                # reader wedged on the nubs, antenna side forward
NUB_LEN = READER_PCB + 0.8


def _hole_positions(dx, dy):
    return [(sx * dx / 2, sy * dy / 2) for sx in (-1, 1) for sy in (-1, 1)]


# ================================================================ body
def outer(chamfered: bool = True):
    """The solid outside shape: side profile, leaning sides, rounded edges."""
    profile = [(0, 0), (0, HF), (YS, ZS), (GY, ZS), (TOP_Y, TOP_Z), (BACK_Y, TOP_Z), (BACK_Y, 0)]
    solid = _yz_prism(profile, W / 2)

    # Lean the left and right faces inwards so it looks planted.
    t, h = (W - TOP_W) / 2 / TOP_Z, TOP_Z + 1.0
    with BuildSketch(Plane.XZ) as tk:
        with BuildLine():
            Polyline((-W / 2, 0), (W / 2, 0), (W / 2 - h * t, h), (-W / 2 + h * t, h), close=True)
        make_face()
    solid = solid & extrude(tk.sketch, amount=200, both=True)
    solid &= _yz_prism([(-50, -1), (back_out_y(-1), -1), (back_out_y(TOP_Z + 1), TOP_Z + 1),
                        (-50, TOP_Z + 1)])

    # Round the outside edges, except the bottom and the corner the print stands in.
    def rounded(e) -> bool:
        c = e.center()
        return c.Z > 0.01 and not (abs(c.Y - GY) < 0.01 and abs(c.Z - ZS) < 0.01)
    solid = fillet([e for e in solid.edges() if rounded(e)], radius=FILLET)
    if not chamfered:
        return solid
    bottom = [e for e in solid.edges() if e.center().Z < 0.01]
    return chamfer(bottom, length=BOTTOM_CHAMFER)


def _faceplate_outline(grow: float, z0: float, z1: float):
    """Faceplate-shaped block in the slope frame, grown by `grow` on every side."""
    b = _box(-FP_HW - grow, FP_HW + grow, FP_Y0 - grow, FP_Y1 + grow, z0, z1)
    return _rounded(b, max(FP_CORNER + grow, 0.5), Axis.Z)


def boss_positions():
    """Insert bosses, merged into the four inside corners."""
    x = W / 2 - WALL - BOSS_R + 1.0
    return [(sx * x, y) for sx in (-1, 1)
            for y in (WALL + BOSS_R - 1.0, WALL_IN_Y - BOSS_R + 1.0)]


def nubs():
    """Four slightly tapered nubs on the inside of the panel; the reader presses on."""
    rb = (READER_HOLE_D + 0.15) / 2      # wedges just before the board reaches the wall
    rt = (READER_HOLE_D - 0.6) / 2
    rf = _reader_frame()
    out = None
    for hx, hy in _hole_positions(*READER_HOLES):
        nub = rf * Pos(hx, hy, SKIN_IN) * Rot(180, 0, 0) * Cone(rb, rt, NUB_LEN, align=C)
        # On a wall leaning back, the nub points slightly down, so its tip would
        # start printing in mid-air: flatten its underside level with its base.
        base_low = (rf * Pos(hx, hy - rb, SKIN_IN)).position.Z
        nub &= Pos(0, 0, base_low) * Box(400, 400, 400, align=C)
        out = nub if out is None else out + nub
    return out


def pi_plugs():
    """Straight micro-USB plugs in the Pi's PWR and USB ports (for clearance)."""
    w, h, length = MICRO_USB_PLUG
    port_z = PI_BOTTOM + PI_T + 1.3
    return [hat_frame() * _box(px - w / 2, px + w / 2, HAT_D / 2, HAT_D / 2 + length,
                               port_z - h / 2, port_z + h / 2) for px in PI_PORTS_X]


def _partition(cavity):
    """Vertical wall under the shelf, from the panel's inner face down to the bed.

    It holds up the shelf (which otherwise prints as a long unsupported
    ceiling) and splits the base into a front bay (Pi) and a back bay (reader
    cable, power). An opening with 45° shoulders lets the Pi's cables through.
    """
    top = ZS - WALL
    y0 = inner_front_y(top)
    wall = _yz_prism([(y0, 0), (y0 + WALL, 0), (y0 + WALL, top), (y0, top)]) & cavity
    # Opening sized to the plugs, measured where they cross the wall.
    plugs = pi_plugs()
    x0 = min(p.bounding_box().min.X for p in plugs) - 2.0
    x1 = max(p.bounding_box().max.X for p in plugs) + 2.0
    z1 = max(p.bounding_box().max.Z for p in plugs) + 2.0
    with BuildSketch(Plane.XZ) as ok:
        with BuildLine():
            Polyline((x0, -1), (x1, -1), (x1, z1 - 4), (x1 - 4, z1), (x0 + 4, z1), (x0, z1 - 4),
                     close=True)
        make_face()
    return wall - extrude(ok.sketch, amount=200, both=True)


def body():
    # Shell the unchamfered shape (offset fails silently with the bottom
    # chamfer), then cut the chamfer off the outside.
    solid = outer(chamfered=False)
    shell = offset(solid, amount=-WALL, openings=solid.faces().sort_by(Axis.Z)[0])
    cavity = solid - shell
    shell -= solid - outer()
    f = hat_frame()

    # Faceplate pocket (from inside) and the window in the lip above it.
    shell -= f * _faceplate_outline(FP_CLEAR, FP_FACE - FP_T - 6, FP_FACE)
    shell -= f * _faceplate_outline(-FP_OVERLAP, -6, 6)

    # 45° wedges under the side ledges beside the faceplate.
    for side in (-1, 1):
        x0 = side * (FP_HW + FP_CLEAR)
        with BuildSketch(Plane.XZ) as wk:
            with BuildLine():
                Polyline((x0, -WALL), (x0 + side * 80, -WALL), (x0 + side * 80, -WALL - 80), close=True)
            make_face()
        wedge = Pos(0, FP_Y1, 0) * extrude(wk.sketch, amount=FP_Y1 - FP_Y0 + 40)
        shell += (f * wedge) & cavity

    # Wall under the shelf, plus a 45° chamfer so the shelf's front edge
    # (beside the faceplate) isn't a bare ledge.
    shell += _partition(cavity)
    fp_back = (f * Pos(0, FP_Y1 + FP_CLEAR, FP_FACE - FP_T)).position.Y + 0.3
    top = ZS - WALL
    drop = inner_front_y(top) - fp_back
    shell += _yz_prism([(fp_back, top), (inner_front_y(top), top),
                        (inner_front_y(top), top - drop)]) & cavity

    # Peaked (45°) roof inside the panel top, so it prints without supports.
    zc = TOP_Z - WALL
    mid = (inner_front_y(zc) + back_in_y(zc)) / 2
    shell += _yz_prism([(mid - 40, zc - 40), (mid, zc), (mid + 40, zc - 40),
                        (mid + 40, zc + 10), (mid - 40, zc + 10)]) & cavity

    # Reader nubs; lip at the front of the print's groove.
    shell += nubs()
    lip = Pos(0, YS + LIP_W / 2, ZS - 1) * Box(PRINT_W + 8, LIP_W, LIP_H + 1, align=C)
    shell += fillet(lip.edges().filter_by(Axis.Z, reverse=True).group_by(Axis.Z)[-1], radius=1.0)

    # USB-C: opening in the back wall; the board itself rides on the base plate.
    opening = _rounded(Box(PLUG_OPENING[0], WALL * 3, PLUG_OPENING[1], align=CC),
                       PLUG_OPENING[1] / 2 - 0.05, Axis.Y)
    shell -= Pos(PWR_X, back_out_y(PWR_Z), PWR_Z) * opening

    # Vents low on the back.
    for i in range(5):
        shell -= Pos(-(14 + 5 * i), back_out_y(13), 6) * _rounded(Box(2.4, WALL * 3, 14, align=C), 1.15, Axis.Y)

    # Corner bosses for the base plate's heat-set inserts: merged into both
    # walls and standing on the bed.
    for bx, by in boss_positions():
        sx = 1 if bx > 0 else -1
        sy = -1 if by < BACK_Y / 2 else 1
        corner = _box(min(bx, bx + sx * 12), max(bx, bx + sx * 12),
                      min(by, by + sy * 12), max(by, by + sy * 12), 0, BOSS_H)
        boss = (Pos(bx, by, 0) * Cylinder(BOSS_R, BOSS_H, align=C) + corner) & solid
        shell = shell + boss - Pos(bx, by, 0) * Cylinder(INSERT_D / 2, INSERT_DEPTH, align=C)
    return shell


# ================================================================ faceplate + spacers
def faceplate():
    """Flat plate with the screen window and joystick opening. The HAT screws to
    its four bosses (from below, through the Pi and the spacers)."""
    plate = _faceplate_outline(0, FP_FACE - FP_T, FP_FACE)
    ww, wh, wx, wy = WINDOW
    plate -= Pos(wx, wy, FP_FACE - FP_T - 1) * _rounded(Box(ww, wh, FP_T + 2, align=C), 1.0, Axis.Z)
    plate -= Pos(*JOY, FP_FACE - FP_T - 1) * _rounded(Box(11, 11, FP_T + 2, align=C), 1.5, Axis.Z)
    ys = [by for _, by in BUTTONS]
    pocket = BUTTON_H - GLASS_H + 0.4
    plate -= Pos(BUTTONS[0][0], (max(ys) + min(ys)) / 2, FP_FACE - FP_T) * Box(
        BUTTON_FOOT[0] + 1.5, max(ys) - min(ys) + BUTTON_FOOT[1] + 1.5, pocket, align=C)
    blind = GLASS_H + FP_T - 0.8                     # leaves 0.8 mm under the visible face
    for hx, hy in _hole_positions(HOLE_DX, HOLE_DY):
        plate += Pos(hx, hy, HAT_TOP) * Cylinder(2.75, GLASS_H, align=C)
        plate -= Pos(hx, hy, HAT_TOP) * Cylinder(PILOT_M25 / 2, blind, align=C)
    return hat_frame() * plate


def spacers():
    """Four tubes for between the HAT and the Pi (M2.5 screws pass through)."""
    out = None
    for i in range(4):
        tube = Pos(i * 8.0, 0, 0) * (Cylinder(2.5, BOARD_GAP, align=C) - Cylinder(1.45, BOARD_GAP, align=C))
        out = tube if out is None else out + tube
    return out


# ================================================================ base plate
def baseplate():
    """Plate under the body: screw holes, vents, posts under the Pi, and the
    bracket the USB-C board screws to at the bench."""
    foot = offset(outer().faces().sort_by(Axis.Z)[0], amount=-PLATE_INSET)
    plate = extrude(foot, amount=PLATE_T, dir=(0, 0, -1))
    for bx, by in boss_positions():
        plate -= Pos(bx, by, -PLATE_T - 1) * Cylinder(SCREW_CLEAR / 2, PLATE_T + 2, align=C)

    # Posts under the Pi's mounting holes, topped with the Pi's tilt and
    # recessed for the screw heads.
    f = hat_frame()
    below_pi = f * _box(-60, 60, -60, 60, PI_BOTTOM - 60, PI_BOTTOM)
    for hx, hy in _hole_positions(HOLE_DX, HOLE_DY):
        at = (f * Pos(hx, hy, PI_BOTTOM)).position
        post = (Pos(at.X, at.Y, 0) * Cylinder(3.5, at.Z + 2, align=C)) & below_pi
        head = f * Pos(hx, hy, PI_BOTTOM - HEAD_H) * Cylinder(HEAD_D / 2 + 0.3, HEAD_H + 1, align=C)
        plate += post - head

    # Vents under the Pi.
    centre_y = (f * Pos(0, 0, 0)).position.Y
    for i in range(-4, 5):
        plate -= Pos(i * 6.0, centre_y, -PLATE_T - 1) * _rounded(
            Box(2.4, 18, PLATE_T + 2, align=C), 1.15, Axis.Z)

    plate += power_bracket()
    return plate


def power_bracket():
    """Upright bracket the USB-C breakout screws to, standing just inside the back wall."""
    bw, bh, _ = PWR_BOARD
    top = PWR_Z + bh / 2 + 2
    y0, y1 = PWR_BOARD_TOP_Y, back_in_y(top) - 0.3      # clears the leaning wall at its top
    bracket = _box(PWR_X - bw / 2 - 2, PWR_X + bw / 2 + 2, y0, y1, 0, top)
    window = _rounded(Box(PWR_COLLAR[0] + 0.6, 40, PWR_COLLAR[1] + 0.6, align=CC),
                      (PWR_COLLAR[1] + 0.6) / 2 - 0.05, Axis.Y)
    bracket -= Pos(PWR_X, y1, PWR_Z) * window
    for dx, dz in _hole_positions(*PWR_HOLES):
        bracket -= Pos(PWR_X + dx, y0, PWR_Z + dz) * Rot(-90, 0, 0) * Cylinder(PILOT_M25 / 2, 7, align=C)
    return bracket


# ================================================================ boards etc. (for checks + renders)
def internals():
    f = hat_frame()
    gw, gh, gx, gy = GLASS
    holes = [Pos(hx, hy, 0) * Cylinder(1.35, 50, align=CC) for hx, hy in _hole_positions(HOLE_DX, HOLE_DY)]
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
    pi = f * Pos(0, 0, PI_BOTTOM) * pi_pcb
    pi_under = f * Pos(0, 0, PI_BOTTOM - PI_UNDER) * Box(HOLE_DX - 8, HAT_D - 4, PI_UNDER, align=C)
    stack_spacers = [f * Pos(hx, hy, PI_BOTTOM + PI_T) * (
        Cylinder(2.5, BOARD_GAP, align=C) - Cylinder(1.45, BOARD_GAP, align=C))
        for hx, hy in _hole_positions(HOLE_DX, HOLE_DY)]

    pf = _print_frame()
    card = pf * Pos(0, PRINT_H / 2, 0) * Box(PRINT_W, PRINT_H, PRINT_T, align=C)
    image = pf * Pos(0, PRINT_H - 6 - 31, PRINT_T + 0.2) * Box(62, 62, 0.2, align=C)
    tag = pf * Pos(0, TAG_UP, -0.3) * Box(TAG, TAG, 0.3, align=C)

    rf = _reader_frame()
    reader = Box(READER_W, READER_H, READER_PCB, align=C)
    for hx, hy in _hole_positions(*READER_HOLES):
        # Hole as wide as the nub's base, so the press fit doesn't count as a clash.
        reader -= Pos(hx, hy, 0) * Cylinder((READER_HOLE_D + 0.15) / 2, 10, align=CC)
    reader = rf * Pos(0, 0, BOARD_FRONT - READER_PCB) * reader
    socket = rf * Pos(0, -READER_H / 2 + 3, BOARD_FRONT - READER_PCB - SOCKET_H) * Box(
        9, 7, SOCKET_H, align=C)
    # Right-angle USB-C plug, turned so its cable leaves towards the back.
    plug = rf * _box(-6.5, 6.5, -READER_H / 2 - 9, -READER_H / 2 + 2,
                     BOARD_FRONT - READER_PCB - 16, BOARD_FRONT - 0.3)
    antenna = rf * Pos(0, ANTENNA_FROM_USB_END - READER_H / 2, BOARD_FRONT - 0.2) * Box(
        READER_W - 1, ANTENNA_H, 0.2, align=C)

    pwr_board = Pos(PWR_X, PWR_BOARD_TOP_Y - PWR_BOARD[2], PWR_Z) * Box(
        PWR_BOARD[0], PWR_BOARD[2], PWR_BOARD[1], align=(Align.CENTER, Align.MIN, Align.CENTER))
    pwr_shell = Pos(PWR_X, PWR_BOARD_TOP_Y, PWR_Z) * _rounded(
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
        "spacers": stack_spacers,
        "plugs": [*pi_plugs(), plug],
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
    fp_flat = Rot(180, 0, 0) * (hat_frame().inverse() * faceplate())
    fp_flat = Pos(0, 0, -fp_flat.bounding_box().min.Z) * fp_flat
    return {
        "body": body(),
        "faceplate": fp_flat,
        "spacers": spacers(),
        "baseplate": Pos(0, 0, PLATE_T) * baseplate(),
    }


def render_print_layout() -> Path:
    """Each part sitting on a print bed, from above and from bed level."""
    flat = print_orientation()

    def on_bed(part, colour_key):
        bb = part.bounding_box()
        bed = Pos(bb.center().X, bb.center().Y, -0.6) * Box(bb.size.X + 30, bb.size.Y + 30, 0.6, align=C)
        return {"bed": bed, colour_key: part}

    def size(part):
        b = part.bounding_box().size
        return f"{b.X:.0f} × {b.Y:.0f} × {b.Z:.0f} mm"

    scenes = {
        f"Body: upright, open bottom on the bed\n{size(flat['body'])}": on_bed(flat["body"], "body"),
        f"Faceplate: visible face DOWN\n{size(flat['faceplate'])}": on_bed(flat["faceplate"], "cover"),
        f"Base plate: flat side down\n{size(flat['baseplate'])}": on_bed(flat["baseplate"], "port"),
    }
    path = OUT / "print_layout.png"
    titles = list(scenes)
    render({**{t: scenes[t] for t in titles}, **{f"{t}\n(bed level)": scenes[t] for t in titles}},
           path, views=[(30, -50), (35, -50), (35, -50), (4, -50), (6, -50), (6, -50)],
           columns=3, show_dims=False)
    return path


def export_parts() -> dict[str, Path]:
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    for old in PRINT_DIR.glob("spotifactory_*"):
        old.unlink()
    out = {}
    for name, part in print_orientation().items():
        stl = PRINT_DIR / f"spotifactory_{name}.stl"
        export_stl(part, str(stl))
        out[name] = stl
    for name, part in (("body", body()), ("faceplate", faceplate()), ("baseplate", baseplate())):
        export_step(part, str(PRINT_DIR / f"spotifactory_{name}.step"))
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    b, fp, bp = body(), faceplate(), baseplate()
    inside = internals()
    whole = {"body": b, "cover": fp, **{k: v for k, v in inside.items() if k not in ("port", "plugs")}}
    whole["port"] = [bp, *inside["port"]]
    section = cut({"body": b, "cover": fp, **{k: v for k, v in inside.items() if k != "pi"},
                   "pi": [*inside["pi"], bp]}, keep_x_max=-0.5)
    render(
        {
            "Front": {k: v for k, v in whole.items() if k not in ("pi", "reader", "tag", "spacers")},
            "Back (USB-C power + vents)": {"body": b, "print": inside["print"], "port": [bp, inside["port"][0]]},
            "Cut-away side view": section,
        },
        OUT / "easel.png",
        views=[(22, -55), (20, 130), (0, 0)],
    )
    files = export_parts()
    render_print_layout()
    print("wrote", OUT / "easel.png", "and", ", ".join(p.name for p in files.values()))
