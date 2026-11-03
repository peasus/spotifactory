from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Callable

from PIL import Image

from spotifactory.vendor.instax.instax_ble import InstaxBLE
from spotifactory.vendor.instax.Types import EventType
from spotifactory.vendor.instax import LedPatterns

CONNECT_TIMEOUT = 10   # seconds to scan for the printer before giving up
PRINT_TIMEOUT   = 90   # seconds to wait for print confirmation after upload

# What the art is padded with when it doesn't fill the film (square art on a
# Mini or Wide print): white, so it reads as a wider version of the film's own
# white border rather than as black bars.
FILL = (255, 255, 255)

# Largest JPEG each film size takes, in KB. Mini Link 3s stall on anything over
# about 55 KB (javl/InstaxBLE#21, #24); a 600x800 JPEG still looks fine at that.
MAX_KB = {(600, 800): 55}
DEFAULT_MAX_KB = 105

# Set to 1 for printers that print upside down (reported for the Mini Link 3).
FLIP_SETTING = "INSTAX_PRINT_UPSIDE_DOWN"


@dataclass
class PrintResult:
    printer_found: bool
    success: bool = False
    photos_left: int = 0
    battery_pct: int | None = None
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


def fit_to_film(image: str | BytesIO | Image.Image, size: tuple[int, int],
                upside_down: bool = False) -> Image.Image:
    """`image` scaled to fit inside a print of `size` (w, h) without stretching
    or cropping, centred, with FILL around it: square art on a 600x800 Mini
    print gets bands top and bottom, on a 1260x840 Wide print bands either side,
    and on an 800x800 Square print fills it."""
    if isinstance(image, Image.Image):
        art = image
    else:
        if isinstance(image, BytesIO):
            image.seek(0)
        art = Image.open(image)
    art = art.convert("RGB")
    w, h = size
    scale = min(w / art.width, h / art.height)
    fit = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
    film = Image.new("RGB", size, FILL)
    film.paste(art.resize(fit, Image.Resampling.LANCZOS), ((w - fit[0]) // 2, (h - fit[1]) // 2))
    return film.rotate(180) if upside_down else film


def _prepare(instax, image: str | BytesIO) -> BytesIO:
    """The art laid out for the connected printer's film, as lossless PNG bytes
    (the printer code makes the one JPEG it sends from them)."""
    size = tuple(instax.imageSize)
    instax.maxImageKb = MAX_KB.get(size, DEFAULT_MAX_KB)
    flip = os.environ.get(FLIP_SETTING, "").strip().lower() in ("1", "true", "yes")
    out = BytesIO()
    fit_to_film(image, size, upside_down=flip).save(out, "PNG")
    out.seek(0)
    return out


def _make_instax(print_enabled: bool, quiet: bool):
    if sys.platform == "linux":
        from spotifactory.vendor.instax.instax_rfcomm import InstaxRFCOMM
        return InstaxRFCOMM(print_enabled=print_enabled, quiet=quiet)
    return _TrackedInstaxBLE(print_enabled=print_enabled, quiet=quiet)


@dataclass
class PrinterStatus:
    printer_found: bool
    photos_left: int = 0
    battery_pct: int | None = None
    charging: bool = False
    error: str | None = None


def _connect(instax) -> None:
    if sys.platform == "linux":
        # The printer asks to confirm a passkey on every RFCOMM connect.
        from spotifactory.hardware.bluetooth import auto_accept_agent
        with auto_accept_agent():
            instax.connect(timeout=CONNECT_TIMEOUT)
    else:
        instax.connect(timeout=CONNECT_TIMEOUT)


def get_status() -> PrinterStatus:
    """Connect to the printer just long enough to read its film count and battery."""
    instax = _make_instax(print_enabled=False, quiet=True)
    try:
        _connect(instax)
        if not instax.peripheral.is_connected():
            return PrinterStatus(printer_found=False, error="Printer not found")
        batt = instax.batteryPercentage
        return PrinterStatus(
            printer_found=True,
            photos_left=instax.photosLeft,
            battery_pct=batt if batt > 0 else None,
            charging=bool(instax.isCharging),
        )
    except Exception as e:
        return PrinterStatus(printer_found=True, error=str(e))
    finally:
        instax.disconnect()


def print_image(
    image: str | BytesIO,
    dry_run: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> PrintResult:
    """Connect to the nearest Instax Link printer (Mini, Square or Wide) and
    print an image, fitted to that printer's film without stretching.

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
        _connect(instax)

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
        instax.print_image(_prepare(instax, image))

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
        batt = instax.batteryPercentage
        return PrintResult(
            printer_found=True,
            success=success,
            photos_left=instax.photosLeft,
            battery_pct=batt if batt > 0 else None,
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
