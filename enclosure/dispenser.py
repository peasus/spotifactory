"""Dispenser for the roll of NFC tag stickers.

The roll sits loose in a curved cradle and turns as you pull. The backing paper
feeds up through a slit near the front of the lid; tear off a sticker, peel
it, and stick it on the print.
Rounded corners, inward-leaning walls and a bottom chamfer match the easel and
the crate.

Print: base open side up; lid top down. No supports.

Run:  enclosure/.venv/bin/python enclosure/dispenser.py
Writes out/dispenser.png and out/print/dispenser_{base,lid}.stl (+ .step).
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
    Pos,
    Polyline,
    RectangleRounded,
    Rot,
    chamfer,
    export_step,
    export_stl,
    extrude,
    fillet,
    make_face,
)

from concepts import OUT, render

C = (Align.CENTER, Align.CENTER, Align.MIN)
PRINT_DIR = OUT / "print"

# ---------------------------------------------------------------- the roll (x = its axis)
PAPER_W = 34.6                # measured
ROLL_OD = 40.0                # largest roll it takes (a loosely re-rolled one measured ~33)
STICKER = 25.0                # 1" square tags
STICKER_T = 0.18              # measured: backing + sticker together

# ---------------------------------------------------------------- box
SIDE_CLEAR = 1.5              # each side of the roll
ROLL_CLEAR = 3.0              # all round a full roll
WALL = 2.4                    # 4 lines at 0.6 mm nozzle
FLOOR = 2.4
TAPER = 4.0                   # walls lean in, degrees
FILLET = 6.0                  # outside corner radius (matches the easel)
BOTTOM_CHAMFER = 1.0
IW = PAPER_W + 2 * SIDE_CLEAR                 # inside, across the roll, at the rim
IL = ROLL_OD + 2 * ROLL_CLEAR                 # inside, front to back, at the rim
LIP_DEPTH = 4.0               # skirt under the lid that locates it in the base
H = FLOOR + ROLL_OD + 2 * ROLL_CLEAR + LIP_DEPTH   # base height: the lid's skirt hangs inside

# ---------------------------------------------------------------- lid
LID_T = 3.0
LID_FILLET = 2.0              # top edges
LIP_WALL = 1.8
LIP_CLEAR = 0.25
# Snap: a bead on each long side of the skirt squeezes past the rim, then sits
# in the extra room below it (the walls lean in, so the inside widens downward).
DETENT = 0.15                 # interference at the rim; raise for a firmer click
BEAD_H = 1.0                  # bead height; with its 0.4 mm reach the faces slope ~39°
BEAD_UP = 1.0                 # bead centre above the skirt's bottom edge
BEAD_LEN = 0.6                # fraction of the long side it runs along (the middle flexes)
SLIT_W = PAPER_W + 3.0        # across
SLIT_GAP = 1.2                # front to back: 0.18 mm stock slides freely; narrow so it doesn't drop back in
SLIT_FROM_FRONT = WALL + LIP_CLEAR + LIP_WALL + 0.8   # inside the skirt, near the front wall


def _grow(z: float) -> float:
    """How far a leaning wall sits outside its rim position at height z."""
    return (H - z) * math.tan(math.radians(TAPER))


def _tapered(w: float, l: float, r: float, z0: float, z1: float):
    """Rounded rectangle that is w x l at the rim (z = H), walls leaning in, from z0 to z1."""
    g = _grow(z0)
    with BuildSketch(Plane.XY.offset(z0)) as sk:
        RectangleRounded(w + 2 * g, l + 2 * g, r + g)
    return extrude(sk.sketch, amount=z1 - z0, taper=TAPER)


def _roll_axis_z() -> float:
    return FLOOR + ROLL_CLEAR + ROLL_OD / 2


def base():
    ow, ol = IW + 2 * WALL, IL + 2 * WALL
    solid = _tapered(ow, ol, FILLET, 0, H)
    solid = chamfer([e for e in solid.edges() if e.center().Z < 0.01], length=BOTTOM_CHAMFER)
    cavity = _tapered(IW, IL, FILLET - WALL, FLOOR, H + 5)
    # Curved cradle: fill the bottom of the cavity, then scoop out a trough
    # concentric with the roll, so a shrinking roll stays centred and turns freely.
    fill = cavity & Pos(0, 0, FLOOR) * Box(200, 200, ROLL_OD / 2, align=C)
    trough = Pos(0, 0, _roll_axis_z()) * Rot(0, 90, 0) * Cylinder(ROLL_OD / 2 + ROLL_CLEAR, 200)
    return solid - cavity + (fill - trough)


def lid():
    """Lid in place on the base (z from H up). Skirt below, slit near the front (-y)."""
    tw, tl = IW + 2 * WALL, IL + 2 * WALL                    # outside of the base at the rim
    with BuildSketch(Plane.XY.offset(H)) as sk:
        RectangleRounded(tw, tl, FILLET)
    plate = extrude(sk.sketch, amount=LID_T)
    plate = fillet([e for e in plate.edges() if e.center().Z > H + LID_T - 0.01], radius=LID_FILLET)

    sw, sl = IW - 2 * LIP_CLEAR, IL - 2 * LIP_CLEAR
    with BuildSketch(Plane.XY.offset(H - LIP_DEPTH)) as sk:
        RectangleRounded(sw, sl, FILLET - WALL - LIP_CLEAR)
    skirt = extrude(sk.sketch, amount=LIP_DEPTH + 0.01)
    with BuildSketch(Plane.XY.offset(H - LIP_DEPTH - 1)) as sk:
        RectangleRounded(sw - 2 * LIP_WALL, sl - 2 * LIP_WALL, max(FILLET - WALL - LIP_CLEAR - LIP_WALL, 0.5))
    skirt -= extrude(sk.sketch, amount=LIP_DEPTH + 1)

    reach = LIP_CLEAR + DETENT
    zb = H - LIP_DEPTH + BEAD_UP
    for side in (-1, 1):
        x0 = side * (sw / 2 - 0.01)
        with BuildSketch(Plane.XZ) as bk:
            with BuildLine():
                Polyline((x0, zb - BEAD_H / 2), (side * (sw / 2 + reach), zb), (x0, zb + BEAD_H / 2), close=True)
            make_face()
        skirt += extrude(bk.sketch, amount=BEAD_LEN * sl / 2, both=True)

    out = plate + skirt
    slit_y = -tl / 2 + SLIT_FROM_FRONT + SLIT_GAP / 2
    slit = Pos(0, slit_y, H - LIP_DEPTH - 1) * Box(SLIT_W, SLIT_GAP, LIP_DEPTH + LID_T + 2, align=C)
    # The slit cuts through the skirt's front wall too, so the paper isn't pinched.
    return out - slit


def roll_and_paper():
    """Roll (full, coreless), and the backing threaded up through the slit and over the front edge."""
    z = _roll_axis_z()
    roll = Pos(0, 0, z) * Rot(0, 90, 0) * Cylinder(ROLL_OD / 2, PAPER_W)     # coreless
    tl = IL + 2 * WALL
    slit_y = -tl / 2 + SLIT_FROM_FRONT + SLIT_GAP / 2
    t = 0.15
    up = Pos(0, slit_y, z) * Box(PAPER_W, t, H + LID_T - z + 0.2, align=C)               # roll to slit
    over = Pos(0, (slit_y - tl / 2) / 2, H + LID_T + 0.2) * Box(PAPER_W, slit_y + tl / 2, t, align=C)
    drop = 20.0                                                                        # pulled down the front,
    down = Pos(0, -tl / 2 - 0.3 - (drop - LID_T) * math.tan(math.radians(TAPER)),      # clear of the leaning wall
               H + LID_T - drop) * Box(PAPER_W, t, drop + 0.2, align=C)
    sticker = Pos(0, -tl / 2 - 6, H + LID_T + 2) * Rot(-25, 0, 0) * Box(STICKER, STICKER_T, STICKER, align=C)
    return [roll, up, over, down], sticker


def print_orientation():
    b = base()
    l = Rot(180, 0, 0) * lid()
    l = Pos(0, 0, -l.bounding_box().min.Z) * l
    return {"base": b, "lid": l}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    PRINT_DIR.mkdir(parents=True, exist_ok=True)
    b, l = base(), lid()
    assert b.is_valid and l.is_valid, "invalid solid"
    paper, sticker = roll_and_paper()
    clash = sum((b & p).volume + (l & p).volume for p in paper[:1])
    lid_fit = (b & l).volume
    # The snap: free when seated, but the bead must squeeze past the rim on the way in.
    passing = (b & Pos(0, 0, LIP_DEPTH - BEAD_UP) * l).volume
    bb = (b + l).bounding_box()
    print(f"dispenser {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; "
          f"full roll vs box {clash:.2f} mm³; lid vs base seated {lid_fit:.2f} mm³, "
          f"bead passing the rim {passing:.2f} mm³")
    render(
        {
            "Dispenser": {"body": b, "cover": l, "print": paper[1:], "tag": sticker},
            "Lid off": {"body": b, "cover": Pos(0, 0, 45) * l, "print": paper[:1]},
            "From above: the slit": {"body": b, "cover": l},
            "Lid underside: snap beads": {"cover": l},
        },
        OUT / "dispenser.png",
        views=[(25, -55), (30, -120), (75, -90), (-35, -30)],
        columns=2,
    )
    for name, part in print_orientation().items():
        export_stl(part, str(PRINT_DIR / f"dispenser_{name}.stl"))
    export_step(b, str(PRINT_DIR / "dispenser_base.step"))
    export_step(l, str(PRINT_DIR / "dispenser_lid.step"))
    print("wrote", OUT / "dispenser.png")
