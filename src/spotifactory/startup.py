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


def _make_qr(url: str):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, box_size=2, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="white", back_color="black").get_image().convert("1")


def _show_auth_url(display, url: str) -> None:
    """Display a QR code + label for the PKCE relay session URL."""
    qr = _make_qr(url)
    display.clear()
    display.draw_image(0, 3, qr)
    x = qr.width + 4
    display.draw_text(x, 4, "Scan to")
    display.draw_text(x, 18, "connect")
    display.draw_text(x, 32, "Spotify")
    display.update()


def _make_display():
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.display.sh1106 import DisplaySH1106
        return DisplaySH1106()
    from spotifactory.display.oled import DisplayOLED
    return DisplayOLED()


def _run_platform(display):
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.platforms.seengreat import main
    else:
        from spotifactory.platforms.pi import main
    main(display=display)


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

    # ---------------------------------------------------------- Bluetooth
    import os as _os
    _mac = _os.environ.get("SPOTIFACTORY_SPEAKER_MAC", "").strip()
    if _mac:
        _show(display, "Connecting BT...", _mac[-8:])
        import threading as _threading
        def _reconnect_bt() -> None:
            try:
                from spotifactory.hardware.bluetooth import is_connected, reconnect
                if not is_connected(_mac):
                    reconnect(_mac)
            except Exception as e:
                print(f"[startup] BT reconnect: {e}", flush=True)
        _threading.Thread(target=_reconnect_bt, daemon=True).start()
        import time as _time
        _time.sleep(1.5)

    # -------------------------------------------------------------- Main app
    _show(display, "Ready!")
    print("[startup] starting main app", flush=True)
    _run_platform(display)


if __name__ == "__main__":
    main()
