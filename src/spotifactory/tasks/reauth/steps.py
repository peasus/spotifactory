from __future__ import annotations

import os
import threading
import uuid

from spotifactory.tasks.base import Cancel, Continue, Done, Step, StepOutcome, TaskContext


def _make_qr(url: str):
    """Generate a QR code as a mode-1 PIL Image. Auto-selects V2 or V3."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_L, box_size=2, border=0)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="white", back_color="black")
    return img.get_image().convert("1")


class QRAuthStep(Step):
    """Shows a scannable QR code + shortened URL for the PKCE relay auth flow.

    The runner renders this step's qr_image + session_url as a full-screen QR
    display. Pressing Up cancels and returns to the main menu.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._show_url: bool = False
        self.qr_image = None   # PIL Image — set once QR is ready, read by runner
        self.session_url: str = ""

    def cancel(self) -> None:
        self._cancel.set()

    def toggle_url(self) -> None:
        self._show_url = not self._show_url

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotipy.oauth2 import SpotifyPKCE
        from spotifactory.spotify import SCOPES
        from spotifactory.auth_server import _poll_for_code, _post_register

        self.status = "Preparing..."
        relay_url = os.environ["RELAY_URL"].rstrip("/")
        session_id = uuid.uuid4().hex[:8]

        auth = SpotifyPKCE(
            client_id=os.environ["SPOTIPY_CLIENT_ID"],
            redirect_uri=f"{relay_url}/callback",
            scope=" ".join(SCOPES),
            open_browser=False,
        )
        authorize_url = auth.get_authorize_url(state=session_id)
        try:
            _post_register(relay_url, session_id, authorize_url)
        except OSError as e:  # URLError, DNS, timeouts: relay unreachable
            print(f"[reauth] can't reach login relay {relay_url!r}: {e}", flush=True)
            self.show_for("Can't reach login", 3.0)
            return Cancel()

        session_url = f"{relay_url}/{session_id}"

        self.status = "Scan QR to connect"
        self.session_url = session_url
        self.qr_image = _make_qr(session_url)

        print(f"[reauth] visit {self.session_url}", flush=True)

        code = _poll_for_code(
            relay_url,
            session_id,
            terminate=self._cancel.is_set,
        )

        self.qr_image = None  # stop QR rendering while we wrap up

        if not code or self._cancel.is_set():
            return Cancel()

        self.status = "Connecting..."
        auth.get_access_token(code, check_cache=False)

        import spotipy as _spotipy
        from spotifactory.spotify import _set_client
        _set_client(_spotipy.Spotify(auth_manager=auth))

        self.show_for("Spotify connected!", 2.0)
        return Continue()


class PlayerLoginStep(Step):
    """Signs the box's own player (Raspotify) in to Spotify, so tags play
    without a phone ever finding the box on the wifi (player_login.py).

    Shows a QR code for spotify.com/pair with the code in it, and the code
    itself to type. Skipped when the player already has a saved login. A box
    whose librespot is too old to pair asks for the Spotify app instead, as
    before. Back skips it.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self._show_url: bool = False
        self.qr_image = None       # read by the runner, as for the Spotify login
        self.session_url: str = ""
        self.qr_lines: list[str] = []
        self.text_lines: list[str] = []
        self.artist: str = ""
        self.detail: str = ""

    def cancel(self) -> None:
        self._cancel.set()

    def toggle_url(self) -> None:
        self._show_url = not self._show_url

    def _show_code(self, url: str, code: str) -> None:
        self.session_url = url
        self.qr_lines = ["Scan so box", "can play", code or "Spotify"]
        self.text_lines = ["Let this box play:", "spotify.com/pair",
                           f"Code: {code}" if code else "", "", "< Skip  > QR Code"]
        self.qr_image = _make_qr(url)

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory import player_login
        if player_login.has_login():
            return Done()
        if not player_login.can_pair():
            return self._ask_for_app()
        self.status = "Getting a code..."
        ok = player_login.pair(self._show_code, self._cancel.is_set)
        self.qr_image = None
        if ok:
            self.show_for("Box can play now!", 2.0)
        elif not self._cancel.is_set():
            self.show_for("Code ran out", 2.0)
        return Done()

    def _ask_for_app(self) -> StepOutcome:
        """librespot older than 0.7: only the Spotify app can sign it in.
        Linking it to the account just signed in avoids the Web API
        controlling one account while audio plays on another."""
        self.status = "Open Spotify app:"
        self.artist = "tap Spotifactory"
        self.detail = "< when done"
        self._cancel.wait(timeout=30.0)
        return Done()


ZeroconfPromptStep = PlayerLoginStep       # older name, used by the setup tasks
