"""Menu-flow behaviour: cancelling, idle return to home, confirmations, input, printing."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call, patch

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

class _FakeReader:
    """Stands in for the RFID calls: `present` is the tag on the reader now,
    `placed` the tags put on it after, in turn. Lifting happens when asked."""

    def __init__(self, present=None, placed=(), on_read=None, apple=None):
        self.present, self.placed, self.writes = present, list(placed), []
        self.extras = []                        # links written after the first, per write
        self.lift_asked = False
        self.on_read = on_read
        self.apple = apple                      # what the Apple Music lookup finds

    def wait_until_clear(self, terminate=None, on_seen=None, settle=1.0):
        if self.present:
            on_seen(self.present)
            self.lift_asked = True
            self.present = None                 # they lift it off
        return not (terminate and terminate())

    def read_next(self, terminate=None):
        if self.on_read:
            self.on_read()
        if terminate and terminate():
            return None
        if self.present is None and self.placed:
            self.present = self.placed.pop(0)
        return self.present

    def write_uri(self, uri, terminate=None, uid=None, extra=()):
        self.writes.append((uri, uid))
        self.extras.append(list(extra))
        return uid

    def patch(self):
        from contextlib import ExitStack
        stack = ExitStack()
        for name in ("wait_until_clear", "read_next", "write_uri"):
            stack.enter_context(patch(f"spotifactory.hardware.rfid.{name}", getattr(self, name)))
        stack.enter_context(patch("spotifactory.spotify.uri_name", return_value="Other Album"))
        stack.enter_context(patch("spotifactory.apple_music.link_for_spotify_album", return_value=self.apple))
        stack.enter_context(patch("spotifactory.tasks.base.time.sleep"))
        return stack


class TestWriteTagStep:
    """The print's tag step: never writes a tag it hasn't read first."""

    def _step(self):
        from spotifactory.tasks.capture.steps import ScanStep
        step = ScanStep()
        ctx = TaskContext(data={"info": MagicMock(album_uri="spotify:album:x")})
        return step, ctx

    def test_album_on_the_reader_is_lifted_off_not_overwritten(self):
        step, ctx = self._step()
        reader = _FakeReader(present={"uid": "OLD", "uri": "spotify:album:old"}, placed=[{"uid": "NEW"}])
        with reader.patch():
            assert isinstance(step.run(ctx), Continue)
        assert reader.lift_asked
        assert reader.writes == [("spotify:album:x", "NEW")]   # only the new tag

    def test_a_tag_with_something_else_asks_first_no_by_default(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T", "uri": "spotify:album:other"}])
        with reader.patch():
            out = step.run(ctx)
            assert out.menu.title == "Overwrite tag?" and out.menu.subtitle == "Has Other Album"
            assert [i.label for i in out.menu.items] == ["No", "Yes"]
            assert reader.writes == []
            ctx.data["selected"] = "overwrite"              # Yes
            assert isinstance(step.run(ctx), Continue)
        assert reader.writes == [("spotify:album:x", "T")]

    def test_saying_no_to_overwrite_wants_it_lifted_off(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T", "uri": "spotify:album:other"}])
        with reader.patch():
            step.run(ctx)                                     # asks; No
            step._cancel = MagicMock(is_set=MagicMock(return_value=False))
            with patch.object(type(step), "_stopped", return_value=Done()):
                step.run(ctx)
        assert reader.lift_asked and reader.writes == []

    def test_tag_already_right_is_left_alone(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T", "uri": "spotify:album:x"}])
        with reader.patch():
            assert isinstance(step.run(ctx), Continue)
        assert reader.writes == [] and step.status == "Tag already set"

    def test_back_asks_before_skipping_no_by_default(self):
        step, ctx = self._step()
        reader = _FakeReader(on_read=step.cancel)
        with reader.patch():
            out = step.run(ctx)
        assert out.menu.title == "Skip the tag?"
        assert [i.label for i in out.menu.items] == ["No", "Yes"]
        assert isinstance(out.on_confirm, Done)
        assert out.on_cancel == Continue(next_step="scan")     # No: keep waiting
        assert reader.writes == []

    def test_unwritable_tag_shows_reason_then_waits_for_another(self):
        from spotifactory.hardware.rfid import TagWriteError
        step, ctx = self._step()
        step._cancel = MagicMock(is_set=MagicMock(return_value=False))
        reader = _FakeReader(placed=[{"uid": "T"}])
        with reader.patch(), patch("spotifactory.hardware.rfid.write_uri",
                                   side_effect=TagWriteError("Not NDEF formatted")):
            out = step.run(ctx)
        assert out == Continue(next_step="scan")
        assert step.artist == "Not NDEF formatted"


class TestAppleMusicLinkOnTags:
    """Album tags carry the album's Apple Music link too, after the Spotify one."""

    APPLE = "https://music.apple.com/album/1440892370"

    def _step(self):
        from spotifactory.tasks.capture.steps import ScanStep
        return ScanStep(), TaskContext(data={"info": MagicMock(album_uri="spotify:album:x")})

    def test_album_tag_gets_both_links_spotify_first(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T"}], apple=self.APPLE)
        with reader.patch():
            assert isinstance(step.run(ctx), Continue)
        assert reader.writes == [("spotify:album:x", "T")] and reader.extras == [[self.APPLE]]

    def test_no_sure_match_writes_spotify_only(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T"}], apple=None)
        with reader.patch():
            step.run(ctx)
        assert reader.extras == [[]]

    def test_same_album_without_the_apple_link_is_topped_up_without_asking(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T", "uri": "spotify:album:x", "uris": ["spotify:album:x"]}],
                             apple=self.APPLE)
        with reader.patch():
            assert isinstance(step.run(ctx), Continue)      # no overwrite question
        assert reader.extras == [[self.APPLE]]

    def test_same_album_with_both_links_is_left_alone(self):
        step, ctx = self._step()
        reader = _FakeReader(placed=[{"uid": "T", "uri": "spotify:album:x",
                                      "uris": ["spotify:album:x", self.APPLE]}], apple=self.APPLE)
        with reader.patch():
            step.run(ctx)
        assert reader.writes == [] and step.status == "Tag already set"

    def test_playlists_dont_look_for_an_apple_link(self):
        from spotifactory.tasks.capture.steps import PlaylistScanStep
        step = PlaylistScanStep()
        ctx = TaskContext(data={"playlist": {"uri": "spotify:playlist:p"}})
        reader = _FakeReader(placed=[{"uid": "T"}], apple=self.APPLE)
        with reader.patch(), patch("spotifactory.apple_music.link_for_spotify_album") as look:
            step.run(ctx)
        look.assert_not_called()
        assert reader.extras == [[]]


class TestAppleMusicMatch:
    """Only a sure match: same artist, name and track count. Barcodes alone
    land on reissues."""

    def _search(self, results, upc_results=()):
        def get(url, params=None, timeout=None):
            r = MagicMock()
            r.json.return_value = {"results": list(upc_results if "lookup" in url else results)}
            return r
        return patch("spotifactory.apple_music.requests.get", side_effect=get)

    def _album(self, cid, name, tracks, artist="Nirvana"):
        return {"wrapperType": "collection", "collectionId": cid, "collectionName": name,
                "trackCount": tracks, "artistName": artist}

    def test_picks_the_edition_with_the_same_tracks(self):
        from spotifactory.apple_music import album_link
        results = [self._album(2, "MTV Unplugged In New York (Live Acoustic) [25th Anniversary Edition]", 19),
                   self._album(1, "MTV Unplugged In New York (Live Acoustic)", 14)]
        with self._search(results):
            assert album_link("Nirvana", "MTV Unplugged In New York", 14) == "https://music.apple.com/album/1"

    def test_a_barcode_pointing_at_a_reissue_isnt_taken(self):
        from spotifactory.apple_music import album_link
        with self._search([], upc_results=[self._album(2, "MTV Unplugged In New York [Deluxe]", 19)]):
            assert album_link("Nirvana", "MTV Unplugged In New York", 14, upc="0072") is None

    def test_another_artist_or_a_failed_lookup_gives_nothing(self):
        from spotifactory.apple_music import album_link
        with self._search([self._album(1, "Wildflowers", 15, artist="Someone Else")]):
            assert album_link("Tom Petty", "Wildflowers", 15) is None
        with patch("spotifactory.apple_music.requests.get", side_effect=OSError("offline")):
            assert album_link("Tom Petty", "Wildflowers", 15) is None


class TestWriteTagFromMenu:
    """Menu > Write Tag: the tag to fix can stay on the reader."""

    def test_offers_the_album_and_the_playlist_playing(self):
        from spotifactory.tasks.capture.steps import ChooseTagTargetStep
        sp = MagicMock()
        sp.current_playback.return_value = {
            "item": {"album": {"uri": "spotify:album:a", "name": "Wildflowers"}},
            "context": {"type": "playlist", "uri": "spotify:playlist:p"}}
        with patch("spotifactory.spotify.get_client", return_value=sp), \
             patch("spotifactory.spotify.uri_name", return_value="Road Trip"):
            out = ChooseTagTargetStep().run(TaskContext())
        assert [i.label for i in out.menu.items] == ["Wildflowers", "Playlist: Road Trip", "Cancel"]
        assert out.menu.items[1].data["uri"] == "spotify:playlist:p"

    def test_fixes_the_tag_on_the_reader_after_asking(self):
        from spotifactory.tasks.capture.steps import WriteChosenTagStep
        step = WriteChosenTagStep()
        ctx = TaskContext(data={"selected": {"uri": "spotify:album:a", "label": "Wildflowers"}})
        reader = _FakeReader(present={"uid": "T", "uri": "spotify:album:wrong"})
        with reader.patch():
            out = step.run(ctx)
            assert not reader.lift_asked                      # no need to lift it off
            assert out.menu.title == "Overwrite tag?"
            ctx.data["selected"] = "overwrite"                # the answer replaces the choice...
            assert isinstance(step.run(ctx), Continue)
        assert reader.writes == [("spotify:album:a", "T")]   # ...but the target was kept


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
        # Data in place before the step starts: it runs on its own thread.
        ctx = TaskContext(display=r.display, dry_run=True,
                          data={"playlist": {"name": "Derpy derp", "labelled": labelled}})
        r._task = _LabelThenBlock(ctx)
        r._task.start_current_step()
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
             patch("spotifactory.tasks.capture.label.add_label",
                   return_value="labelled") as add:
            assert isinstance(FetchPlaylistArtStep().run(ctx), Continue)
        assert add.called is labelled
        assert (ctx.data["image"] == "labelled") is labelled


class TestAlbumNameChoice:
    """Album prints ask too, with No first: most covers already say what they are."""

    def _info(self):
        from spotifactory.spotify import NowPlayingInfo
        return NowPlayingInfo("Track", "Nirvana", "MTV Unplugged In New York",
                              "spotify:album:x", "https://art")

    def test_no_is_selected_first(self):
        from spotifactory.tasks.capture.steps import AlbumLabelStep
        out = AlbumLabelStep().run(TaskContext(data={"info": self._info()}))
        assert out.menu.title == "Add name?"
        assert [(i.label, i.data) for i in out.menu.items] == [("No", "plain"), ("Yes", "label")]
        assert out.menu.subtitle == "MTV Unplugged In New York"
        assert isinstance(out.on_cancel, Cancel)

    @pytest.mark.parametrize("choice, labelled", [("label", True), ("plain", False), (None, False)])
    def test_album_art_gets_name_and_artist_only_when_asked(self, choice, labelled):
        from spotifactory.tasks.capture.steps import FetchArtStep
        data = {"info": self._info()}
        if choice:
            data["selected"] = choice
        ctx = TaskContext(data=data)
        with patch("spotifactory.tasks.capture.steps.requests.get", return_value=MagicMock(content=b"img")), \
             patch("spotifactory.tasks.capture.label.add_label", return_value="labelled") as add:
            assert isinstance(FetchArtStep().run(ctx), Continue)
        assert add.called is labelled
        if labelled:
            assert add.call_args.args[1:] == ("MTV Unplugged In New York", "Nirvana")


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


class TestJoystickHome:
    """Home screen: up cycles repeat; left/right tap to skip, hold to scrub."""

    def _runner(self, duration=200_000, position=60_000, playing=False):
        from spotifactory.tasks.home.steps import HomeScanStep
        r = _runner()
        step = HomeScanStep()
        step.tag_active = True
        step.duration_ms = duration
        step.is_playing = playing
        step.set_position(position)
        r._task = MagicMock(current_step=step)
        patch.object(r, "_in_home_scan", return_value=True).start()
        patch.object(r, "_in_home_mode", return_value=True).start()
        return r, step

    def teardown_method(self):
        patch.stopall()

    def test_tap_skips_when_let_go(self):
        r, _ = self._runner()
        with patch("spotifactory.spotify.next_track") as nxt, \
             patch("spotifactory.spotify.prev_track") as prv:
            r.handle_right()
            nxt.assert_not_called()             # not on the press...
            r.handle_release(+1)
            nxt.assert_called_once()            # ...on letting go
            r.handle_left()
            r.handle_release(-1)
            prv.assert_called_once()

    def test_hold_scrubs_instead_of_skipping(self):
        r, step = self._runner()
        sent = []
        with patch("spotifactory.spotify.seek", side_effect=sent.append), \
             patch("spotifactory.spotify.next_track") as nxt:
            r.handle_right()
            for _ in range(3):
                r.handle_seek_hold(+1)
            r.handle_release(+1)
            assert _wait_for(lambda: r._seek_target is None and not r._seek_sending)
        nxt.assert_not_called()
        assert sent[-1] == 75_000               # 60 s + 3 × 5 s, sent on letting go
        assert step.position_ms() == 75_000

    def test_scrub_stops_at_the_ends(self):
        r, _ = self._runner(position=3_000)
        sent = []
        with patch("spotifactory.spotify.seek", side_effect=sent.append):
            r.handle_left()
            r.handle_seek_hold(-1)
            r.handle_release(-1)
            assert _wait_for(lambda: r._seek_target is None and not r._seek_sending)
        assert sent[-1] == 0

    def test_nothing_to_scrub_without_a_tag(self):
        r, step = self._runner()
        step.tag_active = False
        with patch("spotifactory.spotify.seek") as seek:
            r.handle_seek_hold(+1)
        assert r._seek_target is None
        seek.assert_not_called()

    def test_press_that_wakes_the_screen_does_nothing_else(self):
        r, step = self._runner()
        step.screen_off = True
        with patch("spotifactory.spotify.next_track") as nxt, \
             patch("spotifactory.spotify.seek") as seek:
            r.handle_right()
            r.handle_seek_hold(+1)
            r.handle_release(+1)
        assert not step.screen_off
        nxt.assert_not_called()
        seek.assert_not_called()

    def test_up_cycles_repeat_like_a_cd_player(self):
        r, step = self._runner()
        sent = []
        with patch("spotifactory.spotify.set_repeat", side_effect=sent.append):
            for _ in range(3):
                r.handle_up()
                assert _wait_for(lambda: not r._repeat_busy)
        assert sent == ["context", "track", "off"]
        assert step.repeat_state == "off"

    def test_repeat_reverts_if_the_speaker_refuses(self):
        r, step = self._runner()
        with patch("spotifactory.spotify.set_repeat", side_effect=Exception("403 restricted")):
            r.handle_up()
            assert _wait_for(lambda: not r._repeat_busy)
        assert step.repeat_state == "off"
        assert r._message[:2] == ("Couldn't change", "repeat")

    @pytest.mark.parametrize("repeat, shuffle", [("off", False), ("context", True), ("track", False)])
    def test_home_screen_draws_the_cross(self, repeat, shuffle):
        r, step = self._runner()
        step.status, step.artist = "Song", "Artist"
        step.repeat_state, step.shuffle_active = repeat, shuffle
        r._render_home()
        r._seek_target = 90_000
        r._render_home()                        # scrubbing: position in place of the artist
        texts = [c.args[2] for c in r.display.draw_text.call_args_list]
        assert "Artist" in texts and "1:30 / 3:20" in texts


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
        pins[seengreat._K3] = 0
        assert buttons.read() == "VolUp"
        clock[0] += 0.3
        assert buttons.read() is None          # not held long enough yet
        clock[0] += 0.3
        assert buttons.read() == "VolUp"       # repeating
        clock[0] += 0.05
        assert buttons.read() is None          # not again so soon
        clock[0] += 0.15
        assert buttons.read() == "VolUp"
        pins[seengreat._K3] = 1
        assert buttons.read() is None
        pins[seengreat._K1] = 0
        assert buttons.read() == "Menu"
        clock[0] += 2.0
        assert buttons.read() is None          # the menu button never repeats


def test_left_right_report_holds_and_release():
    from spotifactory.input import seengreat
    pins, clock = {}, [100.0]
    gpio = MagicMock()
    gpio.input.side_effect = lambda pin: pins.get(pin, 1)
    with patch.object(seengreat, "GPIO", gpio), \
         patch.object(seengreat.time, "monotonic", lambda: clock[0]):
        buttons = seengreat.SeenGreatInput()
        pins[seengreat._RIGHT] = 0
        assert buttons.read() == "Right"
        clock[0] += 0.3
        assert buttons.read() is None           # a tap so far
        clock[0] += 0.3
        assert buttons.read() == "RightHold"
        clock[0] += 0.2
        assert buttons.read() == "RightHold"
        pins[seengreat._RIGHT] = 1
        assert buttons.read() == "RightRelease"
        assert buttons.read() is None
        pins[seengreat._RIGHT] = 0              # straight from left to right: both reported
        buttons.read()
        pins[seengreat._RIGHT], pins[seengreat._LEFT] = 1, 0
        assert buttons.read() == "RightRelease"
        assert buttons.read() == "Left"


class TestMenuButton:
    """K3 opens the menu from home and closes it from any depth."""

    def test_opens_the_menu_from_home(self):
        r = _runner(home=_FakeHome)
        with patch.object(r, "_in_home_mode", return_value=True), \
             patch.object(r, "_in_home_scan", return_value=True), \
             patch.object(r, "_open_menu_from_home") as open_menu:
            r.handle_menu()
        open_menu.assert_called_once()

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


class TestDisplayModes:
    """Pressing the joystick on the home screen cycles now playing → time → album."""

    def _runner(self):
        from spotifactory.tasks.home.steps import HomeScanStep
        r = _runner()
        step = HomeScanStep()
        step.tag_active, step.status, step.artist = True, "Song", "Artist"
        step.duration_ms, step.track_number, step.total_tracks = 200_000, 3, 14
        step.album_name, step.album_length_ms = "Album", 31 * 60_000 + 20_000
        step.set_position(41_000)
        r._task = MagicMock(current_step=step)
        patch.object(r, "_in_home_scan", return_value=True).start()
        return r, step

    def teardown_method(self):
        patch.stopall()

    def _texts(self, r):
        return [c.args[2] for c in r.display.draw_text.call_args_list]

    def test_press_cycles_the_screens(self):
        r, _ = self._runner()
        seen = []
        for _ in range(4):
            seen.append(r._display_mode)
            r.handle_select()
        assert seen == ["now", "time", "album", "now"]

    def test_time_and_album_screens(self):
        r, _ = self._runner()
        r._display_mode = "time"
        r._render_home()
        assert self._texts(r) == []             # all seven-segment and pixel font
        r._display_mode = "album"
        r._render_home()
        assert self._texts(r)[:2] == ["Album", "Artist"]

    def test_screens_cycle_with_nothing_playing(self):
        r, step = self._runner()
        step.tag_active, step.status, step.artist = False, "Place tag...", ""
        r.handle_select()
        assert r._display_mode == "time"
        r._render_home()
        assert self._texts(r) == []             # dashes, in seven-segment
        r.handle_select()
        r._render_home()
        assert self._texts(r) == ["Place tag..."]

    def test_now_playing_shows_track_count_and_progress(self):
        r, step = self._runner()
        step.is_playing = False                 # hold the position still
        r._render_home()
        assert self._texts(r) == ["Song", "Artist", "3/14"]
        # 41 s into 3:20 fills the bottom edge about a fifth of the way.
        assert call(0, 62, round(127 * 41 / 200), 63) in r.display.draw_rect.call_args_list

    def test_now_playing_track_count_sits_against_the_right_edge(self):
        r, step = self._runner()
        r.display.text_width.side_effect = lambda t: 6 * len(t)
        r._render_home()
        x = next(c.args[0] for c in r.display.draw_text.call_args_list if c.args[2] == "3/14")
        assert x == 126 - 6 * len("3/14")

    def test_now_playing_without_a_tag_has_no_count_or_bar(self):
        r, step = self._runner()
        step.tag_active, step.status, step.artist = False, "Place tag...", ""
        r._render_home()
        assert self._texts(r) == ["Place tag..."]
        assert not [c for c in r.display.draw_rect.call_args_list if c.args[1] >= 62]

    def test_press_that_wakes_the_screen_keeps_the_mode(self):
        r, step = self._runner()
        step.screen_off = True
        r.handle_select()
        assert r._display_mode == "now" and not step.screen_off


def test_album_length_adds_up_every_page_and_is_remembered():
    from spotifactory import spotify
    sp = MagicMock()
    page2 = {"items": [{"duration_ms": 3}], "next": None}
    sp.album_tracks.return_value = {"items": [{"duration_ms": 1}, {"duration_ms": 2}], "next": "p2"}
    sp.next.return_value = page2
    spotify._album_lengths.clear()
    with patch("spotifactory.spotify.get_client", return_value=sp):
        assert spotify.album_length_ms("spotify:album:x") == 6
        assert spotify.album_length_ms("spotify:album:x") == 6
    sp.album_tracks.assert_called_once()


class TestHomeComesBackFromTheMenu:
    """Leaving for the menu and back: the home screen returns as it was, not
    blank until the reader sees the tag again."""

    def _start(self, monkeypatch):
        from spotifactory.hardware import rfid
        from spotifactory.tasks.home.steps import HomeScanStep
        reader = {}

        def fake_watch(on_place, on_remove, terminate):
            reader["place"] = on_place
            while not terminate():
                time.sleep(0.01)

        monkeypatch.setattr(rfid, "watch_tags", fake_watch)
        monkeypatch.setattr("spotifactory.spotify.get_now_playing", lambda include_paused=False: None)
        step = HomeScanStep()
        threading.Thread(target=step.run, args=(TaskContext(dry_run=True),), daemon=True).start()
        assert _wait_for(lambda: "place" in reader)
        return step, reader

    def _leave_with_a_tag_down(self):
        from spotifactory.tasks.home.steps import HomeScanStep
        old = HomeScanStep()
        old.tag_active, old.tag_uri = True, "spotify:album:x"
        old.status, old.artist, old.track_number = "Song", "Artist", 3
        HomeScanStep.remember(old)

    def test_comes_back_as_it_was_and_stays_when_the_tag_is_seen(self, monkeypatch):
        self._leave_with_a_tag_down()
        step, reader = self._start(monkeypatch)
        assert (step.status, step.artist, step.track_number, step.tag_active) == ("Song", "Artist", 3, True)
        reader["place"]({"uid": "u", "uri": "spotify:album:x"})
        assert step.status == "Song"            # no "Loading..." flash for the same album
        step.cancel()

    def test_falls_back_to_place_tag_if_the_tag_was_lifted(self, monkeypatch):
        monkeypatch.setattr("spotifactory.tasks.home.steps._CARRY_SECS", 0.1)
        self._leave_with_a_tag_down()
        step, _ = self._start(monkeypatch)
        assert _wait_for(lambda: not step.tag_active)
        assert step.status == "Place tag..."
        step.cancel()

    def test_nothing_carried_without_a_tag(self):
        from spotifactory.tasks.home.steps import HomeScanStep
        HomeScanStep.remember(HomeScanStep())
        assert HomeScanStep._carried is None
