"""Crate for the Instax prints: flip through the albums like a record bin.

The prints stand on their 72 mm edge with the art facing the front, one per
slot between low fins that lean back a little. The fins hold the bottoms; above
them the prints are free to bend forward so you can look through them. The
side walls slope down toward the front so the covers show, and lean in like
the easel's.

Print: open side up, no supports.

Run:  enclosure/.venv/bin/python enclosure/crate.py
Writes out/crate.png and out/print/crate.stl (+ .step).
"""
from __future__ import annotations

import math

from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildSketch,
    Plane,
    Polyline,
    Pos,
    RectangleRounded,
    Rot,
    chamfer,
    export_step,
    export_stl,
    extrude,
    fillet,
    make_face,
)

from concepts import OUT, PRINT_H, PRINT_T, PRINT_W, render

C = (Align.CENTER, Align.CENTER, Align.MIN)
PRINT_DIR = OUT / "print"

# ---------------------------------------------------------------- slots
CAPACITY = 40                 # prints, one per slot
SLOT_W = 1.8                  # a ~1 mm print slides in and can rock
FIN_T = 1.2                   # 2 lines at 0.6 mm nozzle
FIN_H = 14.0                  # below the image: an Instax Square's bottom border is ~18 mm
FIN_LEAN = 3.0                # degrees back: prints settle back but still drop straight in
FRONT_ROOM = 10.0             # open floor in front of the first slot, for bending prints forward
PITCH = SLOT_W + FIN_T

# ---------------------------------------------------------------- box
SIDE_CLEAR = 1.5              # each side of a print, so they slide without rubbing
IW = PRINT_W + 2 * SIDE_CLEAR # inner width at the rim
WALL = 2.4                    # 4 lines at 0.6 mm nozzle
FLOOR = 2.4
H_BACK, H_FRONT = 60.0, 38.0  # rim height at the back and front (prints are 86 tall)
TAPER = 4.0                   # walls lean in, degrees
FILLET = 6.0                  # outside corner radius (matches the easel)
RIM_FILLET = 1.0
BOTTOM_CHAMFER = 1.0
_L = math.radians(FIN_LEAN)
# Behind the last slot: the prints lean back while the back wall leans in.
BACK_GAP = 1.0 + H_BACK * (math.tan(_L) + math.tan(math.radians(TAPER)))
FLOOR_LEN = (FRONT_ROOM + (CAPACITY + 1) * FIN_T + CAPACITY * SLOT_W + BACK_GAP
             + FIN_H * math.sin(_L))
IL = FLOOR_LEN - 2 * (H_BACK - FLOOR) * math.tan(math.radians(TAPER))   # inner length at the rim


def _grow(z: float) -> float:
    """How far a leaning wall sits outside its rim position at height z."""
    return (H_BACK - z) * math.tan(math.radians(TAPER))


def _yz_prism(points, half_width=200.0):
    with BuildSketch(Plane.YZ) as sk:
        with BuildLine():
            Polyline(*points, close=True)
        make_face()
    return extrude(sk.sketch, amount=half_width, both=True)


def _tapered(w: float, l: float, r: float, z0: float, z1: float):
    """Rounded rectangle that is w x l at the rim height, walls leaning in, from z0 to z1."""
    g = _grow(z0)
    with BuildSketch(Plane.XY.offset(z0)) as sk:
        RectangleRounded(w + 2 * g, l + 2 * g, r + g)
    return extrude(sk.sketch, amount=z1 - z0, taper=TAPER)


def _rim_cut():
    """Everything above the sloping rim line (low at the front, -y)."""
    y0, y1 = -IL / 2 - 30, IL / 2 + 30
    slope = (H_BACK - H_FRONT) / IL
    z = lambda y: H_FRONT + (y + IL / 2) * slope
    return _yz_prism([(y0, z(y0)), (y1, z(y1)), (y1, 200), (y0, 200)])


def _lean_frame(y0: float, floor: float = FLOOR):
    """(u, v) -> (y, z) for a fin whose front-bottom edge is at y0: u through
    the fin toward the back, v up it."""
    return lambda u, v: (y0 + u * math.cos(_L) + v * math.sin(_L), floor + v * math.cos(_L) - u * math.sin(_L))


