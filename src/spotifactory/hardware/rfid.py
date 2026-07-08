from __future__ import annotations

import os
import sys
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


PORT = os.environ.get("NFC_PORT") or _default_port()


def _parse_tag(tag) -> dict:
    entry = {"uid": tag.identifier.hex().upper()}
    if tag.ndef and tag.ndef.records:
        for record in tag.ndef.records:
            if isinstance(record, ndef.UriRecord):
                entry["uri"] = record.uri
                break
    return entry


def watch_tags(
    on_place: "Callable[[dict], None]",
    on_remove: "Callable[[dict], None] | None" = None,
    terminate: "Callable[[], bool] | None" = None,
    port: str = PORT,
) -> None:
    """Block until terminate() returns True, firing on_place/on_remove as tags enter/leave.

    Uses nfcpy supervision mode (on-connect returns True) so the PN532 handles
    presence detection natively — no application-level polling needed.

    on_place(card) — tag entered the field; card has 'uid' and optionally 'uri'
    on_remove(card) — same card dict, tag has left the field
    terminate() — called periodically; return True to stop
    """
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

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(
            rdwr={"on-connect": on_connect, "on-release": on_release},
            terminate=terminate,
        )


def read_card(port: str = PORT) -> dict | None:
    """Block until a card is scanned. Returns dict with uid and uri (if written)."""
    result = []

    def on_connect(tag):
        result.append(_parse_tag(tag))
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

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
