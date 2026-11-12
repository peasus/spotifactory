"""The box's own audio receiver for the chosen music service.

Spotify mode runs Raspotify (librespot, a Spotify Connect receiver). Music
Assistant mode runs Squeezelite instead, so the box's Bluetooth speaker shows
up in Music Assistant as a player called "Spotifactory" and nothing on the box
talks to Spotify. Both are user services in the autologin session that also
runs PipeWire (deploy/setup.sh and deploy/upgrade.sh install them); only one
runs at a time, so they never play over each other.
"""
from __future__ import annotations

import subprocess
import sys

RASPOTIFY = "raspotify"
SQUEEZELITE = "squeezelite"


def _systemctl_user(*args: str) -> bool:
    if not sys.platform.startswith("linux"):
        print(f"[services] not on the Pi, skipping systemctl --user {' '.join(args)}", flush=True)
        return False
    try:
        result = subprocess.run(["systemctl", "--user", *args],
                                capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"[services] systemctl --user {' '.join(args)}: {e}", flush=True)
        return False
    if result.returncode != 0:
        print(f"[services] systemctl --user {' '.join(args)} failed: "
              f"{(result.stderr or result.stdout).strip()}", flush=True)
        return False
    return True


def apply(backend_name: str) -> None:
    """Run the receiver `backend_name` needs and stop the other one. Kept
    across reboots (enable/disable). Restarts Squeezelite so a new server
    address (MA_SERVER_HOST in .env) takes effect."""
    from spotifactory.backend import MUSIC_ASSISTANT
    _systemctl_user("daemon-reload")         # upgrade.sh may have just installed a unit
    if backend_name == MUSIC_ASSISTANT:
        _systemctl_user("disable", "--now", RASPOTIFY)
        _systemctl_user("enable", SQUEEZELITE)
        _systemctl_user("restart", SQUEEZELITE)
    else:
        _systemctl_user("disable", "--now", SQUEEZELITE)
        _systemctl_user("enable", "--now", RASPOTIFY)
