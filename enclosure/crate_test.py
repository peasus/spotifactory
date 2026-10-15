"""Fit test for the crate's slots: a short, full-width section of the crate
floor with three slots at each of several fin heights. The ends are open so
you can bend the prints forward over the fins the way you would in the crate.

Check which height holds a print upright, keeps the fins below the image, and
still lets you bend the prints forward to look through. Then set FIN_H in
crate.py to it.

Run:  enclosure/.venv/bin/python enclosure/crate_test.py
Writes out/print/crate_test.stl and out/crate_test.png.
"""
from __future__ import annotations

from build123d import Align, Box, Pos, Text, export_stl, extrude, fillet, Axis

import crate
from concepts import OUT, render

HEIGHTS = (10.0, 12.0, 14.0, 16.0)   # fin heights to try; 14 is what the crate has now
SLOTS = 3                            # per height
LABEL_ROOM = 10.0                    # floor in front of each group, for its label
SIDE_H = max(HEIGHTS) + 4.0          # side walls just tall enough to hold the fins
C = (Align.CENTER, Align.CENTER, Align.MIN)


def section():
    group = (SLOTS + 1) * crate.FIN_T + SLOTS * crate.SLOT_W
    length = len(HEIGHTS) * (LABEL_ROOM + group) + 6.0
    ow = crate.IW + 2 * crate.WALL
    outer = Box(ow, length, SIDE_H, align=C)
    outer = fillet(outer.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], radius=1.0)
    channel = Pos(0, 0, crate.FLOOR) * Box(crate.IW, length + 2, SIDE_H, align=C)
    part = outer - channel

    y = -length / 2 + LABEL_ROOM
    for h in HEIGHTS:
        for i in range(SLOTS + 1):
            part += crate.fin(y + i * crate.PITCH, h, crate.IW / 2 + 1) & outer
        label = Pos(0, y - LABEL_ROOM / 2, crate.FLOOR - 0.6) * extrude(
            Text(f"{h:g}", font_size=5, align=(Align.CENTER, Align.CENTER)), amount=1)
        part -= label
        y += group + LABEL_ROOM
    return part


if __name__ == "__main__":
    part = section()
    assert part.is_valid, "test section is not a valid solid"
    bb = part.bounding_box()
    (OUT / "print").mkdir(parents=True, exist_ok=True)
    export_stl(part, str(OUT / "print" / "crate_test.stl"))
    render({"Crate slot test: fin height (mm)": {"body": part}}, OUT / "crate_test.png",
           views=[(40, -60)], columns=1)
    print(f"crate test {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm; wrote",
          OUT / "print" / "crate_test.stl")
