import time

import RPi.GPIO as GPIO

# BCM pin assignments for SeenGreat 1.3" OLED HAT (A)
# Joystick
_UP     = 19
_DOWN   = 13
_LEFT   = 26
_RIGHT  = 6
_SELECT = 5
# Buttons beside the screen, top to bottom
_K1 = 21
_K2 = 20
_K3 = 16

_MAPPING = [
    (_UP,     "Up"),
    (_DOWN,   "Down"),
    (_LEFT,   "Left"),
    (_RIGHT,  "Right"),
    (_SELECT, "Select"),
    (_K1,     "VolUp"),
    (_K2,     "VolDown"),
    (_K3,     "PlayPause"),
]

# Held down, these repeat: after _REPEAT_DELAY, every _REPEAT_EVERY.
_REPEATS = {"VolUp", "VolDown"}
_REPEAT_DELAY = 0.5
_REPEAT_EVERY = 0.15


class SeenGreatInput:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        for pin, _ in _MAPPING:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._held = None
        self._held_since = 0.0
        self._last_fired = 0.0

    def read(self):
        """Return an action once per press (volume buttons repeat while held);
        None otherwise."""
        pressed = None
        for pin, action in _MAPPING:
            if not GPIO.input(pin):  # active-low
                pressed = action
                break
        now = time.monotonic()
        if pressed != self._held:
            self._held = pressed
            self._held_since = self._last_fired = now
            return pressed
        if (pressed in _REPEATS and now - self._held_since >= _REPEAT_DELAY
                and now - self._last_fired >= _REPEAT_EVERY):
            self._last_fired = now
            return pressed
        return None

    def cleanup(self):
        GPIO.cleanup()
