from __future__ import annotations

import os
import sys
import time
from typing import Callable

import ndef
import nfc


def _patch_serial_nonexclusive() -> None:
    """Disable pyserial's TIOCEXCL exclusive-mode ioctl.

    CH340 and similar USB-serial chips return ENODEV for the TIOCEXCL ioctl
    that pyserial issues by default, on both macOS and Linux (Pi). Setting
    exclusive=None tells pyserial not to touch the exclusive-mode flag at all.
    """
    try:
        import serial
        _orig = serial.Serial.__init__

        def _patched(self, *args, **kwargs):
            kwargs.setdefault("exclusive", None)
            _orig(self, *args, **kwargs)

        serial.Serial.__init__ = _patched
    except Exception:
        pass


_patch_serial_nonexclusive()


def _default_port() -> str:
    """Return the default nfcpy port string for the PN532 reader.

    On macOS, 'tty:usbserial' auto-discovers any cu.usbserial-* device.
    On Linux, scan for the first ttyUSB or ttyACM device and build the
    nfcpy port string (e.g. /dev/ttyUSB0 → 'tty:USB0').
    Override at runtime with NFC_PORT env var.
    """
    if sys.platform == "darwin":
        return "tty:usbserial"
    import glob
    for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*"]:
        devices = sorted(glob.glob(pattern))
        if devices:
            # nfcpy expects "tty:USB0" not "/dev/ttyUSB0"
            return "tty:" + devices[0][len("/dev/tty"):]
    return "tty:USB0"


def _dev_path(nfcpy_port: str) -> str | None:
    """'tty:USB0' → '/dev/ttyUSB0', etc. Returns None for non-tty ports."""
    if nfcpy_port.startswith("tty:"):
        return "/dev/tty" + nfcpy_port[4:]
    return None


def current_port() -> str:
    """The reader's port right now: NFC_PORT if that device exists, else auto-detected.

    Checked on every open rather than once at import, because Linux can renumber
    the reader after a replug (ttyUSB0 → ttyUSB1) and a stale NFC_PORT would
    otherwise keep failing until the app restarts.
    """
    override = os.environ.get("NFC_PORT")
    if override:
        dev = _dev_path(override)
        if sys.platform == "darwin" or dev is None or os.path.exists(dev):
            return override
        print(f"[rfid] NFC_PORT {override} not present — auto-detecting", flush=True)
    return _default_port()


PORT = current_port()   # for scripts and the __main__ helper below


def _reset_uart(dev_path: str) -> None:
    """Flush serial buffers to clear leftover PN532 UART data from a previous session."""
    try:
        import serial
        with serial.Serial(dev_path, baudrate=115200, timeout=0.1, exclusive=None) as s:
            s.reset_input_buffer()
            s.reset_output_buffer()
        time.sleep(0.2)
    except Exception as e:
        print(f"[rfid] uart flush: {e}", flush=True)


def _parse_tag(tag) -> dict:
    """uid, plus "uri" (the first link: what plays) and "uris" (every link,
    e.g. a Spotify link then another service's) if it has any."""
    entry = {"uid": tag.identifier.hex().upper()}
    if tag.ndef and tag.ndef.records:
        uris = [r.uri for r in tag.ndef.records if isinstance(r, ndef.UriRecord)]
        if uris:
            entry["uri"], entry["uris"] = uris[0], uris
    return entry


def watch_tags(
    on_place: "Callable[[dict], None]",
    on_remove: "Callable[[dict], None] | None" = None,
    terminate: "Callable[[], bool] | None" = None,
    port: str | None = None,
) -> None:
    """Block until terminate() returns True, firing on_place/on_remove as tags enter/leave.

    Uses nfcpy supervision mode (on-connect returns True) so the PN532 handles
    presence detection natively — no application-level polling needed.

    on_place(card) — tag entered the field; card has 'uid' and optionally 'uri'
    on_remove(card) — same card dict, tag has left the field
    terminate() — called periodically; return True to stop
    """
    port = port or current_port()
    _current: list[dict] = []

    def on_connect(tag) -> bool:
        card = _parse_tag(tag)
        _current.clear()
        _current.append(card)
        on_place(card)
        return True  # enter supervision mode: nfcpy monitors presence until tag leaves

    def on_release(tag) -> None:
        if on_remove and _current:
            on_remove(_current[0])
        _current.clear()

    dev = _dev_path(port)
    last_exc: Exception | None = None

    for attempt in range(2):
        if attempt == 1:
            print("[rfid] retry: flushing UART buffers…", flush=True)
            if dev:
                _reset_uart(dev)

        try:
            with nfc.ContactlessFrontend(port) as clf:
                clf.connect(
                    rdwr={"on-connect": on_connect, "on-release": on_release},
                    terminate=terminate,
                )
            return  # clean exit (terminate() returned True)
        except Exception as exc:
            last_exc = exc
            if terminate and terminate():
                return  # cancelled — don't retry
            print(f"[rfid] attempt {attempt + 1} failed: {exc}", flush=True)

    raise last_exc


