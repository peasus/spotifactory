"""Cast and AirPlay speakers (network_speakers.py, cast_direct.py, owntone.py)."""
from __future__ import annotations

import socket
import struct
from unittest.mock import MagicMock, patch

import pytest

OUTPUTS = {"outputs": [
    {"id": "111", "name": "Kitchen group", "type": "Chromecast", "selected": False},
    {"id": "222", "name": "Living Room", "type": "AirPlay 2", "selected": False},
    {"id": "333", "name": "Apple TV", "type": "AirPlay", "needs_auth_key": True},
    {"id": "0", "name": "Computer", "type": "ALSA"},
]}

GROUP_ID = "cast:192.168.86.40:32187:5b2e0c0f-6c8a-4d36-9b0c-6c3c7c1f0a11"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """No saved speakers, and settings written to a scratch .env."""
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
            self.sinks.append(next(a.split("=", 1)[1] for a in args if a.startswith("sink_name=")))
        elif args[0] == "set-default-sink":
            self.default = args[1]
        elif args[0] == "move-sink-input":
            self.moved.append(args[2])
        return MagicMock(returncode=0, stdout=out, stderr="")


# --- Direct Cast discovery ------------------------------------------------------

def _name(n: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"


def _rr(name: str, rtype: int, rdata: bytes) -> bytes:
    return _name(name) + struct.pack(">HHIH", rtype, 0x8001, 120, len(rdata)) + rdata


def cast_answer(instance="Kitchen-group-5b2e", fn="Kitchen group",
                uuid="5b2e0c0f6c8a4d369b0c6c3c7c1f0a11",
                host="5b2e0c0f.local", ip="192.168.86.40", port=32187) -> bytes:
    full = f"{instance}._googlecast._tcp.local"
    txt = b"".join(bytes([len(s)]) + s for s in
                   (f"id={uuid}".encode(), b"md=Google Cast Group", f"fn={fn}".encode()))
    records = [
        _rr("_googlecast._tcp.local", 12, _name(full)),
        _rr(full, 33, struct.pack(">HHH", 0, 0, port) + _name(host)),
        _rr(full, 16, txt),
        _rr(host, 1, socket.inet_aton(ip)),
    ]
    return struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 3) + b"".join(records)


def test_reads_a_cast_group_from_a_direct_answer():
    from spotifactory import cast_direct
    [dev] = cast_direct.parse_answer(cast_answer(), "192.168.86.31")
    assert dev == {"uuid": "5b2e0c0f6c8a4d369b0c6c3c7c1f0a11", "name": "Kitchen group",
                   "model": "Google Cast Group", "host": "192.168.86.40", "port": 32187}


def test_garbage_answer_is_ignored():
    from spotifactory import cast_direct
    assert cast_direct.parse_answer(b"\x00\x01junk", "1.2.3.4") == []


# --- Choose Speaker -------------------------------------------------------------

def test_list_has_cast_from_direct_discovery_and_airplay_from_owntone(env):
    from spotifactory import cast_direct, owntone, spotify
    spotify_devices = [{"id": "rasp", "name": "Spotifactory", "is_active": True},
                       {"id": "den-cc", "name": "Den", "is_active": False}]
    cast_rows = [{"id": GROUP_ID, "name": "Kitchen group", "type": "Cast",
                  "is_active": False, "is_restricted": False},
                 {"id": "cast:1.2.3.4:8009:x", "name": "Den", "type": "Cast",
                  "is_active": False, "is_restricted": False}]
    request, _ = _api()
    with patch.object(spotify, "get_devices", return_value=spotify_devices), \
         patch.object(spotify, "_sonos_speakers", return_value=[]), \
         patch.object(cast_direct, "available", return_value=True), \
         patch.object(cast_direct, "speakers", return_value=cast_rows), \
         patch.object(owntone, "_request", request):
        rows = spotify.list_speakers()
    # Den is casting from the Spotify app already: Spotify's own entry is kept.
    # OwnTone's Cast entry gives way to the direct one; Apple TV wants a PIN.
    assert [(d["name"], d["id"]) for d in rows] == [
        ("Spotifactory", "rasp"), ("Den", "den-cc"),
        ("Kitchen group", GROUP_ID), ("Living Room", "owntone:222")]


