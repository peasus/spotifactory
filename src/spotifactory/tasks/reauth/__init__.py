from spotifactory.tasks.base import Task
from spotifactory.tasks.reauth.steps import QRAuthStep


class ReAuthTask(Task):
    name = "reauth"
    steps = [("qr_auth", QRAuthStep)]
