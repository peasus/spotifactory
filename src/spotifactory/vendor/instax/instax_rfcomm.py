"""Bluetooth Classic RFCOMM backend for Instax printers (Linux/Pi).

The Instax Square Link advertises two Bluetooth personalities:
  - INSTAX-xxxxxxxx (IOS)     — BLE GATT at FA:AB:BC:xx:xx:xx
  - INSTAX-xxxxxxxx (ANDROID) — Classic BT RFCOMM at 88:B4:36:xx:xx:xx

On BCM43438 (Pi Zero 2W) BLE GATT service discovery fails. However Classic BT
RFCOMM works fine. This module scans for the IOS BLE advertisement (which is
visible even when GATT connection fails), derives the Classic BT address from
the last three octets, and connects via RFCOMM on port 6.

Address derivation: FA:AB:BC:xx:xx:xx → 88:B4:36:xx:xx:xx
This is a Fujifilm firmware convention confirmed across multiple Instax models.
Override with INSTAX_BT_ADDRESS env var if needed.

Reference: paorin/InstaxLink and fernandi/InstaxBLE-Pi on GitHub.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from io import BytesIO
from struct import pack, unpack_from

from PIL import Image

try:
    from .Types import EventType, InfoType, PrinterSettings
    from . import LedPatterns
except ImportError:
    from Types import EventType, InfoType, PrinterSettings
    import LedPatterns

_RFCOMM_PORT = 6
_IOS_PREFIX = "FA:AB:BC:"
_ANDROID_PREFIX = "88:B4:36:"
_SCAN_DURATION_MS = 2000


def _derive_android_addr(ios_addr: str) -> str:
    suffix = ios_addr.upper()[len(_IOS_PREFIX):]
    return _ANDROID_PREFIX + suffix


def _find_printer_address(timeout: int) -> str | None:
    if addr := os.environ.get("INSTAX_BT_ADDRESS"):
        return addr

    try:
        import simplepyble
    except ImportError:
        return None

    adapters = simplepyble.Adapter.get_adapters()
    if not adapters:
        return None
    adapter = adapters[0]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        adapter.scan_for(_SCAN_DURATION_MS)
        for p in adapter.scan_get_results():
            name = p.identifier()
            addr = p.address().upper()
            if name.startswith("INSTAX-") and addr.startswith(_IOS_PREFIX.upper()):
                return _derive_android_addr(addr)
    return None


def _checksum(data: bytes) -> int:
    return (255 - (sum(data) & 255)) & 255


def _make_packet(event, payload: bytes = b"") -> bytes:
    if isinstance(event, EventType):
        event = event.value
    header = b"\x41\x62"
    op = bytes([event[0], event[1]])
    size = pack(">H", 7 + len(payload))
    pkt = header + size + op + payload
    return pkt + pack("B", _checksum(pkt))


class _FakePeripheral:
    def __init__(self, owner: "InstaxRFCOMM") -> None:
        self._owner = owner

    def is_connected(self) -> bool:
        return self._owner._connected


class InstaxRFCOMM:
    """Instax printer driver using Bluetooth Classic RFCOMM.

    Drop-in replacement for _TrackedInstaxBLE in printer.py on Linux.
    Exposes the same attributes: upload_progress, upload_complete,
    print_confirmed, cancelled, photosLeft, peripheral.
    """

    def __init__(self, print_enabled: bool = False, quiet: bool = False, **_):
        self.printEnabled = print_enabled
        self.quiet = quiet

        self.photosLeft = 0
        self.batteryPercentage = 0
        self.isCharging = False
        self.printerSettings: dict | None = None
        self.imageSize: tuple[int, int] = (0, 0)
        self.chunkSize: int = 0

        self._sock: socket.socket | None = None
        self._connected = False
        self._lock = threading.Lock()

        self.cancelled = False
        self.print_confirmed = False
        self._upload_progress = 0.0
        self._upload_complete = False

        self.peripheral = _FakePeripheral(self)

    # ---------- progress properties (mirrors _TrackedInstaxBLE) ----------

    @property
    def upload_progress(self) -> float:
        return self._upload_progress

    @property
    def upload_complete(self) -> bool:
        return self._upload_complete

    # ---------- connection ----------

    def connect(self, timeout: int = 0) -> None:
        addr = _find_printer_address(max(timeout, 10))
        if not addr:
            return
        try:
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(15)
            sock.connect((addr, _RFCOMM_PORT))
            self._sock = sock
            self._connected = True
        except Exception as e:
            if not self.quiet:
                print(f"[rfcomm] connect failed: {e}", flush=True)
            return
        self._query_printer_info()

    def disconnect(self) -> None:
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ---------- low-level I/O ----------

    def _send_recv(self, packet: bytes) -> bytes | None:
        with self._lock:
            if not self._sock:
                return None
            try:
                self._sock.sendall(packet)
                return self._sock.recv(4096)
            except Exception as e:
                if not self.quiet:
                    print(f"[rfcomm] i/o error: {e}", flush=True)
                self.cancelled = True
                return None

    def _parse_response(self, data: bytes) -> None:
        if not data or len(data) < 8:
            return
        _, _length, op1, op2 = unpack_from(">HHBB", data)
        try:
            event = EventType((op1, op2))
        except ValueError:
            return

        if event == EventType.SUPPORT_FUNCTION_INFO:
            try:
                info_type = InfoType(data[7])
            except (ValueError, IndexError):
                return
            if info_type == InfoType.IMAGE_SUPPORT_INFO and len(data) >= 12:
                w, h = unpack_from(">HH", data, 8)
                self.imageSize = (w, h)
                if (w, h) == (600, 800):
                    self.printerSettings = PrinterSettings["mini"]
                elif (w, h) == (800, 800):
                    self.printerSettings = PrinterSettings["square"]
                elif (w, h) == (1260, 840):
                    self.printerSettings = PrinterSettings["wide"]
                if self.printerSettings:
                    self.chunkSize = self.printerSettings["chunkSize"]
            elif info_type == InfoType.BATTERY_INFO and len(data) >= 10:
                self.batteryPercentage = data[9]
            elif info_type == InfoType.PRINTER_FUNCTION_INFO and len(data) >= 9:
                b = data[8]
                self.photosLeft = b & 15
                self.isCharging = bool((1 << 7) & b)
        elif event == EventType.PRINT_IMAGE:
            self.print_confirmed = True

    def _query_printer_info(self) -> None:
        for info in [InfoType.IMAGE_SUPPORT_INFO, InfoType.BATTERY_INFO, InfoType.PRINTER_FUNCTION_INFO]:
            pkt = _make_packet(EventType.SUPPORT_FUNCTION_INFO, pack(">B", info.value))
            resp = self._send_recv(pkt)
            if resp:
                self._parse_response(resp)
        if not self.printerSettings:
            # Fallback: assume Square Link
            self.printerSettings = PrinterSettings["square"]
            self.imageSize = (800, 800)
            self.chunkSize = self.printerSettings["chunkSize"]

    # ---------- high-level API ----------

    def create_color_payload(self, colorArray, speed: int, repeat: int, when: int) -> bytes:
        payload = pack("BBBB", when, len(colorArray), speed, repeat)
        for r, g, b in colorArray:
            payload += pack("BBB", r, g, b)
        return payload

    def send_led_pattern(self, pattern, speed: int = 5, repeat: int = 255, when: int = 0) -> None:
        payload = self.create_color_payload(pattern, speed, repeat, when)
        pkt = _make_packet(EventType.LED_PATTERN_SETTINGS, payload)
        self._send_recv(pkt)  # fire-and-forget (discard ack)

    def _image_to_jpeg(self, img: Image.Image, max_kb: int = 105) -> bytearray:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img = img.resize(self.imageSize, Image.Resampling.LANCZOS)
        buf = BytesIO()
        lo, hi, q = 1, 100, 75
        while lo <= hi:
            buf.seek(0); buf.truncate()
            img.save(buf, format="JPEG", quality=q)
            kb = buf.tell() / 1024
            if kb <= max_kb and kb >= max_kb * 0.9:
                break
            hi, lo = (q - 1, lo) if kb > max_kb else (hi, q + 1)
            q = (lo + hi) // 2
        buf.seek(0); buf.truncate()
        img.save(buf, format="JPEG", quality=q)
        return bytearray(buf.getvalue())

    def _do_print(self, img_data: bytearray) -> None:
        chunk_size = self.chunkSize or 900
        chunks = [img_data[i:i + chunk_size] for i in range(0, len(img_data), chunk_size)]
        if chunks and len(chunks[-1]) < chunk_size:
            chunks[-1] = chunks[-1] + bytes(chunk_size - len(chunks[-1]))

        # START
        start = _make_packet(
            EventType.PRINT_IMAGE_DOWNLOAD_START,
            b"\x02\x00\x00\x00" + pack(">I", len(img_data)),
        )
        resp = self._send_recv(start)
        if resp:
            self._parse_response(resp)
        if self.cancelled:
            return

        # DATA
        n = len(chunks)
        for idx, chunk in enumerate(chunks):
            if self.cancelled:
                return
            pkt = _make_packet(
                EventType.PRINT_IMAGE_DOWNLOAD_DATA,
                pack(">I", idx) + bytes(chunk),
            )
            resp = self._send_recv(pkt)
            if resp:
                self._parse_response(resp)
            self._upload_progress = (idx + 1) / n

        self._upload_complete = True

        # END
        resp = self._send_recv(_make_packet(EventType.PRINT_IMAGE_DOWNLOAD_END))
        if resp:
            self._parse_response(resp)

        if self.printEnabled and not self.cancelled:
            # PRINT
            resp = self._send_recv(_make_packet(EventType.PRINT_IMAGE))
            if resp:
                self._parse_response(resp)
            # Post-print status query
            self._send_recv(_make_packet((0, 2), b"\x02"))

    def print_image(self, imgSrc) -> None:
        if not self._connected or not self.printerSettings:
            return

        if isinstance(imgSrc, str):
            img = Image.open(imgSrc)
        elif isinstance(imgSrc, BytesIO):
            imgSrc.seek(0)
            img = Image.open(imgSrc)
        else:
            img = imgSrc

        img_data = self._image_to_jpeg(img)

        t = threading.Thread(target=self._do_print, args=(img_data,), daemon=True)
        t.start()
