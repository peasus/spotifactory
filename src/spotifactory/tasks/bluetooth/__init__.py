from spotifactory.tasks.base import Task
from spotifactory.tasks.bluetooth.steps import ActStep, ChosenStep, DevicesStep, PairStep, ScanStep


class BluetoothTask(Task):
    """Menu > Bluetooth: paired devices and their state (connect, use as
    speaker, forget), then "+ Pair new device" (scan and pair)."""
    name = "bluetooth"
    steps = [
        ("devices", DevicesStep),
        ("chosen", ChosenStep),
        ("act", ActStep),
        ("scan", ScanStep),
        ("pair", PairStep),
    ]
