"""Tests for startup.py and auth_server.py."""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib opener that treats redirects as errors so we can inspect them."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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

    def _run_main(self, *, network=True, token=True, extra_patches=None):
        """Run startup.main() with the given network/token state."""
        display = MagicMock()
        patches = [
            patch("spotifactory.startup._has_network", return_value=network),
            patch("spotifactory.startup._has_valid_token", return_value=token),
            patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display),
            patch("spotifactory.menu.run_on_pi.main"),
            patch("spotifactory.auth_server.run_auth_server"),
            patch("subprocess.run"),
            patch("dotenv.load_dotenv"),
        ]
        if extra_patches:
            patches.extend(extra_patches)

        mocks = {}
        ctx = {}
        for p in patches:
            m = p.start()
            ctx[p] = m
        try:
            from spotifactory import startup
            startup.main()
        finally:
            for p in patches:
                p.stop()
        return ctx

    def test_runs_pi_when_network_and_token_present(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=True), \
             patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display), \
             patch("spotifactory.menu.run_on_pi.main") as mock_run_pi, \
             patch("spotifactory.auth_server.run_auth_server") as mock_auth, \
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
             patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display), \
             patch("spotifactory.menu.run_on_pi.main"), \
             patch("spotifactory.auth_server.run_auth_server"), \
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
             patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display), \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"), \
             pytest.raises(SystemExit):
            from spotifactory import startup
            startup.main()

    def test_launches_auth_server_when_no_token(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=False), \
             patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display), \
             patch("spotifactory.menu.run_on_pi.main"), \
             patch("spotifactory.auth_server.run_auth_server") as mock_auth, \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        mock_auth.assert_called_once()

    def test_skips_auth_server_when_token_present(self):
        display = MagicMock()
        with patch("spotifactory.startup._has_network", return_value=True), \
             patch("spotifactory.startup._has_valid_token", return_value=True), \
             patch("spotifactory.menu.renderer_oled.DisplayOLED", return_value=display), \
             patch("spotifactory.menu.run_on_pi.main"), \
             patch("spotifactory.auth_server.run_auth_server") as mock_auth, \
             patch("subprocess.run"), \
             patch("dotenv.load_dotenv"):
            from spotifactory import startup
            startup.main()
        mock_auth.assert_not_called()


# ---------------------------------------------------------------------------
# auth_server._Handler
# ---------------------------------------------------------------------------

class TestAuthServer:
    """Test the HTTP handler directly by spinning up a server on a random port."""

    def _start(self):
        import spotifactory.auth_server as mod
        server = HTTPServer(("127.0.0.1", 0), mod._Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, port, thread

    def test_root_redirects_to_spotify(self):
        import spotifactory.auth_server as mod
        mock_oauth = MagicMock()
        mock_oauth.get_authorize_url.return_value = "https://accounts.spotify.com/authorize?test=1"

        server, port, _ = self._start()
        try:
            with patch.object(mod, "_make_oauth", return_value=mock_oauth):
                opener = urllib.request.build_opener(_NoRedirectHandler)
                try:
                    opener.open(f"http://127.0.0.1:{port}/")
                    pytest.fail("expected redirect")
                except urllib.error.HTTPError as e:
                    assert e.code == 302
                    assert "accounts.spotify.com" in e.headers["Location"]
        finally:
            server.shutdown()

    def test_callback_with_code_returns_success_page(self):
        import spotifactory.auth_server as mod
        mock_oauth = MagicMock()
        mock_oauth.get_access_token.return_value = "tok"

        server, port, thread = self._start()
        with patch.object(mod, "_make_oauth", return_value=mock_oauth):
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/callback?code=testcode", timeout=3
            )
            assert resp.status == 200
            assert b"Connected" in resp.read()
        mock_oauth.get_access_token.assert_called_once_with("testcode", as_dict=False)
        thread.join(timeout=3)

    def test_callback_without_code_returns_400(self):
        server, port, _ = self._start()
        try:
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/callback", timeout=2
                )
            assert exc.value.code == 400
        finally:
            server.shutdown()

    def test_server_shuts_down_after_successful_callback(self):
        import spotifactory.auth_server as mod
        mock_oauth = MagicMock()
        mock_oauth.get_access_token.return_value = "tok"

        server, port, thread = self._start()
        with patch.object(mod, "_make_oauth", return_value=mock_oauth):
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/callback?code=abc", timeout=3
            )
        thread.join(timeout=3)
        assert not thread.is_alive(), "server should have shut down after callback"

    def test_unknown_path_returns_404(self):
        server, port, _ = self._start()
        try:
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/unknown", timeout=2
                )
            assert exc.value.code == 404
        finally:
            server.shutdown()
