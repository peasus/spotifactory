"""Tests for startup.py and auth_server.py."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
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

class TestStartupMain:
    """Integration-style tests for the startup sequencing logic.

    All hardware and external calls are mocked so these run on Mac.
    """

    def test_runs_pi_when_network_and_token_present(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=True), \
             patch("spotifactory.display.oled.DisplayOLED", return_value=display), \
             patch("spotifactory.platforms.pi.main") as mock_run_pi, \
             patch("spotifactory.auth_server.run_pkce_auth") as mock_auth, \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        mock_run_pi.assert_called_once()
        mock_auth.assert_not_called()

    def test_launches_wifi_connect_when_offline(self):
        display = MagicMock()
        # First call: no network; second call: connected (after wifi-connect)
        with patch("spotifactory.startup._has_network", side_effect=[False, True]), \
             patch("spotifactory.startup._has_valid_token", return_value=True), \
             patch("spotifactory.display.oled.DisplayOLED", return_value=display), \
             patch("spotifactory.platforms.pi.main"), \
             patch("spotifactory.auth_server.run_pkce_auth"), \
             patch("subprocess.run") as mock_sub, \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        cmd = mock_sub.call_args[0][0]
        assert cmd[0] == "wifi-connect"
        assert "--portal-ssid" in cmd

    def test_exits_if_still_offline_after_wifi_connect(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=False), \
             patch("spotifactory.display.oled.DisplayOLED", return_value=display), \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"), \
             pytest.raises(SystemExit):
            from spotifactory import startup
            startup.main()

    def test_launches_pkce_auth_when_no_token(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=False), \
             patch("spotifactory.display.oled.DisplayOLED", return_value=display), \
             patch("spotifactory.platforms.pi.main"), \
             patch("spotifactory.auth_server.run_pkce_auth") as mock_auth, \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        mock_auth.assert_called_once()

    def test_skips_auth_when_token_present(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=True), \
             patch("spotifactory.display.oled.DisplayOLED", return_value=display), \
             patch("spotifactory.platforms.pi.main"), \
             patch("spotifactory.auth_server.run_pkce_auth") as mock_auth, \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        mock_auth.assert_not_called()


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
        mock_pkce.get_access_token.assert_called_once_with(
            "mycode", as_dict=False, check_cache=False
        )

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
