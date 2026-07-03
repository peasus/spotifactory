import RPi.GPIO as GPIO
from luma.core.interface.serial import spi
from luma.oled.device import sh1106
from PIL import Image, ImageDraw, ImageFont

from spotifactory.menu.scroll import ScrollTracker

WIDTH = 128
HEIGHT = 64

# SPI display pins (BCM) — matches SeenGreat 1.3" OLED HAT (A) hardware switch in SPI mode
_DC_PIN  = 25
_RST_PIN = 17


class DisplaySH1106:
    def __init__(self):
        serial = spi(
            device=0, port=0,
            bus_speed_hz=8_000_000, transfer_size=4096,
            gpio_DC=_DC_PIN, gpio_RST=_RST_PIN,
        )
        self.device = sh1106(serial, rotate=2)
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
        text_w = self._text_width(text)
        overflow = text_w - (WIDTH - x)
        if overflow <= 0:
            self._scroll.clear(key)
            return 0.0
        return self._scroll.offset(key, text, float(overflow))

    def _text_width(self, text: str) -> int:
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

    def update(self):
        self.device.display(self.image)
