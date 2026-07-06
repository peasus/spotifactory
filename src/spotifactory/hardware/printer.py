from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

from spotifactory.vendor.instax.instax_ble import InstaxBLE
from spotifactory.vendor.instax.Types import EventType
from spotifactory.vendor.instax import LedPatterns

CONNECT_TIMEOUT = 10   # seconds to scan for the printer before giving up
PRINT_TIMEOUT   = 90   # seconds to wait for print confirmation after upload


@dataclass
class PrintResult:
    printer_found: bool
    success: bool = False
    photos_left: int = 0
    error: str | None = None


class _TrackedInstaxBLE(InstaxBLE):
    """InstaxBLE subclass that tracks upload progress and print confirmation."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.print_confirmed = False
        self._total_packets = 0

    def print_image(self, imgSrc):
        super().print_image(imgSrc)
        # After super(), the first packet has already been popped and sent.
        # Total = remaining + 1 (already sent).
        self._total_packets = len(self.packetsForPrinting) + 1

    @property
    def upload_progress(self) -> float:
        """0.0–1.0 fraction of image packets sent to the printer."""
        if self._total_packets == 0:
            return 0.0
        remaining = len(self.packetsForPrinting)
        return min(1.0, (self._total_packets - remaining) / self._total_packets)

    @property
    def upload_complete(self) -> bool:
        return self._total_packets > 0 and len(self.packetsForPrinting) == 0

    def parse_printer_response(self, event, packet):
        super().parse_printer_response(event, packet)
        if event == EventType.PRINT_IMAGE:
            self.print_confirmed = True


def _make_instax(print_enabled: bool, quiet: bool):
    if sys.platform == "linux":
        from spotifactory.vendor.instax.instax_rfcomm import InstaxRFCOMM
        return InstaxRFCOMM(print_enabled=print_enabled, quiet=quiet)
    return _TrackedInstaxBLE(print_enabled=print_enabled, quiet=quiet)


def print_image(
    image: str | BytesIO,
    dry_run: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> PrintResult:
    """Connect to the nearest Instax Square Link and print an image.

    Args:
        image:       path to an image file, or a BytesIO of image bytes.
        dry_run:     send all data but skip the final print command (no film used).
        on_progress: optional callback called with a human-readable status string
                     as the job progresses (e.g. "Uploading 42%" / "Printing...").

    Returns:
        PrintResult with success state, photos remaining, and any error message.
    """
    def _report(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    instax = _make_instax(print_enabled=not dry_run, quiet=True)
    try:
        _report("Connecting...")
        instax.connect(timeout=CONNECT_TIMEOUT)

        if not instax.peripheral.is_connected():
            return PrintResult(printer_found=False, error="Printer not found")

        if instax.photosLeft == 0 and not dry_run:
            return PrintResult(
                printer_found=True,
                success=False,
                photos_left=0,
                error="No film left",
            )

        instax.send_led_pattern(LedPatterns.rainbow, when=1)
        instax.send_led_pattern(LedPatterns.pulseGreen, when=2)
        instax.print_image(image)

        # Phase 1 — upload: poll until all packets have been acknowledged.
        deadline = time.monotonic() + PRINT_TIMEOUT
        while time.monotonic() < deadline and not instax.upload_complete:
            if instax.cancelled:
                break
            pct = int(instax.upload_progress * 100)
            _report(f"Uploading {pct}%")
            time.sleep(0.25)

        if instax.cancelled:
            return PrintResult(printer_found=True, success=False, error="Cancelled")

        # Phase 2 — printing: wait for the printer's physical confirmation.
        _report("Printing...")
        deadline = time.monotonic() + PRINT_TIMEOUT
        while time.monotonic() < deadline:
            if instax.print_confirmed or instax.cancelled:
                break
            time.sleep(0.5)

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
        print("Usage: python -m spotifactory.hardware.printer <image_path>")
        sys.exit(1)
    result = print_image(sys.argv[1])
    print(result)
