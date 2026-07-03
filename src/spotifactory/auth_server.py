"""PKCE Spotify auth via Cloudflare Worker relay.

Flow:
  1. Pi generates session_id + SpotifyPKCE object (code_verifier stored internally)
  2. Pi builds Spotify authorize URL that includes the code_challenge
  3. Pi POSTs {session_id, authorize_url} to the relay
  4. on_session_ready callback fires so OLED can display the session URL
  5. Pi polls relay GET /poll/{session_id} every second until code arrives
  6. Pi exchanges code via auth.get_access_token(code) — no client_secret needed
  7. Token saved to .cache; run_pkce_auth() returns True

Required env vars: RELAY_URL, SPOTIPY_CLIENT_ID
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, Optional

POLL_INTERVAL = 1.5   # seconds between relay polls
POLL_TIMEOUT = 300.0  # give up after 5 minutes


def run_pkce_auth(on_session_ready: Optional[Callable[[str], None]] = None) -> bool:
    """Run PKCE relay auth flow. Calls on_session_ready(url) once registered.

    Returns True when the token has been saved to .cache, False on timeout.
    """
    from spotipy.oauth2 import SpotifyPKCE
    from spotifactory.spotify import SCOPES

    relay_url = os.environ["RELAY_URL"].rstrip("/")
    session_id = uuid.uuid4().hex[:8]

    auth = SpotifyPKCE(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        redirect_uri=f"{relay_url}/callback",
        scope=" ".join(SCOPES),
        open_browser=False,
    )

    # get_authorize_url() generates code_verifier + code_challenge internally
    authorize_url = auth.get_authorize_url(state=session_id)

    _post_register(relay_url, session_id, authorize_url)

    session_url = f"{relay_url}/{session_id}"
    print(f"[auth] visit {session_url}", flush=True)

    if on_session_ready is not None:
        on_session_ready(session_url)

    code = _poll_for_code(relay_url, session_id)
    if not code:
        print("[auth] timed out waiting for Spotify code", flush=True)
        return False

    print("[auth] exchanging code for tokens", flush=True)
    auth.get_access_token(code, as_dict=False, check_cache=False)
    print("[auth] token saved", flush=True)
    return True


def _post_register(relay_url: str, session_id: str, authorize_url: str) -> None:
    data = json.dumps({"session_id": session_id, "authorize_url": authorize_url}).encode()
    req = urllib.request.Request(
        f"{relay_url}/register",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def _poll_for_code(
    relay_url: str,
    session_id: str,
    timeout: float = POLL_TIMEOUT,
    terminate: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """Poll the relay until the auth code arrives, timeout expires, or terminate() is True."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if terminate is not None and terminate():
            return None
        try:
            resp = urllib.request.urlopen(
                f"{relay_url}/poll/{session_id}", timeout=5
            )
            body = json.loads(resp.read())
            return body["code"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(POLL_INTERVAL)
            else:
                raise
    return None


def _shorten_url(url: str) -> str:
    """Shorten a URL via TinyURL. Falls back to the original on any error."""
    try:
        api = "https://tinyurl.com/api-create.php?url=" + urllib.parse.quote(url, safe="")
        resp = urllib.request.urlopen(api, timeout=10)
        short = resp.read().decode().strip()
        if short.startswith("http"):
            return short
    except Exception as e:
        print(f"[auth] URL shortening failed: {e}", flush=True)
    return url
