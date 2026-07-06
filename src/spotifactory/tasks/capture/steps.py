from __future__ import annotations

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
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.spotify import get_now_playing
        self.status = "Checking Spotify..."
        info = get_now_playing()
        if info is None:
            self.show_for("Nothing playing", 2.0)
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
        self.status = "Connecting..."
        result = print_image(
            ctx.data["image"],
            dry_run=ctx.printer_dry_run,
            on_progress=lambda msg: setattr(self, "status", msg),
        )
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


class ScanStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.hardware.rfid import write_uri
        self.status = "Please scan tag"
        try:
            write_uri(ctx.data["info"].album_uri)
        except Exception as e:
            self.show_for(f"RFID error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        result = ctx.data.get("print_result")
        photos = f"{result.photos_left} photos left" if result else ""
        self.show_for(f"Album ready! {photos}".strip(), 3.0)
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


class FetchPlaylistArtStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Fetching artwork..."
        try:
            url = ctx.data["playlist"]["image_url"]
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            ctx.data["image"] = BytesIO(resp.content)
        except Exception as e:
            self.show_for(f"Art error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class PlaylistScanStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.hardware.rfid import write_uri
        self.status = "Please scan tag"
        try:
            write_uri(ctx.data["playlist"]["uri"])
        except Exception as e:
            self.show_for(f"RFID error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class PlaylistDoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        result = ctx.data.get("print_result")
        photos = f"{result.photos_left} photos left" if result else ""
        self.show_for(f"Playlist ready! {photos}".strip(), 3.0)
        return Done()
