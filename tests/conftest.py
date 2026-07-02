"""
Mock Raspberry Pi hardware modules that are unavailable on development machines.
These are inserted into sys.modules before any test imports so that files like
renderer_oled.py (which do `import board` at the top level) can be imported
without error.
"""
import sys
from unittest.mock import MagicMock

for _mod in ["board", "digitalio", "busio", "adafruit_ssd1306"]:
    sys.modules.setdefault(_mod, MagicMock())
