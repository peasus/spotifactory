"""Pi startup entrypoint.

Runs pre-flight checks with OLED feedback before handing off to the main loop:
  1. Network — if offline, launches Balena WiFi Connect captive portal
  2. Spotify auth — if no valid token, runs the OAuth callback server
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


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    from spotifactory.menu.renderer_oled import DisplayOLED
    display = DisplayOLED()

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
        _show(display, "Connect Spotify:", "spotifactory", )
        # Second line intentionally short — third line shows port
        display.draw_text(2, 44, ".local:8080")
        display.update()
        print("[startup] no valid Spotify token — starting auth server", flush=True)
        from spotifactory.auth_server import run_auth_server
        run_auth_server()

    # -------------------------------------------------------------- Main app
    _show(display, "Ready!")
    print("[startup] starting main app", flush=True)
    from spotifactory.menu.run_on_pi import main as run_pi
    run_pi()


if __name__ == "__main__":
    main()
