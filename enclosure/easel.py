"""Spotifactory enclosure ("easel"): printable parts.

Screen + joystick on a 12° face you look down on; the Instax print stands in a
groove behind it, leaning against a panel that holds the PN532 reader behind
the tag. USB-C power on the back.

Parts and print orientation:
  body       upright, no supports
  faceplate  face down; the Pi + HAT stack screws to it (through spacers) and
             the assembly goes in from below, under a 1.2 mm lip
  spacers    4 tubes between the HAT and the Pi, plus 4 washers (only for
             M2.5 x 16 stack screws)
  keepers    2 blocks under the reader's bottom corners; each takes an
             M2.5 x 14 screw up into a post in the body
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
WALL = 2.4                # 6 lines at 0.4 mm nozzle (4 at 0.6 mm)
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
UNDER_CLEAR = 3.5         # lowest point of the Pi above the base plate (+2 for the reader's cable below it)
BOSS_R, BOSS_H = 4.0, 8.0
INSERT_D, INSERT_DEPTH = 4.0, 5.5   # Adafruit 4255 M3 x 4 mm heat-set insert
SCREW_CLEAR = 3.4                   # M3
CSK_D = 6.4                         # M3 flat-head countersink (90°, so it prints face down)
HEAD_D, HEAD_H = 5.2, 2.0           # M2.5 pan head under the Pi (posts clear it)
POST_R = 3.95                       # widest that clears the Pi; ~1.2 mm wall round the head pocket

# ---------------------------------------------------------------- boards (measured / datasheet)
HAT_W, HAT_D, HAT_T = 65.0, 30.0, 1.6
HOLE_DX, HOLE_DY = 58.0, 23.5       # same pattern on the Pi Zero
# Positions in the slope frame: x across, y up-slope, origin at board centre.
# Stack as on the device: joystick on the left, the Pi's USB ports along the
# back edge where there's room for straight plugs.
WINDOW = (31.0, 16.0, 0.2, -1.5)    # w, h, cx, cy  (active area 29.4 x 14.7)
GLASS = (35.2, 22.6, 0.3, 0.3)
JOY = (-25.3, 0.2)
BUTTONS = [(24.9, 6.7), (24.9, 0.6), (24.9, -5.4)]  # top to bottom: volume up, down, menu
BUTTON_FOOT = (6.2, 3.6)
# The switches, measured from the HAT board's top: a 1.4 mm body, a thin metal
# lip round the plunger up to 1.7, and the plunger itself up to 2.46.
BUTTON_BODY_H = 1.4
BUTTON_LIP = (3.1, 1.7, 1.7)    # x, y, top
BUTTON_PLUNGER = (2.7, 1.3)
GLASS_H = 1.3             # measured: OLED glass top above HAT board top
JOY_HOUSING = 10.0        # joystick's square base
JOY_HOUSING_H = 2.5       # measured
# Joystick stem, heights above the housing's top (measured, the clear knob off):
JOY_STEM_TOP = 6.61       # top of the stem
JOY_SQ = 2.5              # the two square sections the nub grips (a 1.65 neck between)
JOY_COLLAR_TOP = 2.7      # top of the 3.8 mm round section the nub rests on
JOY_COLLAR_D = 3.8
JOY_PRESS = 0.5           # centre click: the stem slides down through the round section (which stays put)
JOY_TILT = 9.0            # degrees: the top moves ~1 mm sideways
# Faceplate over the joystick: a pocket the housing tucks up into, and a round
# hole for the stem to tilt in.
JOY_POCKET_CLEAR = (0.3, 0.2)   # round the housing; over it
JOY_HOLE_D = 5.0
# Printed nub (like Adafruit's 4697): a tapered post with arrows on top and a
# square socket on the stem. It holds only the stem: its flat bottom stays
# NUB_GAP above the round section, which doesn't move when the stick is pressed.
NUB_D = (6.5, 6.0)        # bottom, top
NUB_ABOVE_STEM = 2.0
NUB_ENTRY = 0.5           # flared socket entrance: cancels first-layer squish, eases it on
NUB_GAP = JOY_PRESS + 0.3                 # nub bottom above the round section: the press, and margin
NUB_BOTTOM = JOY_COLLAR_TOP + NUB_GAP     # above the housing's top
NUB_SOCKET = 2.53         # square socket, from fit tests: 2.45 wouldn't go on, 2.53 just right, 2.55 loose
BUTTON_H = 2.46           # measured: plunger top (2.0 was the case, and pressed the buttons)
# Printed caps for K1-K3: the plunger comes up through an opening in the
# flange and pushes on the cap's body, so the flange sits beside the plunger
# (trapped under the faceplate) rather than on top of it; the body comes up
# through the faceplate with a raised icon.
CAP_BODY = (7.0, 3.8)     # x by y, through the faceplate (5.0 x 3.4 felt small)
CAP_FLANGE = (8.4, 4.8, 0.5)
CAP_OPENING = 3.3         # square, round the plunger and its lip, whichever way it's turned
CAP_ABOVE = 1.2           # how far a cap stands above the faceplate
CAP_CLEAR = 0.2           # round its body, in the faceplate's hole
CAP_LIFT = 0.3            # flange to the pocket's ceiling: room for the board to bow when screwed tight (0.15 pressed a button)
CAP_ICONS = ("plus", "minus", "menu")           # in BUTTONS order
ICON_PROUD = 0.48         # raised symbols on the caps and nub: 4 layers at 0.12, solid in an accent colour
STACK = 11.5              # measured: HAT board top to Pi board bottom
BOARD_GAP = 8.5           # measured: HAT underside to Pi top = spacer length
PI_T = STACK - HAT_T - BOARD_GAP    # Pi board thickness, from the measurements
PI_UNDER = 1.6            # parts on the Pi's underside (estimate)
PI_PORTS_X = (-21.5, -8.9)          # PWR, USB micro-USB ports on the back edge (Pi Zero layout)
MICRO_USB_PLUG = (10.5, 7.0, 28.0)  # overmold w, h, length incl. cable bend

READER_W, READER_H = 38.15, 60.0  # measured PN532 board; stands upright, USB end down
READER_HOLES = (33.2, 54.5)       # measured hole spacing
READER_HOLE_D = 3.0               # measured
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
PWR_SHELL = (9.35, 3.94)           # width per Adafruit's model; height from the fit tests
PWR_COLLAR = (12.0, 5.0)            # measured: square-cornered base of the socket
PWR_COLLAR_DEPTH = 1.5              # measured: how far the collar stands off the board
PWR_COLLAR_POCKET = 2.5             # pocket depth for it (1.7 was too shallow in the fit test)
PWR_COLLAR_CLEAR = 0.3              # round the collar in the bracket (0.2 was tight)
PWR_SHELL_CLEAR = 0.1               # round the metal shell in its slot (0.2 was loose)
PWR_RELIEF_DEPTH = 1.5              # recess behind the board for its solder joints
PWR_PAD_R = 2.0                     # the board rests on pads this far round each screw hole
PWR_RISE = 9.30                     # shell top above the board's top surface
PWR_X, PWR_Z = W / 2 - 30, 13.0     # board centre (lower left, seen from behind)
PLUG_OPENING = (13.5, 8.0)          # wall opening: fits most USB-C plug overmolds

# ---------------------------------------------------------------- derived layout
_A = math.radians(SLOPE)
FP_FACE = -LIP_T                          # faceplate top, below the slope surface
HAT_TOP = FP_FACE - FP_T - GLASS_H        # in the slope frame
PI_BOTTOM = HAT_TOP - STACK
# Stack screws: up through the Pi, a spacer and the HAT into a blind pilot in
# the faceplate. M2.5 pan heads come in 12 and 16 mm (14 isn't a standard
# length), so 16 mm screws get a printed washer under the head that takes up
# the extra and puts the tip at the bottom of the pilot.
STACK_SCREW = 16.0
PILOT_DEPTH = GLASS_H + FP_T - 0.8                 # leaves 0.8 mm under the visible face
WASHER_T = STACK_SCREW - (STACK + PILOT_DEPTH)
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
SOCKET_INSET = 0.7                  # socket's end inside the back wall (0.2 left it poking out)
PWR_BOARD_TOP_Y = back_in_y(PWR_Z + PWR_SHELL[1] / 2) - SOCKET_INSET - PWR_RISE


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
    return _print_frame() * Pos(READER_X, centre_up, 0)


# The reader's cable: a regular straight USB-C plug, centred on the socket,
# straight down from the port; the cable bends back below it.
PLUG_W, PLUG_DOWN, PLUG_T = 10.5, 28.0, 6.5   # measured 10.2 wide; 6.5 thick sits flush with the antenna side
# Reader sits off-centre so its plug clears the Pi's USB plug beside it. At 6 mm
# the real plugs had 5 mm between them, so 2.5 leaves ~1.5 mm and keeps the
# 25 mm tag well inside the ~37 mm antenna either way.
READER_X = 2.5
PLUG_CLEAR = 0.8              # round the plug, in its channel
OPENING_CLEAR = 0.6           # round the Pi's plugs, in the wall under the shelf

# Depths behind the print plane (negative z in the print/reader frame).
SKIN_IN = -(GAP + WALL)                    # inside of the panel's front wall
BOARD_FRONT = SKIN_IN - 0.3                # reader's antenna side, just off the panel's inside

# Reader mount (proven with keeper_test.py): caps over the board's top corners,
# and keepers under its bottom corners, each held by an M2.5 x 14 screw driven
# straight up into a post. The reader goes in from below with its plug in,
# slides READER_SLIDE up the wall into the caps, then the keepers go in.
MOUNT_CLEAR = 0.4             # board's back to the lips
EDGE_CLEAR = 0.15             # each side of the board's width (first section print: 0.4 was loose)
CAP_LIP = 1.3                 # overlap onto the board's back: its 1.5 mm edge strips are component-free
CAP_LIP_T = 1.2
CAP_SIDE_T = 1.8
CAP_LEN = 9.4                 # caps reach this far down the board's long edges
TOP_GAP = 0.3                 # stop above the board's top edge
SHELF_WALL_BACK = 5.0         # partition thickness, behind the panel's inside face line
# The board has to drop this far for its top corners to clear the caps' lips
# (whose lowest point is ~1.06 above the caps' bottom, the underside being sloped).
READER_SLIDE = CAP_LEN - 1.06 + 0.5
KPOST_R = 2.75
KPOST_X = READER_W / 2 + EDGE_CLEAR + KPOST_R   # posts touch the board's edges: they guide its bottom
KPOST_Z = -5.0                 # pilot axis behind the board's front face: clears a 7 mm screwdriver shaft
KPOST_LEN = 14.0
KEEPER_PILOT_DEPTH = 8.0      # M2.5 x 14: ~9.25 mm through the keeper, ~4.75 into the post, tip inside the pilot
# Posts (and the caps' bottoms) stick out behind a wall leaning back, so a square
# underside would start printing at its back edge, in mid-air. Instead the
# underside is level for LEDGE mm off the wall, then rises at 45° (in the
# printer); the keeper's top matches, and tightening wedges it toward the wall.
LEDGE = 2.0
KEEPER_T = 3.0
KEEPER_GAP = -0.1             # keeper top 0.1 above the board's bottom edge: it pushes the board up to the stops
KEEPER_LIP_H = 5.0            # keeper lip behind the board's bottom corner (the corners are rounded)
KEEPER_X0 = READER_W / 2 - 8.0      # keepers reach 8 mm in under the board, past its rounded corners
SCREW_CLEAR_M25 = 2.9
KEEPER_DRIVER_R = 3.5         # room for a 7 mm screwdriver shaft


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


def _mount_frame():
    """x across the reader, y up the wall from its bottom edge, z out of the
    wall; the board's front face is z = 0 (it lies in z < 0)."""
    return _reader_frame() * Pos(0, -READER_H / 2, BOARD_FRONT)


