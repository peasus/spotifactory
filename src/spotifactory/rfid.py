from __future__ import annotations

import os
import sys
import threading
from typing import Callable

import ndef
import nfc


def _patch_serial_nonexclusive() -> None:
    """Disable pyserial's TIOCEXCL on macOS.

    Some macOS USB-serial drivers (e.g. CH340) return ENODEV for the
    TIOCEXCL ioctl that pyserial issues by default.  Setting exclusive=None
    tells pyserial not to touch the exclusive-mode flag at all.
    """
    if sys.platform != "darwin":
        return
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

    'tty:usbserial' lets nfcpy auto-discover any cu.usbserial-* device on
    macOS without needing the exact serial-number suffix. On Pi/Linux the
    specific name is still used. Override at runtime with NFC_PORT.
    """
    if sys.platform == "darwin":
        return "tty:usbserial"
    return "tty:usbserial-210"


PORT = os.environ.get("NFC_PORT") or _default_port()


def read_card(port: str = PORT) -> dict | None:
    """Block until a card is scanned. Returns dict with uid and uri (if written)."""
    result = []

    def on_connect(tag):
        entry = {"uid": tag.identifier.hex().upper()}
        if tag.ndef and tag.ndef.records:
            for record in tag.ndef.records:
                if isinstance(record, ndef.UriRecord):
                    entry["uri"] = record.uri
                    break
        result.append(entry)
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

    return result[0] if result else None


def read_card_cancellable(
    cancel_event: "threading.Event",
    on_poll: "Callable[[], None] | None" = None,
    also_stop: "Callable[[], bool] | None" = None,
    port: str = PORT,
) -> dict | None:
    """Block until a card is scanned, cancel_event is set, or also_stop() returns True.

    on_poll is called on each terminate-check interval so the caller can update
    status text (e.g. with current song info).  also_stop lets callers inject a
    second termination condition (e.g. a simulated tag scan).
    """
    result = []

    def on_connect(tag):
        entry = {"uid": tag.identifier.hex().upper()}
        if tag.ndef and tag.ndef.records:
            for record in tag.ndef.records:
                if isinstance(record, ndef.UriRecord):
                    entry["uri"] = record.uri
                    break
        result.append(entry)
        return False

    def terminate():
        if on_poll:
            try:
                on_poll()
            except Exception:
                pass
        return cancel_event.is_set() or (also_stop is not None and also_stop())

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect}, terminate=terminate)

    return result[0] if result else None


def write_uri(uri: str, port: str = PORT) -> str | None:
    """Write a URI to the next scanned tag. Returns the tag UID on success."""
    result = []

    def on_connect(tag):
        if not tag.ndef:
            print("Tag is not NDEF formatted — cannot write.")
            return False
        tag.ndef.records = [ndef.UriRecord(uri)]
        result.append(tag.identifier.hex().upper())
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

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
