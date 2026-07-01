from spotifactory.tasks.base import Task
from spotifactory.tasks.home.steps import HomeDoneStep, HomePlayStep, HomeScanStep


class HomeTask(Task):
    name = "home"
    steps = [
        ("scan", HomeScanStep),
        ("play", HomePlayStep),
        ("done", HomeDoneStep),
    ]
