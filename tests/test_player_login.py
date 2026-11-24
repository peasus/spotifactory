"""The box's player signs in with a pairing code (player_login.py)."""
from __future__ import annotations

import os
import stat
from unittest.mock import patch

FAKE = """#!/bin/sh
cache=""
while [ $# -gt 0 ]; do [ "$1" = "--system-cache" ] && cache="$2"; shift; done
echo "[INFO] Browse to: https://spotify.com/pair?code=TV2URE"
echo "[INFO] If prompted, enter code: TV2URE"
sleep 0.3
echo '{"auth_type":1}' > "$cache/credentials.json"
echo "[INFO] Authenticated as 'nick' !"
sleep 30
"""


def _fake(tmp_path, body=FAKE):
    path = tmp_path / "librespot"
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_pairing_shows_the_code_saves_the_login_and_restarts_the_player(tmp_path, monkeypatch):
    from spotifactory import player_login
    monkeypatch.setattr(player_login, "CACHE_DIR", str(tmp_path / "cache"))
    codes = []
    with patch.object(player_login, "_binary", return_value=_fake(tmp_path)), \
         patch("spotifactory.services.restart_raspotify") as restart:
        assert not player_login.has_login()
        ok = player_login.pair(lambda url, code: codes.append((url, code)), lambda: False, timeout=10)
    assert ok and player_login.has_login()
    assert codes == [("https://spotify.com/pair?code=TV2URE", "TV2URE")]
    restart.assert_called_once()


def test_cancel_stops_pairing_without_a_login(tmp_path, monkeypatch):
    from spotifactory import player_login
    monkeypatch.setattr(player_login, "CACHE_DIR", str(tmp_path / "cache"))
    waiting = _fake(tmp_path, "#!/bin/sh\necho 'Browse to: https://spotify.com/pair?code=AB12CD'\nsleep 30\n")
    seen = []
    with patch.object(player_login, "_binary", return_value=waiting), \
         patch("spotifactory.services.restart_raspotify") as restart:
        ok = player_login.pair(lambda url, code: seen.append(code), lambda: bool(seen), timeout=10)
    assert not ok and seen == ["AB12CD"]
    restart.assert_not_called()


def test_old_librespot_cannot_pair(tmp_path):
    from spotifactory import player_login
    old = _fake(tmp_path, "#!/bin/sh\necho '--name NAME  --system-cache DIR'\n")
    with patch.object(player_login, "_binary", return_value=old):
        assert not player_login.can_pair()


def test_login_step_is_skipped_when_the_player_has_a_login(tmp_path, monkeypatch):
    from spotifactory import player_login
    from spotifactory.tasks.base import Done, TaskContext
    from spotifactory.tasks.reauth.steps import PlayerLoginStep
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "credentials.json").write_text("{}")
    monkeypatch.setattr(player_login, "CACHE_DIR", str(cache))
    with patch.object(player_login, "pair") as pair:
        assert isinstance(PlayerLoginStep().run(TaskContext()), Done)
    pair.assert_not_called()
    assert os.path.exists(cache / "credentials.json")
