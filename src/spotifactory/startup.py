"""Pi startup entrypoint.

Runs pre-flight checks with OLED feedback before handing off to the main loop:
  1. Network — if offline, the app opens on WiFi setup (the box's own
     "Spotifactory" hotspot, see tasks/wifi_setup), where Menu still works
  2. Main app — starts the regular run_on_pi loop. With no valid Spotify
     login, it opens on the Connect Spotify QR code; Menu leaves it for the
     main menu, so the box is usable before (or without) logging in.
"""
from __future__ import annotations

import time
from pathlib import Path

_BOOT_NETWORK_WAIT_SECS = 30.0  # saved WiFi can take a while to associate after boot
# 128x64 1-bit logo shown while the box boots, held at least this long.
_SPLASH_PATH = Path(__file__).resolve().parent / "display" / "splash.png"
_SPLASH_SECS = 2.0


def _has_network(timeout: float = 3.0) -> bool:
    from spotifactory.wifi import has_internet
    return has_internet(timeout)


def _wait_for_network(timeout: float = _BOOT_NETWORK_WAIT_SECS) -> bool:
    """Poll for connectivity so a slow WiFi join at boot doesn't trigger the captive portal."""
    deadline = time.monotonic() + timeout
    while True:
        if _has_network():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2.0)


def _has_valid_token() -> bool:
    from spotifactory import backend
    return backend.has_login()


def _show(display, line1: str, line2: str = "") -> None:
    display.clear()
    display.draw_text(2, 8, line1)
    if line2:
        display.draw_text(2, 28, line2)
    display.update()


def _show_splash(display) -> None:
    """Logo on the OLED while the network and Spotify checks run. Never blocks boot."""
    try:
        from PIL import Image
        with Image.open(_SPLASH_PATH) as img:
            splash = img.convert("1")
        display.clear()
        display.draw_image(0, 0, splash)
        display.update()
    except Exception as e:
        print(f"[startup] splash skipped: {e}", flush=True)


def _make_display():
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.display.sh1106 import DisplaySH1106
        return DisplaySH1106()
    from spotifactory.display.oled import DisplayOLED
    return DisplayOLED()


def _run_platform(display, first_task_class=None):
    import os
    platform = os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat")
    if platform == "seengreat":
        from spotifactory.platforms.seengreat import main
    else:
        from spotifactory.platforms.pi import main
    main(display=display, first_task_class=first_task_class)


def _network_speaker_chosen() -> bool:
    from spotifactory import network_speakers
    return network_speakers.chosen() is not None


def _bt_reconnect_loop(mac: str) -> None:
    """Background daemon thread: reconnect paired BT speaker whenever it's not connected.

    Runs for the lifetime of the app. Checks every 30 s and reconnects if needed,
    so the speaker can be turned on any time after Spotifactory starts.

    Audio is (re)routed whenever the speaker is connected but not yet routed —
    whether we reconnected it or BlueZ auto-reconnected it — and retried on the
    next pass if PipeWire wasn't reachable yet (e.g. early in boot).
    """
    from spotifactory.hardware.bluetooth import (
        is_connected,
        move_sink_inputs,
        reconnect,
        set_bt_audio_output,
    )

    routed = False
    while True:
        try:
            connected = is_connected(mac)
            if not connected:
                print(f"[startup] BT speaker not connected — reconnecting {mac[-8:]}", flush=True)
                reconnect(mac)
                connected = is_connected(mac)
            if not connected:
                routed = False
            elif not routed and _network_speaker_chosen():
                pass    # a Cast/AirPlay speaker has the audio (network_speakers.py)
            elif not routed:
                print("[startup] BT speaker connected — redirecting audio", flush=True)
                routed = set_bt_audio_output(mac)
                if routed:
                    move_sink_inputs(mac)
        except Exception as e:
            print(f"[startup] BT retry: {e}", flush=True)
        time.sleep(30)


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    display = _make_display()
    _show_splash(display)
    splash_until = time.monotonic() + _SPLASH_SECS

    # ------------------------------------------------------------------ WiFi
    online = _wait_for_network()
    time.sleep(max(0.0, splash_until - time.monotonic()))
    if not online:
        print("[startup] no network — opening WiFi setup", flush=True)

    # ---------------------------------------------------------- Login
    # No working login: the app opens on the Connect Spotify QR code instead of
    # waiting here, so Menu still works (Reboot, Pair Device, and later the
    # choice of music service).
    # Music Assistant mode never needs a Spotify login.
    from spotifactory import backend, services
    services.apply(backend.name())     # Raspotify or Squeezelite, as the setting says
    first_task_class = None
    if not online:
        from spotifactory.tasks.wifi_setup import WifiSetupTask
        first_task_class = WifiSetupTask    # then the Spotify login, if needed
    elif backend.is_music_assistant():
        if not backend.has_login():
            print("[startup] Music Assistant not reachable", flush=True)
            _show(display, "Music Assistant", "not reachable")
            time.sleep(2.0)
    elif not _has_valid_token():
        print("[startup] no valid Spotify token — opening Connect Spotify", flush=True)
        from spotifactory.tasks.reauth import FirstBootLoginTask
        first_task_class = FirstBootLoginTask

    # ---------------------------------------------------------- Bluetooth
    import os as _os
    _mac = _os.environ.get("SPOTIFACTORY_SPEAKER_MAC", "").strip()
    if _mac:
        _show(display, "Connecting BT...", _mac[-8:])
        import threading as _threading
        _threading.Thread(target=_bt_reconnect_loop, args=(_mac,), daemon=True).start()
        time.sleep(1.5)

    # ------------------------------------------- Cast / AirPlay speaker
    if online and not backend.is_music_assistant() and _network_speaker_chosen():
        import threading as _threading

        from spotifactory import network_speakers
        _threading.Thread(target=network_speakers.reselect, daemon=True).start()

    # -------------------------------------------------------------- Main app
    _show(display, "Ready!")
    print("[startup] starting main app", flush=True)
    _run_platform(display, first_task_class)


if __name__ == "__main__":
    main()
