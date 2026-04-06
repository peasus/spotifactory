# simulated_menu.py — desktop simulator runner

from spotifactory.menu.menus import build_menu
from spotifactory.menu.renderer_sim import DisplaySim


def main():
    display = DisplaySim(scale=6)
    current_menu = [build_menu()]  # list so the closure can rebind it

    def redraw():
        menu = current_menu[0]
        display.clear()
        display.draw_text(2, 0, menu.title)
        y = 14
        visible = menu.items[menu.scroll_offset : menu.scroll_offset + menu.visible_rows]
        for idx, item in enumerate(visible):
            actual_index = menu.scroll_offset + idx
            display.draw_text(2, y, item.label, selected=(actual_index == menu.selected_index))
            y += 12
        display.update()

    def on_key(event):
        menu = current_menu[0]
        key = event.keysym
        if key == "Up":
            menu.move_up()
        elif key == "Down":
            menu.move_down()
        elif key == "Return":
            result = menu.select()
            if result:
                current_menu[0] = result
        elif key in ("BackSpace", "Escape"):
            if menu.parent:
                current_menu[0] = menu.parent
        redraw()

    display.root.bind("<Key>", on_key)
    redraw()
    display.root.mainloop()


if __name__ == "__main__":
    main()