def _fin_frame(i: int):
    return _lean_frame(-FLOOR_LEN / 2 + FRONT_ROOM + i * PITCH)


def fin(y0: float, height: float, half_width: float, floor: float = FLOOR):
    """One fin with a round top, sunk 1 mm into the floor. Shared with crate_test.py."""
    to, r = _lean_frame(y0, floor), FIN_T / 2
    pts = [to(0, -1), to(FIN_T, -1), to(FIN_T, height - r)]
    pts += [to(r + r * math.cos(t), height - r + r * math.sin(t))
            for t in (math.pi * k / 8 for k in range(1, 8))]
    pts.append(to(0, height - r))
    return _yz_prism(pts, half_width)


def fins(half_width: float):
    """CAPACITY + 1 fins."""
    out = None
    for i in range(CAPACITY + 1):
        f = fin(-FLOOR_LEN / 2 + FRONT_ROOM + i * PITCH, FIN_H, half_width)
        out = f if out is None else out + f
    return out


def crate():
    ow, ol = IW + 2 * WALL, IL + 2 * WALL
    solid = _tapered(ow, ol, FILLET, 0, H_BACK + 1)
    solid = chamfer([e for e in solid.edges() if e.center().Z < 0.01], length=BOTTOM_CHAMFER)
    cavity = _tapered(IW, IL, FILLET - WALL, FLOOR, H_BACK + 5)
    outside = solid
    solid = solid - cavity + (fins(IW / 2 + 10) & outside)   # fins run into the side walls
    solid -= _rim_cut()
    # Soften the rim: the edges left by the sloping cut.
    a = math.atan2(H_BACK - H_FRONT, IL)
    rim = [e for e in solid.edges() if e.center().Z > H_FRONT - 1 and
           abs(e.center().Z - (H_FRONT + (e.center().Y + IL / 2) * math.tan(a))) < 0.6]
    try:
        solid = fillet(rim, radius=RIM_FILLET)
    except Exception as exc:              # keep a sharp rim rather than fail the build
        print(f"[crate] rim fillet skipped: {exc}")
    return solid


def _card(i: int, lift: float = 0.2):
    """Print standing in slot i, leaning back with the fins."""
    y, _ = _fin_frame(i)(FIN_T + (SLOT_W - PRINT_T) / 2, 0)
    return Pos(0, y, FLOOR + lift) * Rot(-FIN_LEAN, 0, 0) * Box(
        PRINT_W, PRINT_T, PRINT_H, align=(Align.CENTER, Align.MIN, Align.MIN))


def prints():
    return [_card(i) for i in range(CAPACITY)]


def flipping(n: int = 6):
    """The front n prints bent forward over the fin tops, as when looking through."""
    standing, bent = [], []
    for i in range(CAPACITY):
        if i >= n:
            standing.append(_card(i))
            continue
        y, z = _fin_frame(i)(FIN_T + (SLOT_W - PRINT_T) / 2, FIN_H)
        lower = Pos(*_card(i).location.position) * Rot(-FIN_LEAN, 0, 0) * Box(
            PRINT_W, PRINT_T, FIN_H, align=(Align.CENTER, Align.MIN, Align.MIN))
        upper = Pos(0, y, z) * Rot(30 + (n - i) * 4, 0, 0) * Box(
            PRINT_W, PRINT_T, PRINT_H - FIN_H, align=(Align.CENTER, Align.MIN, Align.MIN))
        bent += [lower, upper]
    return standing, bent


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    box = crate()
    assert box.is_valid, "crate is not a valid solid"
    bb = box.bounding_box()
    full = prints()
    clash = sum((box & c).volume for c in full)
    print(f"crate {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; "
          f"{CAPACITY} prints in their slots overlap the crate by {clash:.2f} mm³")
    standing, tipped = flipping()
    render(
        {
            "Crate, 40 prints in slots": {"body": box, "print": full},
            "Looking through": {"body": box, "print": standing + tipped},
            "Side": {"body": box, "print": full},
        },
        OUT / "crate.png",
        views=[(28, -60), (35, -110), (0, 0)],
    )
    export_stl(box, str(PRINT_DIR / "crate.stl"))
    export_step(box, str(PRINT_DIR / "crate.step"))
    print("wrote", OUT / "crate.png", "and", PRINT_DIR / "crate.stl")
