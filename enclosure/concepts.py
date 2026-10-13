"""Block-out models of two enclosure concepts, rendered side by side.

Not printable yet — overall shape, proportions and layout only, using nominal
part sizes. Run:  enclosure/.venv/bin/python enclosure/concepts.py
Writes enclosure/out/concepts.png and one STL per concept.
"""
from __future__ import annotations

import math
from pathlib import Path

from build123d import (
    Align,
    Box,
    BuildLine,
    BuildSketch,
    Cylinder,
    Plane,
    Polyline,
    Pos,
    Rot,
    export_stl,
    extrude,
    make_face,
)

OUT = Path(__file__).parent / "out"

# Nominal part sizes (mm) — replace with caliper measurements later.
PRINT_W, PRINT_H, PRINT_T = 72.0, 86.0, 1.0      # Instax Square print
IMAGE = 62.0                                     # square image area on the print
HAT_W, HAT_D = 65.0, 30.0                        # Pi Zero 2W + SeenGreat OLED HAT
OLED_W, OLED_H = 35.0, 18.0                      # visible OLED glass
WALL = 2.0

C = (Align.CENTER, Align.CENTER, Align.MIN)


def _print_card():
    """The photo as a thin card lying in XY, image area marked, centred at the origin."""
    card = Box(PRINT_W, PRINT_H, PRINT_T, align=C)
    # Instax borders are wider at the bottom; image sits towards the top.
    image = Pos(0, (PRINT_H - IMAGE) / 2 - 6, PRINT_T + 0.2) * Box(IMAGE, IMAGE, 0.2, align=C)
    return card, image


def _controls():
    """OLED glass + joystick + buttons lying in XY, centred on the HAT footprint."""
    screen = Pos(-4, 0, 0) * Box(OLED_W, OLED_H, 0.6, align=C)
    stick = Pos(-HAT_W / 2 + 9, 0, 0) * Cylinder(3.5, 5, align=C)
    keys = [Pos(HAT_W / 2 - 7, y, 0) * Cylinder(2.5, 2, align=C) for y in (-8, 0, 8)]
    return screen, [stick, *keys]


def tray():
    """Concept A: flat box, print lies in a pocket on top, screen in front of it."""
    w, d, h = 104.0, 136.0, 32.0
    body = Box(w, d, h, align=C)
    # Print pocket towards the back, 1.5 mm deep, with a finger notch at the front edge.
    pocket_y = d / 2 - WALL - 4 - PRINT_H / 2
    pocket = Pos(0, pocket_y, h - 1.5) * Box(PRINT_W + 1, PRINT_H + 1, 2, align=C)
    notch = Pos(0, pocket_y - PRINT_H / 2, h - 3) * Cylinder(9, 4, align=C)
    body = body - pocket - notch

    card, image = _print_card()
    lay = Pos(0, pocket_y, h - 1.5)
    screen, buttons = _controls()
    front = Pos(0, -d / 2 + WALL + 6 + HAT_D / 2, h + 0.3)
    return {
        "body": body,
        "print": lay * card,
        "image": lay * image,
        "screen": front * screen,
        "buttons": [front * b for b in buttons],
    }


