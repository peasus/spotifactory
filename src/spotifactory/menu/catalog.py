from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.tasks.capture import CaptureTask

MENUS: dict[str, MenuDef] = {
    "main": MenuDef("Main Menu", [
        ItemDef("Print Now Playing", task=CaptureTask),
        ItemDef("Scan Tag",          action="home"),
        ItemDef("Reboot",            action="reboot"),
        ItemDef("Shutdown",          action="shutdown"),
    ]),
}
