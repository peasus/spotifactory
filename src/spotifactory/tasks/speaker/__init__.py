from spotifactory.tasks.base import Task
from spotifactory.tasks.speaker.steps import FetchDevicesStep, SetDeviceStep


class SpeakerTask(Task):
    name = "speaker"
    steps = [
        ("fetch", FetchDevicesStep),
        ("set",   SetDeviceStep),
    ]
