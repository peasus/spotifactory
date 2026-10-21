"""Sanity checks for the enclosure: validity, fit, assembly and printability.

Run:  enclosure/.venv/bin/python enclosure/check.py
Exits non-zero if anything fails.
"""
from __future__ import annotations

import math
import sys

import numpy as np
import trimesh
from build123d import Box, Pos, Rot, export_stl

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


def manifold(part, name: str) -> None:
    """Every edge of the exported STL is shared by exactly two triangles (what
    the slicer calls non-manifold edges). Near-duplicate vertices from the
    tessellation are merged first; slicers do the same."""
    path = easel.PRINT_DIR / f"_check_{name}.stl"
    export_stl(part, str(path))
    mesh = trimesh.load(path)
    path.unlink()
    mesh.merge_vertices(digits_vertex=3)
    mesh.update_faces(mesh.nondegenerate_faces(height=1e-6))
    edges = np.sort(mesh.edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    bad = int((counts != 2).sum())
    check(bad == 0, f"{name}: STL is watertight" if not bad else f"{name}: {bad} non-manifold edges in the STL")


LAYER = 0.3
MAX_REACH = 5.0   # mm a layer may extend past supported material (ledge, or half a bridge)
# Even a hairline counts: the knife-edge of a 45° wedge starts as a sliver a
# fraction of a layer wide, and if it spans a gap, the printer has to bridge it.
MIN_LOOSE = 0.05


def unsupported(part, name: str, supported=()) -> None:
    """Slice like a slicer and measure, for every bit of a layer that has nothing
    under it, how far it reaches from material that does. Short ledges and
    bridges between walls are fine; a long strand out into thin air (like the
    first layer of a wedge whose bottom edge floats) or a true island is not."""
    path = easel.PRINT_DIR / f"_check_{name}.stl"
    export_stl(part, str(path))
    mesh = trimesh.load(path)
    path.unlink()
    bad = []
    # Two passes, half a layer apart, so a thin feature can't fall between slices.
    for start in (LAYER / 2, LAYER):
        heights = np.arange(start, mesh.bounds[1][2], LAYER)
        sections = mesh.section_multiplane(plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=heights)
        bad += _unsupported_pass(heights, sections)
    # Leave out spans printed on painted supports (easel.supported_bridges).
    inside = lambda c, z: any(x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= z <= z1
                              for x0, x1, y0, y1, z0, z1 in supported)
    report_unsupported([b for b in bad if not inside(b[1], b[0])], name)


def _unsupported_pass(heights, sections):
    from shapely.geometry import Point
    from shapely.ops import unary_union
    prev, bad = None, []
    for z, sec in zip(heights, sections):
        polys = [p for p in (sec.polygons_full if sec is not None else []) if p.area > 0.01]
        if prev is not None:
            support = prev.buffer(LAYER)       # each layer may step out ~one layer (45°)
            for p in polys:
                # A piece touching nothing below is floating, however small (slicers flag these).
                if p.distance(prev) > 0.05:
                    bad.append((z, p.centroid, float("inf"), p.area))
                    continue
                loose = p.difference(support)
                if loose.area < MIN_LOOSE:
                    continue
                held = p.intersection(support)
                for piece in getattr(loose, "geoms", [loose]):
                    if piece.area < MIN_LOOSE:
                        continue
                    if held.is_empty:
                        reach = float("inf")
                    else:
                        reach = max(held.distance(Point(c)) for c in piece.exterior.coords)
                    if reach > MAX_REACH:
                        bad.append((z, piece.centroid, reach, piece.area))
        prev = unary_union(polys) if polys else None
    return bad


def report_unsupported(bad, name: str) -> None:
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
    tilts = [easel.nub_tilted(s, ax) for s in (-1, 1) for ax in ("x", "y")]
    hits = sum(overlap(p, [easel.nub(), *tilts]) for p in (body, fp))
    check(hits < TOUCH, f"joystick nub clears the faceplate and body, upright and pushed over ({hits:.2f} mm³)")
    # Pressing the stick in (its centre click) while it leans a little: the
    # nub mustn't bottom out on the faceplate first.
    press = 0.6
    fdir = easel.hat_frame()
    dz = (fdir * Pos(0, 0, -press)).position - fdir.position
    pressed_nubs = [Pos(dz.X, dz.Y, dz.Z) * n for n in (easel.nub(), easel.nub_tilted(1, "x"), easel.nub_tilted(-1, "y"))]
    press_hits = overlap(fp, pressed_nubs)
    check(press_hits < TOUCH, f"joystick nub can be pressed in {press} mm, upright or leaning ({press_hits:.2f} mm³)")
    caps = easel.button_caps()
    f = easel.hat_frame()
    down = (f * Pos(0, 0, -0.25)).position - f.position             # pressed: a switch's travel
    up = (f * Pos(0, 0, easel.CAP_LIFT - 0.02)).position - f.position
    cap_hits = sum(overlap(p, [Pos(v.X, v.Y, v.Z) * cp for cp in caps for v in (down, up)] + caps)
                   for p in (body, fp))
    check(cap_hits < TOUCH, f"button caps move freely in the faceplate, pressed or lifted ({cap_hits:.2f} mm³)")
    lifted = sum(overlap(fp, Pos(u.X, u.Y, u.Z) * cp) for cp in caps
                 for u in [(f * Pos(0, 0, easel.CAP_LIFT + 0.1)).position - f.position])
    check(lifted > 0.1, "button caps can't come out the front (flange catches)")
    # Only the plunger may touch a cap, even pressed right down: the flange
    # clears the switch's body and metal lip.
    pressed = [Pos(down.X, down.Y, down.Z) * cp for cp in caps]
    under = [f * Pos(bx, by, easel.HAT_TOP) * (
        Box(*easel.BUTTON_FOOT, easel.BUTTON_BODY_H, align=easel.C)
        + Box(*easel.BUTTON_LIP, align=easel.C)) for bx, by in easel.BUTTONS]
    switch_hits = sum(overlap(u, pressed) for u in under)
    check(switch_hits < TOUCH, f"pressed caps touch only the plungers, not the switch bodies ({switch_hits:.2f} mm³)")
    rest = sum(overlap(f * Pos(bx, by, easel.HAT_TOP) * easel.switch(), caps) for bx, by in easel.BUTTONS)
    check(rest < TOUCH, f"caps rest on the plungers without pressing them ({rest:.2f} mm³)")
    stem_hit = overlap(fp, inside["buttons"]) + sum(overlap(fp, easel.hat_frame() * Pos(*easel.JOY, easel.HAT_TOP + easel.JOY_HOUSING_H) * (Rot(easel.JOY_TILT * s, 0, 0) if ax == "x" else Rot(0, easel.JOY_TILT * s, 0)) * easel.joy_stem()) for s in (-1, 1) for ax in ("x", "y"))
    check(stem_hit < TOUCH, f"joystick stem tilts freely in the faceplate's hole ({stem_hit:.2f} mm³)")
    shell_end = inside["port"][0].bounding_box().max.Y
    wall_in = easel.back_in_y(easel.PWR_Z + easel.PWR_SHELL[1] / 2)
    check(wall_in - easel.SOCKET_INSET - 0.3 < shell_end <= wall_in,
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
    # Reader, plug in: down the wall out of the caps, away from the wall, then
    # straight down and out (the reverse of putting it in).
    mf = easel._mount_frame()
    vec = lambda v: (mf * Pos(*v)).position - mf.position
    down, back = vec((0, -1, 0)), vec((0, 0, -(easel.SHELF_WALL_BACK + 1.5)))   # back past the partition
    reader = [inside["reader"], inside["port"][1], inside["plugs"][-1]]
    s = easel.READER_SLIDE
    path = [(down.X * d, down.Y * d, down.Z * d) for d in (s * 0.25, s * 0.5, s * 0.75, s)]
    at = (down.X * s, down.Y * s, down.Z * s)
    path += [(at[0] + back.X * t, at[1] + back.Y * t, at[2] + back.Z * t) for t in (0.25, 0.5, 0.75, 1.0)]
    at = (at[0] + back.X, at[1] + back.Y, at[2] + back.Z)
    path += [(at[0], at[1], at[2] - d) for d in range(2, 120, 2)]
    hit = sweep(body, reader, path)
    check(hit is None, "reader (with its USB-C plug in) goes in from below and up into the caps" +
          ("" if hit is None else f" (blocked at {path[hit]})"))
    # Keepers: up the screw axis into place; the screwdriver reaches from below.
    keepers = [easel.keeper(-1), easel.keeper(1)]
    v, away = vec((0, -1, 0)), vec((0, 0, -(easel.SHELF_WALL_BACK + 1.5)))     # back past the partition
    kpath = [(v.X * d, v.Y * d, v.Z * d) for d in range(1, 8)]
    at = (v.X * 7, v.Y * 7, v.Z * 7)
    kpath += [(at[0] + away.X * t, at[1] + away.Y * t, at[2] + away.Z * t) for t in (0.5, 1.0)]
    at = (at[0] + away.X, at[1] + away.Y, at[2] + away.Z)
    kpath += [(at[0], at[1], at[2] - d) for d in range(2, 40, 2)]
    hit = sweep(body, keepers, kpath)
    check(hit is None, "keepers go in from below and up their screw axes" + ("" if hit is None else f" (blocked at {kpath[hit]})"))
    drv = overlap(body, [easel.keeper_screw_path(-1), easel.keeper_screw_path(1)])
    check(drv < TOUCH, f"screwdriver reaches both keeper screws from below ({drv:.2f} mm³ in the way)")
    # The keepers push the reader up against the stops (KEEPER_GAP < 0): check it seated there.
    lift = max(0.0, -easel.KEEPER_GAP) + 0.01
    up = vec((0, lift, 0))
    seated = [Pos(up.X, up.Y, up.Z) * inside["reader"], Pos(up.X, up.Y, up.Z) * inside["plugs"][-1]]
    k_hits = overlap(seated[0], keepers) + overlap(seated[1], keepers) + overlap(body, keepers)
    top_gap = overlap(body, seated[0])
    check(top_gap < TOUCH, f"pushed up by the keepers, the reader still clears the stops ({top_gap:.2f} mm³)")
    check(k_hits < TOUCH, f"keepers clear the reader, its plug and the body ({k_hits:.2f} mm³)")
    dropped = overlap(Pos(down.X, down.Y, down.Z) * inside["reader"], keepers)
    check(dropped > 1, "reader can't slide down out of the caps: 1 mm down, it lands on the keepers")
    # Base plate, with the power board on its bracket, lifts straight in.
    hit = sweep(body, [bp, inside["pi"][2], inside["port"][0]], [(0, 0, -d) for d in range(1, 40, 2)])
    check(hit is None, "base plate + power board lifts straight in")
    # The stack is clamped: base plate posts reach the Pi.
    f = easel.hat_frame()
    reach = overlap(bp, f * Pos(0, 0, -0.2) * f.inverse() * inside["pi"][0]) > 0.01
    check(reach, "base plate posts reach the Pi (clamp)")

    print("Printability (as oriented in out/print)")
    parts = easel.print_orientation()
    for name in ("body", "faceplate", "baseplate", "spacers", "keepers", "nub", "buttoncaps"):
        manifold(parts[name], name)
        overhangs(parts[name], name)
        unsupported(parts[name], name, easel.supported_bridges() if name == "body" else ())
    for name, part in parts.items():
        bb = part.bounding_box()
        fits = bb.size.X <= 250 and bb.size.Y <= 250 and bb.size.Z <= 250
        check(fits and abs(bb.min.Z) < 0.01,
              f"{name}: {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm, on the bed, fits a P1S")

    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'All checks passed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
