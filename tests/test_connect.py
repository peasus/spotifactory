"""Sonos through the Connect route: the helper pipe, routing and discovery."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from spotifactory.tasks.base import Done, TaskContext

# Stands in for the Rust helper: logs each request, answers ok, or errors for "to": "bad".
_FAKE_HELPER = """#!{python}
import json, sys
log = open({log!r}, "a")
log.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n"); log.flush()
for line in sys.stdin:
    req = json.loads(line)
    log.write(line); log.flush()
    if req.get("to") == "die":
        sys.exit(3)
    ok = req.get("to") != "bad"
    print(json.dumps({{"ok": ok, "error": None if ok else "Restriction violated"}}), flush=True)
"""


@pytest.fixture
def fake_helper(tmp_path, monkeypatch):
    log = tmp_path / "requests.log"
    script = tmp_path / "spotifactory-connect"
    script.write_text(_FAKE_HELPER.format(python=sys.executable, log=str(log)))
    script.chmod(0o755)
    monkeypatch.setenv("SPOTIFACTORY_CONNECT_HELPER", str(script))
    monkeypatch.setenv("SPOTIFACTORY_LIBRESPOT_CACHE", str(tmp_path / "cache"))
    from spotifactory import connect
    connect._helper._stop()
    yield lambda: [json.loads(line) for line in log.read_text().splitlines()]
    connect._helper._stop()


class TestHelperPipe:
    def test_play_sends_the_album_as_a_context(self, fake_helper):
        from spotifactory import connect
        connect.play("sonos-1", "spotify:album:abc")
        start, request = fake_helper()
        assert start["argv"][:1] == ["--cache"]
        assert request["op"] == "command" and request["to"] == "sonos-1"
        command = request["body"]["command"]
        assert command["endpoint"] == "play"
        assert command["context"] == {"uri": "spotify:album:abc",
                                      "url": "context://spotify:album:abc", "metadata": {}}

    def test_one_helper_serves_every_command(self, fake_helper):
        from spotifactory import connect
        connect.pause("s")
        connect.next_track("s")
        connect.seek("s", -5)
        connect.repeat("s", "track")
        endpoints = [r.get("body", {}).get("command") for r in fake_helper()[1:]]
        assert len([r for r in fake_helper() if "argv" in r]) == 1
        assert endpoints[0] == {"endpoint": "pause"}
        assert endpoints[1] == {"endpoint": "skip_next"}
        assert endpoints[2] == {"endpoint": "seek_to", "value": 0}
        assert endpoints[3] == {"endpoint": "set_options", "repeating_context": True,
                                "repeating_track": True}

    def test_a_refused_command_raises_with_spotifys_reason(self, fake_helper):
        from spotifactory import connect
        with pytest.raises(connect.ConnectError, match="Restriction violated"):
            connect.pause("bad")

    def test_a_dead_helper_is_restarted_once(self, fake_helper):
        from spotifactory import connect
        with pytest.raises(connect.ConnectError):
            connect.pause("die")          # dies on the first try and on the retry
        connect.pause("s")                # a fresh helper takes the next command
        starts = [r for r in fake_helper() if "argv" in r]
        assert len(starts) == 3

    def test_missing_helper_is_not_available(self, monkeypatch, tmp_path):
        from spotifactory import connect
        monkeypatch.setenv("SPOTIFACTORY_CONNECT_HELPER", str(tmp_path / "nope"))
        with patch.object(connect, "Path") as path:
            path.home.return_value = tmp_path
            with patch.object(connect, "_REPO", tmp_path):
                assert connect.helper_path() is None


@pytest.fixture
def chosen_sonos(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    env = {"SPOTIFACTORY_DEVICE_ID": "sonos-1", "SPOTIFACTORY_DEVICE_NAME": "Living Room",
           "SPOTIFACTORY_DEVICE_RESTRICTED": "1"}
    with patch.dict("os.environ", env), \
         patch("spotifactory.settings.env_path", return_value=str(env_file)), \
         patch("spotifactory.connect.available", return_value=True):
        yield


class TestRouting:
    def test_tag_on_a_chosen_sonos_goes_through_connect(self, chosen_sonos):
        from spotifactory import spotify
        sp = MagicMock()
        with patch("spotifactory.spotify.get_client", return_value=sp), \
             patch("spotifactory.connect.play") as play, \
             patch("spotifactory.connect.resume") as resume:
            spotify.start_playback("sonos-1", "spotify:album:abc")
            spotify.start_playback("sonos-1")
        play.assert_called_once_with("sonos-1", "spotify:album:abc")
        resume.assert_called_once_with("sonos-1")
        sp.start_playback.assert_not_called()

    def test_other_speakers_still_use_the_web_api(self, chosen_sonos):
        from spotifactory import spotify
        sp = MagicMock()
        with patch("spotifactory.spotify.get_client", return_value=sp), \
             patch("spotifactory.connect.play") as play:
            spotify.start_playback("echo-1", "spotify:album:abc")
        sp.start_playback.assert_called_once_with(context_uri="spotify:album:abc",
                                                  device_id="echo-1")
        play.assert_not_called()

    def test_buttons_control_the_chosen_sonos(self, chosen_sonos):
        from spotifactory import spotify
        sp = MagicMock()
        sp.current_playback.return_value = {"shuffle_state": False}
        with patch("spotifactory.spotify.get_client", return_value=sp), \
             patch("spotifactory.connect.next_track") as nxt, \
             patch("spotifactory.connect.pause") as pause, \
             patch("spotifactory.connect.shuffle") as shuffle:
            spotify.next_track()
            spotify.pause()
            assert spotify.toggle_shuffle() is True
        nxt.assert_called_once_with("sonos-1")
        pause.assert_called_once_with("sonos-1")
        shuffle.assert_called_once_with("sonos-1", True)
        sp.next_track.assert_not_called()
        sp.pause_playback.assert_not_called()
        sp.shuffle.assert_not_called()

    def test_volume_goes_to_the_sonos_itself(self, chosen_sonos):
        from spotifactory import spotify
        with patch("spotifactory.hardware.sonos.get_volume", return_value=30) as get, \
             patch("spotifactory.hardware.sonos.set_volume") as put:
            assert spotify.get_volume() == 30
            spotify.set_volume(35)
        get.assert_called_once_with("Living Room")
        put.assert_called_once_with("Living Room", 35)

    def test_idle_sonos_counts_as_reachable_though_spotify_hides_it(self, chosen_sonos):
        from spotifactory import spotify
        sp = MagicMock()
        sp.devices.return_value = {"devices": []}
        with patch("spotifactory.spotify.get_client", return_value=sp):
            assert spotify.resolve_chosen_device(spotify.get_active_device()) == "sonos-1"

    def test_without_the_helper_nothing_changes(self, chosen_sonos):
        from spotifactory import spotify
        sp = MagicMock()
        with patch("spotifactory.connect.available", return_value=False), \
             patch("spotifactory.spotify.get_client", return_value=sp):
            spotify.next_track()
        sp.next_track.assert_called_once()


class TestChooseSonos:
    def test_finds_sonos_rooms_by_their_spotify_endpoint(self):
        from spotifactory.hardware import sonos
        rooms = [MagicMock(player_name="Kitchen", ip_address="10.0.0.5"),
                 MagicMock(player_name="Den", ip_address="10.0.0.6")]
        ids = {"10.0.0.5": "dev-k", "10.0.0.6": None}
        with patch("soco.discovery.discover", return_value=set(rooms)), \
             patch.object(sonos, "_spotify_device_id", side_effect=lambda ip: ids[ip]):
            found = sonos.connect_speakers()
        assert found == [{"id": "dev-k", "name": "Kitchen", "type": "Speaker",
                          "is_active": False, "is_restricted": True}]

    def test_list_adds_sonos_rooms_spotify_left_out(self):
        from spotifactory.tasks.speaker.steps import FetchDevicesStep
        listed = [{"id": "echo", "name": "Echo"}, {"id": "dev-k", "name": "Kitchen"}]
        sonos_rows = [{"id": "dev-k", "name": "Kitchen", "is_restricted": True},
                      {"id": "dev-d", "name": "Den", "is_restricted": True}]
        ctx = TaskContext(dry_run=False)
        with patch("spotifactory.spotify.get_devices", return_value=listed), \
             patch("spotifactory.connect.available", return_value=True), \
             patch("spotifactory.hardware.sonos.connect_speakers", return_value=sonos_rows):
            FetchDevicesStep().run(ctx)
        assert [d["name"] for d in ctx.data["devices"]] == ["Echo", "Kitchen", "Den"]

    def test_choosing_a_sonos_saves_it_as_restricted(self, tmp_path):
        from spotifactory.spotify import get_active_device
        from spotifactory.tasks.speaker.steps import SetDeviceStep
        env_file = tmp_path / ".env"
        env_file.write_text("")
        clean = {"SPOTIFACTORY_DEVICE_ID": "", "SPOTIFACTORY_DEVICE_NAME": "",
                 "SPOTIFACTORY_DEVICE_RESTRICTED": ""}
        selected = {"id": "dev-d", "name": "Den", "is_restricted": True}
        ctx = TaskContext(dry_run=False, data={"selected": selected})
        with patch.dict("os.environ", clean), \
             patch("spotifactory.settings.env_path", return_value=str(env_file)), \
             patch("spotifactory.connect.available", return_value=True), \
             patch("spotifactory.connect.transfer") as transfer, \
             patch("spotifactory.tasks.base.time.sleep"):
            assert isinstance(SetDeviceStep().run(ctx), Done)
            chosen = get_active_device()
        assert (chosen.id, chosen.name, chosen.restricted) == ("dev-d", "Den", True)
        transfer.assert_called_once_with("dev-d")
