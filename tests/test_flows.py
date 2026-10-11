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


# ---------------------------------------------------------------------------
# Chosen speaker persists across restarts and idle
# ---------------------------------------------------------------------------

class TestChosenSpeaker:
    @pytest.fixture(autouse=True)
    def _isolated_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        clean = {"SPOTIFACTORY_DEVICE_ID": "", "SPOTIFACTORY_DEVICE_NAME": ""}
        with patch.dict("os.environ", clean), \
             patch("spotifactory.settings.env_path", return_value=str(env_file)):
            self.env_file = env_file
            yield

    def test_choice_is_saved_to_env_and_read_back(self):
        from dotenv import dotenv_values

        from spotifactory.spotify import get_active_device, set_active_device
        assert get_active_device() is None
        set_active_device("abc_amzn_1", "Joe's Echo")
        assert get_active_device().name == "Joe's Echo"
        saved = dotenv_values(self.env_file)
        assert saved["SPOTIFACTORY_DEVICE_ID"] == "abc_amzn_1"
        assert saved["SPOTIFACTORY_DEVICE_NAME"] == "Joe's Echo"

    def test_resolves_by_name_when_id_changed(self):
        from spotifactory.spotify import ChosenDevice, resolve_chosen_device
        sp = MagicMock()
        sp.devices.return_value = {"devices": [{"id": "new-id", "name": "Guest Room Echo"}]}
        with patch("spotifactory.spotify.get_client", return_value=sp):
            assert resolve_chosen_device(ChosenDevice("old-id", "Guest Room Echo")) == "new-id"
            assert resolve_chosen_device(ChosenDevice("old-id", "Gone")) is None

    def test_choice_saved_even_if_speaker_is_asleep(self):
        from spotifactory.spotify import get_active_device
        from spotifactory.tasks.speaker.steps import SetDeviceStep
        ctx = TaskContext(dry_run=False, data={"selected": {"id": "e1", "name": "Guest Room Echo"}})
        step = SetDeviceStep()
        with patch("spotifactory.spotify.transfer_playback", side_effect=Exception("404")), \
             patch("spotifactory.tasks.base.time.sleep"):
            assert isinstance(step.run(ctx), Done)
        assert get_active_device().id == "e1"
        assert step.status == "Saved: Guest Room Echo"
        assert step.artist == "Not responding now"


# ---------------------------------------------------------------------------
# Shuffle icon responds instantly on the home screen
# ---------------------------------------------------------------------------

class TestShuffleIcon:
    def _runner_with_home_step(self):
        from spotifactory.tasks.home.steps import HomeScanStep
        r = _runner()
        step = HomeScanStep()
        r._task = MagicMock(current_step=step)
        return r, step

    def test_icon_flips_before_spotify_answers_then_confirms(self):
        r, step = self._runner_with_home_step()
        release = threading.Event()

        def slow_toggle():
            release.wait(2)
            return True

        with patch("spotifactory.spotify.toggle_shuffle", side_effect=slow_toggle):
            r._toggle_shuffle()
            assert step.shuffle_active is True       # instant, Spotify hasn't answered
            r._toggle_shuffle()                      # ignored while the first is in flight
            release.set()
            assert _wait_for(lambda: not r._shuffle_busy)
        assert step.shuffle_active is True

    def test_icon_reverts_when_nothing_is_playing(self):
        r, step = self._runner_with_home_step()
        with patch("spotifactory.spotify.toggle_shuffle", return_value=None):
            r._toggle_shuffle()
            assert _wait_for(lambda: not r._shuffle_busy)
        assert step.shuffle_active is False


# ---------------------------------------------------------------------------
# Menu scrollbar
# ---------------------------------------------------------------------------

class TestMenuScrollbar:
    def _thumb(self, r):
        """(top, bottom) of the solid thumb: the draw_rect call 3 px wide."""
        calls = [c.args for c in r.display.draw_rect.call_args_list
                 if c.args[2] - c.args[0] == 2 and c.kwargs.get("on", True)]
        assert len(calls) == 1
        return calls[0][1], calls[0][3]

    def test_long_menu_shows_bar_that_tracks_position(self):
        r = _runner()
        r._render_menu()
        top_at_start, _ = self._thumb(r)
        for _ in range(len(r.nav.current.menu.items)):
            r.nav.current.move_down()
        r.display.draw_rect.reset_mock()
        r._render_menu()
        _, bottom_at_end = self._thumb(r)
        assert top_at_start == 14                  # top of the first list row
        assert bottom_at_end == 14 + 4 * 12 - 2    # bottom of the last list row

    def test_short_menu_has_no_bar(self):
        r = _runner()
        r.nav.push(r.menus["confirm_reboot"])
        r._render_menu()
        r.display.draw_rect.assert_not_called()