def _prism_x(points_yz, x0: float, x1: float):
    """Polygon in (y, z), extruded across x0..x1."""
    with BuildSketch(Plane.YZ.offset(x0)) as sk:
        with BuildLine():
            Polyline(*points_yz, close=True)
        make_face()
    return extrude(sk.sketch, amount=x1 - x0)


SKIN_GAP = SKIN_IN - BOARD_FRONT     # the board sits this far off the panel's inside


def _underside(z: float, y0: float) -> float:
    """Height up the wall of a sloped underside that starts at y0 on the panel's
    inside face, at depth z behind the board's face (the panel is z = SKIN_GAP)."""
    d = max(SKIN_GAP - z, 0.0)
    flat, rise = math.tan(math.radians(LEAN)), math.tan(math.radians(45 + LEAN))
    return y0 + flat * min(d, LEDGE) + rise * max(d - LEDGE, 0.0)


def _under_outline(y0: float, depth: float, front: float):
    """(y, z) points along the sloped underside, from `front` back to -depth."""
    pts = [(_underside(front, y0), front)]
    if front > SKIN_GAP:
        pts.append((y0, SKIN_GAP))
    return pts + [(_underside(SKIN_GAP - LEDGE, y0), SKIN_GAP - LEDGE), (_underside(-depth, y0), -depth)]


