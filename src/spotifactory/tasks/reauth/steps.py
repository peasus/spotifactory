from __future__ import annotations

import os
import threading
import uuid

from spotifactory.tasks.base import Cancel, Done, Step, StepOutcome, TaskContext


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
        _post_register(relay_url, session_id, authorize_url)

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
        auth.get_access_token(code, as_dict=False, check_cache=False)

        import spotipy as _spotipy
        from spotifactory.spotify import _set_client
        _set_client(_spotipy.Spotify(auth_manager=auth))

        self.show_for("Spotify connected!", 2.0)
        return Done()
