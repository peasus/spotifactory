from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.tasks.capture import CaptureTask
from spotifactory.tasks.reauth import ReAuthTask
from spotifactory.tasks.speaker import SpeakerTask

MENUS: dict[str, MenuDef] = {
    "main": MenuDef("Main Menu", [
        ItemDef("Print Now Playing", task=CaptureTask),
        ItemDef("Choose Speaker",    task=SpeakerTask),
        ItemDef("Connect Spotify",   task=ReAuthTask),
        ItemDef("Scan Tag",          action="home"),
        ItemDef("Reboot",            action="reboot"),
        ItemDef("Shutdown",          action="shutdown"),
    ]),
}
