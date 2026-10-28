"""Boot logo, drawn early in boot by spotifactory-splash.service.

The app itself can't start until the network is up, which is half a minute
after the OLED's I2C bus is. This runs as soon as the bus exists, draws the
logo and exits, leaving it on screen; the app redraws it when it takes over.
Kept to the display's own imports so it starts quickly.
"""
from __future__ import annotations

import os
import time

_I2C_DEV = "/dev/i2c-1"
_I2C_WAIT_SECS = 10.0


def main() -> None:
    if os.environ.get("SPOTIFACTORY_PLATFORM", "seengreat") != "seengreat":
        return
    deadline = time.monotonic() + _I2C_WAIT_SECS
    while not os.path.exists(_I2C_DEV):
        if time.monotonic() >= deadline:
            print(f"[splash] {_I2C_DEV} never appeared, skipping", flush=True)
            return
        time.sleep(0.1)

    from spotifactory.display.sh1106 import DisplaySH1106
    from spotifactory.startup import _show_splash

    display = DisplaySH1106()
    display.device.persist = True    # keep the logo on screen after we exit
    _show_splash(display)


if __name__ == "__main__":
    main()
