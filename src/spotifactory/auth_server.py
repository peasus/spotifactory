"""Minimal Spotify OAuth callback server for headless Pi setup.

Serves on port 8080:
  GET /          → redirects to Spotify authorise URL
  GET /callback  → exchanges code for token (spotipy saves .cache), returns success page

Call run_auth_server() and it blocks until the callback is received.
"""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

PORT = 8080

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
])

SUCCESS_HTML = b"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Spotifactory</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:sans-serif;text-align:center;padding:60px 20px;background:#191414;color:#fff}
h1{color:#1DB954;font-size:2em}p{color:#ccc}</style></head>
<body><h1>&#10003; Connected!</h1>
<p>Your Spotifactory is ready.<br>You can close this tab.</p>
</body></html>
"""

ERROR_HTML = b"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Spotifactory</title></head>
<body><h1>Something went wrong</h1><p>Please restart the device and try again.</p></body>
</html>
"""


def _make_oauth():
    from spotipy.oauth2 import SpotifyOAuth
    return SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=SCOPES,
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress request logs

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            url = _make_oauth().get_authorize_url()
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        elif parsed.path == "/callback":
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            if code:
                try:
                    _make_oauth().get_access_token(code, as_dict=False)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(SUCCESS_HTML)
                    # Shut down server after response is sent
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                except Exception as e:
                    print(f"[auth] token exchange failed: {e}", flush=True)
                    self.send_response(500)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(ERROR_HTML)
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


def run_auth_server() -> None:
    """Block until Spotify OAuth callback is received and token is saved."""
    server = HTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[auth] listening on :{PORT}", flush=True)
    server.serve_forever()
    print("[auth] token saved, server stopped", flush=True)
