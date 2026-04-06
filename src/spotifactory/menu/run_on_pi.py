# run_on_pi.py — Raspberry Pi hardware runner

import time

from spotifactory.menu.menus import build_menu
from spotifactory.menu.renderer_oled import DisplayOLED
from spotifactory.menu.input_buttons import ButtonInput


def main():
    display = DisplayOLED()
    buttons = ButtonInput()
    current_menu = build_menu()

    while True:
        action = buttons.read()

        if action == "Up":
            current_menu.move_up()
        elif action == "Down":
            current_menu.move_down()
        elif action == "Select":
            result = current_menu.select()
            if result:
                current_menu = result
        elif action == "Back":
            if current_menu.parent:
                current_menu = current_menu.parent

        display.clear()
        display.draw_text(2, 0, current_menu.title)
        y = 12
        visible = current_menu.items[
            current_menu.scroll_offset : current_menu.scroll_offset + current_menu.visible_rows
        ]
        for i, item in enumerate(visible):
            actual_idx = i + current_menu.scroll_offset
            display.draw_text(2, y, item.label, selected=(actual_idx == current_menu.selected_index))
            y += 11
        display.update()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
