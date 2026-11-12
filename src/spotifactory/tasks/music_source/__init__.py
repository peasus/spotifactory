from spotifactory.tasks.base import Task
from spotifactory.tasks.music_source.steps import MAServerStep, MASetupStep, UseSpotifyStep
from spotifactory.tasks.reauth.steps import QRAuthStep, ZeroconfPromptStep


class UseSpotifyTask(Task):
    name = "use_spotify"
    steps = [
        ("switch",          UseSpotifyStep),
        ("qr_auth",         QRAuthStep),
        ("zeroconf_prompt", ZeroconfPromptStep),
    ]


class UseMusicAssistantTask(Task):
    name = "use_music_assistant"
    steps = [("setup", MASetupStep)]


class MusicAssistantServerTask(Task):
    name = "music_assistant_server"
    steps = [("setup", MAServerStep)]
