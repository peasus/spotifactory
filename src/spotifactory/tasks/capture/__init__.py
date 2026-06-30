from spotifactory.tasks.base import Task
from spotifactory.tasks.capture.steps import (
    FetchInfoStep,
    ConfirmStep,
    FetchArtStep,
    PrintStep,
    ScanStep,
    DoneStep,
)


class CaptureTask(Task):
    name = "capture"
    steps = [
        ("fetch_info", FetchInfoStep),
        ("confirm",    ConfirmStep),
        ("fetch_art",  FetchArtStep),
        ("print",      PrintStep),
        ("scan",       ScanStep),
        ("done",       DoneStep),
    ]
