"""Sanity checks for the enclosure: validity, fit, assembly and printability.

Run:  enclosure/.venv/bin/python enclosure/check.py
Exits non-zero if anything fails.
"""
from __future__ import annotations

import math
import sys

import numpy as np
import trimesh
from build123d import Pos, export_stl

import easel

TOUCH = 0.05      # mm^3 of overlap treated as just touching
MAX_SPAN = 8.0    # mm: bridges and ledges narrower than this print without support
failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + msg)
    if not ok:
        failures.append(msg)


def as_list(v):
    return v if isinstance(v, list) else [v]


def overlap(a, b) -> float:
    return sum((a & s).volume for s in as_list(b))


def sweep(body, shapes, moves) -> int | None:
    """Move `shapes` through each offset in `moves`; return the index of the
    first offset that collides with `body`, or None if the path is clear."""
    for i, (dx, dy, dz) in enumerate(moves):
        if overlap(body, [Pos(dx, dy, dz) * s for s in shapes]) > TOUCH:
            return i
    return None


def overhangs(part, name: str) -> None:
    """Down-facing regions steeper than 45° (not on the bed), sized by effective
    span = 2 x area / outline length. Narrow ones (short bridges, small ledges)
    print fine; a wide one is an unsupported ceiling."""
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
    span, _, (b0, b1) = max(spans, key=lambda s: s[0])
    total = sum(s[1] for s in spans)
    check(span <= MAX_SPAN,
          f"{name}: {len(spans)} overhang regions ({total:.0f} mm²), widest span {span:.1f} mm "
          f"at x {b0[0]:.0f}..{b1[0]:.0f} y {b0[1]:.0f}..{b1[1]:.0f} z {b0[2]:.0f}..{b1[2]:.0f} "
          f"(limit {MAX_SPAN:.0f})")


LAYER = 0.3
MAX_REACH = 5.0   # mm a layer may extend past supported material (ledge, or half a bridge)


def unsupported(part, name: str) -> None:
    """Slice like a slicer and measure, for every bit of a layer that has nothing
    under it, how far it reaches from material that does. Short ledges and
    bridges between walls are fine; a long strand out into thin air (like the
    first layer of a wedge whose bottom edge floats) or a true island is not."""
    path = easel.PRINT_DIR / f"_check_{name}.stl"
    export_stl(part, str(path))
    mesh = trimesh.load(path)
    path.unlink()
    from shapely.geometry import Point
    from shapely.ops import unary_union
    heights = np.arange(LAYER / 2, mesh.bounds[1][2], LAYER)
    sections = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=heights)
    prev, bad = None, []
    for z, sec in zip(heights, sections):
        polys = [p for p in (sec.polygons_full if sec is not None else []) if p.area > 0.01]
        if prev is not None:
            support = prev.buffer(LAYER)       # each layer may step out ~one layer (45°)
            for p in polys:
                loose = p.difference(support)
                if loose.area < 1.0:
                    continue
                held = p.intersection(support)
                for piece in getattr(loose, "geoms", [loose]):
                    if piece.area < 1.0:
                        continue
                    if held.is_empty:
                        reach = float("inf")
                    else:
                        reach = max(held.distance(Point(c)) for c in piece.exterior.coords)
                    if reach > MAX_REACH:
                        bad.append((z, piece.centroid, reach, piece.area))
        prev = unary_union(polys) if polys else None
    # One line per place, not per layer.
    seen, report = [], []
    for z, c, reach, area in bad:
        if any(c.distance(o) < 5 for o in seen):
            continue
        seen.append(c)
        r = "island" if reach == float("inf") else f"reaches {reach:.0f} mm"
        report.append(f"z {z:.1f} at ({c.x:.0f}, {c.y:.0f}) {r}")
    check(not bad, f"{name}: " + ("; ".join(report[:4]) if bad else
                                  f"every layer is supported within {MAX_REACH:.0f} mm"))


