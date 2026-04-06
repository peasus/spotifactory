# renderer_oled.py

import board
import digitalio
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306

class DisplayOLED:
    def __init__(self):
        # I2C connection
        self.i2c = board.I2C()
        self.display = adafruit_ssd1306.SSD1306_I2C(128, 64, self.i2c)

        self.image = Image.new("1", (self.display.width, self.display.height))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.load_default()

    def clear(self):
        self.draw.rectangle((0, 0, self.display.width, self.display.height), outline=0, fill=0)

    def draw_text(self, x, y, text, selected=False):
        if selected:
            self.draw.rectangle((0, y, self.display.width, y + 10), outline=255, fill=0)

        self.draw.text((x, y), text, font=self.font, fill=255)

    def update(self):
        self.display.image(self.image)
        self.display.show()
