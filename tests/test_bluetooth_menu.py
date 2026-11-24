"""Menu > Bluetooth: paired devices, their state, and what can be done."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

MOVE = {"mac": "48:A6:B8:E6:F0:D6", "name": "Sonos Move (SONOS F0D6)", "connected": False, "audio": True}
JBL = {"mac": "AA:BB:CC:DD:EE:FF", "name": "JBL Flip", "connected": True, "audio": True}
INSTAX = {"mac": "88:B4:36:01:02:03", "name": "INSTAX-12345678", "connected": False, "audio": False}


@pytest.fixture
def env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr("spotifactory.settings.env_path", lambda: str(env_file))
    monkeypatch.setenv("SPOTIFACTORY_SPEAKER_MAC", JBL["mac"])
    monkeypatch.setenv("INSTAX_BT_ADDRESS", INSTAX["mac"])
    return monkeypatch


def _ctx(**data):
    from spotifactory.tasks.base import TaskContext
    return TaskContext(dry_run=False, data=dict(data))


def test_lists_paired_devices_then_pair_new(env):
    from spotifactory.tasks.bluetooth.steps import DevicesStep
    with patch("spotifactory.hardware.bluetooth.paired_devices", return_value=[MOVE, JBL, INSTAX]):
        out = DevicesStep().run(_ctx())
    labels = [i.label for i in out.menu.items]
    assert labels == ["Sonos Move (SONO…", "JBL Flip *", "INSTAX-12345678", "+ Pair new device", "Back"]
    assert out.menu.title == "Bluetooth" and out.menu.subtitle == "* = connected"


def test_device_menu_offers_what_fits(env):
    from spotifactory.tasks.bluetooth.steps import _device_actions_menu
    move = _device_actions_menu(MOVE)
    assert [i.label for i in move.items] == ["Use as speaker", "Forget", "Back"]
    assert move.subtitle == "Paired - not connected"
    jbl = _device_actions_menu(JBL)                # the box's speaker, connected
    assert [i.label for i in jbl.items] == ["Forget", "Back"]
    assert jbl.subtitle == "In use - connected"
    assert [i.label for i in _device_actions_menu(INSTAX).items] == ["Forget", "Back"]


def test_pair_new_goes_to_the_scan(env):
    from spotifactory.tasks.base import Continue
    from spotifactory.tasks.bluetooth.steps import _PAIR_NEW, ChosenStep
    assert ChosenStep().run(_ctx(selected=_PAIR_NEW)) == Continue("scan")


def test_use_as_speaker_saves_and_routes(env):
    import os
    from spotifactory.tasks.bluetooth.steps import ActStep
    p = "spotifactory.hardware.bluetooth."
    with patch(p + "reconnect") as reconnect, patch(p + "is_connected", return_value=True), \
         patch(p + "set_bt_audio_output") as set_out, patch(p + "move_sink_inputs"), \
         patch("spotifactory.tasks.base.time.sleep"):
        ActStep().run(_ctx(bt_device=MOVE, selected={"action": "use"}))
    reconnect.assert_called_once_with(MOVE["mac"])
    set_out.assert_called_once_with(MOVE["mac"])
    assert os.environ["SPOTIFACTORY_SPEAKER_MAC"] == MOVE["mac"]


def test_forget_asks_first_then_clears_the_saved_speaker(env):
    import os
    from spotifactory.tasks.base import PushMenu
    from spotifactory.tasks.bluetooth.steps import ActStep
    ask = ActStep().run(_ctx(bt_device=JBL, selected={"action": "forget"}))
    assert isinstance(ask, PushMenu) and ask.menu.items[0].label == "Cancel"
    with patch("spotifactory.hardware.bluetooth.forget", return_value=True) as forget, \
         patch("spotifactory.tasks.base.time.sleep"):
        ActStep().run(_ctx(bt_device=JBL, selected={"action": "forget_now"}))
    forget.assert_called_once_with(JBL["mac"])
    assert os.environ["SPOTIFACTORY_SPEAKER_MAC"] == ""
    assert os.environ["INSTAX_BT_ADDRESS"] == INSTAX["mac"]


def test_paired_devices_reads_bluetoothctl():
    from spotifactory.hardware import bluetooth

    def run(args, **kw):
        if args[1] == "devices":
            return MagicMock(stdout="Device 48:A6:B8:E6:F0:D6 Sonos Move (SONOS F0D6)\n")
        return MagicMock(stdout="\tPaired: yes\n\tConnected: no\n\tUUID: Audio Sink (0000110b-...)\n")
    with patch("subprocess.run", side_effect=run):
        assert bluetooth.paired_devices() == [MOVE]
