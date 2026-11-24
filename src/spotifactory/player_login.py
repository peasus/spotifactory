"""Sign the box's own player (Raspotify / librespot) in to Spotify with a
pairing code, so it plays without a phone ever finding it on the wifi.

librespot normally only gets a login when someone picks it in a Spotify app
on the same network (zeroconf). Networks that keep multicast to one radio band
(mesh routers, a 2.4 GHz-only Pi) hide the box from the phone, so that never
happens and nothing can play. librespot 0.7+ can pair instead:

    librespot --enable-device-auth ...
      Browse to: https://spotify.com/pair?code=TV2URE
      If prompted, enter code: TV2URE
      ... Authenticated as 'user'

It saves a reusable login in the cache folder Raspotify already uses
(deploy/setup.sh: --system-cache ~/.cache/librespot), so Raspotify signs in by
itself on every start from then on. Guests can still pick the box over
zeroconf as before.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

from spotifactory import services

LIBRESPOT = "/usr/bin/librespot"
CACHE_DIR = "~/.cache/librespot"          # Raspotify's --system-cache (deploy/setup.sh)
CODE_SECS = 300.0                         # Spotify's codes last a few minutes

_URL = re.compile(r"(https://\S*spotify\.com/pair\S*)")
_CODE = re.compile(r"code[=:]\s*([A-Za-z0-9]{4,12})")
_DONE = re.compile(r"Authenticated as")


def _cache() -> str:
    return os.path.expanduser(CACHE_DIR)


def _binary() -> str | None:
    return LIBRESPOT if os.path.exists(LIBRESPOT) else shutil.which("librespot")


def has_login() -> bool:
    """librespot has a saved login of its own."""
    return os.path.exists(os.path.join(_cache(), "credentials.json"))


def can_pair() -> bool:
    """This box's librespot knows the pairing-code sign in."""
    binary = _binary()
    if not binary:
        return False
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return "enable-device-auth" in (out.stdout + out.stderr)


def needs_pairing() -> bool:
    return not has_login() and can_pair()


def pair(on_code: Callable[[str, str], None], cancelled: Callable[[], bool],
         timeout: float = 600.0) -> bool:
    """Run librespot's pairing until someone approves the code, `cancelled()`
    turns true, or `timeout` passes. on_code(url, code) is called with each
    new code (a fresh one when the last expires). True once signed in; the
    box's player is restarted then, so it picks up the saved login."""
    binary = _binary()
    if not binary:
        return False
    os.makedirs(_cache(), exist_ok=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cancelled():
        if _pair_once(binary, on_code, cancelled, min(CODE_SECS, deadline - time.monotonic())):
            services.restart_raspotify()
            return True
    return False


def _pair_once(binary: str, on_code, cancelled, secs: float) -> bool:
    # Its own name, no discovery and no audio: the box's real player keeps
    # running meanwhile, and only the login lands in the shared cache folder.
    proc = subprocess.Popen(
        [binary, "--enable-device-auth", "--disable-discovery",
         "--name", "Spotifactory setup", "--system-cache", _cache(),
         "--disable-audio-cache", "--backend", "pipe", "--device", "/dev/null"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    state = {"url": "", "done": False}

    def read() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            m = _URL.search(line)
            if m and m.group(1) != state["url"]:
                state["url"] = m.group(1)
                code = _CODE.search(state["url"]) or _CODE.search(line)
                print(f"[player-login] pairing code at {state['url']}", flush=True)
                on_code(state["url"], code.group(1).upper() if code else "")
            if _DONE.search(line):
                state["done"] = True
                return
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    end = time.monotonic() + secs
    try:
        while time.monotonic() < end and not cancelled() and not state["done"]:
            if proc.poll() is not None and not reader.is_alive():
                break
            time.sleep(0.25)
        if state["done"]:
            time.sleep(1.0)                 # let it finish writing credentials.json
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    ok = state["done"] and has_login()
    print(f"[player-login] {'signed in' if ok else 'not signed in'}", flush=True)
    return ok
