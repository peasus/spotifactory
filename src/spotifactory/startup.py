"""Pi startup entrypoint.

Runs pre-flight checks with OLED feedback before handing off to the main loop:
  1. Network — if offline, launches Balena WiFi Connect captive portal
  2. Spotify auth — if no valid token, runs the PKCE relay auth flow
  3. Main app — starts the regular run_on_pi loop
"""
from __future__ import annotations

import socket
import subprocess
import sys


def _has_network(timeout: float = 3.0) -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except OSError:
        return False


def _has_valid_token() -> bool:
    try:
        from spotifactory.spotify import get_now_playing
        get_now_playing()
        return True
    except Exception:
        return False


def _show(display, line1: str, line2: str = "") -> None:
    display.clear()
    display.draw_text(2, 8, line1)
    if line2:
        display.draw_text(2, 28, line2)
    display.update()


def _show_auth_url(display, url: str) -> None:
    """Display a relay session URL split across OLED lines."""
    # Strip protocol: "spotifactory-auth.x.workers.dev/a1b2c3d4"
    short = url.replace("https://", "").replace("http://", "")
    slash = short.rfind("/")
    host = short[:slash] if slash >= 0 else short
    code = short[slash:] if slash >= 0 else ""

    display.clear()
    display.draw_text(2, 0, "Setup Spotify:")
    if len(host) <= 21:
        display.draw_text(2, 14, host)
        display.draw_text(2, 26, code)
    else:
        # Break host at a dot boundary that fits within 21 chars
        mid = host.rfind(".", 0, 22)
        if mid < 0:
            mid = 21
        display.draw_text(2, 14, host[:mid + 1])
        display.draw_text(2, 26, host[mid + 1:])
        display.draw_text(2, 38, code)
    display.update()


def _make_display():
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.display.sh1106 import DisplaySH1106
        return DisplaySH1106()
    from spotifactory.display.oled import DisplayOLED
    return DisplayOLED()


def _run_platform():
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.platforms.seengreat import main
    else:
        from spotifactory.platforms.pi import main
    main()


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    display = _make_display()

    # ------------------------------------------------------------------ WiFi
    if not _has_network():
        _show(display, "Connect to WiFi:", "Spotifactory")
        print("[startup] no network — launching WiFi Connect", flush=True)
        try:
            subprocess.run(
                ["wifi-connect", "--portal-ssid", "Spotifactory"],
                check=True,
            )
        except FileNotFoundError:
            print("[startup] wifi-connect not found — skipping", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[startup] wifi-connect exited {e.returncode}", flush=True)

        if not _has_network():
            _show(display, "No network", "Restarting...")
            print("[startup] still no network after WiFi Connect, exiting", flush=True)
            sys.exit(1)

    # ---------------------------------------------------------- Spotify auth
    if not _has_valid_token():
        print("[startup] no valid Spotify token — starting PKCE relay auth", flush=True)
        from spotifactory.auth_server import run_pkce_auth
        run_pkce_auth(on_session_ready=lambda url: _show_auth_url(display, url))

    # -------------------------------------------------------------- Main app
    _show(display, "Ready!")
    print("[startup] starting main app", flush=True)
    _run_platform()


if __name__ == "__main__":
    main()
