"""Cast and AirPlay speakers through OwnTone (spotifactory/owntone.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

OUTPUTS = {"outputs": [
    {"id": "111", "name": "Kitchen group", "type": "Chromecast", "selected": False},
    {"id": "222", "name": "Living Room", "type": "AirPlay", "selected": False},
    {"id": "333", "name": "Apple TV", "type": "AirPlay", "needs_auth_key": True},
    {"id": "0", "name": "Computer", "type": "ALSA"},
    {"id": "444", "name": "Den", "type": "Chromecast"},
]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """No saved network speaker, and settings written to a scratch .env."""
    for key in ("SPOTIFACTORY_NETWORK_SPEAKER_ID", "SPOTIFACTORY_NETWORK_SPEAKER_NAME",
                "SPOTIFACTORY_DEVICE_ID", "SPOTIFACTORY_DEVICE_NAME",
                "SPOTIFACTORY_DEVICE_RESTRICTED", "SPOTIFACTORY_SPEAKER_MAC"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr("spotifactory.settings.env_path", lambda: str(env_file))
    return monkeypatch


def _api(outputs=OUTPUTS):
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, body))
        if path == "/api/outputs":
            return outputs
        return None
    return request, calls


class FakePactl:
    """pactl with the Bluetooth speaker's sink, and librespot playing."""

    def __init__(self):
        self.sinks = ["bluez_output.AA_BB_CC_DD_EE_FF.1"]
        self.default = self.sinks[0]
        self.moved = []

    def __call__(self, *args):
        out = ""
        if args[:3] == ("list", "short", "sinks"):
            out = "\n".join(f"{i}\t{s}\tPipeWire\ts16le 2ch 44100Hz\tIDLE"
                            for i, s in enumerate(self.sinks))
        elif args[:3] == ("list", "short", "sink-inputs"):
            out = "42\t0\t7\tPipeWire\ts16le 2ch 44100Hz"
        elif args[0] == "load-module":
            self.sinks.append("spotifactory_network")
        elif args[0] == "set-default-sink":
            self.default = args[1]
        elif args[0] == "move-sink-input":
            self.moved.append(args[2])
        return MagicMock(returncode=0, stdout=out, stderr="")


def test_lists_only_network_speakers(env):
    from spotifactory import owntone
    request, _ = _api()
    with patch.object(owntone, "_request", request):
        rows = owntone.speakers()
    assert [(r["name"], r["type"]) for r in rows] == [
        ("Apple TV", "AirPlay"), ("Den", "Cast"),
        ("Kitchen group", "Cast"), ("Living Room", "AirPlay")]
    assert all(r["id"].startswith("owntone:") for r in rows)
    assert [r["name"] for r in rows if r["needs_pairing"]] == ["Apple TV"]


def test_no_owntone_means_no_extra_speakers(env):
    from spotifactory import owntone
    with patch.object(owntone, "_request", side_effect=owntone.OwnToneError("refused")):
        assert owntone.speakers() == []


def test_choose_speaker_list_adds_network_speakers_not_listed_by_spotify(env):
    from spotifactory import owntone, spotify
    spotify_devices = [{"id": "rasp", "name": "Spotifactory", "is_active": True},
                       {"id": "den-cc", "name": "Den", "is_active": False}]
    request, _ = _api()
    with patch.object(spotify, "get_devices", return_value=spotify_devices), \
         patch.object(spotify, "_sonos_speakers", return_value=[]), \
         patch.object(owntone, "_request", request):
        names = [d["name"] for d in spotify.list_speakers()]
    # Den is casting from the Spotify app already, so Spotify's own entry is kept.
    # Apple TV wants a PIN, which the box can't enter yet.
    assert names == ["Spotifactory", "Den", "Kitchen group", "Living Room"]


def test_choosing_a_cast_group_plays_through_the_box(env):
    from spotifactory import owntone, spotify
    request, calls = _api()
    pactl = FakePactl()
    sp = MagicMock()
    with patch.object(owntone, "_request", request), patch.object(owntone, "_pactl", pactl), \
         patch.object(spotify, "get_client", return_value=sp), \
         patch.object(spotify, "find_device_by_name", return_value={"id": "rasp"}):
        spotify.choose_speaker({"id": "owntone:111", "name": "Kitchen group"})

    assert owntone.chosen() == ("111", "Kitchen group")
    assert spotify.get_active_device() is None          # tags go to the box's Raspotify
    assert ("PUT", "/api/outputs/set", {"outputs": ["111"]}) in calls
    assert pactl.default == "spotifactory_network" and pactl.moved == ["spotifactory_network"]
    sp.transfer_playback.assert_called_once_with("rasp", force_play=False)


def test_choosing_another_speaker_hands_the_audio_back(env):
    from spotifactory import owntone, spotify
    env.setenv("SPOTIFACTORY_NETWORK_SPEAKER_ID", "111")
    env.setenv("SPOTIFACTORY_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF")
    request, calls = _api()
    pactl = FakePactl()
    pactl.sinks.append("spotifactory_network")
    pactl.default = "spotifactory_network"
    with patch.object(owntone, "_request", request), patch.object(owntone, "_pactl", pactl), \
         patch.object(spotify, "transfer_playback"):
        spotify.choose_speaker({"id": "echo", "name": "Echo"})

    assert owntone.chosen() is None
    assert pactl.default == "bluez_output.AA_BB_CC_DD_EE_FF.1"
    assert ("PUT", "/api/outputs/set", {"outputs": []}) in calls
    assert spotify.get_active_device().name == "Echo"


def test_speaker_that_needs_a_pin_is_refused(env):
    from spotifactory import owntone, spotify
    with pytest.raises(owntone.OwnToneError):
        spotify.choose_speaker({"id": "owntone:333", "name": "Apple TV", "needs_pairing": True})
    assert owntone.chosen() is None


def test_speaker_off_still_saves_the_choice(env):
    from spotifactory import owntone
    request, _ = _api({"outputs": []})
    with patch.object(owntone, "_request", request), patch.object(owntone, "_pactl", FakePactl()):
        with pytest.raises(owntone.OwnToneError):
            owntone.select({"id": "owntone:111", "name": "Kitchen group"}, wait_secs=0)
    assert owntone.chosen() == ("111", "Kitchen group")


def test_tag_reroutes_audio_if_pipewire_restarted(env):
    from spotifactory import owntone, spotify
    env.setenv("SPOTIFACTORY_NETWORK_SPEAKER_ID", "111")
    pactl = FakePactl()          # the pipe sink is gone, as after a PipeWire restart
    sp = MagicMock()
    sp.current_playback.return_value = None
    with patch.object(owntone, "_pactl", pactl), \
         patch.object(spotify, "get_client", return_value=sp), \
         patch.object(spotify, "find_device_by_name", return_value={"id": "rasp"}):
        result = spotify.play_tag("spotify:album:abc")
    assert result.message is None
    assert pactl.default == "spotifactory_network"
    sp.start_playback.assert_called_once_with(context_uri="spotify:album:abc", device_id="rasp")
