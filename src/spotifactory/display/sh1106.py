from __future__ import annotations

import os

from luma.core.error import DeviceNotFoundError
from luma.core.interface.serial import i2c, spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

from spotifactory.display.scroll import ScrollTracker

WIDTH = 128
HEIGHT = 64

# I2C — SeenGreat 1.3" OLED HAT (A) with SW1=0, SW2=0 (I2C mode)
_I2C_ADDRESS = 0x3C
# SPI — Waveshare 1.3inch OLED HAT as shipped: CE0, DC on BCM 24, RST on 25
_SPI_DC, _SPI_RST = 24, 25


def _open_device(hat: str):
    """The screen over I2C, or for the Waveshare HAT over SPI if nothing answers on I2C.

    The SeenGreat HAT is set to I2C. The Waveshare one ships set to SPI and
    talks I2C only after moving resistors on its back, so it tries both. (SPI
    writes can't fail, so the SeenGreat doesn't fall back: a missing screen
    should stop the app, not blank it.)"""
    try:
        return sh1106(i2c(port=1, address=_I2C_ADDRESS), rotate=2)
    except (DeviceNotFoundError, OSError):
        if hat != "waveshare":
            raise
        return sh1106(spi(port=0, device=0, gpio_DC=_SPI_DC, gpio_RST=_SPI_RST), rotate=2)


class DisplaySH1106:
    def __init__(self, hat: str | None = None):
        self.device = _open_device(hat or os.environ.get("SPOTIFACTORY_HAT", "seengreat"))
        self.image = Image.new("1", (WIDTH, HEIGHT))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.load_default()
        self._scroll = ScrollTracker()

    def clear(self):
        self.draw.rectangle((0, 0, WIDTH, HEIGHT), outline=0, fill=0)

    def draw_text(self, x, y, text, selected=False):
        key = (x, y)
        offset = self._scroll_offset(key, text, x)
        draw_x = x - int(offset)
        row_h = 10

        if selected:
            self.draw.rectangle((0, y, WIDTH, y + row_h), fill=255)
            self.draw.text((draw_x, y), text, font=self.font, fill=0)
            if offset > 0 and x > 0:
                self.draw.rectangle((0, y, x - 1, y + row_h), fill=255)
        else:
            self.draw.text((draw_x, y), text, font=self.font, fill=255)
            if offset > 0 and x > 0:
                self.draw.rectangle((0, y, x - 1, y + row_h), fill=0)

    def _scroll_offset(self, key: tuple, text: str, x: int) -> float:
        text_w = self.text_width(text)
        overflow = text_w - (WIDTH - x)
        if overflow <= 0:
            self._scroll.clear(key)
            return 0.0
        return self._scroll.offset(key, text, float(overflow))

    def text_width(self, text: str) -> int:
        """How many pixels wide `text` draws."""
        try:
            bbox = self.draw.textbbox((0, 0), text, font=self.font)
            return bbox[2] - bbox[0]
        except AttributeError:
            return self.font.getsize(text)[0]  # Pillow < 9.2

    def draw_image(self, x: int, y: int, image) -> None:
        self.image.paste(image.convert("1"), (x, y))

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, width: float = 1) -> None:
        self.draw.line([(x1, y1), (x2, y2)], fill=255, width=round(width))

    def draw_circle(self, cx: int, cy: int, r: int) -> None:
        self.draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=255)

    def draw_rect(self, x1: int, y1: int, x2: int, y2: int, on: bool = True) -> None:
        """Filled rectangle, corners inclusive; on=False draws black."""
        self.draw.rectangle((x1, y1, x2, y2), fill=255 if on else 0)

    def update(self):
        self.device.display(self.image)
