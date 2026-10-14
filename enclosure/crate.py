"""Crate for the Instax prints: flip through the albums like a record bin.

The prints stand on their 72 mm edge with the art facing the front. The side
walls slope down toward the front so the covers show as you flip. Saw-tooth
ridges on the floor catch the prints' bottom edges, so they fan out when you
tip them forward instead of sliding flat. The walls lean in like the easel's.

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

# ---------------------------------------------------------------- size
CAPACITY = 40                 # prints
SIDE_CLEAR = 1.5              # each side of a print, so they flip without rubbing
IW = PRINT_W + 2 * SIDE_CLEAR # inner width at the rim
IL = 100.0                    # inner length at the rim: ~40 mm of prints + room to fan them
WALL = 2.4                    # 4 lines at 0.6 mm nozzle
FLOOR = 2.4
H_BACK, H_FRONT = 60.0, 38.0  # rim height at the back and front (prints are 86 tall)
TAPER = 4.0                   # walls lean in, degrees
FILLET = 6.0                  # outside corner radius (matches the easel)
RIM_FILLET = 1.0
BOTTOM_CHAMFER = 1.0

# ---------------------------------------------------------------- floor ridges
PITCH = 5.0                   # a valley every 5 mm
RIDGE_H = 1.5                 # vertical face toward the front catches a print's bottom edge
RIDGE_MARGIN = 3.0            # keep the ridges off the front and back walls


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


def ridges():
    """Saw-tooth strip across the floor: vertical face toward the front, ramp down behind."""
    y_front = -IL / 2 - _grow(FLOOR) + RIDGE_MARGIN
    y_back = IL / 2 + _grow(FLOOR) - RIDGE_MARGIN
    # One outline, sunk 0.5 mm into the floor so it fuses: up each vertical face,
    # down each ramp to the next.
    pts, y = [(y_front, FLOOR - 0.5), (y_front, FLOOR)], y_front + PITCH
    while y + PITCH <= y_back:
        pts += [(y, FLOOR), (y, FLOOR + RIDGE_H), (y + PITCH, FLOOR)]
        y += PITCH
    pts += [(y_back, FLOOR), (y_back, FLOOR - 0.5)]
    pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    return _yz_prism(pts, IW / 2 + _grow(FLOOR) + 1)


def crate():
    ow, ol = IW + 2 * WALL, IL + 2 * WALL
    solid = _tapered(ow, ol, FILLET, 0, H_BACK + 1)
    solid = chamfer([e for e in solid.edges() if e.center().Z < 0.01], length=BOTTOM_CHAMFER)
    cavity = _tapered(IW, IL, FILLET - WALL, FLOOR, H_BACK + 5)
    floor_strip = ridges() & cavity
    solid = solid - cavity + floor_strip
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


def prints(n: int = CAPACITY, lean: float = 14.0):
    """n prints packed at the back, leaning back (for the render and the fit check)."""
    a = math.radians(lean)
    out, y = [], IL / 2 + _grow(FLOOR) - RIDGE_MARGIN - PRINT_H * math.sin(a) - 1.0
    for i in range(n):
        card = Pos(0, y - i * PRINT_T / math.cos(a), FLOOR + RIDGE_H + 0.3) * Rot(-lean, 0, 0) * Box(
            PRINT_W, PRINT_T, PRINT_H, align=(Align.CENTER, Align.MIN, Align.MIN))
        out.append(card)
    return out


def fanned():
    """The front 8 prints tipped forward, as when flipping."""
    cards = prints()
    front = cards[-8:]
    a = math.radians(14)
    tipped = []
    for i, c in enumerate(front):
        ang = -14 + 26 + i * 3     # leaning forward
        y = c.bounding_box().min.Y
        tipped.append(Pos(0, y - 2, FLOOR + RIDGE_H) * Rot(ang, 0, 0) * Box(
            PRINT_W, PRINT_T, PRINT_H, align=(Align.CENTER, Align.MAX, Align.MIN)))
    return cards[:-8], tipped


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    box = crate()
    assert box.is_valid, "crate is not a valid solid"
    bb = box.bounding_box()
    full = prints()
    clash = sum((box & c).volume for c in full)
    print(f"crate {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; "
          f"{CAPACITY} prints packed at the back overlap the walls by {clash:.2f} mm³; "
          f"free length in front: {full[-1].bounding_box().min.Y - (-IL / 2):.0f} mm")
    standing, tipped = fanned()
    render(
        {
            "Crate, 40 prints": {"body": box, "print": full},
            "Flipping": {"body": box, "print": standing + tipped},
            "Side": {"body": box, "print": full},
        },
        OUT / "crate.png",
        views=[(28, -60), (35, -110), (0, 0)],
    )
    export_stl(box, str(PRINT_DIR / "crate.stl"))
    export_step(box, str(PRINT_DIR / "crate.step"))
    print("wrote", OUT / "crate.png", "and", PRINT_DIR / "crate.stl")
