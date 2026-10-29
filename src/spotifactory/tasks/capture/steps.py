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


class AlbumLabelStep(Step):
    """Ask whether to print the album's name and artist on it. Most album
    covers say what they are, so No comes first; Back cancels the print."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        return PushMenu(
            menu=_label_menu(ctx.data["info"].album_name, yes_first=False),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


class FetchArtStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Fetching artwork..."
        info = ctx.data["info"]
        try:
            resp = requests.get(info.artwork_url, timeout=10)
            resp.raise_for_status()
            ctx.data["image"] = BytesIO(resp.content)
        except Exception as e:
            self.show_for(f"Art error: {str(e)[:20]}", 3.0)
            return Done()
        if ctx.data.get("selected") == "label":
            try:
                from spotifactory.tasks.capture.label import add_label
                ctx.data["image"] = add_label(ctx.data["image"], info.album_name, info.artist_name)
            except Exception as e:
                print(f"[print] couldn't add album name: {e}", flush=True)
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


def _skip_tag_menu():
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef("Skip the tag?", [
        ItemDef("No",  action="cancel"),
        ItemDef("Yes", action="confirm"),
    ], visible_rows=2, subtitle="Menu > Write Tag later")


def _overwrite_menu(has: str):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef("Overwrite tag?", [
        ItemDef("No",  action="cancel"),
        ItemDef("Yes", action="confirm", data="overwrite"),
    ], visible_rows=2, subtitle=f"Has {has}")


class _WriteTagStep(Step):
    """Writes an album/playlist URI to a tag.

    Never writes to a tag it hasn't read first: a tag already on the reader
    (the album that was playing) must be lifted off before a print's tag is
    written, and a tag that already holds something else is only overwritten
    if asked. Back asks before skipping; gives up after a timeout so the
    device can't get stuck here. A tag that can't be written shows why.
    """

    step_name = "scan"     # its name in the task: the prompts come back to it
    fresh_tag = True       # a tag already on the reader must be lifted off first

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self.artist: str = ""

    def cancel(self) -> None:
        self._cancel.set()

    def _uri(self, ctx: TaskContext) -> str:
        raise NotImplementedError

    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.hardware.rfid import read_next, wait_until_clear

        self._cancel.clear()
        deadline = time.monotonic() + _TAG_WRITE_TIMEOUT_SECS

        def stop() -> bool:
            return self._cancel.is_set() or time.monotonic() >= deadline

        uri = self._uri(ctx)
        again = Continue(next_step=self.step_name)
        try:
            offered = ctx.data.pop("tag_offered", None)
            if offered and ctx.data.pop("selected", None) == "overwrite":
                return self._write(uri, offered["uid"], stop)
            # A print's tag goes on a tag placed now, not the one already
            # there; and a tag we were told not to overwrite has to go.
            if self.fresh_tag or offered:
                self.status, self.artist = "Checking reader...", ""

                def seen(card: dict) -> None:
                    self.status, self.artist = "Lift the tag off", "the reader"

                if not wait_until_clear(terminate=stop, on_seen=seen):
                    return self._stopped()
            self.status, self.artist = "Place tag to write", "< to skip"
            card = read_next(terminate=stop)
            if card is None:
                return self._stopped()
            has = card.get("uri")
            if has == uri:
                self.artist = ""
                self.show_for("Tag already set", 1.5)
                return Continue()
            if has:
                ctx.data["tag_offered"] = card
                return PushMenu(menu=_overwrite_menu(_describe(has)), on_confirm=again, on_cancel=again)
            return self._write(uri, card["uid"], stop)
        except Exception as e:
            print(f"[capture] RFID error: {e}", flush=True)
            self.artist = ""
            self.show_for(f"RFID error: {e}", 3.0)
            return Done()

    def _write(self, uri: str, uid: str, stop) -> StepOutcome:
        """Write to the tag we just read, and no other."""
        from spotifactory.hardware.rfid import TagWriteError, write_uri
        self.status, self.artist = "Writing tag...", ""
        try:
            if write_uri(uri, terminate=stop, uid=uid):
                print(f"[capture] wrote {uri} to tag {uid}", flush=True)
                return Continue()
        except TagWriteError as e:
            print(f"[capture] tag write failed: {e}", flush=True)
            self.status, self.artist = "Can't write this tag", str(e)
            self._cancel.wait(3.0)
            return Continue(next_step=self.step_name)     # lift it off, try another
        return self._stopped()

    def _stopped(self) -> StepOutcome:
        if self._cancel.is_set():                         # Back: check first
            return PushMenu(menu=_skip_tag_menu(), on_confirm=Done(),
                            on_cancel=Continue(next_step=self.step_name))
        self.artist = ""
        self.show_for("Tag not written", 2.0)
        return Done()


def _describe(uri: str) -> str:
    """What a tag holds, for the overwrite question."""
    if not uri.startswith("spotify:"):
        return "something else"
    try:
        from spotifactory.spotify import uri_name
        return uri_name(uri)
    except Exception:
        return "another " + uri.split(":")[1]


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


def _label_menu(name: str, yes_first: bool):
    """Whether to print the name on it. The first item is the one selected."""
    from spotifactory.menu.definitions import ItemDef, MenuDef
    yes = ItemDef("Yes", action="confirm", data="label")
    no = ItemDef("No", action="confirm", data="plain")
    return MenuDef("Add name?", [yes, no] if yes_first else [no, yes],
                   visible_rows=2, subtitle=name)


class PlaylistLabelStep(Step):
    """Ask whether to print the playlist's name on it: auto-made covers need
    it, custom ones often don't, and some custom ones still do. Back cancels
    the print, as on the confirm screen."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        pl = ctx.data["playlist"]
        if not pl.get("labelled", True):
            return Continue()    # auto playlist: no name to print
        return PushMenu(
            menu=_label_menu(pl["name"], yes_first=True),
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
                from spotifactory.tasks.capture.label import add_label
                ctx.data["image"] = add_label(ctx.data["image"], pl["name"])
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


# ---------------------------------------------------------------------------
# Write Tag (from the menu): write what's playing to a tag, no print. For
# fixing a tag that got messed up, or one that was skipped after printing.
# ---------------------------------------------------------------------------

def _target_menu(targets: list[dict]):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    items = [ItemDef(t["label"], action="confirm", data=t) for t in targets]
    return MenuDef("Write tag for", items + [ItemDef("Cancel", action="cancel")],
                   visible_rows=min(3, len(items) + 1))


class ChooseTagTargetStep(Step):
    """What's playing: its album, and its playlist if it's playing from one."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Checking Spotify..."
        try:
            from spotifactory.spotify import get_client, uri_name
            playback = get_client().current_playback()
        except Exception as e:
            self.show_for(f"Spotify error: {str(e)[:20]}", 3.0)
            return Done()
        item = (playback or {}).get("item") or {}
        album = item.get("album") or {}
        targets = []
        if album.get("uri"):
            targets.append({"uri": album["uri"], "label": album.get("name") or "This album"})
        context = (playback or {}).get("context") or {}
        if context.get("type") == "playlist":
            try:
                name = uri_name(context["uri"])
            except Exception:
                name = "This playlist"
            targets.append({"uri": context["uri"], "label": f"Playlist: {name}"})
        if not targets:
            self.show_for("Nothing playing", 2.0)
            return Done()
        return PushMenu(menu=_target_menu(targets), on_confirm=Continue(), on_cancel=Cancel())


class WriteChosenTagStep(_WriteTagStep):
    """Like the print's tag step, but the tag to fix may already be on the
    reader: no need to lift it off, the overwrite question covers it."""

    step_name = "write"
    fresh_tag = False

    def _uri(self, ctx: TaskContext) -> str:
        # Kept apart: the overwrite question replaces ctx.data["selected"].
        if "tag_target" not in ctx.data:
            ctx.data["tag_target"] = ctx.data["selected"]["uri"]
        return ctx.data["tag_target"]


class TagWrittenStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.show_for("Tag written!", 2.0)
        return Done()
