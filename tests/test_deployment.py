"""Tests for startup.py and auth_server.py."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# startup._has_network
# ---------------------------------------------------------------------------

class TestHasNetwork:
    def test_true_when_connection_succeeds(self):
        from spotifactory.startup import _has_network
        with patch("socket.create_connection"):
            assert _has_network() is True

    def test_false_on_oserror(self):
        from spotifactory.startup import _has_network
        with patch("socket.create_connection", side_effect=OSError):
            assert _has_network() is False


# ---------------------------------------------------------------------------
# startup._has_valid_token
# ---------------------------------------------------------------------------

class TestHasValidToken:
    def test_true_when_spotify_responds(self):
        from spotifactory.startup import _has_valid_token
        with patch("spotifactory.spotify.get_now_playing", return_value=None):
            assert _has_valid_token() is True

    def test_false_on_any_exception(self):
        from spotifactory.startup import _has_valid_token
        with patch("spotifactory.spotify.get_now_playing", side_effect=Exception("no auth")):
            assert _has_valid_token() is False


# ---------------------------------------------------------------------------
# startup.main() flow
# ---------------------------------------------------------------------------

class TestWaitForNetwork:
    def test_returns_true_once_network_comes_up(self):
        from spotifactory.startup import _wait_for_network
        with patch("spotifactory.startup._has_network", side_effect=[False, False, True]), \
             patch("spotifactory.startup.time.sleep") as mock_sleep:
            assert _wait_for_network(timeout=60) is True
        assert mock_sleep.call_count == 2

    def test_returns_false_after_timeout(self):
        from spotifactory.startup import _wait_for_network
        with patch("spotifactory.startup._has_network", return_value=False), \
             patch("spotifactory.startup.time.sleep"):
            assert _wait_for_network(timeout=0.0) is False


class TestBtReconnectLoop:
    class _Stop(Exception):
        pass

    def _run(self, sleeps, **bt):
        from spotifactory.startup import _bt_reconnect_loop
        side = [None] * (sleeps - 1) + [self._Stop()]
        with patch("spotifactory.hardware.bluetooth.is_connected", **bt["is_connected"]), \
             patch("spotifactory.hardware.bluetooth.reconnect"), \
             patch("spotifactory.hardware.bluetooth.set_bt_audio_output",
                   **bt["set_out"]) as set_out, \
             patch("spotifactory.hardware.bluetooth.move_sink_inputs") as move, \
             patch("spotifactory.startup.time.sleep", side_effect=side), \
             pytest.raises(self._Stop):
            _bt_reconnect_loop("AA:BB:CC:DD:EE:FF")
        return set_out, move

    def test_routes_once_when_already_connected(self):
        # BlueZ auto-reconnected before the loop ran — audio must still be routed, once.
        set_out, move = self._run(
            3, is_connected={"return_value": True}, set_out={"return_value": True},
        )
        set_out.assert_called_once()
        move.assert_called_once()

    def test_retries_routing_until_pactl_succeeds(self):
        set_out, move = self._run(
            3, is_connected={"return_value": True}, set_out={"side_effect": [False, True]},
        )
        assert set_out.call_count == 2
        move.assert_called_once()


class TestStartupMain:
    """Integration-style tests for the startup sequencing logic.

    The display and platform launcher are stubbed so main() returns instead of
    entering the real hardware loop; no BT speaker MAC so no reconnect thread.
    """

    @staticmethod
    def _patches(network_up=True, token_valid=True):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"SPOTIFACTORY_SPEAKER_MAC": ""}))
        stack.enter_context(patch("dotenv.load_dotenv"))
        s = "spotifactory.startup"
        stack.enter_context(patch(f"{s}._make_display", return_value=MagicMock()))
        stack.enter_context(patch(f"{s}._wait_for_network", return_value=network_up))
        stack.enter_context(patch(f"{s}._has_valid_token", return_value=token_valid))
        mocks = {
            "run_platform": stack.enter_context(patch("spotifactory.startup._run_platform")),
            "auth": stack.enter_context(patch("spotifactory.auth_server.run_pkce_auth")),
            "subprocess": stack.enter_context(patch("subprocess.run")),
        }
        return stack, mocks

    def test_runs_platform_when_network_and_token_present(self):
        from spotifactory import startup
        stack, m = self._patches()
        with stack:
            startup.main()
        m["run_platform"].assert_called_once()
        m["auth"].assert_not_called()
        m["subprocess"].assert_not_called()

    def test_launches_wifi_connect_when_offline(self):
        from spotifactory import startup
        stack, m = self._patches(network_up=False)
        with stack, patch("spotifactory.startup._has_network", return_value=True):
            startup.main()
        cmd = m["subprocess"].call_args[0][0]
        assert cmd[0] == "wifi-connect"
        assert "--portal-ssid" in cmd
        m["run_platform"].assert_called_once()

    def test_exits_if_still_offline_after_wifi_connect(self):
        from spotifactory import startup
        stack, m = self._patches(network_up=False)
        with stack, patch("spotifactory.startup._has_network", return_value=False), \
             pytest.raises(SystemExit):
            startup.main()
        m["run_platform"].assert_not_called()

    def test_launches_pkce_auth_when_no_token(self):
        from spotifactory import startup
        stack, m = self._patches(token_valid=False)
        with stack:
            startup.main()
        m["auth"].assert_called_once()

    def test_skips_auth_when_token_present(self):
        from spotifactory import startup
        stack, m = self._patches(token_valid=True)
        with stack:
            startup.main()
        m["auth"].assert_not_called()


# ---------------------------------------------------------------------------
# auth_server — PKCE relay flow
# ---------------------------------------------------------------------------

class TestPkceAuth:
    """Tests for auth_server.run_pkce_auth and its helpers."""

    _ENV = {"RELAY_URL": "https://relay.test", "SPOTIPY_CLIENT_ID": "cid"}

    def _make_mock_pkce(self):
        m = MagicMock()
        m.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?x=1"
        return m

    def test_happy_path_returns_true(self):
        import spotifactory.auth_server as mod
        mock_pkce = self._make_mock_pkce()
        with patch.dict("os.environ", self._ENV), \
             patch("spotipy.oauth2.SpotifyPKCE", return_value=mock_pkce), \
             patch.object(mod, "_post_register"), \
             patch.object(mod, "_poll_for_code", return_value="mycode"):
            result = mod.run_pkce_auth()
        assert result is True
        mock_pkce.get_access_token.assert_called_once_with("mycode", check_cache=False)

    def test_on_session_ready_receives_session_url(self):
        import spotifactory.auth_server as mod
        mock_pkce = self._make_mock_pkce()
        received: list[str] = []
        with patch.dict("os.environ", self._ENV), \
             patch("spotipy.oauth2.SpotifyPKCE", return_value=mock_pkce), \
             patch.object(mod, "_post_register"), \
             patch.object(mod, "_poll_for_code", return_value="code"):
            mod.run_pkce_auth(on_session_ready=received.append)
        assert len(received) == 1
        assert received[0].startswith("https://relay.test/")
        assert len(received[0]) == len("https://relay.test/") + 8  # 8-char hex session id

    def test_returns_false_when_poll_times_out(self):
        import spotifactory.auth_server as mod
        mock_pkce = self._make_mock_pkce()
        with patch.dict("os.environ", self._ENV), \
             patch("spotipy.oauth2.SpotifyPKCE", return_value=mock_pkce), \
             patch.object(mod, "_post_register"), \
             patch.object(mod, "_poll_for_code", return_value=None):
            result = mod.run_pkce_auth()
        assert result is False
        mock_pkce.get_access_token.assert_not_called()

    def test_poll_retries_on_404_then_returns_code(self):
        import spotifactory.auth_server as mod
        call_n = [0]
        responses: list = [
            urllib.error.HTTPError("url", 404, "Not Found", {}, None),
            urllib.error.HTTPError("url", 404, "Not Found", {}, None),
        ]

        def fake_urlopen(req, **kw):
            n = call_n[0]
            call_n[0] += 1
            if n < len(responses):
                raise responses[n]
            m = MagicMock()
            m.read.return_value = json.dumps({"code": "abc123"}).encode()
            return m

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            code = mod._poll_for_code("https://relay.test", "sess01", timeout=10)
        assert code == "abc123"

    def test_poll_returns_none_after_timeout(self):
        import spotifactory.auth_server as mod
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError("url", 404, "", {}, None)), \
             patch("time.sleep"):
            # timeout=0.0 → deadline is already past on first check
            code = mod._poll_for_code("https://relay.test", "sess02", timeout=0.0)
        assert code is None


def test_sudo_rule_covers_every_power_action():
    """The Reboot/Shutdown menu items run `sudo -n systemctl <verb>`; each verb
    must be in the passwordless rule, or the item silently does nothing."""
    from spotifactory.runner import _POWER
    rule = (Path(__file__).parent.parent / "deploy" / "sudoers.sh").read_text()
    for verb, _ in _POWER.values():
        assert f'"/usr/bin/systemctl {verb}"' in rule, verb
    setup = (Path(__file__).parent.parent / "deploy" / "setup.sh").read_text()
    assert "deploy/sudoers.sh" in setup
