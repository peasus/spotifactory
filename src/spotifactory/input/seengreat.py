import RPi.GPIO as GPIO

# BCM pin assignments for SeenGreat 1.3" OLED HAT (A)
# Joystick
_UP     = 6
_DOWN   = 19
_LEFT   = 5
_RIGHT  = 26
_SELECT = 13
# Buttons — K1 wired to Back, K2/K3 unused by default
_K1 = 21
_K2 = 20
_K3 = 16

_MAPPING = [
    (_UP,     "Up"),
    (_DOWN,   "Down"),
    (_LEFT,   "Left"),
    (_RIGHT,  "Right"),
    (_SELECT, "Select"),
    (_K1,     "Back"),
]


class SeenGreatInput:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        for pin, _ in _MAPPING:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def read(self):
        for pin, action in _MAPPING:
            if not GPIO.input(pin):  # active-low
                return action
        return None

    def cleanup(self):
        GPIO.cleanup()
