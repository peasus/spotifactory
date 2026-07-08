from spotifactory.tasks.base import Task
from spotifactory.tasks.bluetooth.steps import ScanStep, PairStep


class BluetoothTask(Task):
    name = "bluetooth"
    steps = [
        ("scan", ScanStep),
        ("pair", PairStep),
    ]
