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
        with patch("spotifactory.runner.subprocess.run") as run:
            r.handle_select()
            assert r.nav.current.menu.title == title
            r.handle_select()  # default item is Cancel
        run.assert_not_called()
        assert r.nav.current.menu.title == "Main Menu"

    def _confirm(self, r, label):
        labels = [i.label for i in r.nav.current.menu.items]
        r.nav.current.selected_index = labels.index(label)
        r.handle_select()                      # into the confirm menu
        r.nav.current.move_down()              # Cancel -> the action
        r.handle_select()

    @pytest.mark.parametrize("label,verb", [("Reboot", "reboot"), ("Shutdown", "poweroff")])
    def test_confirmed_runs_systemctl_without_waiting_for_a_password(self, label, verb):
        r = _runner()
        with patch("spotifactory.runner.sys.platform", "linux"), \
             patch("spotifactory.runner.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            self._confirm(r, label)
        run.assert_called_once()
        assert run.call_args.args[0] == ["sudo", "-n", "systemctl", verb]
        assert r._message[0] in ("Rebooting...", "Shutting down...")

    def test_failure_is_shown_not_swallowed(self):
        r = _runner()
        with patch("spotifactory.runner.sys.platform", "linux"), \
             patch("spotifactory.runner.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stderr="sudo: a password is required")
            self._confirm(r, "Shutdown")
        assert r._message[0] == "Couldn't shut down"

    def test_simulator_never_powers_off_the_computer(self):
        r = _runner()
        with patch("spotifactory.runner.sys.platform", "darwin"), \
             patch("spotifactory.runner.subprocess.run") as run:
            self._confirm(r, "Shutdown")
        run.assert_not_called()


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


class TestPlaylistNameChoice:
    """Playlist prints ask whether to add the name; either answer prints."""

    def _runner_at_label_step(self, labelled=True):
        from spotifactory.tasks.capture.steps import PlaylistLabelStep

        class _LabelThenBlock(Task):
            steps = [("label", PlaylistLabelStep), ("block", _BlockingStep)]

        r = _runner()
        r._start_task(_LabelThenBlock)
        r._task.ctx.data["playlist"] = {"name": "Derpy derp", "labelled": labelled}
        r.tick()
        return r

    @pytest.mark.parametrize("presses, choice", [(0, "label"), (1, "plain")])
    def test_yes_or_no_both_carry_on_to_printing(self, presses, choice):
        r = self._runner_at_label_step()
        assert _wait_for(lambda: (r.tick(), r._pushed_menu)[1] is not None)
        assert r.nav.current.menu.title == "Add name?"
        for _ in range(presses):
            r.handle_down()
        r.handle_select()
        assert r._pushed_menu is None and r._task.current_step_name == "block"
        assert r._task.ctx.data["selected"] == choice
        r._cancel_running_step()

    def test_back_cancels_the_print(self):
        r = self._runner_at_label_step()
        assert _wait_for(lambda: (r.tick(), r._pushed_menu)[1] is not None)
        r.handle_back()
        assert r._task is None

    def test_auto_playlists_skip_the_question(self):
        r = self._runner_at_label_step(labelled=False)
        assert _wait_for(lambda: (r.tick(), r._task.current_step_name)[1] == "block")
        assert r._pushed_menu is None
        r._cancel_running_step()

    @pytest.mark.parametrize("choice, labelled", [("label", True), ("plain", False)])
    def test_art_gets_the_name_only_when_asked(self, choice, labelled):
        from spotifactory.tasks.capture.steps import FetchPlaylistArtStep
        ctx = TaskContext(data={"playlist": {"name": "P", "image_url": "u", "labelled": True},
                                "selected": choice})
        resp = MagicMock(content=b"img")
        with patch("spotifactory.tasks.capture.steps.requests.get", return_value=resp), \
             patch("spotifactory.tasks.capture.label.add_playlist_label",
                   return_value="labelled") as add:
            assert isinstance(FetchPlaylistArtStep().run(ctx), Continue)
        assert add.called is labelled
        assert (ctx.data["image"] == "labelled") is labelled


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


# ---------------------------------------------------------------------------
# Auto-update: heartbeat, Check for Updates, the "Updated" note
# ---------------------------------------------------------------------------

class TestUpdates:
    def test_check_for_updates_asks_the_updater_and_says_up_to_date(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFACTORY_STATE", str(tmp_path))
        r = _runner()
        (tmp_path / "update-status").write_text("current abc1234\n")
        with patch("spotifactory.runner.sys.platform", "linux"), \
             patch("spotifactory.runner.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            labels = [i.label for i in r.nav.current.menu.items]
            r.nav.current.selected_index = labels.index("Check for Updates")
            r.handle_select()
            assert _wait_for(lambda: r._message and r._message[0] == "Up to date")
        assert run.call_args.args[0] == ["sudo", "-n", "systemctl", "start", "spotifactory-update"]
        assert (tmp_path / "update-requested").exists()     # tells update.sh not to wait for idle

    def test_failed_update_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFACTORY_STATE", str(tmp_path))
        r = _runner()
        (tmp_path / "update-status").write_text("rolled back abc1234\n")
        with patch("spotifactory.runner.sys.platform", "linux"), \
             patch("spotifactory.runner.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stderr="failed")
            r._check_for_updates()
            assert _wait_for(lambda: r._message and r._message[0] == "Update failed")

    def test_heartbeat_says_idle_or_busy_under_systemd_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFACTORY_STATE", str(tmp_path))
        monkeypatch.delenv("INVOCATION_ID", raising=False)  # CI runners are systemd services too
        r = _runner()
        r._last_input = time.monotonic() - 600
        r.tick()
        assert not (tmp_path / "heartbeat").exists()        # not under systemd: no file
        monkeypatch.setenv("INVOCATION_ID", "x")
        r.tick()
        assert (tmp_path / "heartbeat").read_text() == "idle\n"
        r._last_beat = 0.0
        r.handle_down()                                     # someone in the menus
        r.tick()
        assert (tmp_path / "heartbeat").read_text() == "busy\n"

    def test_shows_updated_after_an_update_restart(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPOTIFACTORY_STATE", str(tmp_path))
        (tmp_path / "update-status").write_text("updated def5678\n")
        r = _runner()
        assert r._message[:2] == ("Updated", "def5678")


# ---------------------------------------------------------------------------
# Volume and play/pause buttons (K1-K3)
# ---------------------------------------------------------------------------

def test_volume_buttons_repeat_when_held_but_menu_does_not():
    from spotifactory.input import seengreat
    pins, clock = {}, [100.0]
    gpio = MagicMock()
    gpio.input.side_effect = lambda pin: pins.get(pin, 1)
    with patch.object(seengreat, "GPIO", gpio), \
         patch.object(seengreat.time, "monotonic", lambda: clock[0]):
        buttons = seengreat.SeenGreatInput()
        pins[seengreat._K1] = 0
        assert buttons.read() == "VolUp"
        clock[0] += 0.3
        assert buttons.read() is None          # not held long enough yet
        clock[0] += 0.3
        assert buttons.read() == "VolUp"       # repeating
        clock[0] += 0.05
        assert buttons.read() is None          # not again so soon
        clock[0] += 0.15
        assert buttons.read() == "VolUp"
        pins[seengreat._K1] = 1
        assert buttons.read() is None
        pins[seengreat._K3] = 0
        assert buttons.read() == "Menu"
        clock[0] += 2.0
        assert buttons.read() is None          # the menu button never repeats


class TestMenuButton:
    """K3 opens the menu from home and closes it from any depth."""

    def test_opens_the_menu_from_home(self):
        r = _runner(home=_FakeHome)
        with patch.object(r, "_in_home_mode", return_value=True), \
             patch.object(r, "_in_home_scan", return_value=True), \
             patch.object(r, "handle_up") as up:
            r.handle_menu()
        up.assert_called_once()                 # home → menu, as joystick up does

    def test_closes_the_menu_straight_to_home(self):
        r = _runner(home=_FakeHome)
        r._task = None
        r.nav.push(r.menus[next(iter(r.menus))])
        r.nav.push(r.menus[next(iter(r.menus))])
        r.handle_menu()
        assert isinstance(r._task, _FakeHome)
        assert not r.nav.pop()                  # back at the top level
        r._cancel_running_step()

    def test_is_back_over_a_prompt(self):
        r = _runner(home=_FakeHome)
        r._start_task(_BlockingTask)
        step = r._task.current_step
        r.handle_menu()
        assert _wait_for(lambda: step.is_done)


class TestVolumeAndPlayPause:
    def _runner(self):
        r = _runner()
        r._task = None
        return r

    def test_presses_step_by_five_and_show_a_bar(self):
        r = self._runner()
        sent = []
        with patch("spotifactory.spotify.get_volume", return_value=40), \
             patch("spotifactory.spotify.set_volume", side_effect=sent.append):
            r.handle_volume(+1)
            assert _wait_for(lambda: sent and not r._volume_sending)
            r.handle_volume(+1)
            r.handle_volume(-1)
            r.handle_volume(+1)
            assert _wait_for(lambda: not r._volume_sending and r._volume_pending == 0)
        assert sent[0] == 45 and sent[-1] == 50
        assert r._volume == 50 and r._volume_shown_until > time.monotonic()

    def test_volume_stops_at_the_ends(self):
        r = self._runner()
        sent = []
        with patch("spotifactory.spotify.get_volume", return_value=98), \
             patch("spotifactory.spotify.set_volume", side_effect=sent.append):
            r.handle_volume(+1)
            assert _wait_for(lambda: sent and not r._volume_sending)
        assert sent == [100]

    def test_speaker_without_volume_control_says_so(self):
        r = self._runner()
        with patch("spotifactory.spotify.get_volume", return_value=None), \
             patch("spotifactory.spotify.set_volume") as set_volume:
            r.handle_volume(+1)
            assert _wait_for(lambda: r._message is not None)
        set_volume.assert_not_called()
        assert r._message[:2] == ("Volume:", "use the speaker")

    @pytest.mark.parametrize("result,note", [(True, "Playing"), (False, "Paused"), (None, "Nothing to play")])
    def test_play_pause_says_what_happened(self, result, note):
        r = self._runner()
        with patch("spotifactory.spotify.play_pause", return_value=result):
            r.handle_play_pause()
            assert _wait_for(lambda: r._message is not None)
        assert r._message[0] == note
