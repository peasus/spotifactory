import time

import RPi.GPIO as GPIO

# BCM pin assignments for SeenGreat 1.3" OLED HAT (A)
# Joystick
_UP     = 19
_DOWN   = 13
_LEFT   = 26
_RIGHT  = 6
_SELECT = 5
# Buttons beside the screen. With the box upright, K3's pin is the top button
# and K1's the bottom (checked on the hardware).
_K1 = 21
_K2 = 20
_K3 = 16

_MAPPING = [
    (_UP,     "Up"),
    (_DOWN,   "Down"),
    (_LEFT,   "Left"),
    (_RIGHT,  "Right"),
    (_SELECT, "Select"),
    (_K3,     "VolUp"),       # top
    (_K2,     "VolDown"),
    (_K1,     "Menu"),        # bottom
]

# Held down, these repeat: after _REPEAT_DELAY, every _REPEAT_EVERY.
_REPEATS = {"VolUp", "VolDown"}
_REPEAT_DELAY = 0.5
_REPEAT_EVERY = 0.15
# Held down, these send "<name>Hold" after _REPEAT_DELAY, every _HOLD_EVERY,
# and "<name>Release" when let go: tap to skip, hold to seek.
_HOLDS = {"Left", "Right"}
_HOLD_EVERY = 0.2


class SeenGreatInput:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        for pin, _ in _MAPPING:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._held = None
        self._held_since = 0.0
        self._last_fired = 0.0
        self._queued = None          # a press that came with another button's release

    def read(self):
        """Return an action once per press (volume buttons repeat while held;
        left/right report holds and their release); None otherwise."""
        if self._queued:
            action, self._queued = self._queued, None
            return action
        pressed = None
        for pin, action in _MAPPING:
            if not GPIO.input(pin):  # active-low
                pressed = action
                break
        now = time.monotonic()
        if pressed != self._held:
            released, self._held = self._held, pressed
            self._held_since = self._last_fired = now
            if released in _HOLDS:
                self._queued = pressed
                return f"{released}Release"
            return pressed
        if pressed in _REPEATS or pressed in _HOLDS:
            every = _REPEAT_EVERY if pressed in _REPEATS else _HOLD_EVERY
            if now - self._held_since >= _REPEAT_DELAY and now - self._last_fired >= every:
                self._last_fired = now
                return pressed if pressed in _REPEATS else f"{pressed}Hold"
        return None

    def cleanup(self):
        GPIO.cleanup()
