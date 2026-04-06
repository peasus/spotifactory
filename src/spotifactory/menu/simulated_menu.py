# simulate_menu.py

from menu import Menu, MenuItem
from renderer_sim import DisplaySim

display = DisplaySim(scale=6)


# ----- CALLBACK EXAMPLES -----
def reboot():
    print("Rebooting...")
def shutdown():
    print("Shutdown requested")


# ----- CREATE MENUS -----
settings_menu = Menu("Settings", [
    MenuItem("WiFi"),
    MenuItem("Brightness"),
    MenuItem("Back")
])

main_menu = Menu("Main Menu", [
    MenuItem("Status"),
    MenuItem("Settings", submenu=settings_menu),
    MenuItem("Reboot", callback=reboot),
    MenuItem("Shutdown", callback=shutdown)
])


current_menu = main_menu


def redraw():
    display.clear()
    display.draw_text(2, 0, current_menu.title)

    y = 14
    visible_items = current_menu.items[current_menu.scroll_offset:current_menu.scroll_offset + current_menu.visible_rows]

    for idx, item in enumerate(visible_items):
        actual_index = current_menu.scroll_offset + idx
        display.draw_text(2, y, item.label, selected=(actual_index == current_menu.selected_index))
        y += 12

    display.update()


def on_key(event):
    global current_menu
    key = event.keysym

    if key == "Up":
        current_menu.move_up()

    elif key == "Down":
        current_menu.move_down()

    elif key == "Return":
        result = current_menu.select()
        if result:
            current_menu = result

    elif key in ("BackSpace", "Escape"):
        if current_menu.parent:
            current_menu = current_menu.parent

    redraw()


display.root.bind("<Key>", on_key)
redraw()
display.root.mainloop()
