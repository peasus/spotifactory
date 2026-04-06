# menus.py — shared menu tree definition

from spotifactory.menu.menu import Menu, MenuItem


def reboot():
    print("Rebooting...")


def shutdown():
    print("Shutdown requested")


def build_menu() -> Menu:
    """Build and return the root menu."""
    settings_menu = Menu("Settings", [
        MenuItem("WiFi"),
        MenuItem("Brightness"),
        MenuItem("Back"),
    ])

    return Menu("Main Menu", [
        MenuItem("Status"),
        MenuItem("Settings", submenu=settings_menu),
        MenuItem("Reboot", callback=reboot),
        MenuItem("Shutdown", callback=shutdown),
    ])
