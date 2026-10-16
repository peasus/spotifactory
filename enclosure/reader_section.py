"""Test print: the part of the body that holds the reader, cut out of the real
body model and printed in the same orientation, so the fit carries over.

It has the panel with its top caps, the keeper posts, the shelf, and the
solid wall under the shelf down to the bed with its channels for the reader's
plug and the keeper screwdrivers, exactly as in the body. Assemble
it for real: plug the cable into the reader, slide the reader up into the
caps, then fit both keepers with M2.5 x 12 screws.

Run:  enclosure/.venv/bin/python enclosure/reader_section.py
Writes out/print/reader_section.stl and out/reader_section.png.
"""
from __future__ import annotations

from build123d import Align, Box, Pos, export_stl

import check
import easel
from concepts import OUT, render

C = (Align.CENTER, Align.CENTER, Align.MIN)
STAND_T = 1.6
SHELF_BACK = easel.SHELF_WALL_BACK


def section():
    """The body cut down to the reader's surroundings: the panel with its caps,
    the keeper posts, the shelf and the solid wall under it with its channels.
    The cut sides fall in solid wall, clear of the openings."""
    top, yb, fp_back = easel.shelf_geometry()
    mf = easel._mount_frame()
    x = mf.position.X
    reach = easel.KPOST_X + easel.KPOST_R + easel.KEEPER_DRIVER_R
    x0, x1 = x - reach - 2.0, x + reach + 2.0
    # Widen to take in any partition gap the edges fall in (and a bit of wall past it),
    # so every gap's chamfer keeps both its sides.
    slab = easel._yz_prism([(yb, 0), (yb + SHELF_BACK, 0), (yb + SHELF_BACK, top), (yb, top)])
    for a, b in easel.partition_gaps(slab):
        if a < x0 < b:
            x0 = a - 3.0
        if a < x1 < b:
            x1 = b + 3.0
    y1 = yb + 26
    z_top = (mf * Pos(0, easel.READER_H + 8, 0)).position.Z
    region = Pos((x0 + x1) / 2, (fp_back + y1) / 2, 0) * Box(x1 - x0, y1 - fp_back, z_top, align=C)
    part = easel.body() & region
    # Test-print stand only: a thin frame on the bed out to the back, so the
    # panel (leaning back past the wall's footprint) can't tip as it prints.
    # Its middle is open, so the reader and screwdrivers come in from below.
    frame = Pos((x0 + x1) / 2, (fp_back + y1) / 2, 0) * Box(x1 - x0, y1 - fp_back, STAND_T, align=C)
    frame -= Pos(x, (fp_back - 1 + y1 - 6) / 2, -1) * Box(2 * (reach - 1), y1 - 6 - fp_back + 1, STAND_T + 2, align=C)
    return part + frame


if __name__ == "__main__":
    part = section()
    assert part.is_valid, "section is not a valid solid"
    ins = easel.internals()
    reader = [ins["reader"], ins["port"][1], ins["plugs"][-1]]
    keepers = [easel.keeper(-1), easel.keeper(1)]

    # Same assembly paths as check.py, against the section.
    mf = easel._mount_frame()
    vec = lambda v: (mf * Pos(*v)).position - mf.position
    down, back = vec((0, -1, 0)), vec((0, 0, -(easel.SHELF_WALL_BACK + 1.5)))
    s = easel.READER_SLIDE
    path = [(down.X * d, down.Y * d, down.Z * d) for d in (s * 0.25, s * 0.5, s * 0.75, s)]
    at = (down.X * s, down.Y * s, down.Z * s)
    path += [(at[0] + back.X * t, at[1] + back.Y * t, at[2] + back.Z * t) for t in (0.5, 1.0)]
    at = (at[0] + back.X, at[1] + back.Y, at[2] + back.Z)
    path += [(at[0], at[1], at[2] - d) for d in range(2, 60, 2)]
    hit = check.sweep(part, reader, path)
    check.check(hit is None, "reader + plug go in and up into the caps")
    check.check(check.overlap(part, keepers) < check.TOUCH, "keepers fit")
    up = vec((0, max(0.0, -easel.KEEPER_GAP) + 0.01, 0))
    check.check(check.overlap(Pos(up.X, up.Y, up.Z) * reader[0], keepers) < check.TOUCH, "keepers clear the seated reader")
    drv = check.overlap(part, [easel.keeper_screw_path(-1), easel.keeper_screw_path(1)])
    check.check(drv < check.TOUCH, "screwdriver reaches both keeper screws")
    check.manifold(part, "reader section")
    check.unsupported(part, "reader section")

    (OUT / "print").mkdir(parents=True, exist_ok=True)
    export_stl(part, str(OUT / "print" / "reader_section.stl"))
    bb = part.bounding_box()
    scene = {"body": part, "reader": reader[0], "port": reader[1], "plugs": reader[2], "cover": keepers}
    render({"Assembled, from behind": scene, "As printed": {"body": part}},
           OUT / "reader_section.png", views=[(15, 95), (25, -60)], columns=2)
    print(f"reader section {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; "
          f"{'FAILED: ' + str(len(check.failures)) if check.failures else 'all checks passed'}")
