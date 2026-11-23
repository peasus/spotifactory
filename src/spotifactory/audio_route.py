"""Where the box's own audio goes: PipeWire, through its PulseAudio commands.

librespot plays to PipeWire's default sink. Normally that's the Bluetooth
speaker; for a Cast or AirPlay speaker (network_speakers.py) it's a sink
whose audio is streamed on to the speaker instead.
"""
from __future__ import annotations

import os
import subprocess
import sys


def pactl(*args: str) -> subprocess.CompletedProcess | None:
    if not sys.platform.startswith("linux"):
        print(f"[audio] not on the Pi, skipping pactl {' '.join(args)}", flush=True)
        return None
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[audio] pactl {' '.join(args)}: {e}", flush=True)
        return None


def sinks() -> list[str]:
    result = pactl("list", "short", "sinks")
    if result is None or result.returncode != 0:
        return []
    return [line.split()[1] for line in result.stdout.splitlines() if len(line.split()) > 1]


def ensure_sink(name: str, module: str, *args: str) -> bool:
    """Load `module` as sink `name` unless it's there. PipeWire forgets loaded
    modules when it restarts, so this is checked before each use."""
    if name in sinks():
        return True
    result = pactl("load-module", module, f"sink_name={name}", *args)
    if result is None or result.returncode != 0:
        print(f"[audio] couldn't add sink {name}: "
              f"{(result.stderr if result else '').strip()}", flush=True)
        return False
    return True


def route_to(sink: str) -> bool:
    """Make `sink` the default and move streams already playing onto it."""
    result = pactl("set-default-sink", sink)
    if result is None or result.returncode != 0:
        return False
    inputs = pactl("list", "short", "sink-inputs")
    for line in (inputs.stdout.splitlines() if inputs and inputs.returncode == 0 else []):
        parts = line.split()
        if parts:
            pactl("move-sink-input", parts[0], sink)
    return True


def local_sink(exclude: tuple[str, ...] = ()) -> str | None:
    """Where the audio goes without a network speaker: the paired Bluetooth
    speaker if it's there, else the first other sink."""
    mac = os.environ.get("SPOTIFACTORY_SPEAKER_MAC", "").strip()
    found = [s for s in sinks() if s not in exclude]
    if mac:
        bt = "bluez_output." + mac.replace(":", "_") + ".1"
        if bt in found:
            return bt
    return found[0] if found else None
