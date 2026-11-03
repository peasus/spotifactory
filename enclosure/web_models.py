"""Web-ready 3D models of the easel, dispenser and crate for the site's gallery.

Exports one coloured, assembled GLB per object (metres, Y up) for
<model-viewer> on spotifactory.com/gallery. The easel is shown closed up with
a print on it; the dispenser with its roll; the crate with some prints in it.

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

# Colours of the real build: cream PLA, black faceplate and caps.
CREAM = "#e6e0d0"
BLACK = "#141414"
AVOCADO = "#a9c23f"
INK = "#111111"
PAPER = "#f6f3ec"
COVERS = ["#3d5a80", "#e07a5f", "#a9c23f", "#2b2b2b", "#f2a541", "#8d5b9c", "#2d6a4f", "#c1121f"]


def _mesh(shape, colour: str, tolerance: float) -> trimesh.Trimesh:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "part.stl"
        export_stl(shape, str(path), tolerance=tolerance, angular_tolerance=0.3)
        mesh = trimesh.load(path, force="mesh")
    mesh.merge_vertices()
    # Smooth the fillets, keep the hard edges hard.
    mesh = trimesh.graph.smooth_shade(mesh, angle=np.radians(35))
    rgba = trimesh.visual.color.hex_to_rgba(colour)
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
        (easel.body(), CREAM),
        (easel.faceplate(), BLACK),
        (easel.baseplate(), CREAM),
        (inside["screen"], INK),
        (easel.nub(), BLACK),
        ([*easel.button_caps()], BLACK),
        (inside["print"], PAPER),
        (inside["image"], COVERS[0]),
    ]


def dispenser_parts():
    paper, sticker = disp_mod.roll_and_paper()
    return [
        (disp_mod.base(), CREAM),
        (disp_mod.lid(), CREAM),
        (paper[1:], PAPER),
        (sticker, PAPER),
    ]


def _crate_cover(i: int):
    """The album art on the front of the print in slot i (Instax Square: 62 mm image, 6 mm top border)."""
    c = crate_mod
    y, _ = c._fin_frame(i)(c.FIN_T + (c.SLOT_W - c.PRINT_T) / 2, 0)
    return Pos(0, y, c.FLOOR + 0.2) * Rot(-c.FIN_LEAN, 0, 0) * Pos(0, -0.25, c.PRINT_H - 6 - 62) * Box(
        62, 0.2, 62, align=(Align.CENTER, Align.MIN, Align.MIN))


def crate_parts(shown: int = 14):
    parts = [(crate_mod.crate(), CREAM), (crate_mod.prints()[:shown], PAPER)]
    for i in range(shown):
        parts.append((_crate_cover(i), COVERS[i % len(COVERS)]))
    return parts


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
