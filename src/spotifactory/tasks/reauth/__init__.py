from spotifactory.tasks.base import Task
from spotifactory.tasks.reauth.steps import QRAuthStep, PlayerLoginStep


class ReAuthTask(Task):
    name = "reauth"
    steps = [
        ("qr_auth", QRAuthStep),
        ("player_login", PlayerLoginStep),
    ]


class FirstBootLoginTask(ReAuthTask):
    """The login a new box opens on. Leaving it (Menu or Back) goes to the
    main menu, not the home screen, so the box can be set up another way."""
    cancel_to_menu = True


class PlayerLoginTask(Task):
    """Opened at startup when the app is signed in but the box's own player
    isn't: shows the pairing code, then the home screen."""
    name = "player_login"
    steps = [("player_login", PlayerLoginStep)]