def _xs(s: int, a: float, b: float):
    return min(s * a, s * b), max(s * a, s * b)


def reader_mount():
    """Caps over the reader's top corners and the keepers' posts (mount frame)."""
    half, back = READER_W / 2, -(READER_PCB + MOUNT_CLEAR)
    into = 0.6                                   # into the panel's skin (the board sits 0.3 off it)
    side0 = half + EDGE_CLEAR
    out = None
    for s in (-1, 1):
        y0, top = READER_H - CAP_LEN, READER_H + TOP_GAP + 2
        cap = _prism_x([(y0, into), (top, into), (top, back - CAP_LIP_T), (y0, back - CAP_LIP_T)],
                       *_xs(s, side0, side0 + CAP_SIDE_T))
        cap += _prism_x([(y0, back), (top, back), (top, back - CAP_LIP_T), (y0, back - CAP_LIP_T)],
                        *_xs(s, half - CAP_LIP, side0 + 0.01))
        stop = _prism_x([(READER_H + TOP_GAP, into), (top, into), (top, back), (READER_H + TOP_GAP, back)],
                        *_xs(s, half - 4, side0 + 0.01))
        stop -= _prism_x(_under_outline(READER_H + TOP_GAP, 15, 1.0) + [(0, -15), (0, 1.0)],
                         *_xs(s, half - 5, side0 + 1))
        cap += stop
        below = _under_outline(y0, 15, 1.0) + [(y0 - 60, -15), (y0 - 60, 1.0)]
        cap -= _prism_x(below, *_xs(s, half - CAP_LIP - 1, side0 + CAP_SIDE_T + 1))

        p0, depth = -KEEPER_GAP, -(KPOST_Z - KPOST_R)
        post = _prism_x(_under_outline(p0, depth, into) + [(p0 + KPOST_LEN, -depth), (p0 + KPOST_LEN, into)],
                        *_xs(s, side0 - 0.01, KPOST_X + KPOST_R))
        post -= Pos(s * KPOST_X, _underside(KPOST_Z + PILOT_M25 / 2, p0) - 1, KPOST_Z) * Rot(-90, 0, 0) * Cylinder(
            PILOT_M25 / 2, KEEPER_PILOT_DEPTH + 1, align=C)
        out = cap + post if out is None else out + cap + post
    return _mount_frame() * out


