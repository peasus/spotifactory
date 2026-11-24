from spotifactory.tasks.base import Task
from spotifactory.tasks.reauth.steps import QRAuthStep, PlayerLoginStep
from spotifactory.tasks.wifi_setup.steps import WifiSetupStep


class WifiSetupTask(Task):
    """The setup hotspot, then the Spotify login if there isn't one yet.
    Menu (or Back) leaves it for the main menu, as for the first-boot login."""
    name = "wifi_setup"
    cancel_to_menu = True
    steps = [
        ("wifi", WifiSetupStep),
        ("qr_auth", QRAuthStep),
        ("player_login", PlayerLoginStep),
    ]
