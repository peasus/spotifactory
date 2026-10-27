"""Spotify Connect commands for speakers the Web API won't control (Sonos).

Spotify marks some Connect speakers as restricted: the Web API refuses every
player command aimed at one. Spotify's own apps steer them through the
Connect state service instead, which a librespot session can call too. The
`spotifactory-connect` helper (connect-helper/, Rust) signs in with the login
Raspotify saved on the box and passes our commands on; this module builds
them and keeps one helper running so each command doesn't sign in again.

Unofficial: it's the route Spotify's apps use, not a published API.
"""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import threading
from pathlib import Path

_HELPER_ENV = "SPOTIFACTORY_CONNECT_HELPER"
_CACHE_ENV = "SPOTIFACTORY_LIBRESPOT_CACHE"   # Raspotify's --system-cache (deploy/setup.sh)
_FROM_ENV = "SPOTIFACTORY_CONNECT_FROM"       # send commands "from" this device id instead
_TIMEOUT_SECS = 15.0                          # signing in on a Pi Zero takes a few seconds

_REPO = Path(__file__).resolve().parents[2]


class ConnectError(Exception):
    pass


def helper_path() -> str | None:
    """The helper binary, or None if it isn't installed on this box."""
    candidates = [
        os.environ.get(_HELPER_ENV, ""),
        str(Path.home() / ".local/bin/spotifactory-connect"),
        str(_REPO / "connect-helper/target/release/spotifactory-connect"),
    ]
    for path in candidates:
        if path and os.access(path, os.X_OK):
            return path
    return None


def available() -> bool:
    return helper_path() is not None


class _Helper:
    """One long-running helper process: a JSON request per line, a JSON reply per line."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _start(self) -> subprocess.Popen:
        path = helper_path()
        if path is None:
            raise ConnectError("spotifactory-connect isn't installed")
        cache = os.environ.get(_CACHE_ENV) or str(Path.home() / ".cache/librespot")
        cmd = [path, "--cache", cache]
        if os.environ.get(_FROM_ENV):
            cmd += ["--from", os.environ[_FROM_ENV]]
        print(f"[connect] starting {' '.join(cmd)}", flush=True)
        return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, bufsize=1)

    def _stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def _readline(self, proc: subprocess.Popen) -> str:
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            if not sel.select(_TIMEOUT_SECS):
                raise ConnectError("helper didn't answer")
        finally:
            sel.close()
        line = proc.stdout.readline()
        if not line:
            raise ConnectError(f"helper stopped (exit {proc.poll()})")
        return line

    def request(self, payload: dict) -> None:
        with self._lock:
            for attempt in (1, 2):
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = self._start()
                proc = self._proc
                try:
                    proc.stdin.write(json.dumps(payload) + "\n")
                    proc.stdin.flush()
                    reply = json.loads(self._readline(proc))
                except (OSError, ValueError, ConnectError) as e:
                    # A dead or hung helper (or one whose sign-in failed and
                    # already said why) gets one fresh start.
                    self._stop()
                    if attempt == 2:
                        raise ConnectError(str(e)) from e
                    continue
                if not reply.get("ok"):
                    if proc.poll() is not None:    # sign-in failed: the reason, then exit
                        self._stop()
                    raise ConnectError(reply.get("error") or "helper refused")
                return


_helper = _Helper()


def _command(to: str, command: dict) -> None:
    print(f"[connect] {command.get('endpoint')} → {to}", flush=True)
    _helper.request({"op": "command", "to": to, "body": {"command": command}})


def play_body(uri: str) -> dict:
    """Start an album or playlist from its first track."""
    return {
        "endpoint": "play",
        "context": {"uri": uri, "url": f"context://{uri}", "metadata": {}},
        "play_origin": {"feature_identifier": "spotifactory"},
        "options": {"license": "on-demand", "skip_to": {}, "player_options_override": {}},
    }


def repeat_body(state: str) -> dict:
    """"off", "context" (the album or playlist) or "track", as in the Web API."""
    return {"endpoint": "set_options",
            "repeating_context": state != "off",
            "repeating_track": state == "track"}


def play(to: str, uri: str) -> None:
    _command(to, play_body(uri))


def resume(to: str) -> None:
    _command(to, {"endpoint": "resume"})


def pause(to: str) -> None:
    _command(to, {"endpoint": "pause"})


def next_track(to: str) -> None:
    _command(to, {"endpoint": "skip_next"})


def prev_track(to: str) -> None:
    _command(to, {"endpoint": "skip_prev"})


def seek(to: str, position_ms: int) -> None:
    _command(to, {"endpoint": "seek_to", "value": max(0, int(position_ms))})


def shuffle(to: str, active: bool) -> None:
    _command(to, {"endpoint": "set_shuffling_context", "value": bool(active)})


def repeat(to: str, state: str) -> None:
    _command(to, repeat_body(state))


def set_volume(to: str, percent: int) -> None:
    _helper.request({"op": "volume", "to": to, "percent": max(0, min(100, int(percent)))})


def transfer(to: str) -> None:
    print(f"[connect] transfer → {to}", flush=True)
    _helper.request({"op": "transfer", "to": to})
