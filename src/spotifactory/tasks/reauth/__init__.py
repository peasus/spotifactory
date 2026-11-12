from spotifactory.tasks.base import Task
from spotifactory.tasks.reauth.steps import QRAuthStep, ZeroconfPromptStep


class ReAuthTask(Task):
    name = "reauth"
    steps = [
        ("qr_auth", QRAuthStep),
        ("zeroconf_prompt", ZeroconfPromptStep),
    ]


class FirstBootLoginTask(ReAuthTask):
    """The login a new box opens on. Leaving it (Menu or Back) goes to the
    main menu, not the home screen, so the box can be set up another way."""
    cancel_to_menu = True