def test_owntone_lists_only_network_speakers():
    from spotifactory import owntone
    request, _ = _api()
    with patch.object(owntone, "_request", request):
        rows = owntone.speakers()
    assert [(r["name"], r["type"]) for r in rows] == [
        ("Apple TV", "AirPlay"), ("Kitchen group", "Cast"), ("Living Room", "AirPlay")]
    assert [r["name"] for r in rows if r["needs_pairing"]] == ["Apple TV"]


def test_no_owntone_means_no_network_speakers(env):
    from spotifactory import network_speakers, owntone
    with patch.object(owntone, "_request", side_effect=owntone.OwnToneError("refused")):
        assert network_speakers.speakers() == []


def test_choosing_a_cast_group_plays_through_the_box(env):
    from spotifactory import cast_direct, network_speakers, spotify
    sp = MagicMock()
    with patch.object(cast_direct, "play") as cast_play, \
         patch.object(spotify, "get_client", return_value=sp), \
         patch.object(spotify, "find_device_by_name", return_value={"id": "rasp"}):
        spotify.choose_speaker({"id": GROUP_ID, "name": "Kitchen group"})

    assert network_speakers.chosen() == (GROUP_ID, "Kitchen group")
    assert spotify.get_active_device() is None          # tags go to the box's Raspotify
    cast_play.assert_called_once_with(GROUP_ID, "Kitchen group")
    sp.transfer_playback.assert_called_once_with("rasp", force_play=False)


def _cast_env(cc, request):
    from spotifactory import cast_direct, owntone
    return (patch.object(owntone, "_request", request),
            patch.object(cast_direct, "discover", return_value=[]),
            patch.object(cast_direct, "_connect", return_value=cc),
            patch.object(cast_direct, "_box_ip", return_value="192.168.86.229"))


def test_cast_play_routes_audio_and_starts_owntone(env):
    from spotifactory import cast_direct, owntone
    request, calls = _api()
    pactl = FakePactl()
    cc = MagicMock()
    cc.media_controller.status = None
    a, b, c, d = _cast_env(cc, request)
    with a, b, c, d, patch("spotifactory.audio_route.pactl", pactl):
        cast_direct.play(GROUP_ID, "Kitchen group")

    assert pactl.default == owntone.SINK and pactl.moved == [owntone.SINK]
    assert ("PUT", "/api/outputs/set", {"outputs": []}) in calls    # OwnTone's speakers stay off
    url = cc.media_controller.play_media.call_args[0][0]
    assert url == "http://192.168.86.229:3689/stream.mp3"
    assert calls[-1] == ("PUT", "/api/player/play", None)


def test_cast_play_leaves_a_speaker_already_playing_the_stream(env):
    from spotifactory import cast_direct
    request, _ = _api()
    cc = MagicMock()
    cc.media_controller.status.content_id = "http://192.168.86.229:3689/stream.mp3"
    cc.media_controller.status.player_state = "PLAYING"
    a, b, c, d = _cast_env(cc, request)
    with a, b, c, d, patch("spotifactory.audio_route.pactl", FakePactl()):
        cast_direct.play(GROUP_ID)
    cc.media_controller.play_media.assert_not_called()


def test_choosing_airplay_selects_it_in_owntone(env):
    from spotifactory import network_speakers, owntone
    request, calls = _api()
    pactl = FakePactl()
    with patch.object(owntone, "_request", request), patch("spotifactory.audio_route.pactl", pactl):
        network_speakers.select({"id": "owntone:222", "name": "Living Room"})
    assert ("PUT", "/api/outputs/set", {"outputs": ["222"]}) in calls
    assert pactl.default == owntone.SINK


