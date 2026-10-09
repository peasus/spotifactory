# input_buttons.py

import board
import digitalio
import time

class ButtonInput:
    def __init__(self):
        # Configure buttons
        self.btn_up = digitalio.DigitalInOut(board.D5)
        self.btn_up.switch_to_input(pull=digitalio.Pull.UP)

        self.btn_down = digitalio.DigitalInOut(board.D6)
        self.btn_down.switch_to_input(pull=digitalio.Pull.UP)

        self.btn_left = digitalio.DigitalInOut(board.D16)
        self.btn_left.switch_to_input(pull=digitalio.Pull.UP)

        self.btn_right = digitalio.DigitalInOut(board.D20)
        self.btn_right.switch_to_input(pull=digitalio.Pull.UP)

        self.btn_select = digitalio.DigitalInOut(board.D21)
        self.btn_select.switch_to_input(pull=digitalio.Pull.UP)
        self._held = None

    def read(self):
        """Return an action once per press; None while it's held or nothing is pressed."""
        pressed = None
        if not self.btn_up.value:
            pressed = "Up"
        elif not self.btn_down.value:
            pressed = "Down"
        elif not self.btn_left.value:
            pressed = "Left"
        elif not self.btn_right.value:
            pressed = "Right"
        elif not self.btn_select.value:
            pressed = "Select"
        if pressed == self._held:
            return None
        self._held = pressed
        return pressed
