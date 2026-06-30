from dataclasses import dataclass
from io import BytesIO

from spotifactory.vendor.instax.instax_ble import InstaxBLE
from spotifactory.vendor.instax.Types import EventType
from spotifactory.vendor.instax import LedPatterns

CONNECT_TIMEOUT = 10  # seconds to scan before giving up


@dataclass
class PrintResult:
    printer_found: bool
    success: bool = False
    photos_left: int = 0
    error: str | None = None


class _TrackedInstaxBLE(InstaxBLE):
    """InstaxBLE subclass that records whether the printer confirmed the print."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.print_confirmed = False

    def parse_printer_response(self, event, packet):
        super().parse_printer_response(event, packet)
        if event == EventType.PRINT_IMAGE:
            self.print_confirmed = True


def print_image(image: str | BytesIO, dry_run: bool = False) -> PrintResult:
    """Connect to the nearest Instax Square Link and print an image.

    Args:
        image: path to an image file, or a BytesIO containing image bytes.
        dry_run: sends all data but skips the final print command (no film used).

    Returns:
        PrintResult with success state, photos remaining, and any error message.
    """
    instax = _TrackedInstaxBLE(print_enabled=not dry_run, quiet=True)
    try:
        instax.connect(timeout=CONNECT_TIMEOUT)

        if instax.peripheral is None or not instax.peripheral.is_connected():
            return PrintResult(printer_found=False, error="Printer not found")

        instax.send_led_pattern(LedPatterns.rainbow, when=1)
        instax.send_led_pattern(LedPatterns.pulseGreen, when=2)
        instax.print_image(image)
        instax.wait_one_minute()

        if instax.cancelled:
            return PrintResult(printer_found=True, success=False, error="Cancelled")

        success = dry_run or instax.print_confirmed
        return PrintResult(
            printer_found=True,
            success=success,
            photos_left=instax.photosLeft,
        )
    except Exception as e:
        return PrintResult(printer_found=True, success=False, error=str(e))
    finally:
        instax.disconnect()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m spotifactory.printer <image_path>")
        sys.exit(1)
    result = print_image(sys.argv[1])
    print(result)
