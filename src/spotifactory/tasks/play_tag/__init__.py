from spotifactory.tasks.base import Task
from spotifactory.tasks.play_tag.steps import DoneStep, PlayStep, ScanStep


class PlayTagTask(Task):
    name = "play_tag"
    steps = [
        ("scan", ScanStep),
        ("play", PlayStep),
        ("done", DoneStep),
    ]
