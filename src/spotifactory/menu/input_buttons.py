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

    def read(self):
        if not self.btn_up.value:
            return "Up"
        if not self.btn_down.value:
            return "Down"
        if not self.btn_left.value:
            return "Left"
        if not self.btn_right.value:
            return "Right"
        if not self.btn_select.value:
            return "Select"
        return None
