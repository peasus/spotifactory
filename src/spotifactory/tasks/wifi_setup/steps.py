"""WiFi setup: the box's own "Spotifactory" hotspot and setup page.

Runs as a step inside the app, so the screen stays live and Menu works
(it leaves setup for the main menu). The page is deploy/portal/index.html,
served on port 80 of the hotspot; every DNS name points there, so phones
open it on their own once they join.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from spotifactory import wifi
from spotifactory.tasks.base import Cancel, Continue, Done, Step, StepOutcome, TaskContext

PORTAL_PAGE = Path(__file__).resolve().parents[4] / "deploy" / "portal" / "index.html"
_PORTS = (80, 8080)              # 80 for the phone's sign-in popup; 8080 if we can't bind it
_SAVED_RETRY_SECS = 300.0        # with nobody on the page, retry saved WiFi this often
_IDLE_BEFORE_RETRY_SECS = 180.0


def _page_security(sec: str) -> str:
    """The page knows none|wep|wpa|enterprise."""
    return "wpa" if sec == "wpa3" else sec


class WifiSetupStep(Step):
    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._requests: queue.Queue = queue.Queue()
        self._show_url = False
        self.qr_image = None             # the runner draws it, as for the Spotify login
        self.session_url = ""
        self.qr_lines = ("Join WiFi", wifi.AP_SSID, "for setup")
        self.text_lines = ("On your phone, join", f"WiFi: {wifi.AP_SSID}", "and pick your WiFi.",
                           "Menu: more options")
        self.artist = ""
        self.detail = ""
        self.networks: list[wifi.Network] = []
        self.last_error = ""
        self._last_request = 0.0

    def cancel(self) -> None:
        self._cancel.set()

    def toggle_url(self) -> None:
        self._show_url = not self._show_url

    # ----------------------------------------------------------- screen

    def _say(self, line1: str, line2: str = "", line3: str = "") -> None:
        self.qr_image = None
        self.status, self.artist, self.detail = line1, line2, line3

    def _show_qr(self) -> None:
        from spotifactory.tasks.reauth.steps import _make_qr
        self.status, self.artist, self.detail = "Join WiFi for setup", "", ""
        self.qr_image = _make_qr(wifi.wifi_qr_payload())

    # ------------------------------------------------------------ server

    def _serve(self) -> ThreadingHTTPServer | None:
        step = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj) -> None:
                self._send(200, json.dumps(obj).encode(), "application/json")

            def do_GET(self) -> None:
                step._last_request = time.monotonic()
                path = urllib.parse.urlsplit(self.path).path
                if path == "/networks":
                    self._json([{"ssid": n.ssid, "security": _page_security(n.security)}
                                for n in step.networks])
                elif path == "/status":
                    self._json({"error": step.last_error})
                elif path != "/" and (self.headers.get("Host") or "").split(":")[0] != wifi.AP_ADDRESS:
                    # A phone checking for a sign-in page (captive.apple.com,
                    # connectivitycheck.gstatic.com...): send it to ours.
                    self._send(302, b"", "text/plain", {"Location": step.session_url})
                else:
                    try:
                        body = PORTAL_PAGE.read_bytes()
                    except OSError:
                        body = b"<h1>Spotifactory WiFi setup</h1>"
                    self._send(200, body, "text/html; charset=utf-8")

            def do_POST(self) -> None:
                step._last_request = time.monotonic()
                if urllib.parse.urlsplit(self.path).path != "/connect":
                    self._send(404, b"", "text/plain")
                    return
                length = min(int(self.headers.get("Content-Length") or 0), 8192)
                raw = self.rfile.read(length).decode(errors="replace")
                try:
                    fields = json.loads(raw)
                except ValueError:
                    fields = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
                ssid = str(fields.get("ssid") or "").strip()
                if not ssid:
                    self._send(400, b"ssid missing", "text/plain")
                    return
                self._json({})
                step._requests.put((ssid, str(fields.get("passphrase") or ""),
                                    str(fields.get("identity") or "")))

            def log_message(self, fmt: str, *args) -> None:
                print(f"[wifi-setup] {self.address_string()} {fmt % args}", flush=True)

        for port in _PORTS:
            try:
                server = ThreadingHTTPServer(("", port), Handler)
            except OSError as e:
                print(f"[wifi-setup] can't serve on port {port}: {e}", flush=True)
                continue
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.session_url = f"http://{wifi.AP_ADDRESS}" + ("" if port == 80 else f":{port}") + "/"
            print(f"[wifi-setup] setup page at {self.session_url}", flush=True)
            return server
        return None

    # --------------------------------------------------------------- run

    def _hotspot_up(self) -> bool:
        for attempt in range(3):
            try:
                wifi.start_hotspot()
                self._show_qr()
                return True
            except Exception as e:
                print(f"[wifi-setup] hotspot failed ({attempt + 1}/3): {e}", flush=True)
                self._say("WiFi setup failed", "Trying again...")
                if self._cancel.wait(5.0):
                    return False
        return False

    def _rescan(self) -> None:
        nets = wifi.scan()
        if not nets:
            time.sleep(3.0)
            nets = wifi.scan()
        self.networks = nets
        print(f"[wifi-setup] {len(nets)} networks nearby", flush=True)

    def _join(self, ssid: str, passphrase: str, identity: str) -> bool:
        self._say("Joining WiFi...", ssid[:21])
        wifi.stop_hotspot()
        known = next((n for n in self.networks if n.ssid == ssid), None)
        try:
            # Rescan first either way: the list was made before the hotspot
            # went up and can be stale.
            found = wifi.scan_until_found(ssid)
            sec = found.security if found else (known.security if known else None)
            if sec is None:
                raise wifi.JoinError("Network not found")
            wifi.join(ssid, passphrase, identity, security=sec)
            self.last_error = ""
            return True
        except wifi.JoinError as e:
            self.last_error = f"Couldn't join {ssid} ({e})"
            self._say("Couldn't join", ssid[:21], str(e))
            self._cancel.wait(5.0)
            return False

    def run(self, ctx: TaskContext) -> StepOutcome:
        if ctx.dry_run:                       # the simulator: just the screen
            self._show_qr()
            self._cancel.wait()
            return Cancel()

        self._say("Starting WiFi", "setup...")
        self._rescan()
        server = self._serve()
        if server is None or not self._hotspot_up():
            if server is not None:
                server.shutdown()
                server.server_close()
            wifi.stop_hotspot()
            self._say("WiFi setup failed", "Menu > Reboot", "to try again")
            self._cancel.wait(8.0)
            return Cancel()

        connected = False
        last_retry = time.monotonic()
        try:
            while not self._cancel.is_set():
                try:
                    ssid, passphrase, identity = self._requests.get(timeout=1.0)
                except queue.Empty:
                    now = time.monotonic()
                    if (now - last_retry > _SAVED_RETRY_SECS
                            and now - self._last_request > _IDLE_BEFORE_RETRY_SECS
                            and wifi.saved_wifi()):
                        last_retry = now
                        self._say("Trying saved", "WiFi...")
                        wifi.stop_hotspot()
                        if wifi.try_saved_networks():
                            connected = True
                            break
                        self._rescan()
                        if not self._hotspot_up():
                            break
                    continue
                if self._join(ssid, passphrase, identity):
                    connected = True
                    break
                self._rescan()
                if not self._hotspot_up():
                    break
        finally:
            server.shutdown()
            server.server_close()
            if not connected:
                wifi.stop_hotspot()
                # Leaving setup from the menu: let a saved network come back.
                wifi.try_saved_networks(seconds=1.0)

        if not connected:
            return Cancel()
        self._say("WiFi connected!")
        time.sleep(2.0)
        from spotifactory import backend
        if backend.is_music_assistant() or backend.has_login():
            return Done()
        return Continue()                     # on to the Spotify login
