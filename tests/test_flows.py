"""Menu-flow behaviour: cancelling, idle return to home, confirmations, input, printing."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from spotifactory.tasks.base import Cancel, Continue, Done, Step, Task, TaskContext


def _wait_for(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


class _BlockingStep(Step):
    """Runs until cancel() — stands in for QR auth / tag write / prompts."""

    def __init__(self):
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self, ctx):
        self._cancel.wait(5.0)
        return Cancel()


class _BlockingTask(Task):
    steps = [("block", _BlockingStep)]


class _FakeHome(Task):
    steps = [("block", _BlockingStep)]


def _runner(home=None):
    from spotifactory.menu.catalog import MENUS
    from spotifactory.runner import Runner
    return Runner(MagicMock(), MENUS, dry_run=True, home_task_class=home)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class TestBackCancelsRunningStep:
    @pytest.mark.parametrize("button", ["handle_back", "handle_left"])
    def test_back_and_left_cancel_a_cancellable_step(self, button):
        r = _runner()
        r._start_task(_BlockingTask)
        step = r._task.current_step
        getattr(r, button)()
        assert _wait_for(lambda: step.is_done)
        r.tick()
        assert r._task is None


class TestIdleReturnsHome:
    def test_idle_menu_returns_to_home_at_root(self):
        r = _runner(home=_FakeHome)
        r._task.current_step.cancel()          # leave home → menu
        r._task = None
        r.nav.push(r.menus["confirm_reboot"])
        r._last_input = time.monotonic() - 61
        r.tick()
        assert isinstance(r._task, _FakeHome)
        assert r.nav.depth == 1
        r._task.current_step.cancel()

    def test_recent_input_keeps_menu_open(self):
        r = _runner(home=_FakeHome)
        r._task.current_step.cancel()
        r._task = None
        r.handle_down()
        r.tick()
        assert r._task is None

    def test_menu_pushed_after_long_step_gets_a_fresh_timeout(self):
        from spotifactory.menu.definitions import ItemDef, MenuDef
        from spotifactory.tasks.base import PushMenu
        r = _runner(home=_FakeHome)
        r._task.current_step.cancel()
        r._last_input = time.monotonic() - 120  # e.g. a long print attempt
        r._resolve(PushMenu(MenuDef("Printer Off?", [ItemDef("Retry")]), Continue(), Cancel()))
        r.tick()
        assert r._pushed_menu is not None


class TestRebootShutdownConfirm:
    @pytest.mark.parametrize("label,title", [("Reboot", "Reboot?"), ("Shutdown", "Shut down?")])
    def test_needs_confirmation_and_defaults_to_cancel(self, label, title):
        r = _runner()
        labels = [i.label for i in r.nav.current.menu.items]
        r.nav.current.selected_index = labels.index(label)
        with patch("spotifactory.runner.os.system") as system:
            r.handle_select()
            assert r.nav.current.menu.title == title
            r.handle_select()  # default item is Cancel
        system.assert_not_called()
        assert r.nav.current.menu.title == "Main Menu"


# ---------------------------------------------------------------------------
# Button input fires once per press
# ---------------------------------------------------------------------------

def test_seengreat_input_fires_once_per_press():
    from spotifactory.input import seengreat
    pins = {}
    gpio = MagicMock()
    gpio.input.side_effect = lambda pin: pins.get(pin, 1)  # active-low, 1 = released
    with patch.object(seengreat, "GPIO", gpio):
        buttons = seengreat.SeenGreatInput()
        pins[seengreat._DOWN] = 0
        assert buttons.read() == "Down"
        assert buttons.read() is None   # still held
        pins[seengreat._DOWN] = 1
        assert buttons.read() is None   # released
        pins[seengreat._DOWN] = 0
        assert buttons.read() == "Down"  # pressed again


# ---------------------------------------------------------------------------
# Tag write step
# ---------------------------------------------------------------------------

class TestWriteTagStep:
    def _step(self):
        from spotifactory.tasks.capture.steps import ScanStep
        step = ScanStep()
        ctx = TaskContext(data={"info": MagicMock(album_uri="spotify:album:x")})
        return step, ctx

    def test_success_continues(self):
        step, ctx = self._step()
        with patch("spotifactory.hardware.rfid.write_uri", return_value="UID1"):
            assert isinstance(step.run(ctx), Continue)

    def test_unwritable_tag_shows_reason_then_waits_for_another(self):
        from spotifactory.hardware.rfid import TagWriteError
        step, ctx = self._step()
        step._cancel = MagicMock(is_set=MagicMock(return_value=False))
        with patch("spotifactory.hardware.rfid.write_uri",
                   side_effect=[TagWriteError("Not NDEF formatted"), "UID1"]) as write:
            assert isinstance(step.run(ctx), Continue)
        assert write.call_count == 2

    def test_cancel_skips_without_claiming_success(self):
        step, ctx = self._step()

        def write(uri, terminate):
            step.cancel()
            assert terminate()
            return None

        with patch("spotifactory.hardware.rfid.write_uri", side_effect=write), \
             patch("spotifactory.tasks.base.time.sleep"):
            assert isinstance(step.run(ctx), Done)
        assert step.status == "Tag not written"


# ---------------------------------------------------------------------------
# Pause music on this device while printing
# ---------------------------------------------------------------------------

class TestPauseWhilePrinting:
    def _run_print(self, device_name, is_playing=True):
        from spotifactory.tasks.capture.steps import PrintStep
        sp = MagicMock()
        sp.current_playback.return_value = {"is_playing": is_playing,
                                            "device": {"name": device_name}}
        ctx = TaskContext(data={"image": MagicMock()})
        result = MagicMock(printer_found=True, success=True)
        with patch("spotifactory.spotify.get_client", return_value=sp), \
             patch("spotifactory.hardware.printer.print_image", return_value=result):
            assert isinstance(PrintStep().run(ctx), Continue)
        return sp

    def test_pauses_and_resumes_local_playback(self):
        sp = self._run_print("Spotifactory")
        sp.pause_playback.assert_called_once()
        sp.start_playback.assert_called_once()

    def test_leaves_other_devices_alone(self):
        sp = self._run_print("Living Room Sonos")
        sp.pause_playback.assert_not_called()
        sp.start_playback.assert_not_called()

    def test_does_not_resume_if_it_was_already_paused(self):
        sp = self._run_print("Spotifactory", is_playing=False)
        sp.start_playback.assert_not_called()


# ---------------------------------------------------------------------------
# Bluetooth pairing
# ---------------------------------------------------------------------------

class TestPairAndConfigure:
    def _pair(self, pair_out, conn_out, connect=True):
        from spotifactory.hardware import bluetooth
        with patch.object(bluetooth, "_pair_interactive", return_value=pair_out), \
             patch.object(bluetooth, "_pty_session", return_value=conn_out) as session:
            bluetooth.pair_and_configure("88:B4:36:18:6F:4F", connect=connect)
        return session.call_args[0][0]

    def test_printer_pairs_without_connect(self):
        # The Instax has no BlueZ profile to connect; NotAvailable must not fail pairing.
        cmds = self._pair("Pairing successful", "Failed to connect: NotAvailable",
                          connect=False)
        assert cmds == ["trust 88:B4:36:18:6F:4F"]

    def test_speaker_connect_failure_raises(self):
        with pytest.raises(RuntimeError, match="could not connect"):
            self._pair("Pairing successful", "Failed to connect: br-connection")

    def test_already_paired_is_not_a_failure(self):
        cmds = self._pair("Failed to pair: org.bluez.Error.AlreadyExists",
                          "Connection successful")
        assert cmds[-1] == "connect 88:B4:36:18:6F:4F"