def test_choosing_another_speaker_hands_the_audio_back(env):
    from spotifactory import cast_direct, network_speakers, spotify
    env.setenv("SPOTIFACTORY_NETWORK_SPEAKER_ID", GROUP_ID)
    env.setenv("SPOTIFACTORY_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF")
    pactl = FakePactl()
    pactl.sinks.append("spotifactory_network")
    pactl.default = "spotifactory_network"
    with patch("spotifactory.audio_route.pactl", pactl), \
         patch.object(cast_direct, "stop") as cast_stop, \
         patch.object(spotify, "transfer_playback"):
        spotify.choose_speaker({"id": "echo", "name": "Echo"})

    assert network_speakers.chosen() is None
    assert pactl.default == "bluez_output.AA_BB_CC_DD_EE_FF.1"
    cast_stop.assert_called_once_with(GROUP_ID)
    assert spotify.get_active_device().name == "Echo"


def test_speaker_that_needs_a_pin_is_refused(env):
    from spotifactory import network_speakers, spotify
    with pytest.raises(network_speakers.NetworkSpeakerError):
        spotify.choose_speaker({"id": "owntone:333", "name": "Apple TV", "needs_pairing": True})
    assert network_speakers.chosen() is None


def test_speaker_off_still_saves_the_choice(env):
    from spotifactory import cast_direct, network_speakers
    with patch.object(cast_direct, "play", side_effect=OSError("no route")):
        with pytest.raises(network_speakers.NetworkSpeakerError):
            network_speakers.select({"id": GROUP_ID, "name": "Kitchen group"})
    assert network_speakers.chosen() == (GROUP_ID, "Kitchen group")


def test_tag_reroutes_audio_and_rechecks_the_speaker(env):
    from spotifactory import network_speakers, spotify
    env.setenv("SPOTIFACTORY_NETWORK_SPEAKER_ID", GROUP_ID)
    pactl = FakePactl()          # the pipe sink is gone, as after a PipeWire restart
    sp = MagicMock()
    sp.current_playback.return_value = None
    with patch("spotifactory.audio_route.pactl", pactl), \
         patch.object(network_speakers, "after_play") as after, \
         patch.object(spotify, "get_client", return_value=sp), \
         patch.object(spotify, "find_device_by_name", return_value={"id": "rasp"}):
        result = spotify.play_tag("spotify:album:abc")
    assert result.message is None
    assert pactl.default == "spotifactory_network"
    sp.start_playback.assert_called_once_with(context_uri="spotify:album:abc", device_id="rasp")
    after.assert_called_once()


def test_discovery_also_asks_every_address_on_the_network():
    from spotifactory import cast_direct
    ip_out = MagicMock(stdout="3: wlan0    inet 192.168.86.229/24 brd 192.168.86.255 scope global wlan0\n")
    with patch("subprocess.run", return_value=ip_out):
        hosts = cast_direct._local_hosts()
    assert len(hosts) == 253 and "192.168.86.27" in hosts and "192.168.86.229" not in hosts

    sent = []
    sock = MagicMock()
    sock.sendto.side_effect = lambda data, target: sent.append(target)
    sock.recvfrom.side_effect = lambda n: ((cast_answer(fn="Ceiling speakers"), ("192.168.86.27", 5353))
                                           if len(sent) < 600 else (_ for _ in ()).throw(socket.timeout()))
    with patch("socket.socket", return_value=sock), \
         patch.object(cast_direct, "_local_hosts", return_value=["192.168.86.27", "192.168.86.30"]):
        found = cast_direct.discover(timeout=0.3)
    assert ("192.168.86.27", 5353) in sent and cast_direct.MDNS_ADDR in sent
    assert [d["name"] for d in found] == ["Ceiling speakers"]
