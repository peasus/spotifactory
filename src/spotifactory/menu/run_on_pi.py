from menu import Menu, MenuItem
from renderer_oled import DisplayOLED
from input_buttons import ButtonInput
import time

display = DisplayOLED()
buttons = ButtonInput()

# --- same menu definitions here ---
current_menu = main_menu

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

    # draw menu
    display.clear()
    y = 12
    display.draw_text(2, 0, current_menu.title)

    visible = current_menu.items[current_menu.scroll_offset : current_menu.scroll_offset + current_menu.visible_rows]

    for i, item in enumerate(visible):
        actual_idx = i + current_menu.scroll_offset
        display.draw_text(2, y, item.label, selected=(actual_idx == current_menu.selected_index))
        y += 11

    display.update()
    time.sleep(0.1)
