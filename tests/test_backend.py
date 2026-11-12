"""The music backend layer (spotifactory/backend) and first-boot login."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from spotifactory.tasks.base import Cancel, Done, Step, Task, TaskContext


def _wait_for(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


APPLE = "https://music.apple.com/us/album/wildflowers/1"


class TestBackendChoice:
    def test_spotify_is_the_default(self, monkeypatch):
        from spotifactory import backend, spotify
        monkeypatch.delenv("MUSIC_BACKEND", raising=False)
        assert backend.name() == "spotify"
        assert backend.current() is spotify
        assert backend.label() == "Spotify"

    def test_unknown_backend_falls_back_to_spotify(self, monkeypatch):
        from spotifactory import backend, spotify
        monkeypatch.setenv("MUSIC_BACKEND", "nonsense")
        assert backend.current() is spotify

    def test_calls_reach_the_backend_when_it_is_patched(self):
        from spotifactory import backend
        with patch("spotifactory.spotify.next_track") as nxt:
            backend.next_track()
        nxt.assert_called_once()


class TestSpotifyPickUri:
    @pytest.mark.parametrize("uris,expected", [
        (["spotify:album:a"], "spotify:album:a"),
        ([APPLE, "spotify:album:a"], "spotify:album:a"),
        (["https://open.spotify.com/album/abc123?si=x"], "spotify:album:abc123"),
        (["https://open.spotify.com/intl-de/playlist/P1"], "spotify:playlist:P1"),
        ([APPLE], None),
        ([], None),
    ])
    def test_first_spotify_link(self, uris, expected):
        from spotifactory.spotify import pick_uri
        assert pick_uri(uris) == expected


class TestTagsWithOtherLinksFirst:
    def _home(self, monkeypatch):
        from spotifactory.hardware import rfid
        from spotifactory.tasks.home.steps import HomeScanStep
        HomeScanStep._carried = None
        reader = {}

        def fake_watch(on_place, on_remove, terminate):
            reader["place"], reader["remove"] = on_place, on_remove
            while not terminate():
                time.sleep(0.01)

        monkeypatch.setattr(rfid, "watch_tags", fake_watch)
        monkeypatch.setattr("spotifactory.spotify.get_now_playing", lambda include_paused=False: None)
        step = HomeScanStep()
        threading.Thread(target=step.run, args=(TaskContext(dry_run=True),), daemon=True).start()
        assert _wait_for(lambda: "place" in reader)
        return step, reader

    def test_home_plays_the_spotify_link_even_when_it_is_not_first(self, monkeypatch):
        step, reader = self._home(monkeypatch)
        reader["place"]({"uid": "u", "uri": APPLE, "uris": [APPLE, "spotify:album:a"]})
        assert step.tag_uri == "spotify:album:a" and step.tag_active
        step.cancel()

    def test_home_says_so_when_there_is_no_spotify_link(self, monkeypatch):
        step, reader = self._home(monkeypatch)
        reader["place"]({"uid": "u", "uri": APPLE, "uris": [APPLE]})
        assert (step.status, step.artist) == ("No Spotify link", "on this tag")
        assert not step.tag_active
        reader["remove"]({"uid": "u"})
        assert step.status == "Place tag..."
        step.cancel()

    def test_scan_tag_skips_to_the_spotify_link(self):
        from spotifactory.tasks.play_tag.steps import ScanStep
        ctx = TaskContext(dry_run=False)
        card = {"uid": "u", "uri": APPLE, "uris": [APPLE, "spotify:album:a"]}
        with patch("spotifactory.hardware.rfid.read_card", return_value=card):
            ScanStep().run(ctx)
        assert ctx.data["uri"] == "spotify:album:a"

    def test_scan_tag_with_no_spotify_link(self):
        from spotifactory.tasks.play_tag.steps import ScanStep
        step, ctx = ScanStep(), TaskContext(dry_run=False)
        step.show_for = MagicMock()
        with patch("spotifactory.hardware.rfid.read_card", return_value={"uid": "u", "uri": APPLE, "uris": [APPLE]}):
            assert isinstance(step.run(ctx), Done)
        step.show_for.assert_called_once_with("No Spotify link", 3.0)


class TestSpotifyPlayTag:
    def test_restricted_speaker_without_helper_pauses_over_sonos_on_lift(self):
        from spotifactory import spotify
        dev = spotify.DeviceInfo("sonos", restricted=True, name="Den")
        with patch.object(spotify, "get_current_context", return_value=(None, None)), \
             patch.object(spotify, "get_active_device", return_value=None), \
             patch.object(spotify, "find_device_by_name", return_value=None), \
             patch.object(spotify, "get_playback_device", return_value=dev), \
             patch("spotifactory.connect.available", return_value=False):
            result = spotify.play_tag("spotify:album:a")
        assert result.message == ("Start in Spotify,", "tag removes pauses")
        with patch("spotifactory.hardware.sonos.pause_speaker") as sonos_pause, \
             patch.object(spotify, "pause") as web_pause:
            spotify.stop_tag()
        sonos_pause.assert_called_once_with("Den")
        web_pause.assert_not_called()

    def test_resumes_when_the_tag_is_already_loaded(self):
        from spotifactory import spotify
        with patch.object(spotify, "get_current_context", return_value=("spotify:album:a", None)), \
             patch.object(spotify, "get_active_device", return_value=None), \
             patch.object(spotify, "find_device_by_name", return_value={"id": "box"}), \
             patch.object(spotify, "get_client"), \
             patch.object(spotify, "start_playback") as start:
            assert spotify.play_tag("spotify:album:a").message is None
        start.assert_called_once_with("box", None, restricted=None)

    def test_chosen_speaker_not_listed(self):
        from spotifactory import spotify
        chosen = spotify.ChosenDevice("echo", "Kitchen Echo")
        with patch.object(spotify, "get_current_context", return_value=(None, None)), \
             patch.object(spotify, "get_active_device", return_value=chosen), \
             patch.object(spotify, "resolve_chosen_device", return_value=None):
            assert spotify.play_tag("spotify:album:a").message == ("Kitchen Echo", "not available")


class _IdleStep(Step):
    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, ctx):
        self._cancel.wait(2)
        return Cancel()


class _Home(Task):
    name = "home"
    steps = [("idle", _IdleStep)]


class TestFirstBootLogin:
    """A new box opens on the Spotify login; Menu leaves it for the main menu."""

    def _runner(self, monkeypatch):
        from spotifactory.menu.catalog import MENUS
        from spotifactory.runner import Runner
        from spotifactory.tasks.reauth.steps import QRAuthStep
        from spotifactory.tasks.reauth import FirstBootLoginTask

        def waiting_run(step, ctx):
            step.qr_image = MagicMock(width=20)
            step._cancel.wait(2)
            return Cancel()

        monkeypatch.setattr(QRAuthStep, "run", waiting_run)
        return Runner(MagicMock(), MENUS, dry_run=True, home_task_class=_Home,
                      first_task_class=FirstBootLoginTask)

    def test_opens_on_the_login(self, monkeypatch):
        from spotifactory.tasks.reauth import FirstBootLoginTask
        r = self._runner(monkeypatch)
        assert isinstance(r._task, FirstBootLoginTask)
        assert _wait_for(r._in_qr_auth)

    def test_menu_button_goes_to_the_main_menu(self, monkeypatch):
        r = self._runner(monkeypatch)
        assert _wait_for(r._in_qr_auth)
        r.handle_menu()
        assert _wait_for(lambda: (r.tick(), r._task is None)[1])
        assert r.nav.current.menu.title == "Main Menu"

    def test_connect_spotify_from_the_menu_still_returns_home(self, monkeypatch):
        from spotifactory.tasks.reauth import ReAuthTask
        r = self._runner(monkeypatch)
        r._start_task(ReAuthTask)
        assert _wait_for(r._in_qr_auth)
        r.handle_menu()
        assert _wait_for(lambda: (r.tick(), not isinstance(r._task, ReAuthTask))[1])
        assert isinstance(r._task, _Home)       # the home screen, not the menu
