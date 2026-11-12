from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.tasks.bluetooth import BluetoothTask
from spotifactory.tasks.capture import CapturePlaylistTask, CaptureTask, WriteTagTask
from spotifactory.tasks.film import FilmCountTask
from spotifactory.tasks.music_source import (
    MusicAssistantServerTask,
    UseMusicAssistantTask,
    UseSpotifyTask,
)
from spotifactory.tasks.reauth import ReAuthTask
from spotifactory.tasks.speaker import SpeakerTask

MENUS: dict[str, MenuDef] = {
    "main": MenuDef("Main Menu", [
        ItemDef("Print Album",    task=CaptureTask),
        ItemDef("Print Playlist", task=CapturePlaylistTask, backend="spotify"),
        ItemDef("Film Left",      task=FilmCountTask),
        ItemDef("Choose Speaker", task=SpeakerTask),
        ItemDef("Pair Device",    task=BluetoothTask),
        ItemDef("Connect Spotify", task=ReAuthTask, backend="spotify"),
        ItemDef("Music Source",   submenu="music_source"),
        ItemDef("Scan Tag",       action="home"),
        ItemDef("Check for Updates", action="update"),
        ItemDef("Write Tag",      task=WriteTagTask),     # fixing a tag: rarely needed
        ItemDef("Reboot",         submenu="confirm_reboot"),
        ItemDef("Shutdown",       submenu="confirm_shutdown"),
    ]),
    # Music Assistant is for owners who run their own server (advanced).
    "music_source": MenuDef("Music Source", [
        ItemDef("Spotify",          task=UseSpotifyTask),
        ItemDef("Music Assistant",  task=UseMusicAssistantTask),
        ItemDef("Change MA Server", task=MusicAssistantServerTask, backend="music_assistant"),
        ItemDef("Back",             action="back"),
    ]),
    # Cancel is listed first so it's the default selection.
    "confirm_reboot": MenuDef("Reboot?", [
        ItemDef("Cancel",     action="back"),
        ItemDef("Reboot now", action="reboot"),
    ], visible_rows=2),
    "confirm_shutdown": MenuDef("Shut down?", [
        ItemDef("Cancel",        action="back"),
        ItemDef("Shut down now", action="shutdown"),
    ], visible_rows=2, subtitle="Unplug to restart"),
}
