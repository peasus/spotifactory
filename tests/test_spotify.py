"""Spotify helpers: non-interactive login, and what's-playing parsing edge cases."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spotifactory.tasks.base import Done, TaskContext


def test_device_login_raises_instead_of_waiting_for_input():
    """With no saved login, the Pi's auth manager must not block on input()."""
    from spotipy.cache_handler import MemoryCacheHandler
    from spotipy.oauth2 import SpotifyOauthError

    from spotifactory import spotify

    env = {"SPOTIPY_CLIENT_ID": "cid", "RELAY_URL": "https://relay.test", "SPOTIPY_CLIENT_SECRET": ""}
    with patch.dict("os.environ", env), \
         patch("builtins.input", side_effect=AssertionError("prompted on the terminal")):
        auth = spotify._make_auth_manager()
        auth.cache_handler = MemoryCacheHandler()
        with pytest.raises(SpotifyOauthError):
            auth.get_access_token()


def _now_playing(item):
    from spotifactory import spotify
    sp = MagicMock()
    sp.current_playback.return_value = {"is_playing": True, "item": item, "context": None}
    with patch("spotifactory.spotify.get_client", return_value=sp):
        info = spotify.get_now_playing()
    sp.current_playback.assert_called_once_with(additional_types="episode")
    return info


def test_podcast_episode_uses_the_show_as_the_album():
    info = _now_playing({
        "type": "episode", "name": "Ep 12",
        "images": [{"url": "https://img/ep.jpg"}],
        "show": {"name": "The Show", "publisher": "Some Network", "uri": "spotify:show:abc",
                 "images": [{"url": "https://img/show.jpg"}]},
    })
    assert (info.track_name, info.artist_name, info.album_name) == ("Ep 12", "Some Network", "The Show")
    assert info.album_uri == "spotify:show:abc"
    assert info.artwork_url == "https://img/ep.jpg"


def test_track_without_artwork_does_not_crash():
    info = _now_playing({
        "type": "track", "name": "Song", "artists": [{"name": "A"}, {"name": "B"}],
        "album": {"name": "Album", "uri": "spotify:album:x", "images": []},
    })
    assert info.artist_name == "A, B"
    assert info.artwork_url is None


def test_local_file_has_no_uri():
    info = _now_playing({
        "type": "track", "name": "Demo", "artists": [{"name": "Me"}], "is_local": True,
        "album": {"name": "Local", "uri": None, "images": []},
    })
    assert info.album_uri is None


@pytest.mark.parametrize("uri,art,reason", [
    (None, None, "local file"),
    ("spotify:album:x", None, "no artwork"),
])
def test_print_album_stops_early_when_it_cant_print(uri, art, reason):
    from spotifactory.spotify import NowPlayingInfo
    from spotifactory.tasks.capture.steps import FetchInfoStep
    info = NowPlayingInfo("T", "A", "Al", uri, art)
    step = FetchInfoStep()
    seen = {}

    def show_for(message, seconds):
        seen["status"], seen["artist"] = message, step.artist

    step.show_for = show_for
    with patch("spotifactory.spotify.get_now_playing", return_value=info):
        assert isinstance(step.run(TaskContext()), Done)
    assert seen == {"status": "Can't print this", "artist": reason}


# ---------------------------------------------------------------------------
# NFC reader port
# ---------------------------------------------------------------------------

def test_stale_nfc_port_falls_back_to_the_device_that_exists():
    """Linux can renumber the reader (ttyUSB0 -> ttyUSB1); a stale NFC_PORT must not stick."""
    from spotifactory.hardware import rfid
    with patch.dict("os.environ", {"NFC_PORT": "tty:USB0"}), \
         patch.object(rfid.sys, "platform", "linux"), \
         patch("os.path.exists", side_effect=lambda p: p == "/dev/ttyUSB1"), \
         patch("glob.glob", side_effect=lambda pat: ["/dev/ttyUSB1"] if "USB" in pat else []):
        assert rfid.current_port() == "tty:USB1"


def test_nfc_port_override_kept_when_present():
    from spotifactory.hardware import rfid
    with patch.dict("os.environ", {"NFC_PORT": "tty:USB0"}), \
         patch.object(rfid.sys, "platform", "linux"), \
         patch("os.path.exists", return_value=True):
        assert rfid.current_port() == "tty:USB0"


# ---------------------------------------------------------------------------
# Volume and play/pause
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device,expected", [
    ({"id": "d", "volume_percent": 37, "supports_volume": True}, 37),
    ({"id": "d", "volume_percent": 37, "supports_volume": False}, None),
    ({"id": "d", "volume_percent": 37, "is_restricted": True}, None),     # Sonos
    ({"id": "d", "volume_percent": None}, None),
])
def test_volume_only_where_spotify_can_set_it(device, expected):
    from spotifactory import spotify
    sp = MagicMock()
    sp.current_playback.return_value = {"device": device, "is_playing": True}
    with patch("spotifactory.spotify.get_client", return_value=sp):
        assert spotify.get_volume() == expected


def test_play_pause_resumes_on_the_same_device():
    from spotifactory import spotify
    sp = MagicMock()
    sp.current_playback.return_value = {"device": {"id": "echo"}, "is_playing": False}
    with patch("spotifactory.spotify.get_client", return_value=sp):
        assert spotify.play_pause() is True
    sp.start_playback.assert_called_once_with(device_id="echo")
    sp.current_playback.return_value = {"device": {"id": "echo"}, "is_playing": True}
    with patch("spotifactory.spotify.get_client", return_value=sp):
        assert spotify.play_pause() is False
    sp.pause_playback.assert_called_once()


def test_playback_log_flags_tracks_off_the_tags_album(capsys):
    """One line per track change; a track from another album is called out."""
    from spotifactory.spotify import NowPlayingInfo
    from spotifactory.tasks.home.steps import PlaybackLog
    tag = "spotify:album:unplugged"
    log = PlaybackLog()
    log.reset(tag)

    def info(track, album_uri, progress):
        return NowPlayingInfo(track, "A", "Al", album_uri, None, context_uri=tag,
                              device_name="Living Room", track_uri=f"spotify:track:{track}",
                              progress_ms=progress, duration_ms=200_000)

    log.update(info("one", tag, 10_000))
    log.update(info("one", tag, 150_000))     # same track: no new line
    log.update(info("weezer", "spotify:album:pinkerton", 5_000))
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "off-album" not in lines[0]
    assert "off-album" in lines[1] and "prev last seen 2:30/3:20" in lines[1]


def test_playlist_label_keeps_print_square_and_marks_the_bottom():
    """The labelled print is 800x800; the name darkens/whitens only the bottom."""
    from io import BytesIO

    from PIL import Image

    from spotifactory.tasks.capture.label import add_label
    src = BytesIO()
    Image.new("RGB", (640, 480), (120, 160, 200)).save(src, "PNG")
    out = Image.open(add_label(src, "A Very Long Playlist Name That Needs Wrapping Or Cutting Short"))
    assert out.size == (800, 800)
    assert out.getpixel((400, 50)) == pytest.approx((120, 160, 200), abs=3)
    assert out.getpixel((400, 790)) != out.getpixel((400, 50))


def test_label_with_an_artist_line_stays_square():
    from io import BytesIO

    from PIL import Image

    from spotifactory.tasks.capture.label import add_label
    src = BytesIO()
    Image.new("RGB", (640, 640), (200, 180, 160)).save(src, "PNG")
    out = Image.open(add_label(src, "MTV Unplugged In New York", "Nirvana and Some Very Long Featured Artist Names"))
    assert out.size == (800, 800)
