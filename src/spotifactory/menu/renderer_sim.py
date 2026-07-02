import tkinter as tk
from tkinter import font as tkfont

from spotifactory.menu.scroll import ScrollTracker


class DisplaySim:
    def __init__(self, width=128, height=64, scale=4):
        self.width = width
        self.height = height
        self.scale = scale

        self.root = tk.Tk()
        self.root.title("OLED Simulator (128×64)")

        # Font object lets us measure text width for scroll detection
        self._font = tkfont.Font(family="Courier", size=self.scale * 6)
        self._scroll = ScrollTracker()

        self.canvas = tk.Canvas(
            self.root,
            width=self.width * self.scale,
            height=self.height * self.scale,
            bg="black",
        )
        self.canvas.pack()

    def clear(self):
        self.canvas.delete("all")

    def draw_text(self, x, y, text, selected=False):
        sx, sy = x * self.scale, y * self.scale
        row_h = 10 * self.scale  # matches OLED selection rect height

        # --- scroll offset ---
        text_screen_px = self._font.measure(text)
        available_screen_px = (self.width - x) * self.scale
        overflow_screen_px = text_screen_px - available_screen_px
        key = (x, y)

        if overflow_screen_px > 0:
            overflow_display = overflow_screen_px / self.scale
            scroll_px = int(self._scroll.offset(key, text, overflow_display) * self.scale)
        else:
            self._scroll.clear(key)
            scroll_px = 0

        draw_sx = sx - scroll_px

        # --- draw ---
        if selected:
            self.canvas.create_rectangle(
                0, sy, self.width * self.scale, sy + row_h, fill="white", outline=""
            )
            self.canvas.create_text(draw_sx, sy, anchor="nw", text=text, fill="black", font=self._font)
            if scroll_px > 0:
                # white rect clips text that has scrolled past the left margin
                self.canvas.create_rectangle(0, sy, sx, sy + row_h, fill="white", outline="")
        else:
            self.canvas.create_text(draw_sx, sy, anchor="nw", text=text, fill="white", font=self._font)
            if scroll_px > 0:
                self.canvas.create_rectangle(0, sy, sx, sy + row_h, fill="black", outline="")

    def draw_line(self, x1: int, y1: int, x2: int, y2: int, width: float = 1) -> None:
        self.canvas.create_line(
            x1 * self.scale, y1 * self.scale,
            x2 * self.scale, y2 * self.scale,
            fill="white", width=width * self.scale,
        )

    def draw_circle(self, cx: int, cy: int, r: int) -> None:
        self.canvas.create_oval(
            (cx - r) * self.scale, (cy - r) * self.scale,
            (cx + r) * self.scale, (cy + r) * self.scale,
            fill="white", outline="",
        )

    def update(self):
        self.root.update_idletasks()
        self.root.update()
