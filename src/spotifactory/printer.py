from spotifactory.vendor.instax.instax_ble import InstaxBLE
from spotifactory.vendor.instax import LedPatterns


def print_image(image_path: str) -> None:
    """Connect to the nearest Instax Square Link and print an image."""
    instax = InstaxBLE(print_enabled=True, quiet=False)
    try:
        instax.connect()
        instax.send_led_pattern(LedPatterns.rainbow, when=1)
        instax.send_led_pattern(LedPatterns.pulseGreen, when=2)
        instax.print_image(image_path)
        instax.wait_one_minute()
    finally:
        instax.disconnect()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m spotifactory.printer <image_path>")
        sys.exit(1)
    print_image(sys.argv[1])
