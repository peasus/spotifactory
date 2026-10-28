"""Stencil for a black vinyl square behind the photo's picture.

A dummy Instax Square print: a 72 x 86 card that stands in the groove and
leans on the panel just like a real print, with a window where the print's
62 x 62 picture is. Use it twice:

  1. Cutting: lay it flat on the vinyl and run a knife round the inside of
     the window, keeping the blade against the wall. That gives a 62 mm square.
  2. Placing: stand it in the groove, peel the square and lay it into the
     window, bottom edge first, then lift the stencil off.

The picture's top border on a real print is TOP_BORDER: measure yours and
change it if it differs. The top few mm of the square wrap over the panel's
rounded top edge.

Run:  enclosure/.venv/bin/python enclosure/vinyl_stencil.py
Writes out/print/vinyl_stencil.stl (flat, to print) and checks the stencil
fits the body's groove the way a print does.
"""
from __future__ import annotations

from build123d import Align, Box, Pos, Text, export_stl, extrude, Plane

import easel
from concepts import OUT, PRINT_H, PRINT_T, PRINT_W

IMAGE = 62.0                  # Instax Square picture
TOP_BORDER = 6.0              # print's top edge to the picture (as easel.py's mock print)
THICK = 1.6                   # stiff enough to lean on, thin enough for the 2.5 mm groove
C = (Align.CENTER, Align.CENTER, Align.MIN)


def stencil():
    """In the print frame: y up the print from its bottom edge, z out of its face,
    back face where a real print's back is."""
    back = -PRINT_T / 2
    card = Pos(0, PRINT_H / 2, back) * Box(PRINT_W, PRINT_H, THICK, align=C)
    window = Pos(0, PRINT_H - TOP_BORDER - IMAGE / 2, back - 1) * Box(IMAGE, IMAGE, THICK + 2, align=C)
    card -= window
    # Which way up: engraved in the wide bottom border, on the front.
    label = Plane.XY.offset(back + THICK - 0.4) * Pos(0, (PRINT_H - TOP_BORDER - IMAGE) / 2)
    card -= extrude(label * Text("BOTTOM", font_size=5, align=(Align.CENTER, Align.CENTER)), amount=1)
    return card


if __name__ == "__main__":
    s = stencil()
    placed = easel._print_frame() * s
    hit = (placed & easel.body()).volume
    print(f"stencil in the groove overlaps the body by {hit:.2f} mm³" + ("" if hit < 0.01 else "  <-- doesn't fit"))
    (OUT / "print").mkdir(parents=True, exist_ok=True)
    flat = Pos(0, 0, PRINT_T / 2) * s          # back face on the bed
    export_stl(flat, str(OUT / "print" / "vinyl_stencil.stl"))
    bb = flat.bounding_box()
    print(f"print {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.1f} mm; wrote", OUT / "print" / "vinyl_stencil.stl")
