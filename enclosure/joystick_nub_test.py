"""Fit test for the printed joystick nub: the same nub with a range of socket
sizes, smallest on the left, lettered A, B, C... on top. Press each onto the stem (clear knob off): the
right one goes on with firm thumb pressure, all the way down onto the round
section, and doesn't pull off with the stick. Set NUB_SOCKET in easel.py to it.

Run:  enclosure/.venv/bin/python enclosure/joystick_nub_test.py
Writes out/print/joystick_nub_test.stl.
"""
from __future__ import annotations

from build123d import Pos, export_stl

import easel

SOCKETS = (2.47, 2.50, 2.53)          # square socket, mm; left to right (round 2: 2.55 loose, 2.45 too tight)
PITCH = 10.0

if __name__ == "__main__":
    lift = -easel.JOY_COLLAR_TOP                            # bottom on the bed
    letters = "ABCD"
    parts = [Pos((i - (len(SOCKETS) - 1) / 2) * PITCH, 0, lift) * easel._nub_local(s, label=letters[i])
             for i, s in enumerate(SOCKETS)]
    out = parts[0]
    for p in parts[1:]:
        out += p
    easel.PRINT_DIR.mkdir(parents=True, exist_ok=True)
    export_stl(out, str(easel.PRINT_DIR / "joystick_nub_test.stl"))
    print("sockets left to right:", ", ".join(f"{letters[i]} {s:.2f}" for i, s in enumerate(SOCKETS)))
