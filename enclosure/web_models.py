"""Web-ready 3D models of the easel, dispenser and crate for the site's gallery.

Exports one coloured, assembled GLB per object (metres, Y up) for
<model-viewer> on spotifactory.com/gallery. The easel is shown closed up with
a print on it, the dispenser with a tag ready to pull, and the crate empty.

Run:  enclosure/.venv/bin/python enclosure/web_models.py [out_dir]
Writes site/models/{easel,dispenser,crate}.glb by default.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from build123d import Align, Box, Pos, Rot, export_stl

import crate as crate_mod
import dispenser as disp_mod
import easel

# Printed parts in putty: the real build's cream, darkened so the shading shows
# the shape on screen (true cream reads as a flat white blob). Black faceplate and caps.
BODY = "#b8ad96"
BLACK = "#141414"
INK = "#111111"
PAPER = "#f6f3ec"
COVER = "#3d5a80"


def _mesh(shape, colour: str, tolerance: float) -> trimesh.Trimesh:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "part.stl"
        export_stl(shape, str(path), tolerance=tolerance, angular_tolerance=0.3)
        mesh = trimesh.load(path, force="mesh")
    mesh.merge_vertices()
    # Smooth the fillets, keep the hard edges hard.
    mesh = trimesh.graph.smooth_shade(mesh, angle=np.radians(35))
    rgba = trimesh.visual.color.hex_to_rgba(colour) / 255.0
    # glTF base colours are linear; convert from sRGB so the hex values look right.
    rgba[:3] = np.where(rgba[:3] <= 0.04045, rgba[:3] / 12.92, ((rgba[:3] + 0.055) / 1.055) ** 2.4)
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=0.65))
    return mesh


def _scene(parts: list[tuple[object, str]], tolerance: float = 0.15) -> trimesh.Scene:
    scene = trimesh.Scene()
    for i, (shape, colour) in enumerate(parts):
        for j, s in enumerate(shape if isinstance(shape, list) else [shape]):
            scene.add_geometry(_mesh(s, colour, tolerance), node_name=f"part{i}_{j}")
    # build123d is Z-up in mm; glTF is Y-up in metres. Sit it on the floor, centred.
    turn = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
    scene.apply_transform(turn)
    lo, hi = scene.bounds
    centre = (lo + hi) / 2
    scene.apply_translation([-centre[0], -lo[1], -centre[2]])
    scene.apply_scale(0.001)
    return scene


def easel_parts():
    inside = easel.internals()
    return [
        (easel.body(), BODY),
        (easel.faceplate(), BLACK),
        (easel.baseplate(), BODY),
        (inside["screen"], INK),
        (easel.nub(), BLACK),
        ([*easel.button_caps()], BLACK),
        (inside["print"], PAPER),
        (inside["image"], COVER),
    ]


def dispenser_parts():
    """Lid on, with a short tail of backing paper sticking up out of the slit and
    a round tag on it, ready to pull."""
    from build123d import Cylinder
    d = disp_mod
    tl = d.IL + 2 * d.WALL
    slit_y = -tl / 2 + d.SLIT_FROM_FRONT + d.SLIT_GAP / 2
    top, tail = d.H + d.LID_T, 26.0
    paper = Pos(0, slit_y, top - 2) * Box(d.PAPER_W, 0.15, tail + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    tag = Pos(0, slit_y - 0.2, top + tail / 2 + 1) * Rot(90, 0, 0) * Cylinder(11, 0.25)
    return [
        (d.base(), BODY),
        (d.lid(), BODY),
        (paper, PAPER),
        (tag, "#cfc9ba"),
    ]


def crate_parts():
    return [(crate_mod.crate(), BODY)]


def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, parts in (("easel", easel_parts()), ("dispenser", dispenser_parts()),
                        ("crate", crate_parts())):
        path = out_dir / f"{name}.glb"
        _scene(parts).export(path)
        print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    default = Path(__file__).resolve().parent.parent / "site" / "models"
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else default)
