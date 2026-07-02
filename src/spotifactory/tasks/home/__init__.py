from spotifactory.tasks.base import Task
from spotifactory.tasks.home.steps import HomeScanStep


class HomeTask(Task):
    name = "home"
    steps = [
        ("scan", HomeScanStep),
    ]