def _keeper_local(s: int):
    half, back = READER_W / 2, -(READER_PCB + MOUNT_CLEAR)
    p0, depth, front = -KEEPER_GAP, -(KPOST_Z - KPOST_R), 0.1     # 0.2 mm off the skin
    bottom = p0 - KEEPER_T                       # flat: the screw head bears here
    side_x = half + EDGE_CLEAR                   # where the post starts
    # Under the board's corner: flat top just below the board, and a lip behind it.
    k = _prism_x([(bottom, front), (p0, front), (p0, -depth), (bottom, -depth)], *_xs(s, KEEPER_X0, side_x))
    k += _prism_x([(p0 - 0.01, back), (p0 + KEEPER_LIP_H, back), (p0 + KEEPER_LIP_H, back - CAP_LIP_T),
                   (p0 - 0.01, back - CAP_LIP_T)], *_xs(s, half - CAP_LIP, half))
    # Under the post: top follows the post's sloped underside.
    k += _prism_x(_under_outline(p0, depth, front) + [(bottom, -depth), (bottom, front)],
                  *_xs(s, side_x - 0.01, KPOST_X + KPOST_R))
    k -= Pos(s * KPOST_X, bottom - 1, KPOST_Z) * Rot(-90, 0, 0) * Cylinder(SCREW_CLEAR_M25 / 2, 30, align=C)
    return k


def reader_plug():
    """The reader's USB-C plug, in place."""
    zc = BOARD_FRONT - READER_PCB - SOCKET_H / 2          # socket's centre line
    return _reader_frame() * _box(-PLUG_W / 2, PLUG_W / 2, -READER_H / 2 - PLUG_DOWN, -READER_H / 2,
                                  zc - PLUG_T / 2, zc + PLUG_T / 2)


def shelf_geometry():
    """(shelf underside z, panel's inside face y there, wall front y)."""
    top = ZS - WALL
    fp_back = (hat_frame() * Pos(0, FP_Y1 + FP_CLEAR, FP_FACE - FP_T)).position.Y + 0.3
    return top, inner_front_y(top), fp_back


def plug_relief():
    """Room in the back of the shelf's chamfer for the reader's plug as the
    reader slides into the caps. Its roof rises at 45° to the shelf's
    underside, so it prints without support; the plug runs along the panel's
    15° line, which stays behind that roof."""
    mf = _mount_frame()
    front = -READER_PCB - SOCKET_H / 2 + PLUG_T / 2 + PLUG_CLEAR      # plug's front, mount frame
    lowest = (mf * Pos(0, -PLUG_DOWN - READER_SLIDE, front)).position
    top, yb, _ = shelf_geometry()
    y0 = lowest.Y - 0.5
    yr = yb - 1.0                 # roof starts just in front of the plug's line, then drops at 45°
    x = mf.position.X
    half = PLUG_W / 2 + PLUG_CLEAR
    return _prism_x([(yb + SHELF_WALL_BACK + 1, top), (yr, top), (y0, top - (yr - y0)), (y0, -1),
                     (yb + SHELF_WALL_BACK + 1, -1)], x - half, x + half)


