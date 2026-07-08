from spotifactory.tasks.base import Task
from spotifactory.tasks.reauth.steps import QRAuthStep, ZeroconfPromptStep


class ReAuthTask(Task):
    name = "reauth"
    steps = [
        ("qr_auth", QRAuthStep),
        ("zeroconf_prompt", ZeroconfPromptStep),
    ]
