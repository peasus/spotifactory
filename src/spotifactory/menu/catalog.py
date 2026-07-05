from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.tasks.capture import CaptureTask, CapturePlaylistTask
from spotifactory.tasks.reauth import ReAuthTask
from spotifactory.tasks.speaker import SpeakerTask

MENUS: dict[str, MenuDef] = {
    "main": MenuDef("Main Menu", [
        ItemDef("Print Album",    task=CaptureTask),
        ItemDef("Print Playlist", task=CapturePlaylistTask),
        ItemDef("Choose Speaker", task=SpeakerTask),
        ItemDef("Connect Spotify", task=ReAuthTask),
        ItemDef("Scan Tag",       action="home"),
        ItemDef("Reboot",         action="reboot"),
        ItemDef("Shutdown",       action="shutdown"),
    ]),
}