def partition_gaps(slab, margin: float = OPENING_CLEAR, min_wall: float = 6.0):
    """x-ranges where the partition has to be open: where the Pi's plugs or the
    reader's plug cross it. Gaps closer than min_wall are merged (a thin post of
    wall between them doesn't print). With straight micro-USB plugs at the Pi
    this is one wide opening: in its middle the chamfer is gone and the shelf's
    underside is only a ~3 mm ledge off the material in front, which prints."""
    spans = []
    for t in (*pi_plugs(), plug_relief()):
        hit = t & slab
        if hit.volume > 0.01:
            bb = hit.bounding_box()
            spans.append([bb.min.X - margin, bb.max.X + margin])
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + min_wall:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(s) for s in merged]


def _halfspace(point, normal):
    """Everything on the `normal` side of the plane through `point`."""
    return Plane(origin=point, z_dir=normal) * Box(1000, 1000, 1000, align=C)


def _gap_chamfer(chamfer, a: float, b: float, top: float, fp_back: float):
    """The chamfer over the gap a..b, also sloped at 45° up from each side of
    the gap, so it grows out from the partition on both sides instead of
    spanning the gap. Leaves a short flat bridge in the middle of wide gaps."""
    gap = chamfer & _box(a, b, -500, 500, -500, 500)
    # The chamfer's underside is z = top - (y - fp_back); keep z >= that plus the
    # distance to the nearer edge of the gap (above either edge's 45° slope).
    return gap & (_halfspace((a, fp_back, top), (-1, 1, 1)) + _halfspace((b, fp_back, top), (1, 1, 1)))


def supported_bridges():
    """Boxes (x0, x1, y0, y1, z0, z1) printed on painted supports (or bridged):
    over the wide opening the shelf is a strip with the screen's pocket in
    front and the panel behind, and nothing under it once the chamfer's 45°
    slopes from the opening's sides have run out. check.py leaves these out."""
    top, yb, fp_back = shelf_geometry()
    slab = _yz_prism([(yb, 0), (yb + SHELF_WALL_BACK, 0), (yb + SHELF_WALL_BACK, top), (yb, top)])
    reach = yb - fp_back                     # how far the 45° slopes close in from each side
    return [(a + reach - 1, b - reach + 1, fp_back - 1, yb + 1, top - 1, top + 1.5)
            for a, b in partition_gaps(slab) if b - a > 2 * reach]


def under_shelf(cavity):
    """The partition (shelf's back edge down to the bed) and the 45° chamfer in
    front of it. The partition has gaps for the Pi's power plug and the
    reader's plug, with the chamfer sloped up from both sides over each, and
    round holes for the keeper screwdrivers."""
    top, yb, fp_back = shelf_geometry()
    slab = _yz_prism([(yb, 0), (yb + SHELF_WALL_BACK, 0), (yb + SHELF_WALL_BACK, top), (yb, top)]) & cavity
    gaps = partition_gaps(slab)
    for a, b in gaps:
        slab -= _box(a, b, -50, 400, -1, top + 1)
    for s in (-1, 1):
        slab -= keeper_screw_path(s, 80, KEEPER_DRIVER_R + 0.1)
    chamfer = _yz_prism([(fp_back, top), (yb, top), (yb, top - (yb - fp_back))]) & cavity
    kept = chamfer
    for a, b in gaps:
        kept = kept - _box(a, b, -500, 500, -500, 500) + _gap_chamfer(chamfer, a, b, top, fp_back)
    return slab + kept - plug_relief()


def keeper(s: int):
    """Keeper under one of the reader's bottom corners, in place."""
    return _mount_frame() * _keeper_local(s)


def keepers_flat():
    """Both keepers lying on their screw-head faces (holes vertical), side by side."""
    out = None
    for i, s in enumerate((-1, 1)):
        k = Rot(90, 0, 0) * _keeper_local(s)          # mount y (the screw axis) becomes z
        bb = k.bounding_box()
        k = Pos(-bb.center().X + (i - 0.5) * 20, -bb.center().Y, -bb.min.Z) * k
        out = k if out is None else out + k
    return out


def keeper_screw_path(s: int, length: float = 60.0, r: float = None):
    """A 7 mm screwdriver shaft from under keeper s straight down the screw axis."""
    r = KEEPER_DRIVER_R if r is None else r
    y = -KEEPER_GAP - KEEPER_T - 1.6
    return _mount_frame() * Pos(s * KPOST_X, y, KPOST_Z) * Rot(90, 0, 0) * Cylinder(
        r, length, align=C)


