import board
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306

from spotifactory.menu.scroll import ScrollTracker


class DisplayOLED:
    def __init__(self):
        self.i2c = board.I2C()
        self.display = adafruit_ssd1306.SSD1306_I2C(128, 64, self.i2c)
        self.image = Image.new("1", (self.display.width, self.display.height))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.load_default()
        self._scroll = ScrollTracker()

    def clear(self):
        self.draw.rectangle(
            (0, 0, self.display.width, self.display.height), outline=0, fill=0
        )

    def draw_text(self, x, y, text, selected=False):
        key = (x, y)
        offset = self._scroll_offset(key, text, x)
        draw_x = x - int(offset)
        row_h = 10  # matches selection rect height

        if selected:
            self.draw.rectangle((0, y, self.display.width, y + row_h), fill=255)
            self.draw.text((draw_x, y), text, font=self.font, fill=0)
            if offset > 0 and x > 0:
                self.draw.rectangle((0, y, x - 1, y + row_h), fill=255)
        else:
            self.draw.text((draw_x, y), text, font=self.font, fill=255)
            if offset > 0 and x > 0:
                self.draw.rectangle((0, y, x - 1, y + row_h), fill=0)

    def _scroll_offset(self, key: tuple, text: str, x: int) -> float:
        text_w = self._text_width(text)
        overflow = text_w - (self.display.width - x)
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
        self.display.image(self.image)
        self.display.show()