def read_card(port: str | None = None) -> dict | None:
    """Block until a card is scanned. Returns dict with uid and uri (if written)."""
    port = port or current_port()
    result = []

    def on_connect(tag):
        result.append(_parse_tag(tag))
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

    return result[0] if result else None


class TagWriteError(Exception):
    """A tag was found but the URI could not be written to it."""


def wait_until_clear(
    terminate: "Callable[[], bool] | None" = None,
    on_seen: "Callable[[dict], None] | None" = None,
    settle: float = 1.0,
    port: str | None = None,
) -> bool:
    """Block until no tag is on the reader: True once it's clear, False if
    terminate() returned True first. on_seen(card) fires if a tag is there
    (so the screen can ask for it to be lifted off). With nothing on the
    reader this returns after `settle` seconds."""
    port = port or current_port()
    stop = terminate or (lambda: False)
    state = {"seen": False, "released": False}
    start = time.monotonic()

    def on_connect(tag) -> bool:
        state["seen"] = True
        if on_seen:
            on_seen(_parse_tag(tag))
        return True                     # supervise it until it's lifted off

    def on_release(tag) -> None:
        state["released"] = True

    def done() -> bool:
        return (stop() or state["released"]
                or (not state["seen"] and time.monotonic() - start >= settle))

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect, "on-release": on_release}, terminate=done)
    return not stop()


def read_next(
    terminate: "Callable[[], bool] | None" = None,
    port: str | None = None,
) -> dict | None:
    """The next tag on the reader (uid, and uri if it has one), or None if
    terminate() returned True first. The tag is left where it is."""
    port = port or current_port()
    result: list[dict] = []

    def on_connect(tag) -> bool:
        result.append(_parse_tag(tag))
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect}, terminate=terminate or (lambda: False))
    return result[0] if result else None


def write_uri(
    uri: str,
    port: str | None = None,
    terminate: "Callable[[], bool] | None" = None,
    uid: str | None = None,
    extra: "list[str] | tuple[str, ...]" = (),
) -> str | None:
    """Write a URI to a tag on the reader: the one with `uid` if given (other
    tags are left alone), otherwise the next one. `extra` links follow it on
    the tag (the first link is the one boxes play by default).

    Returns the tag UID on success, or None if terminate() returned True first.
    Raises TagWriteError if a tag was found but couldn't be written
    (not NDEF-formatted, read-only, or too small for the URI).
    """
    port = port or current_port()
    stop = terminate or (lambda: False)
    result: list[str] = []
    errors: list[str] = []

    def on_connect(tag):
        if uid and tag.identifier.hex().upper() != uid:
            return False                # not the tag we checked: leave it be
        if not tag.ndef:
            errors.append("Not NDEF formatted")
            return False
        if not tag.ndef.is_writeable:
            errors.append("Tag is read-only")
            return False
        try:
            tag.ndef.records = [ndef.UriRecord(u) for u in (uri, *extra)]
        except Exception as e:
            errors.append(str(e) or type(e).__name__)
            return False
        result.append(tag.identifier.hex().upper())
        return False

    with nfc.ContactlessFrontend(port) as clf:
        while not stop() and not result and not errors:
            clf.connect(rdwr={"on-connect": on_connect}, terminate=stop)
            if not result and not errors:
                time.sleep(0.2)         # a different tag is there: look again shortly

    if errors:
        raise TagWriteError(errors[0])
    return result[0] if result else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2:
        uri = sys.argv[1]
        print(f"Scan a tag to write: {uri}")
        uid = write_uri(uri)
        if uid:
            print(f"Written to tag UID: {uid}")
    else:
        print(f"Listening on {PORT} — scan a card...")
        card = read_card()
        if card:
            print(f"UID: {card['uid']}")
            if "uri" in card:
                print(f"URI: {card['uri']}")
            else:
                print("(no NDEF data written)")