def pi_plugs():
    """Straight micro-USB plugs in the Pi's PWR and USB ports (for clearance)."""
    w, h, length = MICRO_USB_PLUG
    port_z = PI_BOTTOM + PI_T + 1.3
    return [hat_frame() * _box(px - w / 2, px + w / 2, HAT_D / 2, HAT_D / 2 + length,
                               port_z - h / 2, port_z + h / 2) for px in PI_PORTS_X]


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

    # Under the shelf: the partition and chamfer, with openings for the
    # reader's plug, the keeper screwdrivers and the Pi's power plug.
    shell += under_shelf(cavity)

    # Peaked (45°) roof inside the panel top, so it prints without supports.
    zc = TOP_Z - WALL
    mid = (inner_front_y(zc) + back_in_y(zc)) / 2
    shell += _yz_prism([(mid - 40, zc - 40), (mid, zc), (mid + 40, zc - 40),
                        (mid + 40, zc + 10), (mid - 40, zc + 10)]) & cavity

    # Reader caps and keeper posts; lip at the front of the print's groove.
    shell += reader_mount() & solid
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
    # Joystick: its housing tucks up into a pocket underneath; just a round
    # hole for the stem shows on the face.
    side, over = JOY_POCKET_CLEAR
    pw = JOY_HOUSING + 2 * side
    plate -= Pos(*JOY, FP_FACE - FP_T - 1) * _rounded(
        Box(pw, pw, HAT_TOP + JOY_HOUSING_H + over - (FP_FACE - FP_T) + 1, align=C), 1.0, Axis.Z)
    plate -= Pos(*JOY, FP_FACE - FP_T - 1) * Cylinder(JOY_HOLE_D / 2, FP_T + 2, align=C)
    # Buttons: a pocket underneath for the caps' flanges (and the switches),
    # and a hole for each cap's body.
    ys = [by for _, by in BUTTONS]
    fw, fh, ft = CAP_FLANGE
    pocket_top = HAT_TOP + BUTTON_H + CAP_LIFT        # the flange's top is level with the plunger
    plate -= Pos(BUTTONS[0][0], (max(ys) + min(ys)) / 2, FP_FACE - FP_T - 1) * _rounded(Box(
        max(fw, BUTTON_FOOT[0]) + 0.8, max(ys) - min(ys) + max(fh, BUTTON_FOOT[1]) + 0.8,
        pocket_top - (FP_FACE - FP_T) + 1, align=C), 1.0, Axis.Z)
    cw, ch = CAP_BODY
    for bx, by in BUTTONS:
        plate -= Pos(bx, by, FP_FACE - FP_T - 1) * _rounded(
            Box(cw + 2 * CAP_CLEAR, ch + 2 * CAP_CLEAR, FP_T + 2, align=C), 1.0, Axis.Z)
    blind = PILOT_DEPTH
    for hx, hy in _hole_positions(HOLE_DX, HOLE_DY):
        plate += Pos(hx, hy, HAT_TOP) * Cylinder(2.75, GLASS_H, align=C)
        plate -= Pos(hx, hy, HAT_TOP) * Cylinder(PILOT_M25 / 2, blind, align=C)
    return hat_frame() * plate


def _cap_icon(kind: str, z: float):
    """Raised icon on a button cap's top, ICON_PROUD high."""
    def poly(*pts):
        with BuildSketch(Plane.XY.offset(z - 0.05)) as sk:
            with BuildLine():
                Polyline(*pts, close=True)
            make_face()
        return extrude(sk.sketch, amount=ICON_PROUD + 0.05)
    bar = lambda x0, x1, y0, y1: Pos(0, 0, z - 0.05) * _box(x0, x1, y0, y1, 0, ICON_PROUD + 0.05)
    if kind == "plus":
        return bar(-1.0, 1.0, -0.3, 0.3) + bar(-0.3, 0.3, -1.0, 1.0)
    if kind == "minus":
        return bar(-1.0, 1.0, -0.3, 0.3)
    if kind == "menu":            # three bars, like the menu icon on screen
        return sum((bar(-1.2, 1.2, y - 0.225, y + 0.225) for y in (-0.9, 0.9)),
                   bar(-1.2, 1.2, -0.225, 0.225))
    # play/pause: a triangle pointing right, then two bars
    return poly((-1.6, -0.8), (-0.3, 0), (-1.6, 0.8)) + bar(0.2, 0.6, -0.8, 0.8) + bar(1.0, 1.4, -0.8, 0.8)


