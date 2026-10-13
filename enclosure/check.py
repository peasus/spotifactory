"""Sanity checks for the enclosure: validity, fit, assembly and printability.

Run:  enclosure/.venv/bin/python enclosure/check.py
Exits non-zero if anything fails.
"""
from __future__ import annotations

import sys

import numpy as np
import trimesh
from build123d import Pos, export_stl

import easel

TOUCH = 0.05      # mm^3 of overlap treated as just touching
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def overlap(a, b) -> float:
    shapes = b if isinstance(b, list) else [b]
    return sum((a & s).volume for s in shapes)


MAX_SPAN = 8.0    # mm: bridges and ledges narrower than this print without support


def overhangs(part, name: str) -> None:
    """Find surfaces facing down more steeply than 45° (not on the bed).

    Each connected region gets an effective span, 2 x area / outline length: about
    the width of a band or bridge. Narrow ones (short bridges between walls, small
    ledges) print fine; a wide one is an unsupported ceiling.
    """
    path = easel.PRINT_DIR / f"_check_{name}.stl"
    export_stl(part, str(path))
    mesh = trimesh.load(path)
    path.unlink()
    n, centres = mesh.face_normals, mesh.triangles_center
    idx = np.where((n[:, 2] < -0.72) & (centres[:, 2] > 0.3))[0]
    if not len(idx):
        check(True, f"{name}: nothing needs support")
        return
    regions = mesh.submesh([idx], append=True).split(only_watertight=False)
    spans = []
    for r in regions:
        outline = r.outline()
        length = outline.length if outline is not None else 0
        spans.append((2 * r.area / length if length else 0, r.area, r.bounds))
    span, area, (b0, b1) = max(spans, key=lambda s: s[0])
    total = sum(s[1] for s in spans)
    check(span <= MAX_SPAN,
          f"{name}: {len(spans)} overhang regions ({total:.0f} mm²), widest span {span:.1f} mm "
          f"at x {b0[0]:.0f}..{b1[0]:.0f} y {b0[1]:.0f}..{b1[1]:.0f} z {b0[2]:.0f}..{b1[2]:.0f} "
          f"(limit {MAX_SPAN:.0f})")


def main() -> int:
    body, fp, bp = easel.body(), easel.faceplate(), easel.baseplate()
    inside = easel.internals()

    print("Validity")
    for name, part in (("body", body), ("faceplate", fp), ("baseplate", bp)):
        check(part.is_valid, f"{name} is a valid solid")

    print("Parts don't collide")
    check(overlap(body, fp) < TOUCH, f"body / faceplate: {overlap(body, fp):.2f} mm³")
    check(overlap(body, bp) < TOUCH, f"body / baseplate: {overlap(body, bp):.2f} mm³")
    check(overlap(fp, bp) < TOUCH, f"faceplate / baseplate: {overlap(fp, bp):.2f} mm³")

    print("Boards fit")
    for key in ("hat", "screen", "buttons", "pi", "reader", "port", "print"):
        for name, part in (("body", body), ("faceplate", fp), ("baseplate", bp)):
            v = overlap(part, inside[key])
            check(v < TOUCH, f"{key:8s} vs {name}: {v:.2f} mm³")

    print("Assembly")
    # Faceplate goes in from below, along the slope's normal, body upside down.
    f = easel.hat_frame()
    blocked = None
    for d in range(2, 40, 2):
        moved = f * Pos(0, 0, -d) * f.inverse() * fp
        if overlap(body, moved) > TOUCH:
            blocked = d
            break
    check(blocked is None, "faceplate slides in from below" +
          (f" (blocked {blocked} mm out)" if blocked else ""))
    # The stack clamps: base plate posts touch the Pi's underside.
    pi_board = inside["pi"][0]
    # Shift the Pi slightly towards the plate: posts that reach it will then overlap.
    f = easel.hat_frame()
    gap_closed = overlap(bp, f * Pos(0, 0, -0.2) * f.inverse() * pi_board) > 0.01
    check(gap_closed, "base plate posts reach the Pi (clamp)")
    # Reader lifts out through the top slot.
    pf = easel._print_frame()
    lifted_clear = all(
        overlap(body, [pf * Pos(0, step, 0) * pf.inverse() * s
                       for s in (inside["reader"], inside["port"][1])]) < TOUCH
        for step in range(5, 90, 5))
    check(lifted_clear, "reader lifts out through the top slot")

    print("Printability (as oriented in out/print)")
    parts = easel.print_orientation()
    for name in ("body", "faceplate", "baseplate"):
        overhangs(parts[name], name)
    for name, part in parts.items():
        bb = part.bounding_box()
        fits = bb.size.X <= 250 and bb.size.Y <= 250 and bb.size.Z <= 250
        check(fits and abs(bb.min.Z) < 0.01,
              f"{name}: {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm, on the bed, fits a P1S")

    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'All checks passed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
