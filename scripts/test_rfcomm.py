#!/usr/bin/env python3
"""Test RFCOMM connection to Instax Square Link on Pi Zero 2W.

Run from the repo root:
    .venv/bin/python scripts/test_rfcomm.py

What it does:
  1. BLE-scans for INSTAX-(IOS) address
  2. Derives the Classic BT ANDROID address (FA:AB:BC → 88:B4:36)
  3. Connects via RFCOMM socket on port 6
  4. Queries printer info (model, battery, film count)
  5. Sends a rainbow LED pattern (no film used)

Set INSTAX_BT_ADDRESS env var to skip the BLE scan and use a known address.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spotifactory.vendor.instax.instax_rfcomm import InstaxRFCOMM

print("==> Testing Instax RFCOMM connection")
instax = InstaxRFCOMM(print_enabled=False, quiet=False)
instax.connect(timeout=15)

if not instax.peripheral.is_connected():
    print("FAIL: could not connect to printer")
    print("  Make sure the Instax is powered on and close to the Pi.")
    print("  If address derivation fails, set INSTAX_BT_ADDRESS=88:B4:36:xx:xx:xx")
    sys.exit(1)

print(f"OK: connected")
print(f"   Model:      {instax.printerSettings.get('modelName') if instax.printerSettings else 'unknown'}")
print(f"   Image size: {instax.imageSize[0]}x{instax.imageSize[1]}")
print(f"   Battery:    {instax.batteryPercentage}%")
print(f"   Film left:  {instax.photosLeft}")

print("\n==> Sending rainbow LED pattern (no film used)...")
from spotifactory.vendor.instax import LedPatterns
instax.send_led_pattern(LedPatterns.rainbow, when=0)
print("OK: LED command sent")

instax.disconnect()
print("\nAll done!")