def switch():
    """A K1-K3 switch on the board (z = 0 at the board's top): body, lip, plunger."""
    lx, ly, ltop = BUTTON_LIP
    px, py = BUTTON_PLUNGER
    return (Box(*BUTTON_FOOT, BUTTON_BODY_H, align=C)
            + Box(lx, ly, ltop, align=C)
            + Box(px, py, BUTTON_H, align=C))


def _button_cap_local(kind: str):
    """A button cap, upright, z = 0 at the plunger's top (where it rests). The
    flange hangs below that, the plunger up through its opening."""
    fw, fh, ft = CAP_FLANGE
    cw, ch = CAP_BODY
    top = GLASS_H + FP_T + CAP_ABOVE - BUTTON_H
    cap = Pos(0, 0, -ft) * _rounded(Box(fw, fh, ft, align=C), 1.0, Axis.Z)
    cap -= Pos(0, 0, -ft - 0.01) * _rounded(Box(CAP_OPENING, CAP_OPENING, ft + 0.01, align=C), 0.5, Axis.Z)
    body = _rounded(Box(cw, ch, top, align=C), 0.9, Axis.Z)
    body = fillet(body.edges().group_by(Axis.Z)[-1], radius=0.4)
    return cap + body + _cap_icon(kind, top)


def button_caps():
    """The three caps, in place on K1-K3."""
    f = hat_frame()
    return [f * Pos(bx, by, HAT_TOP + BUTTON_H) * _button_cap_local(k)
            for (bx, by), k in zip(BUTTONS, CAP_ICONS)]


def button_caps_flat():
    """The three caps standing on their flanges, side by side, top to bottom left to right."""
    out = None
    for i, k in enumerate(CAP_ICONS):
        c = Pos((i - 1) * 9.0, 0, CAP_FLANGE[2]) * _button_cap_local(k)
        out = c if out is None else out + c
    return out


def joy_collar():
    """The round section round the stem's foot (z = 0 at the housing's top):
    it tilts with the stick but doesn't go down when it's pressed."""
    return Cylinder(JOY_COLLAR_D / 2, JOY_COLLAR_TOP, align=C)


def joy_stem():
    """The joystick's stem above its housing, with its round section."""
    stem = joy_collar()
    stem += Pos(0, 0, JOY_COLLAR_TOP) * Box(JOY_SQ, JOY_SQ, JOY_STEM_TOP - JOY_COLLAR_TOP, align=C)
    return stem


_NUB_LETTERS = {          # 4 x 5 blocks, for telling fit-test nubs apart
    "A": (".##.", "#..#", "####", "#..#", "#..#"),
    "B": ("###.", "#..#", "###.", "#..#", "###."),
    "C": (".###", "#...", "#...", "#...", ".###"),
    "D": ("###.", "#..#", "#..#", "#..#", "###."),
}


def _nub_letter(letter: str, top: float, cell: float = 0.6):
    """A raised blocky letter centred on the nub's top, 0.3 mm proud."""
    rows = _NUB_LETTERS[letter]
    w, h = len(rows[0]) * cell, len(rows) * cell
    out = None
    for r, line in enumerate(rows):
        for c, px in enumerate(line):
            if px == "#":
                x, y = -w / 2 + (c + 0.5) * cell, h / 2 - (r + 0.5) * cell
                b = Pos(x, y, top - 0.05) * Box(cell + 0.02, cell + 0.02, 0.35, align=C)
                out = b if out is None else out + b
    return out


def _nub_local(socket: float = NUB_SOCKET, label: str | None = None):
    """Printed joystick nub, upright, z = 0 at the housing's top. A `label`
    (fit tests) replaces the arrows on top with that letter."""
    z0 = NUB_BOTTOM
    h = JOY_STEM_TOP + NUB_ABOVE_STEM - z0
    nub = Pos(0, 0, z0) * Cone(NUB_D[0] / 2, NUB_D[1] / 2, h, align=C)
    nub = fillet(nub.edges().group_by(Axis.Z)[-1], radius=0.6)
    # Socket: the square sections, with a flared entrance at the bottom.
    nub -= Pos(0, 0, z0 - 0.01) * Box(socket, socket, JOY_STEM_TOP - z0 + 0.2, align=C)
    corner = socket / 2 * 2 ** 0.5
    nub -= Pos(0, 0, z0 - 0.01) * Cone(corner + 0.15, socket / 2, NUB_ENTRY + 0.01, align=C)
    # Four raised arrows on top, pointing the way the stick goes.
    top = z0 + h
    if label:
        return nub + _nub_letter(label, top)
    for a in (0, 90, 180, 270):
        with BuildSketch(Plane.XY.offset(top - 0.05)) as sk:
            with BuildLine():
                Polyline((0.9, -0.6), (2.05, 0), (0.9, 0.6), close=True)
            make_face()
        nub += Rot(0, 0, a) * extrude(sk.sketch, amount=ICON_PROUD + 0.05)
    return nub


