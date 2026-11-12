"""Music Assistant mode: the MA backend, its setup page and the menus."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from spotifactory import music_assistant as ma
from spotifactory.tasks.base import Done, TaskContext

SPOTIFY_URL = "https://open.spotify.com/album/abc"
APPLE_URL = "https://music.apple.com/us/album/x/1"


def _wait_for(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _ma_env(monkeypatch):
    monkeypatch.setenv("MUSIC_BACKEND", "music_assistant")
    monkeypatch.setenv("MA_URL", "http://ma.local:8095")
    monkeypatch.setenv("MA_TOKEN", "tok")
    monkeypatch.setenv("MA_PLAYER", "kitchen")
    ma._resolved.clear()
    ma._albums.clear()


class FakeMA:
    """Stands in for the server: answers commands from a table, records them."""

    def __init__(self, queues=None, players=None, items=None, tracks=None):
        self.queues = queues or {}
        self.players = players or [{"player_id": "kitchen", "name": "Kitchen", "available": True}]
        self.items = items or {}
        self.tracks = tracks or []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, command, **args):
        self.calls.append((command, args))
        if command == "players/all":
            return self.players
        if command == "player_queues/get_active_queue":
            return self.queues.get(args["player_id"])
        if command == "player_queues/all":
            return list(self.queues.values())
        if command == "music/item_by_uri":
            if args["uri"] not in self.items:
                raise ma.MAError("no provider")
            return self.items[args["uri"]]
        if command == "music/albums/album_tracks":
            return self.tracks
        return None

    def sent(self, command):
        return [a for c, a in self.calls if c == command]


def _queue(state="playing", album=None, **extra):
    album = album if album is not None else {
        "name": "Wildflowers", "uri": "spotify://album/abc", "item_id": "abc", "provider": "spotify"}
    q = {"queue_id": "kitchen", "display_name": "Kitchen", "state": state,
         "shuffle_enabled": False, "repeat_mode": "all", "elapsed_time": 61,
         "current_item": {"name": "You Don't Know How It Feels", "duration": 290,
                          "image": {"path": "abc.jpg", "provider": "spotify", "proxy_id": "p1"},
                          "media_item": {"name": "You Don't Know How It Feels", "uri": "spotify://track/t",
                                         "track_number": 3, "artists": [{"name": "Tom Petty"}],
                                         "album": album,
                                         "provider_mappings": [{"provider_instance": "spotify"}]}}}
    q.update(extra)
    return q


ALBUM_ITEM = {"name": "Wildflowers", "uri": "spotify://album/abc", "item_id": "abc", "provider": "spotify",
              "media_type": "album",
              "provider_mappings": [
                  {"item_id": "1", "provider_instance": "apple_music", "provider_domain": "apple_music",
                   "url": APPLE_URL},
                  {"item_id": "abc", "provider_instance": "spotify", "provider_domain": "spotify",
                   "url": SPOTIFY_URL}]}


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------

class FakeSocket:
    def __init__(self, schema=28, auth_ok=True):
        self.inbox = [json.dumps({"server_id": "s", "schema_version": schema,
                                  "base_url": "http://10.0.0.2:8095"})]
        self.sent: list[dict] = []
        self.auth_ok = auth_ok

    def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        mid = msg["message_id"]
        if msg["command"] == "auth":
            self.inbox.append(json.dumps({"message_id": mid, "result": self.auth_ok}))
        elif msg["command"] == "players/all":
            self.inbox.append(json.dumps({"event": "player_updated", "data": {}}))   # skipped
            self.inbox.append(json.dumps({"message_id": mid, "result": [{"player_id": "a"}],
                                          "partial": True}))
            self.inbox.append(json.dumps({"message_id": mid, "result": [{"player_id": "b"}]}))
        else:
            self.inbox.append(json.dumps({"message_id": mid, "error_code": 999, "details": "nope"}))

    def recv(self):
        return self.inbox.pop(0)

    def close(self):
        pass


class TestClient:
    @pytest.mark.parametrize("url,ws", [
        ("http://ma.local:8095", "ws://ma.local:8095/ws"),
        ("https://ma.example.com/", "wss://ma.example.com/ws"),
        ("10.0.0.2:8095", "ws://10.0.0.2:8095/ws"),
    ])
    def test_ws_url(self, url, ws):
        assert ma.ws_url(url) == ws

    def test_authenticates_then_joins_partial_results(self):
        sock = FakeSocket()
        with patch("websocket.create_connection", return_value=sock):
            client = ma.Client("http://ma.local:8095", "tok")
            assert client.call("players/all") == [{"player_id": "a"}, {"player_id": "b"}]
        assert sock.sent[0]["command"] == "auth" and sock.sent[0]["args"] == {"token": "tok"}
        assert client.base_url == "http://10.0.0.2:8095"

    def test_rejected_token(self):
        with patch("websocket.create_connection", return_value=FakeSocket(auth_ok=False)), \
             pytest.raises(ma.MAAuthError):
            ma.Client("http://ma.local:8095", "bad").call("players/all")

    def test_command_error(self):
        with patch("websocket.create_connection", return_value=FakeSocket()), \
             pytest.raises(ma.MAError, match="nope"):
            ma.Client("http://ma.local:8095", "tok").call("player_queues/next", queue_id="q")

    def test_unreachable(self):
        with patch("websocket.create_connection", side_effect=OSError("refused")), \
             pytest.raises(ma.MAOffline):
            ma.Client("http://ma.local:8095", "tok").call("players/all")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    def test_backend_is_music_assistant(self):
        from spotifactory import backend
        assert backend.current() is ma and backend.label() == "Music Assistant"

    def test_picks_the_first_link_ma_can_play(self):
        fake = FakeMA(items={SPOTIFY_URL: ALBUM_ITEM})
        with patch.object(ma, "_call", fake):
            assert ma.pick_uri([APPLE_URL, SPOTIFY_URL]) == SPOTIFY_URL
            assert ma.pick_uri([APPLE_URL]) is None

    def test_offline_keeps_the_first_link_so_play_can_say_so(self):
        with patch.object(ma, "_call", side_effect=ma.MAOffline("down")):
            assert ma.pick_uri([APPLE_URL, SPOTIFY_URL]) == APPLE_URL
            assert ma.play_tag(APPLE_URL).message == ("Music Assistant", "offline")

    def test_starts_the_album_on_the_chosen_speaker(self):
        fake = FakeMA(queues={"kitchen": _queue(album={"name": "Other", "uri": "x://album/9"})},
                      items={SPOTIFY_URL: ALBUM_ITEM})
        with patch.object(ma, "_call", fake):
            assert ma.play_tag(SPOTIFY_URL).message is None
        assert fake.sent("player_queues/play_media") == [
            {"queue_id": "kitchen", "media": SPOTIFY_URL, "option": "replace"}]

    def test_resumes_when_the_album_is_already_loaded(self):
        fake = FakeMA(queues={"kitchen": _queue(state="paused")}, items={SPOTIFY_URL: ALBUM_ITEM})
        with patch.object(ma, "_call", fake):
            ma.play_tag(SPOTIFY_URL)
        assert fake.sent("player_queues/play") == [{"queue_id": "kitchen"}]
        assert not fake.sent("player_queues/play_media")

    def test_no_speaker(self, monkeypatch):
        monkeypatch.delenv("MA_PLAYER")
        fake = FakeMA(players=[{"player_id": "den", "name": "Den"}])
        with patch.object(ma, "_call", fake):
            assert ma.play_tag(SPOTIFY_URL).message == ("No speaker:", "Up > Choose Speaker")

    def test_defaults_to_the_box_s_own_player(self, monkeypatch):
        monkeypatch.delenv("MA_PLAYER")
        fake = FakeMA(players=[{"player_id": "den", "name": "Den"},
                               {"player_id": "aa:bb", "name": "Spotifactory"}])
        with patch.object(ma, "_call", fake):
            ma.play_tag(SPOTIFY_URL)
        assert fake.sent("player_queues/play_media")[0]["queue_id"] == "aa:bb"

    def test_lifting_the_tag_pauses(self):
        fake = FakeMA(queues={"kitchen": _queue()})
        with patch.object(ma, "_call", fake):
            ma.stop_tag()
        assert fake.sent("player_queues/pause") == [{"queue_id": "kitchen"}]


# ---------------------------------------------------------------------------
# Now playing and print
# ---------------------------------------------------------------------------

class TestNowPlaying:
    def test_what_ma_is_playing(self):
        fake = FakeMA(queues={"kitchen": _queue()}, items={"spotify://album/abc": ALBUM_ITEM},
                      tracks=[{"duration": 100}, {"duration": 200}])
        client = MagicMock(base_url="http://10.0.0.2:8095")
        with patch.object(ma, "_call", fake), patch.object(ma, "get_client", return_value=client):
            info = ma.get_now_playing()
        assert (info.track_name, info.artist_name, info.album_name) == (
            "You Don't Know How It Feels", "Tom Petty", "Wildflowers")
        # The playing service's public link first, then the others: for the tag.
        assert info.links == [SPOTIFY_URL, APPLE_URL] and info.album_uri == SPOTIFY_URL
        assert info.artwork_url == "http://10.0.0.2:8095/imageproxy/p1?size=800"
        assert info.repeat_state == "context" and info.total_tracks == 2
        assert info.duration_ms == 290_000 and info.progress_ms >= 61_000
        assert ma.album_length_ms(SPOTIFY_URL) == 300_000

    def test_print_falls_back_to_any_speaker_that_is_playing(self):
        fake = FakeMA(queues={"kitchen": _queue(state="idle"),
                              "den": dict(_queue(), queue_id="den", display_name="Den")})
        client = MagicMock(base_url="http://ma")
        with patch.object(ma, "_call", fake), patch.object(ma, "get_client", return_value=client):
            assert ma.get_now_playing().device_name == "Den"
            # The home screen only follows the chosen speaker.
            assert ma.get_now_playing(include_paused=True).device_name == "Kitchen"

    def test_nothing_playing(self):
        fake = FakeMA(queues={"kitchen": _queue(state="idle")})
        with patch.object(ma, "_call", fake):
            assert ma.get_now_playing() is None

    def test_print_writes_every_service_link_that_fits(self):
        from spotifactory.tasks.capture.steps import ScanStep
        from spotifactory.backend.types import NowPlayingInfo
        info = NowPlayingInfo("t", "a", "Wildflowers", SPOTIFY_URL, None,
                              links=[SPOTIFY_URL, APPLE_URL, "https://tidal.com/album/1" + "x" * 80])
        assert ScanStep()._extra(TaskContext(data={"info": info})) == info.links[1:]
        from spotifactory.tasks.capture.steps import _fit
        assert _fit(SPOTIFY_URL, info.links[1:]) == [APPLE_URL]   # the long one doesn't fit


class TestControls:
    def test_buttons_go_to_the_chosen_queue(self):
        fake = FakeMA(queues={"kitchen": _queue()})
        with patch.object(ma, "_call", fake):
            ma.next_track()
            ma.prev_track()
            ma.seek(65_500)
            ma.set_repeat("track")
            assert ma.toggle_shuffle() is True
            assert ma.play_pause() is False
        assert fake.sent("player_queues/seek") == [{"queue_id": "kitchen", "position": 65}]
        assert fake.sent("player_queues/repeat") == [{"queue_id": "kitchen", "repeat_mode": "one"}]
        assert fake.sent("player_queues/shuffle") == [{"queue_id": "kitchen", "shuffle_enabled": True}]
        assert fake.sent("player_queues/pause") == [{"queue_id": "kitchen"}]

    def test_volume(self):
        fake = FakeMA(players=[{"player_id": "kitchen", "name": "Kitchen", "volume_level": 40}])
        with patch.object(ma, "_call", fake):
            assert ma.get_volume() == 40
            ma.set_volume(55)
        assert fake.sent("players/cmd/volume_set") == [{"player_id": "kitchen", "volume_level": 55}]

    def test_print_pauses_only_the_box_s_own_speaker(self):
        fake = FakeMA(queues={"kitchen": _queue()})
        with patch.object(ma, "_call", fake):
            assert ma.pause_if_local() is False
        fake = FakeMA(queues={"kitchen": dict(_queue(), display_name="Spotifactory")})
        with patch.object(ma, "_call", fake):
            assert ma.pause_if_local() is True


class TestSpeakers:
    def test_lists_ma_players(self):
        fake = FakeMA(players=[{"player_id": "k", "name": "Kitchen", "playback_state": "playing"},
                               {"player_id": "x", "name": "Gone", "available": False},
                               {"player_id": "b", "name": "Spotifactory"}])
        with patch.object(ma, "_call", fake):
            assert [(d["name"], d["is_active"]) for d in ma.list_speakers()] == [
                ("Kitchen", True), ("Spotifactory", False)]

    def test_choosing_moves_what_is_playing(self):
        fake = FakeMA(queues={"kitchen": _queue()})
        with patch.object(ma, "_call", fake), patch("spotifactory.settings.save_setting") as save:
            ma.choose_speaker({"id": "den", "name": "Den"})
        save.assert_any_call("MA_PLAYER", "den")
        assert fake.sent("player_queues/transfer") == [
            {"source_queue_id": "kitchen", "target_queue_id": "den", "auto_play": True}]


# ---------------------------------------------------------------------------
# Menus and setup
# ---------------------------------------------------------------------------

class TestMenus:
    def _labels(self):
        from spotifactory.menu.catalog import MENUS
        from spotifactory.menu.navigation import NavState
        return [i.label for i in NavState(MENUS["main"]).items]

    def test_spotify_only_items_hide_in_ma_mode(self, monkeypatch):
        assert "Print Playlist" not in self._labels() and "Connect Spotify" not in self._labels()
        assert "Music Source" in self._labels() and "Print Album" in self._labels()
        monkeypatch.setenv("MUSIC_BACKEND", "spotify")
        assert "Print Playlist" in self._labels() and "Connect Spotify" in self._labels()

    def test_selection_stays_in_range_when_items_hide(self, monkeypatch):
        from spotifactory.menu.catalog import MENUS
        from spotifactory.menu.navigation import NavState
        monkeypatch.setenv("MUSIC_BACKEND", "spotify")
        state = NavState(MENUS["main"])
        state.selected_index = len(state.items) - 1
        monkeypatch.setenv("MUSIC_BACKEND", "music_assistant")
        assert state.selected_item.label == state.items[-1].label


class TestSetupPage:
    def _start(self, monkeypatch, step_class=None):
        from spotifactory.tasks.music_source import steps
        monkeypatch.setattr(steps, "SETUP_PORT", 0)
        monkeypatch.setattr(steps, "_local_ip", lambda: "127.0.0.1")
        step = (step_class or steps.MAServerStep)()
        out = {}
        threading.Thread(target=lambda: out.setdefault("outcome", step.run(TaskContext(dry_run=False))),
                         daemon=True).start()
        assert _wait_for(lambda: step.qr_image is not None)
        return step, out

    def _post(self, page_url, **fields):
        data = urllib.parse.urlencode(fields).encode()
        with urllib.request.urlopen(page_url, data=data, timeout=5) as r:
            return r.read().decode()

    def test_connects_saves_and_switches(self, monkeypatch):
        with patch.object(ma, "check", return_value=4) as check, \
             patch("spotifactory.settings.save_setting") as save, \
             patch("spotifactory.services.apply") as services, \
             patch("spotifactory.tasks.base.time.sleep"):
            step, out = self._start(monkeypatch)
            page = urllib.request.urlopen(step.session_url, timeout=5).read().decode()
            assert 'name="token"' in page
            page = self._post(step.session_url, url="10.0.0.2:8095", token="tok")
            assert "Connected" in page and "4 speakers" in page
            assert _wait_for(lambda: "outcome" in out, timeout=6)
        check.assert_called_once_with("http://10.0.0.2:8095", "tok")
        save.assert_any_call("MA_URL", "http://10.0.0.2:8095")
        save.assert_any_call("MA_TOKEN", "tok")
        save.assert_any_call("MA_SERVER_HOST", "10.0.0.2")
        save.assert_any_call("MUSIC_BACKEND", "music_assistant")
        services.assert_called_once_with("music_assistant")
        assert isinstance(out["outcome"], Done)

    def test_bad_token_asks_again(self, monkeypatch):
        with patch.object(ma, "check", side_effect=ma.MAAuthError("no")), \
             patch("spotifactory.settings.save_setting") as save:
            step, out = self._start(monkeypatch)
            page = self._post(step.session_url, url="http://ma:8095", token="bad")
            assert "didn't accept that token" in page and 'value="http://ma:8095"' in page
            step.cancel()
            assert _wait_for(lambda: "outcome" in out)
        save.assert_not_called()

    def test_saved_settings_switch_straight_away(self, monkeypatch):
        from spotifactory.tasks.music_source.steps import MASetupStep
        step = MASetupStep()
        with patch.object(ma, "has_login", return_value=True), \
             patch("spotifactory.settings.save_setting") as save, \
             patch("spotifactory.services.apply"), \
             patch("spotifactory.tasks.base.time.sleep"):
            assert isinstance(step.run(TaskContext(dry_run=False)), Done)
        save.assert_called_once_with("MUSIC_BACKEND", "music_assistant")

    def test_back_to_spotify_logs_in_if_needed(self):
        from spotifactory.tasks.base import Continue
        from spotifactory.tasks.music_source.steps import UseSpotifyStep
        with patch("spotifactory.settings.save_setting") as save, \
             patch("spotifactory.services.apply") as services, \
             patch("spotifactory.spotify.has_login", return_value=False):
            assert isinstance(UseSpotifyStep().run(TaskContext(dry_run=False)), Continue)
        save.assert_called_once_with("MUSIC_BACKEND", "spotify")
        services.assert_called_once_with("spotify")


def test_services_swap_the_receivers():
    from spotifactory import services
    with patch.object(services, "_systemctl_user") as ctl:
        services.apply("music_assistant")
    assert ctl.call_args_list[1:] == [
        (("disable", "--now", "raspotify"),), (("enable", "squeezelite"),), (("restart", "squeezelite"),)]