def easel():
    """Concept B: sloped control face you look down on, print stands upright behind it."""
    w = 100.0
    hf, ys, zs = 14.0, 62.0, 40.0          # front height; slope ends at (y, z)
    lean = math.radians(15)                # print leans back this far from vertical
    s, c = math.sin(lean), math.cos(lean)
    panel_len, panel_t = 78.0, 6.0
    lip_h, groove = 5.0, 3.0

    bx, bz = ys + groove + 2 + panel_t * c, zs - panel_t * s   # panel back-bottom corner
    profile = [
        (0, 0), (0, hf), (ys, zs),
        (ys, zs + lip_h), (ys + groove, zs + lip_h), (ys + groove, zs),
        (ys + groove + 2, zs),
        (ys + groove + 2 + panel_len * s, zs + panel_len * c),
        (bx + panel_len * s, bz + panel_len * c),
        (bx, bz), (bx, 0),
    ]
    with BuildSketch(Plane.YZ) as sk:
        with BuildLine():
            Polyline(*profile, close=True)
        make_face()
    body = extrude(sk.sketch, amount=w / 2, both=True)

    # Print standing in the groove, leaning against the panel.
    card, image = _print_card()
    stand = (
        Pos(0, ys + groove / 2 + 0.6, zs + 0.5)
        * Rot(90 - 15, 0, 0)
        * Pos(0, PRINT_H / 2, 0)
    )
    # Controls on the slope, tilted to match it.
    slope = math.degrees(math.atan2(zs - hf, ys))
    screen, buttons = _controls()
    on_slope = Pos(0, ys * 0.5, hf + (zs - hf) * 0.5) * Rot(slope, 0, 0) * Pos(0, 0, 0.3)
    return {
        "body": body,
        "print": stand * card,
        "image": stand * image,
        "screen": on_slope * screen,
        "buttons": [on_slope * b for b in buttons],
    }


COLORS = {
    "body": "#9aa5b1",
    "print": "#f4f1ea",
    "image": "#3d5a80",
    "screen": "#111111",
    "buttons": "#e07a5f",
    "pi": "#2d6a4f",
    "hat": "#222222",
    "reader": "#c1121f",
    "tag": "#f2a541",
    "port": "#555555",
    "cover": "#5c7fa3",
    "antenna": "#d4a017",
}


def _meshes(parts: dict):
    import trimesh

    OUT.mkdir(exist_ok=True)
    out = []
    for key, value in parts.items():
        for i, shape in enumerate(value if isinstance(value, list) else [value]):
            path = OUT / f"_tmp_{key}_{i}.stl"
            export_stl(shape, str(path))
            mesh = trimesh.load(path)
            path.unlink()
            # Small triangles so matplotlib's per-face depth sort doesn't let big
            # body faces paint over the parts sitting on them.
            v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge=4)
            out.append((trimesh.Trimesh(v, f), COLORS[key]))
    return out


def render(concepts: dict[str, dict], path: Path,
           views: list[tuple[float, float]] | None = None) -> None:
    """Render each concept in its own panel; views gives (elev, azim) per panel."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import to_rgb
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    light = np.array([-0.4, -0.6, 0.8])
    light /= np.linalg.norm(light)
    fig = plt.figure(figsize=(13, 6.5))
    for i, (title, parts) in enumerate(concepts.items(), start=1):
        ax = fig.add_subplot(1, len(concepts), i, projection="3d")
        # One collection for everything so faces are depth-sorted together;
        # separate collections let the body paint over parts sitting on it.
        tris, colors = [], []
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for mesh, color in _meshes(parts):
            shade = 0.45 + 0.55 * np.clip(mesh.face_normals @ light, 0, 1)
            tris.append(mesh.triangles)
            colors.extend(tuple(np.array(to_rgb(color)) * k) for k in shade)
            lo, hi = np.minimum(lo, mesh.bounds[0]), np.maximum(hi, mesh.bounds[1])
        faces = Poly3DCollection(np.concatenate(tris), facecolors=colors, edgecolors=colors,
                                 linewidths=0.3)
        ax.add_collection3d(faces)
        size = (hi - lo).max()
        mid = (hi + lo) / 2
        for setter, m in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), mid):
            setter(m - size / 2, m + size / 2)
        ax.set_box_aspect((1, 1, 1))
        elev, azim = views[i - 1] if views else (24, -58)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        dims = hi - lo
        ax.set_title(f"{title}\n{dims[0]:.0f} W × {dims[1]:.0f} D × {dims[2]:.0f} H mm", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=130, bbox_inches="tight", pad_inches=0.3)


if __name__ == "__main__":
    concepts = {"A — Tray (print lies on top)": tray(), "B — Easel (print stands up)": easel()}
    OUT.mkdir(exist_ok=True)
    for name, parts in zip(("tray", "easel"), concepts.values()):
        export_stl(parts["body"], str(OUT / f"{name}_body.stl"))
    render(concepts, OUT / "concepts.png")
    print(f"wrote {OUT / 'concepts.png'}")