def main() -> int:
    body, fp, bp = easel.body(), easel.faceplate(), easel.baseplate()
    inside = easel.internals()

    print("Validity")
    for name, part in (("body", body), ("faceplate", fp), ("baseplate", bp),
                       ("spacers", easel.spacers())):
        check(part.is_valid, f"{name} is a valid solid")

    print("Parts don't collide")
    for (an, a), (bn, b) in ((("body", body), ("faceplate", fp)), (("body", body), ("baseplate", bp)),
                             (("faceplate", fp), ("baseplate", bp))):
        v = overlap(a, b)
        check(v < TOUCH, f"{an} / {bn}: {v:.2f} mm³")

    print("Boards, cables and plugs fit")
    clashes = 0
    for key in ("hat", "screen", "buttons", "pi", "spacers", "reader", "port", "plugs", "print"):
        for name, part in (("body", body), ("faceplate", fp), ("baseplate", bp)):
            v = overlap(part, inside[key])
            if v >= TOUCH:
                clashes += 1
                check(False, f"{key} vs {name}: {v:.2f} mm³")
    if not clashes:
        check(True, "boards, spacers, reader, sockets, plugs and the print all clear the parts")
    shell_end = inside["port"][0].bounding_box().max.Y
    wall_in = easel.back_in_y(easel.PWR_Z + easel.PWR_SHELL[1] / 2)
    check(wall_in - 0.5 < shell_end <= wall_in,
          f"USB-C socket ends {wall_in - shell_end:.1f} mm inside the back wall")

    print("Assembly")
    a = math.radians(easel.SLOPE)
    ny, nz = -math.sin(a), math.cos(a)
    # Faceplate + Pi stack, screwed together, goes in from below: out of the
    # pocket along the face's normal, then straight down past the bed.
    module = [fp, *inside["hat"], inside["screen"], inside["buttons"], *inside["spacers"],
              *inside["pi"][:2]]
    path = [(0, -ny * d, -nz * d) for d in range(1, 7)]
    path += [(0, -ny * 6, -nz * 6 - d) for d in range(2, 60, 2)]
    hit = sweep(body, module, path)
    check(hit is None, "faceplate + Pi stack goes in from below" +
          ("" if hit is None else f" (blocked at {path[hit]})"))
    # Reader: off the nubs (away from the wall), then straight down and out.
    rf = easel._reader_frame()
    back = (rf * Pos(0, 0, -4)).position - rf.position
    reader = [inside["reader"], inside["port"][1], inside["plugs"][-1]]
    path = [(back.X * t, back.Y * t, back.Z * t) for t in (0.25, 0.5, 0.75, 1.0)]
    path += [(back.X, back.Y, back.Z - d) for d in range(2, 120, 2)]
    hit = sweep(body, reader, path)
    check(hit is None, "reader (with its right-angle plug) goes in from below onto the nubs" +
          ("" if hit is None else f" (blocked at {path[hit]})"))
    # Base plate, with the power board on its bracket, lifts straight in.
    hit = sweep(body, [bp, inside["pi"][2], inside["port"][0]], [(0, 0, -d) for d in range(1, 40, 2)])
    check(hit is None, "base plate + power board lifts straight in")
    # The stack is clamped: base plate posts reach the Pi.
    f = easel.hat_frame()
    reach = overlap(bp, f * Pos(0, 0, -0.2) * f.inverse() * inside["pi"][0]) > 0.01
    check(reach, "base plate posts reach the Pi (clamp)")

    print("Printability (as oriented in out/print)")
    parts = easel.print_orientation()
    for name in ("body", "faceplate", "baseplate", "spacers"):
        overhangs(parts[name], name)
        unsupported(parts[name], name)
    for name, part in parts.items():
        bb = part.bounding_box()
        fits = bb.size.X <= 250 and bb.size.Y <= 250 and bb.size.Z <= 250
        check(fits and abs(bb.min.Z) < 0.01,
              f"{name}: {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm, on the bed, fits a P1S")

    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'All checks passed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
