from __future__ import annotations

import threading
import time
from io import BytesIO

import requests

from spotifactory.tasks.base import (
    Cancel,
    Continue,
    Done,
    PushMenu,
    Step,
    StepOutcome,
    TaskContext,
)


def _confirm_menu(album_name: str, artist_name: str):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef(album_name, [
        ItemDef("Yes", action="confirm"),
        ItemDef("No",  action="cancel"),
    ], visible_rows=2, subtitle=artist_name)


def _printer_off_menu():
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef("Printer Off?", [
        ItemDef("Retry",  action="confirm"),
        ItemDef("Cancel", action="cancel"),
    ], visible_rows=2)


class FetchInfoStep(Step):
    def __init__(self) -> None:
        super().__init__()
        self.artist: str = ""

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.spotify import get_now_playing
        self.status = "Checking Spotify..."
        info = get_now_playing()
        if info is None:
            self.show_for("Nothing playing", 2.0)
            return Done()
        # A print needs artwork and a tag needs a Spotify link; local files have
        # neither, and some tracks have no artwork. Stop before asking to print.
        if not info.album_uri or not info.artwork_url:
            self.artist = "no artwork" if info.album_uri else "local file"
            self.show_for("Can't print this", 2.5)
            self.artist = ""
            return Done()
        ctx.data["info"] = info
        return Continue()


class ConfirmStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        info = ctx.data["info"]
        return PushMenu(
            menu=_confirm_menu(info.album_name, info.artist_name),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


class FetchArtStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Fetching artwork..."
        try:
            url = ctx.data["info"].artwork_url
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            ctx.data["image"] = BytesIO(resp.content)
        except Exception as e:
            self.show_for(f"Art error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


def _pause_local_playback() -> bool:
    """Pause Spotify if it's playing on this device's Raspotify.

    The Pi Zero 2W has one radio for WiFi and Bluetooth, so streaming to the BT
    speaker while uploading to the Instax over Bluetooth makes the audio stutter.
    Music on other devices (Sonos, phone) is left alone. Returns True if paused.
    """
    try:
        from spotifactory.spotify import get_client
        sp = get_client()
        playback = sp.current_playback()
        device_name = ((playback or {}).get("device") or {}).get("name", "")
        is_local = device_name.lower().startswith("spotifactory")
        if playback and playback.get("is_playing") and is_local:
            sp.pause_playback()
            return True
    except Exception as e:
        print(f"[print] couldn't pause playback: {e}", flush=True)
    return False


def _resume_playback() -> None:
    try:
        from spotifactory.spotify import get_client
        get_client().start_playback()
    except Exception as e:
        print(f"[print] couldn't resume playback: {e}", flush=True)


class PrintStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        if ctx.printer_dry_run:
            try:
                from PIL import Image
                buf = ctx.data["image"]
                buf.seek(0)
                Image.open(buf).show()
            except Exception as e:
                print(f"[print] artwork preview failed: {e}", flush=True)

        from spotifactory.hardware.printer import print_image
        paused = _pause_local_playback()
        self.status = "Connecting..."
        try:
            result = print_image(
                ctx.data["image"],
                dry_run=ctx.printer_dry_run,
                on_progress=lambda msg: setattr(self, "status", msg),
            )
        finally:
            if paused:
                _resume_playback()
        ctx.data["print_result"] = result

        if not result.printer_found:
            return PushMenu(
                menu=_printer_off_menu(),
                on_confirm=Continue(next_step="print"),  # retry
                on_cancel=Cancel(),
            )
        if not result.success and not ctx.dry_run:
            msg = result.error or "Print failed"
            self.show_for(msg, 3.0)
            return Done()
        return Continue()


_TAG_WRITE_TIMEOUT_SECS = 120.0


class _WriteTagStep(Step):
    """Writes the just-printed album/playlist URI to a tag.

    Back skips; gives up after a timeout so the device can't get stuck here.
    A tag that can't be written shows why and waits for another one.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self.artist: str = ""

    def cancel(self) -> None:
        self._cancel.set()

    def _uri(self, ctx: TaskContext) -> str:
        raise NotImplementedError

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.hardware.rfid import TagWriteError, write_uri

        self._cancel.clear()
        deadline = time.monotonic() + _TAG_WRITE_TIMEOUT_SECS

        def stop() -> bool:
            return self._cancel.is_set() or time.monotonic() >= deadline

        while not stop():
            self.status = "Place tag to write"
            self.artist = "< to skip"
            try:
                if write_uri(self._uri(ctx), terminate=stop):
                    self.artist = ""
                    return Continue()
            except TagWriteError as e:
                print(f"[capture] tag write failed: {e}", flush=True)
                self.status = "Can't write this tag"
                self.artist = str(e)
                self._cancel.wait(3.0)
            except Exception as e:
                print(f"[capture] RFID error: {e}", flush=True)
                self.artist = ""
                self.show_for(f"RFID error: {e}", 3.0)
                return Done()

        self.artist = ""
        self.show_for("Tag not written", 2.0)
        return Done()


class ScanStep(_WriteTagStep):
    def _uri(self, ctx: TaskContext) -> str:
        return ctx.data["info"].album_uri


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        result = ctx.data.get("print_result")
        self.status = "Album ready!"
        self.artist = f"{result.photos_left} photos left" if result else ""
        self.detail = f"Battery: {result.battery_pct}%" if (result and result.battery_pct is not None) else ""
        time.sleep(3.0)
        return Done()


# ---------------------------------------------------------------------------
# Playlist-specific steps  (share FetchArtStep, PrintStep with the album task)
# ---------------------------------------------------------------------------

class FetchPlaylistInfoStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Checking Spotify..."
        try:
            from spotifactory.spotify import get_client
            sp = get_client()
            playback = sp.current_playback()
        except Exception as e:
            self.show_for(f"Spotify error: {str(e)[:20]}", 3.0)
            return Done()

        if not playback:
            self.show_for("Nothing playing", 2.0)
            return Done()

        context = playback.get("context")
        if not context or context.get("type") != "playlist":
            self.show_for("No playlist playing", 2.0)
            return Done()

        playlist_uri = context["uri"]
        playlist_id = playlist_uri.split(":")[-1]

        self.status = "Fetching playlist..."
        pl = None
        try:
            # sp.playlist() adds additional_types=track which causes 404 on
            # auto-generated playlists; use _get directly to avoid it.
            pl = sp._get(f"playlists/{playlist_id}")
        except Exception as e:
            if "404" not in str(e):
                self.show_for(f"Playlist error: {str(e)[:20]}", 3.0)
                return Done()
            # Auto-generated playlists (Discover Weekly, Daily Mix, radio) are
            # not accessible via the public API. Fall back to the current
            # track's album art so the tag is still useful.

        if pl is not None:
            images = pl.get("images", [])
            name = pl.get("name", "Unknown Playlist")
            owner = pl.get("owner", {}).get("display_name", "")
            image_url = images[0]["url"] if images else None
        else:
            item = playback.get("item", {})
            album_images = item.get("album", {}).get("images", [])
            image_url = album_images[0]["url"] if album_images else None
            name = "Auto Playlist"
            owner = item.get("name", "")

        if not image_url:
            self.show_for("No image available", 2.0)
            return Done()

        ctx.data["playlist"] = {
            "name": name,
            "uri": playlist_uri,
            "image_url": image_url,
            "owner": owner,
            "labelled": pl is not None,
        }
        return Continue()


class PlaylistConfirmStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        pl = ctx.data["playlist"]
        return PushMenu(
            menu=_confirm_menu(pl["name"], pl["owner"]),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


def _label_menu(playlist_name: str):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef("Add name?", [
        ItemDef("Yes", action="confirm", data="label"),
        ItemDef("No",  action="confirm", data="plain"),
    ], visible_rows=2, subtitle=playlist_name)


class PlaylistLabelStep(Step):
    """Ask whether to print the playlist's name on it: auto-made covers need
    it, custom ones often don't, and some custom ones still do. Back cancels
    the print, as on the confirm screen."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        pl = ctx.data["playlist"]
        if not pl.get("labelled", True):
            return Continue()    # auto playlist: no name to print
        return PushMenu(
            menu=_label_menu(pl["name"]),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


class FetchPlaylistArtStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Fetching artwork..."
        try:
            pl = ctx.data["playlist"]
            resp = requests.get(pl["image_url"], timeout=10)
            resp.raise_for_status()
            ctx.data["image"] = BytesIO(resp.content)
        except Exception as e:
            self.show_for(f"Art error: {str(e)[:20]}", 3.0)
            return Done()
        # The playlist's name across the bottom, if asked for (album prints
        # stay plain). Auto playlists have no name we can read.
        if pl.get("labelled", True) and ctx.data.get("selected") == "label":
            try:
                from spotifactory.tasks.capture.label import add_playlist_label
                ctx.data["image"] = add_playlist_label(ctx.data["image"], pl["name"])
            except Exception as e:
                print(f"[print] couldn't add playlist name: {e}", flush=True)
        return Continue()


class PlaylistScanStep(_WriteTagStep):
    def _uri(self, ctx: TaskContext) -> str:
        return ctx.data["playlist"]["uri"]


class PlaylistDoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        result = ctx.data.get("print_result")
        self.status = "Playlist ready!"
        self.artist = f"{result.photos_left} photos left" if result else ""
        self.detail = f"Battery: {result.battery_pct}%" if (result and result.battery_pct is not None) else ""
        time.sleep(3.0)
        return Done()
