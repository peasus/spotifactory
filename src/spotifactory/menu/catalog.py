from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.tasks.capture import CaptureTask

MENUS: dict[str, MenuDef] = {
    "main": MenuDef("Main Menu", [
        ItemDef("Print Now Playing", task=CaptureTask),
        ItemDef("Status"),
        ItemDef("Settings",  submenu="settings"),
        ItemDef("Reboot",    action="reboot"),
        ItemDef("Shutdown",  action="shutdown"),
    ]),
    "settings": MenuDef("Settings", [
        ItemDef("WiFi"),
        ItemDef("Brightness"),
        ItemDef("Back", action="back"),
    ]),
}