def nub(socket: float = NUB_SOCKET):
    """The nub on the stem, in place."""
    return hat_frame() * Pos(*JOY, HAT_TOP + JOY_HOUSING_H) * _nub_local(socket)


def nub_tilted(sign: int, axis: str = "x"):
    """The nub pushed fully over (about the housing's top, centre), for the check."""
    r = Rot(JOY_TILT * sign, 0, 0) if axis == "x" else Rot(0, JOY_TILT * sign, 0)
    return hat_frame() * Pos(*JOY, HAT_TOP + JOY_HOUSING_H) * r * _nub_local()


def spacers():
    """Four tubes for between the HAT and the Pi, and (second row) four washers
    for under the screw heads (M2.5 screws pass through both)."""
    out = None
    for row, length in ((0, BOARD_GAP), (1, WASHER_T)):
        for i in range(4):
            tube = Pos(i * 8.0, row * 8.0, 0) * (Cylinder(2.5, length, align=C) - Cylinder(1.45, length, align=C))
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
        # 90° cone: its 45° sides print without support, unlike a flat counterbore.
        csk = (CSK_D - SCREW_CLEAR) / 2
        plate -= Pos(bx, by, -PLATE_T - 0.01) * Cone(CSK_D / 2 + 0.01, SCREW_CLEAR / 2, csk + 0.01, align=C)

    # Posts under the Pi's mounting holes, leaning with the Pi so the
    # screw-head pocket is coaxial and the wall round it stays even.
    f = hat_frame()
    above_plate = _box(-100, 100, -100, 200, -PLATE_T, 100)
    for hx, hy in _hole_positions(HOLE_DX, HOLE_DY):
        post = f * Pos(hx, hy, PI_BOTTOM) * Cylinder(
            POST_R, 40, align=(Align.CENTER, Align.CENTER, Align.MAX))
        sink = HEAD_H + WASHER_T                     # washer and screw head
        head = f * Pos(hx, hy, PI_BOTTOM - sink) * Cylinder(HEAD_D / 2 + 0.15, sink + 1, align=C)
        plate += (post & above_plate) - head

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
    # Stepped window: a square-cornered pocket the socket's collar seats in,
    # then a snug slot that holds the metal shell along its length.
    cw, ch = PWR_COLLAR[0] + 2 * PWR_COLLAR_CLEAR, PWR_COLLAR[1] + 2 * PWR_COLLAR_CLEAR
    bracket -= _box(PWR_X - cw / 2, PWR_X + cw / 2, y0 - 1, y0 + PWR_COLLAR_POCKET,
                    PWR_Z - ch / 2, PWR_Z + ch / 2)
    # Relief behind the middle of the board, so solder joints on its back don't
    # hold it off the bracket: it rests on four pads round its screw holes.
    rx = PWR_HOLES[0] / 2 - PWR_PAD_R
    bracket -= _box(PWR_X - rx, PWR_X + rx, y0 - 1, y0 + PWR_RELIEF_DEPTH,
                    PWR_Z - bh / 2 - 1, PWR_Z + bh / 2 + 1)
    sw, sh = PWR_SHELL[0] + 2 * PWR_SHELL_CLEAR, PWR_SHELL[1] + 2 * PWR_SHELL_CLEAR
    slot = _rounded(Box(sw, 40, sh, align=CC), sh / 2 - 0.05, Axis.Y)
    bracket -= Pos(PWR_X, y1, PWR_Z) * slot
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
    knob = f * Pos(*JOY, HAT_TOP + JOY_HOUSING_H) * joy_stem()
    buttons = [f * Pos(bx, by, HAT_TOP) * switch() for bx, by in BUTTONS]
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
        reader -= Pos(hx, hy, 0) * Cylinder(READER_HOLE_D / 2, 10, align=CC)
    reader = rf * Pos(0, 0, BOARD_FRONT - READER_PCB) * reader
    socket = rf * Pos(0, -READER_H / 2 + 3, BOARD_FRONT - READER_PCB - SOCKET_H) * Box(
        9, 7, SOCKET_H, align=C)
    plug = reader_plug()
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
        "keepers": keepers_flat(),
        "nub": Pos(0, 0, -NUB_BOTTOM) * _nub_local(),
        "buttoncaps": button_caps_flat(),
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
