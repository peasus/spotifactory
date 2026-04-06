# renderer_sim.py

import tkinter as tk

class DisplaySim:
    def __init__(self, width=128, height=64, scale=6):
        self.width = width
        self.height = height
        self.scale = scale

        self.root = tk.Tk()
        self.root.title("OLED Display Simulator")

        self.canvas = tk.Canvas(
            self.root, width=self.width * self.scale, height=self.height * self.scale, bg="black"
        )
        self.canvas.pack()

    def clear(self):
        self.canvas.delete("all")

    def draw_text(self, x, y, text, selected=False):
        if selected:
            self.canvas.create_rectangle(
                0, y * self.scale, self.width * self.scale, (y + 10) * self.scale,
                fill="white", outline=""
            )
            self.canvas.create_text(
                x * self.scale, y * self.scale, anchor="nw",
                text=text, fill="black", font=("Courier", 10 * self.scale // 6)
            )
        else:
            self.canvas.create_text(
                x * self.scale, y * self.scale, anchor="nw",
                text=text, fill="white", font=("Courier", 10 * self.scale // 6)
            )

    def update(self):
        self.root.update_idletasks()
        self.root.update()
