"""Menu > Music Source: switch between Spotify and Music Assistant.

Music Assistant is for advanced users who run their own Music Assistant
server. Setting it up shows a QR code for a small page served by the box on
the home network (the Wi-Fi portal only runs while the box is offline),
where the server address and an access token are entered.
"""
from __future__ import annotations

import html
import os
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from spotifactory.tasks.base import Continue, Done, Step, StepOutcome, TaskContext

SETUP_PORT = 8080
_DEFAULT_SERVER = "http://homeassistant.local:8095"


def _local_ip() -> str:
    """This box's address on the home network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))       # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return "spotifactory.local"
    finally:
        s.close()


def _make_qr(url: str):
    from spotifactory.tasks.reauth.steps import _make_qr as make
    return make(url)


def _switch_to_music_assistant() -> None:
    from spotifactory import backend, services
    from spotifactory.settings import save_setting
    save_setting(backend.BACKEND_KEY, backend.MUSIC_ASSISTANT)
    services.apply(backend.MUSIC_ASSISTANT)


class UseSpotifyStep(Step):
    """Back to Spotify. Goes on to the Spotify login if there isn't one."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory import backend, services, spotify
        from spotifactory.settings import save_setting
        self.status = "Switching..."
        if not ctx.dry_run:
            save_setting(backend.BACKEND_KEY, backend.SPOTIFY)
            services.apply(backend.SPOTIFY)
        if ctx.dry_run or spotify.has_login():
            self.show_for("Using Spotify", 2.0)
            return Done()
        return Continue()                 # → the Spotify login


# ---------------------------------------------------------------------------
# The setup page
# ---------------------------------------------------------------------------

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spotifactory: Music Assistant</title>
<style>
  :root {{ --bg: #191414; --card: #241f1f; --line: #3a3333; --text: #fff;
          --muted: #b3b3b3; --accent: #A9C23F; --red: #ff6b6b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
         font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width: 460px; margin: 0 auto; padding: 32px 16px; }}
  h1 {{ font-size: 1.4em; margin: 0 0 4px; }}
  p {{ color: var(--muted); margin: 0 0 16px; }}
  label {{ display: block; margin: 16px 0 6px; color: var(--muted); font-size: 0.9em; }}
  input {{ width: 100%; padding: 12px 14px; border-radius: 8px; border: 1px solid var(--line);
          background: var(--card); color: var(--text); font-size: 16px; }}
  input:focus {{ outline: 2px solid var(--accent); border-color: transparent; }}
  button {{ width: 100%; margin-top: 24px; padding: 14px; border: 0; border-radius: 999px;
           background: var(--accent); color: #000; font-weight: 700; font-size: 1em; cursor: pointer; }}
  .err {{ color: var(--red); }} .ok {{ color: var(--accent); }}
  small {{ color: var(--muted); }} a {{ color: var(--accent); }}
</style></head><body><main>
<h1>Music Assistant</h1>
{body}
</main></body></html>"""

_FORM = """<p>Play tags through your own Music Assistant server instead of Spotify.</p>
{message}
<form method="post">
  <label for="url">Server address</label>
  <input id="url" name="url" value="{url}" placeholder="http://homeassistant.local:8095"
         autocapitalize="off" autocorrect="off" spellcheck="false" required>
  <label for="token">Access token</label>
  <input id="token" name="token" type="password" autocomplete="off" required>
  <small>Make a long-lived access token in Music Assistant, under your user profile.</small>
  <button type="submit">Connect</button>
</form>"""

_DONE = """<p class="ok"><strong>Connected.</strong> Music Assistant has {players} speakers.</p>
<p>Spotifactory now plays through Music Assistant. Its own Bluetooth speaker joins
Music Assistant as a player called "Spotifactory" in a few seconds; pick any
speaker from Choose Speaker on the box.</p>
<p>To go back, choose Music Source &gt; Spotify on the box.</p>"""


class MASetupStep(Step):
    """Connect to Music Assistant and switch to it.

    With saved settings that still work, switches straight away (unless
    `always_ask`); otherwise serves the setup page until it's filled in or
    the user leaves with Back.
    """

    always_ask = False

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._connected = threading.Event()
        self._show_url = False
        self.qr_image = None        # read by the runner, as for the Spotify login
        self.session_url = ""
        self.artist = ""

    def cancel(self) -> None:
        self._cancel.set()

    def toggle_url(self) -> None:
        self._show_url = not self._show_url

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory import music_assistant as ma
        if not self.always_ask and ma.configured():
            self.status = "Connecting..."
            if ctx.dry_run or ma.has_login():
                if not ctx.dry_run:
                    _switch_to_music_assistant()
                self.show_for("Using Music Asst.", 2.0)
                return Done()

        self.status = "Preparing..."
        players: dict = {}
        step = self

        class Handler(BaseHTTPRequestHandler):
            def _page(self, body: str, status: int = 200) -> None:
                data = _PAGE.format(body=body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _form(self, message: str = "", url: str = "") -> None:
                url = url or os.environ.get(ma.URL_KEY, "") or _DEFAULT_SERVER
                self._page(_FORM.format(message=message, url=html.escape(url, quote=True)))

            def do_GET(self) -> None:
                if step._connected.is_set():
                    self._page(_DONE.format(players=players.get("n", 0)))
                else:
                    self._form()

            def do_POST(self) -> None:
                length = min(int(self.headers.get("Content-Length") or 0), 8192)
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode(errors="replace"))
                url = (fields.get("url") or [""])[0].strip()
                token = (fields.get("token") or [""])[0].strip()
                if url and "://" not in url:
                    url = "http://" + url
                try:
                    n = ma.check(url, token)
                except ma.MAAuthError:
                    self._form('<p class="err">Music Assistant didn\'t accept that token.</p>', url)
                    return
                except Exception as e:
                    print(f"[ma-setup] {url}: {e}", flush=True)
                    self._form(f'<p class="err">Couldn\'t reach Music Assistant at '
                               f'{html.escape(url)}.</p>', url)
                    return
                from spotifactory.settings import save_setting
                save_setting(ma.URL_KEY, url)
                save_setting(ma.TOKEN_KEY, token)
                save_setting(ma.SERVER_HOST_KEY, ma.server_host(url))
                players["n"] = n
                step._connected.set()
                self._page(_DONE.format(players=n))

            def log_message(self, fmt: str, *args) -> None:
                print(f"[ma-setup] {self.address_string()} {fmt % args}", flush=True)

        try:
            server = ThreadingHTTPServer(("", SETUP_PORT), Handler)
        except OSError as e:
            print(f"[ma-setup] can't serve the setup page: {e}", flush=True)
            self.show_for("Setup page error", 3.0)
            return Done()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.session_url = f"http://{_local_ip()}:{server.server_address[1]}/"
            print(f"[ma-setup] visit {self.session_url}", flush=True)
            self.status = "Scan to set up"
            self.qr_image = _make_qr(self.session_url)
            while not self._cancel.is_set() and not self._connected.is_set():
                self._cancel.wait(0.25)
        finally:
            self.qr_image = None
            # Let the phone load the "Connected" page before the server goes.
            if self._connected.is_set():
                self._cancel.wait(3.0)
            server.shutdown()
            server.server_close()

        if not self._connected.is_set():
            return Done()
        self.status = "Switching..."
        _switch_to_music_assistant()
        self.show_for("MA connected!", 2.0)
        return Done()


class MAServerStep(MASetupStep):
    """Music Source > Change MA Server: always shows the setup page."""
    always_ask = True
